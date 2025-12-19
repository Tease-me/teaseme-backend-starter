import json
import logging
import secrets
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
    Response,
    status,
)
from langchain_openai import ChatOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from app.db.session import get_db
from app.db.models import PreInfluencer
from app.schemas.pre_influencer import (
    PreInfluencerRegisterRequest,
    PreInfluencerRegisterResponse,
    SurveyQuestionsResponse,
    PreInfluencerAcceptTermsRequest,
    SurveyState,
    SurveySaveRequest,
    InfluencerAudioDeleteRequest,
    SurveyPromptRequest,
    SurveyPromptResponse,
)
from app.core.config import settings
from app.utils.email import send_profile_survey_email
from app.utils.s3 import save_influencer_photo_to_s3, generate_presigned_url, delete_file_from_s3


log = logging.getLogger(__name__)
router = APIRouter(prefix="/pre-influencers", tags=["pre-influencers"])
SURVEY_QUESTIONS_PATH = Path(__file__).resolve().parent.parent / "raw" / "survey-questions.json"
SURVEY_SUMMARIZER = ChatOpenAI(
    api_key=settings.OPENAI_API_KEY,
    model="gpt-4o",
    temperature=1,
)


def _load_survey_questions():
    try:
        with SURVEY_QUESTIONS_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Survey questions file missing",
        )
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Failed to load survey questions: {exc}",
        )

    if not isinstance(data, list):
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Survey questions file is malformed",
        )
    return data


def _format_survey_markdown(sections, answers, username: str | None = None) -> str:
    """Build a simple markdown report of questions and answers."""
    lines = []
    if username:
        lines.append(f"# {username}'s Survey")
        lines.append("")
    def _format_answer(question: dict, value: Any) -> str:
        options = question.get("options") or []
        label_map = {str(opt.get("value")): opt.get("label", opt.get("value")) for opt in options if isinstance(opt, dict)}
        if isinstance(value, list):
            mapped = [str(label_map.get(str(v), v)) for v in value]
            return ", ".join(mapped)
        return str(label_map.get(str(value), value))

    for section in sections:
        lines.append(f"## {section.get('title', section.get('id', ''))}")
        for q in section.get("questions", []):
            qid = q.get("id")
            label = q.get("label", qid)
            val = answers.get(qid) if isinstance(answers, dict) else None
            if val is None or val == "":
                ans_text = "_Not answered_"
            elif isinstance(val, list):
                ans_text = _format_answer(q, val)
            elif isinstance(val, dict):
                ans_text = json.dumps(val, ensure_ascii=False)
            else:
                ans_text = _format_answer(q, val)
            lines.append(f"- **{label}**: {ans_text}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _unwrap_json(raw: str) -> str:
    """Strip markdown code fences if the model wrapped the JSON."""
    text = raw.strip()
    if text.startswith("```"):
        # Remove opening fence with optional language
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    return text.strip()


async def _generate_prompt_from_markdown(markdown: str, additional_prompt: str | None) -> str:

    sys_msg = (
        "You are a prompt engineer. Read the survey markdown and output only JSON matching this schema exactly: "
        "{ likes: string[], dislikes: string[], mbti_architype: string, mbti_rules: string, personality_rules: string, tone: string, "
        "stages: { hate: string, dislike: string, strangers: string, talking: string, flirting: string, dating: string, in_love: string } }."
        "Fill likes/dislikes from foods, hobbies, entertainment, routines, and anything the user enjoys or hates. "
        "mbti_architype should select one of: ISTJ, ISFJ, INFJ, INTJ, ISTP, ISFP, INFP, INTP, ESTP, ESFP, ENFP, ENTP, ESTJ, ESFJ, ENFJ, ENTJ. "
        "mbti_rules should use mbti_architype to summarize decision style, social energy, planning habits. "
        "personality_rules should use mbti_architype to summarize overall personality, humor, boundaries, relationship vibe. "
        "tone should use mbti_architype to describe speaking style in a short sentence. "
        "Each stage string should describe how the persona behaves toward the user at that relationship stage. These should be influenced by mbti_architype."
        "Keep strings concise (1-2 sentences). If unclear, use an empty string. No extra keys, no prose."
    )
    user_msg = f"Survey markdown:\n{markdown}\n\nExtra instructions for style/tone:\n{additional_prompt or '(none)'}"

    try:
        resp = await SURVEY_SUMMARIZER.ainvoke(
            [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_msg},
            ]
        )
        raw = getattr(resp, "content", "") or ""
    except Exception as exc:
        log.warning("survey_prompt.llm_failed err=%s", exc)
        raw = ""
    try:
        parsed = json.loads(_unwrap_json(raw))
        log.info("survey_prompt.parsed ok keys=%s", list(parsed.keys()))
    except Exception as exc:
        log.warning("survey_prompt.parse_failed err=%s raw=%s", exc, raw[:2000])
        parsed = {}

    if not isinstance(parsed, dict):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Prompt generation returned non-object JSON.")

    # Basic normalization/defaults
    parsed.setdefault("likes", [])
    parsed.setdefault("dislikes", [])
    parsed.setdefault("mbti_architype", "")
    parsed.setdefault("mbti_rules", "")
    parsed.setdefault("personality_rules", "")
    parsed.setdefault("tone", "")
    stages = parsed.get("stages") or {}
    parsed["stages"] = {
        "hate": stages.get("hate", ""),
        "dislike": stages.get("dislike", ""),
        "strangers": stages.get("strangers", ""),
        "talking": stages.get("talking", ""),
        "flirting": stages.get("flirting", ""),
        "dating": stages.get("dating", ""),
        "in_love": stages.get("in_love", ""),
    }

    # Ensure lists are lists of strings
    def _as_str_list(val):
        if isinstance(val, list):
            return [str(x) for x in val]
        if val is None:
            return []
        return [str(val)]

    parsed["likes"] = _as_str_list(parsed.get("likes"))
    parsed["dislikes"] = _as_str_list(parsed.get("dislikes"))

    return parsed
