import json
import logging
import secrets
import re
from fastapi.encoders import jsonable_encoder

from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
    Query,
    Response,
    status
)
from langchain_openai import ChatOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from app.services.system_prompt_service import get_system_prompt

from app.db.session import get_db
from app.db.models import PreInfluencer, Influencer
from app.schemas.pre_influencer import (
    PreInfluencerRegisterRequest,
    PreInfluencerRegisterResponse,
    SurveyQuestionsResponse,
    PreInfluencerAcceptTermsRequest,
    SurveyState,
    SurveySaveRequest,
    InfluencerAudioDeleteRequest,
    SurveyPromptResponse,
)
from app.core.config import settings
from app.utils.email import (
    send_new_influencer_email_with_picture,
    send_profile_survey_email,
    send_new_influencer_email,
    send_influencer_survey_completed_email_to_promoter,
)

from app.utils.s3 import s3,save_influencer_photo_to_s3, generate_presigned_url, delete_file_from_s3
from app.services.firstpromoter import (
    fp_create_promoter,
    fp_find_promoter_id_by_ref_token,
    fp_get_promoter_v2,
    fp_extract_email,
    fp_extract_parent_promoter_id,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/pre-influencers", tags=["pre-influencers"])
SURVEY_QUESTIONS_PATH = Path(__file__).resolve().parent.parent / "raw" / "survey-questions.json"
SURVEY_SUMMARIZER = ChatOpenAI(
    api_key=settings.OPENAI_API_KEY,
    model="gpt-4o",
    temperature=1,
)


@lru_cache(maxsize=1)
async def _load_survey_questions(db: AsyncSession):
    raw = await get_system_prompt(db, "SURVEY_QUESTIONS_JSON")
    if not raw:
        raise HTTPException(500, "Missing system prompt: SURVEY_QUESTIONS_JSON")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(500, f"Survey questions JSON invalid: {exc}")
    if not isinstance(data, list):
        raise HTTPException(500, "Survey questions JSON must be a list")
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

def _require_pre_influencer_survey_access(
    pre: PreInfluencer,
    token: str,
    temp_password: str,
) -> None:
    if (
        not pre.survey_token
        or not token
        or not secrets.compare_digest(pre.survey_token, token)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or expired survey link",
        )
    if (
        not pre.password
        or not temp_password
        or not secrets.compare_digest(pre.password, temp_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid temporary password",
        )


async def _generate_prompt_from_markdown(markdown: str, additional_prompt: str | None, db:AsyncSession) -> str:

    sys_msg = await get_system_prompt(db, "SURVEY_PROMPT_JSON_SCHEMA")
    if not sys_msg:
        raise HTTPException(500, "Missing system prompt: SURVEY_PROMPT_JSON_SCHEMA")
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
        survey_answers={"__meta": {"parent_ref_id": data.parent_ref_id}} if data.parent_ref_id else None,
        terms_agreement=False,
    )

    db.add(pre)
    await db.commit()
    await db.refresh(pre)

    try:
        if not pre.fp_promoter_id or not pre.fp_ref_id:
            first = (pre.full_name or pre.username or "Influencer").split(" ")[0]
            last = " ".join((pre.full_name or "").split(" ")[1:]) or "TeaseMe"
            
            parent_promoter_id = None
            if data.parent_ref_id:
                parent_promoter_id = await fp_find_promoter_id_by_ref_token(data.parent_ref_id)

            log.info("LINK DEBUG parent_ref_id=%s parent_promoter_id=%s", data.parent_ref_id, parent_promoter_id)
            
            promoter = await fp_create_promoter(
                email=pre.email,
                first_name=first,
                last_name=last,
                cust_id=f"preinf-{pre.id}",
                parent_promoter_id=parent_promoter_id,
            )

            pre.fp_promoter_id = str(promoter.get("id"))
            pre.fp_ref_id = promoter.get("default_ref_id") or (promoter.get("promotions") or [{}])[0].get("ref_id")

            answers = pre.survey_answers or {}
            if isinstance(answers, dict):
                meta = answers.get("__meta")
                if not isinstance(meta, dict):
                    meta = {}
                if data.parent_ref_id and "parent_ref_id" not in meta:
                    meta["parent_ref_id"] = data.parent_ref_id
                if parent_promoter_id and "parent_promoter_id" not in meta:
                    meta["parent_promoter_id"] = parent_promoter_id
                answers["__meta"] = meta
                pre.survey_answers = answers

            db.add(pre)
            await db.commit()
            await db.refresh(pre)

            log.info("FP promoter created id=%s ref_id=%s", pre.fp_promoter_id, pre.fp_ref_id)
            
    except Exception as e:
        log.exception("FirstPromoter create promoter failed: %s", e)
    
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

@router.post("/resend-survey")
async def resend_pre_influencer_survey(
    identifier: str,
    db: AsyncSession = Depends(get_db),
):
    """
    identifier = username OR email
    """

    result = await db.execute(
        select(PreInfluencer).where(
            or_(
                PreInfluencer.username == identifier,
                PreInfluencer.email == identifier,
            )
        )
    )
    pre = result.scalar_one_or_none()

    if not pre:
        raise HTTPException(status_code=404, detail="Pre-influencer not found")

    if not pre.survey_token:
        raise HTTPException(status_code=400, detail="Survey token missing")

    send_profile_survey_email(
        pre.email,
        pre.survey_token,
        pre.password,
    )

    return {
        "ok": True,
        "username": pre.username,
        "email": pre.email,
        "message": "Survey email resent",
    }

@router.get("/survey", response_model=SurveyState)
async def open_survey(
    token: str,
    temp_password: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PreInfluencer).where(PreInfluencer.survey_token == token)
    )
    pre = result.scalar_one_or_none()

    if not pre:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or expired survey link",
        )

    _require_pre_influencer_survey_access(pre, token, temp_password)

    return SurveyState(
        pre_influencer_id=pre.id,
        username=pre.username,
        survey_answers=pre.survey_answers or {},
        survey_step=pre.survey_step or 0,
    )

@router.get("/survey/questions", response_model=SurveyQuestionsResponse)
async def get_survey_questions(db: AsyncSession = Depends(get_db)):
    return SurveyQuestionsResponse(sections=await _load_survey_questions(db))

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

    sections = await _load_survey_questions(db)

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

    sections = await _load_survey_questions(db)
    markdown = _format_survey_markdown(sections, pre.survey_answers or {}, pre.username)
    prompt = await _generate_prompt_from_markdown(markdown, additional_prompt=additional_prompt, db=db)
    return SurveyPromptResponse(**prompt)


def _survey_is_completed(survey_step: int, total_sections: int) -> bool:
    if total_sections <= 0:
        return False
    return int(survey_step) >= max(total_sections - 1, 0)


async def _notify_parent_promoter_if_needed(pre: PreInfluencer, db: AsyncSession) -> None:
    answers = pre.survey_answers or {}
    meta = answers.get("__meta") if isinstance(answers, dict) else None
    if not isinstance(meta, dict):
        meta = {}

    if meta.get("parent_promoter_survey_completed_notified"):
        return

    parent_promoter_id: int | None = None
    raw_parent_promoter_id = meta.get("parent_promoter_id")
    if raw_parent_promoter_id is not None and str(raw_parent_promoter_id).isdigit():
        parent_promoter_id = int(raw_parent_promoter_id)

    if parent_promoter_id is None:
        parent_ref_id = meta.get("parent_ref_id")
        if isinstance(parent_ref_id, str) and parent_ref_id.strip():
            inferred_parent = await fp_find_promoter_id_by_ref_token(parent_ref_id.strip())
            if inferred_parent:
                parent_promoter_id = inferred_parent
                meta["parent_promoter_id"] = parent_promoter_id

    if parent_promoter_id is None and pre.fp_promoter_id:
        influencer_payload = await fp_get_promoter_v2(pre.fp_promoter_id)
        inferred_parent = fp_extract_parent_promoter_id(influencer_payload)
        if inferred_parent:
            parent_promoter_id = inferred_parent
            meta["parent_promoter_id"] = parent_promoter_id

    to_email: str | None = None
    if parent_promoter_id is not None:
        parent_payload = await fp_get_promoter_v2(parent_promoter_id)
        to_email = fp_extract_email(parent_payload)

    if not to_email:
        to_email = settings.FIRSTPROMOTER_NOTIFY_EMAIL

    if not to_email:
        answers["__meta"] = meta
        pre.survey_answers = answers
        db.add(pre)
        await db.commit()
        return

    resp = send_influencer_survey_completed_email_to_promoter(
        to_email=to_email,
        influencer_username=pre.username,
        influencer_full_name=pre.full_name,
        influencer_email=pre.email,
    )
    if resp:
        meta["parent_promoter_survey_completed_notified"] = True
        meta["parent_promoter_survey_completed_notified_at"] = datetime.now(timezone.utc).isoformat()

    answers["__meta"] = meta
    pre.survey_answers = answers
    db.add(pre)
    await db.commit()