@router.post("/{pre_id}/accept-terms")
async def accept_pre_influencer_terms(
    pre_id: int,
    payload: PreInfluencerAcceptTermsRequest,
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(select(PreInfluencer).where(PreInfluencer.id == pre_id))
    pre = res.scalar_one_or_none()
    if not pre:
        raise HTTPException(status_code=404, detail="Pre-influencer not found")
    
    pre.terms_agreement = True 
    await db.commit()
    return {"ok": True, "terms_agreement": True}


@router.post("/register", response_model=PreInfluencerRegisterResponse)
async def register_pre_influencer(
    data: PreInfluencerRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(PreInfluencer).where(
            or_(
                PreInfluencer.email == data.email,
                PreInfluencer.username == data.username,
            )
        )
    )
    if existing.scalar():
        raise HTTPException(
            status_code=200,
            detail="Username or email already registered as pre-influencer",
        )

    verify_token = secrets.token_urlsafe(32)

    pre = PreInfluencer(
        full_name=data.full_name,
        location=data.location,
        username=data.username,
        email=data.email,
        password=data.password,
        survey_token=verify_token,
        terms_agreement=False,
    )

    db.add(pre)
    await db.commit()
    await db.refresh(pre)

    send_profile_survey_email(
        pre.email,
        verify_token,
        data.password,
    )

    return PreInfluencerRegisterResponse(
        ok=True,
        user_id=pre.id,
        email=pre.email,
        message="Check your email.",
    )


@router.get("/survey", response_model=SurveyState)
async def open_survey(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PreInfluencer).where(PreInfluencer.survey_token == token)
    )
    pre = result.scalar_one_or_none()

    if not pre:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or expired survey link",
        )

    return SurveyState(
        pre_influencer_id=pre.id,
        username=pre.username,
        survey_answers=pre.survey_answers or {},
        survey_step=pre.survey_step or 0,
    )

@router.get("/survey/questions", response_model=SurveyQuestionsResponse)
async def get_survey_questions():
    return SurveyQuestionsResponse(sections=_load_survey_questions())

@router.get("/{pre_id}/survey/markdown")
async def get_survey_markdown(
    pre_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PreInfluencer).where(PreInfluencer.id == pre_id)
    )
    pre = result.scalar_one_or_none()

    if not pre:
        raise HTTPException(status_code=404, detail="Pre-influencer not found")

    sections = _load_survey_questions()
    markdown = _format_survey_markdown(sections, pre.survey_answers or {}, pre.username)
    return Response(content=markdown, media_type="text/markdown")

@router.get("/{pre_id}/survey/generate-prompt", response_model=SurveyPromptResponse)
async def generate_prompt_from_survey(
    pre_id: int,
    additional_prompt: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PreInfluencer).where(PreInfluencer.id == pre_id)
    )
    pre = result.scalar_one_or_none()

    if not pre:
        raise HTTPException(status_code=404, detail="Pre-influencer not found")

    sections = _load_survey_questions()
    markdown = _format_survey_markdown(sections, pre.survey_answers or {}, pre.username)
    prompt = await _generate_prompt_from_markdown(markdown, additional_prompt=additional_prompt)
    return SurveyPromptResponse(**prompt)

@router.put("/{pre_id}/survey", response_model=SurveyState)
async def save_survey_state(
    pre_id: int,
    data: SurveySaveRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PreInfluencer).where(PreInfluencer.id == pre_id)
    )
    pre = result.scalar_one_or_none()

    if not pre:
        raise HTTPException(status_code=404, detail="Pre-influencer not found")

    pre.survey_answers = data.survey_answers
    pre.survey_step = data.survey_step

    await db.commit()
    await db.refresh(pre)

    return SurveyState(
        pre_influencer_id=pre.id,
        username=pre.username,
        survey_answers=pre.survey_answers or {},
        survey_step=pre.survey_step or 0,
    )

@router.post("/upload-picture")
async def upload_pre_influencer_picture(
    pre_influencer_id: int = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    
):
    result = await db.execute(
        select(PreInfluencer).where(PreInfluencer.id == pre_influencer_id)
    )
    pre = result.scalar_one_or_none()

    if not pre:
        raise HTTPException(status_code=404, detail="Pre-influencer not found")

    if not pre.username:
        raise HTTPException(
            status_code=400,
            detail="Pre-influencer has no username to store picture under",
        )

    answers = pre.survey_answers or {}
    previous_key = answers.get("profile_picture_key")

    s3_key = await save_influencer_photo_to_s3(
        file.file,
        file.filename or "profile.jpg",
        file.content_type or "image/jpeg",
        influencer_id=pre.username,
    )

    answers["profile_picture_key"] = s3_key
    pre.survey_answers = answers

    try:
        await db.commit()
        await db.refresh(pre)
    except Exception:
        await db.rollback()
        if s3_key and s3_key != previous_key:
            try:
                await delete_file_from_s3(s3_key)
            except Exception:
                log.warning("Failed to rollback uploaded S3 picture %s", s3_key, exc_info=True)
        raise

    if previous_key and previous_key != s3_key:
        try:
            await delete_file_from_s3(previous_key)
        except Exception:
            log.warning("Failed to delete previous S3 picture %s", previous_key, exc_info=True)

    return {"s3_key": s3_key}

@router.get("/{pre_id}/picture-url")
async def get_pre_influencer_picture_url(
    pre_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PreInfluencer).where(PreInfluencer.id == pre_id)
    )
    pre = result.scalar_one_or_none()

    if not pre:
        raise HTTPException(status_code=404, detail="Pre-influencer not found")

    answers = pre.survey_answers or {}
    key = answers.get("profile_picture_key")
    if not key:
        raise HTTPException(status_code=404, detail="No picture stored")

    url = generate_presigned_url(key, expires=3600)
    return {"url": url}

@router.delete("/influencer-audio/{influencer_id}")
async def delete_influencer_audio(
    influencer_id: str,
    payload: InfluencerAudioDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    key = payload.key

    expected_prefix = f"influencer-audio/{influencer_id}/"
    if not key.startswith(expected_prefix):
      raise HTTPException(status_code=400, detail="Invalid audio key for this influencer")

    await delete_file_from_s3(key)

    return {"ok": True}