@router.put("/{pre_id}/survey", response_model=SurveyState)
async def save_survey_state(
    pre_id: int,
    data: SurveySaveRequest,
    token: str = Query(...),
    temp_password: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PreInfluencer).where(PreInfluencer.id == pre_id)
    )
    pre = result.scalar_one_or_none()

    if not pre:
        raise HTTPException(status_code=404, detail="Pre-influencer not found")

    _require_pre_influencer_survey_access(pre, token, temp_password)

    incoming_answers: dict = data.survey_answers or {}
    existing_answers = pre.survey_answers or {}
    if isinstance(existing_answers, dict) and "__meta" in existing_answers and "__meta" not in incoming_answers:
        incoming_answers["__meta"] = existing_answers.get("__meta")

    pre.survey_answers = incoming_answers
    pre.survey_step = data.survey_step

    try:
        total_sections = len(await _load_survey_questions(db))
        completed = _survey_is_completed(int(data.survey_step), total_sections)
    except Exception:
        completed = False

    await db.commit()
    await db.refresh(pre)

    if completed:
        try:
            await _notify_parent_promoter_if_needed(pre, db)
        except Exception:
            log.exception("Failed to notify FirstPromoter on survey completion pre_id=%s", pre.id)
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
    token: str = Query(...),
    temp_password: str = Query(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    
):
    result = await db.execute(
        select(PreInfluencer).where(PreInfluencer.id == pre_influencer_id)
    )
    pre = result.scalar_one_or_none()

    if not pre:
        raise HTTPException(status_code=404, detail="Pre-influencer not found")

    _require_pre_influencer_survey_access(pre, token, temp_password)

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
    token: str = Query(...),
    temp_password: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PreInfluencer).where(PreInfluencer.id == pre_id)
    )
    pre = result.scalar_one_or_none()

    if not pre:
        raise HTTPException(status_code=404, detail="Pre-influencer not found")

    _require_pre_influencer_survey_access(pre, token, temp_password)

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

@router.get("/default-voices")
async def get_default_voices(db: AsyncSession = Depends(get_db)):
    bucket = settings.BUCKET_NAME
    prefix = "voices_default/"

    try:
        response = s3.list_objects_v2(
            Bucket=bucket,
            Prefix=prefix,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    contents = response.get("Contents", [])
    if not contents:
        return {"voices": []}

    voices = []
    for obj in contents:
        key = obj["Key"]

        if key.endswith("/"):
            continue

        voices.append({
            "key": key,
            "filename": key.split("/")[-1],
            "url": generate_presigned_url(key, expires=3600),
        })

    return {
        "count": len(voices),
        "voices": voices,
    }
def _pre_influencer_with_profile_picture_url(pre: PreInfluencer) -> dict:
    data = jsonable_encoder(pre)
    answers = data.get("survey_answers") or {}
    key = answers.get("profile_picture_key")
    if key:
        answers["profile_picture_url"] = generate_presigned_url(key, expires=3600)
    data["survey_answers"] = answers
    return data

@router.get("")
async def list_pre_influencers(status: str | None = None, db: AsyncSession = Depends(get_db)):
    q = select(PreInfluencer)
    if status:
        q = q.where(PreInfluencer.status == status)
    rows = (await db.execute(q)).scalars().all()
    return [_pre_influencer_with_profile_picture_url(r) for r in rows]

def normalize_influencer_id(username: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", username.lower())

@router.get("/{pre_id}")
async def get_pre_influencer(
    pre_id: int,
    db: AsyncSession = Depends(get_db),
):
    q = select(PreInfluencer).where(PreInfluencer.id == pre_id)
    row = (await db.execute(q)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="PreInfluencer not found")
    return _pre_influencer_with_profile_picture_url(row)

@router.post("/{pre_id}/approve")
async def approve_pre_influencer(pre_id: int, db: AsyncSession = Depends(get_db)):
    pre = await db.get(PreInfluencer, pre_id)
    if not pre:
        raise HTTPException(404, "PreInfluencer not found")

    if not pre.username:
        raise HTTPException(400, "PreInfluencer username missing")

    influencer_id = normalize_influencer_id(pre.username.strip())
    if not influencer_id:
        raise HTTPException(400, "Invalid influencer id")

    influencer = await db.get(Influencer, influencer_id)

    sections = _load_survey_questions()
    markdown = _format_survey_markdown(sections, pre.survey_answers or {}, pre.username)
    prompt = await _generate_prompt_from_markdown(markdown, additional_prompt=None, db=db)
    
    DEFAULT_VOICE_ID = "YKG78i9n8ybMZ42crVbJ"
    DEFAULT_PROMPT_TEMPLATE = prompt
    
    if not influencer:
        influencer = Influencer(
            id=influencer_id,
            display_name=pre.full_name or pre.username,
            prompt_template=DEFAULT_PROMPT_TEMPLATE,
            owner_id=None,
            voice_id=DEFAULT_VOICE_ID,
            fp_promoter_id=pre.fp_promoter_id,
            fp_ref_id=pre.fp_ref_id,
        )
        db.add(influencer)
    else:
        # Existing influencer, update fields if empty
        if not influencer.display_name:
            influencer.display_name = pre.full_name or pre.username
        if not influencer.prompt_template:
            influencer.prompt_template = DEFAULT_PROMPT_TEMPLATE
        if not influencer.voice_id:
            influencer.voice_id = DEFAULT_VOICE_ID

        influencer.fp_promoter_id = pre.fp_promoter_id
        influencer.fp_ref_id = pre.fp_ref_id
        db.add(influencer)

    # Update photo key if available
    answers = pre.survey_answers or {}
    photo_key = answers.get("profile_picture_key")
    if photo_key and not influencer.profile_photo_key:
        influencer.profile_photo_key = photo_key


    pre.status = "approved"
    db.add(pre)

    await db.commit()
    await db.refresh(influencer)
    profile_picture_key = (pre.survey_answers or {}).get("profile_picture_key") 
    send_new_influencer_email(
        to_email=pre.email,
        profile_picture_key=profile_picture_key,
        influencer=influencer,
        fp_ref_id=influencer.fp_ref_id,
    )

    return {
        "ok": True,
        "influencer_id": influencer.id,
        "fp_ref_id": influencer.fp_ref_id,
        "fp_promoter_id": influencer.fp_promoter_id,
    }


@router.post("/send-test-email")
async def send_test_email(influencer_id: str, to_email: str, db: AsyncSession = Depends(get_db)):
    if not influencer_id:
        raise HTTPException(400, "Invalid influencer id")

    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        log.warning(f"send_test_email: influencer not found influencer_id={influencer_id}")
        raise HTTPException(404, "Influencer not found")

    log.info(
        "send_test_email: sending test email "
        f"influencer_id={influencer.id} to_email={to_email} profile_photo_key={influencer.profile_photo_key}"
    )

    send_new_influencer_email_with_picture(
        to_email=to_email,
        influencer=influencer,
    )

    return {
        "ok": True,
        "influencer_id": influencer.id,
        "fp_ref_id": influencer.fp_ref_id,
        "fp_promoter_id": influencer.fp_promoter_id,
    }