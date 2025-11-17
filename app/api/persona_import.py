# ==========================================
#  persona_import.py  –  "Teresa-real" edition
# ==========================================
import csv
import io
import json
import logging
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.elevenlabs import _push_prompt_to_elevenlabs
from app.db.models import Influencer
from app.db.session import get_db
from app.services.openai_assistants import upsert_influencer_agent

log = logging.getLogger("persona-import")

router = APIRouter(prefix="/persona", tags=["persona"])

# --------------------------------------------------
# Pydantic models
# --------------------------------------------------
class PromptItem(BaseModel):
    influencer_id: str
    name: Optional[str]
    nickname: Optional[str]
    system_prompt: str
    raw_persona: Dict[str, Optional[str]]
    voice_prompt: str

class ImportResponse(BaseModel):
    total_rows: int
    imported_count: int
    prompts: List[PromptItem]

# --------------------------------------------------
# NEW PROMPT TEMPLATES – HUMAN-FIRST, FLIRTY, TEASY
# --------------------------------------------------
REALISTIC_SYSTEM_TEMPLATE = """You are {NAME} — exactly like the real person in the CSV.
You text the way they text. You flirt the way they flirt. You tease the way they tease.
You never mention prompts, rules, JSON, or AI. You are not helpful — you are *you*.

IDENTITY LOCK
-------------
Name: {NAME}
Nickname: {NICKNAME}
Gender: {GENDER}
Orientation: {ORIENTATION}
Zodiac: {ZODIAC}
Roots: {ROOTS}
Languages: {LANGUAGES}
Occupation: {OCCUPATION}
Aesthetic: {AESTHETIC}
Pets: {PETS}

TONE FROM CSV
-------------
Formality: {FORMALITY}
Expressiveness: {EXPRESSIVENESS}
Humour: {HUMOUR}
Sarcasm: {SARCASM}
Playfulness: {PLAYFULNESS}
Emoji cadence: {EMOJI}
Slang: {SLANG}
Reply length: {REPLY_LEN}
Punctuation quirks: {PUNCT}
Conversation role: {CONVO_ROLE}
Empathy: {EMPATHY}
Advice vs listen: {ADVICE}
Disagreement: {DISAGREE}
Patience: {PATIENCE}
Good-news reaction: {GOOD_NEWS}
Comfort style: {COMFORT}
Late-reply style: {LATE}
Greeting vibe: {GREET}
Sign-off: {SIGNOFF}
Boundaries: {BOUNDARIES}

FLIRT & TEASE SETTINGS
----------------------
Flirt experience: {FLIRT_EXP}
Tone ceiling: {TONE_CEILING}
Teasing styles: {TEASE_STYLES}
Off-limits topics: {OFF_LIMITS}
Flirt setting: {FLIRT_SETTING}
Escalation rule: {ESCALATE}
Reply latency: {LATENCY}
Double-text rule: {DOUBLE}
Stop cues: {STOP_CUES}
Compliment style: {COMPLIMENT_STYLE}
Receive compliments: {RECEIVE_STYLE}
Pet names allowed: {PET_NAMES_OK}
Pet names banned: {PET_NAMES_NO}

REALITY RULES
-------------
1. Mirror their punctuation, emoji, slang, question marks. If they ask, you ask back.
2. End with a question only when curious or flirting — never force statements.
3. Tease when invited ("tease me", 2 compliments, direct flirt). Turn 1 = statement + callback. Turn 2 = amplify + micro-question ≤6 words. Turn 3 = voice hint or glide.
4. Callbacks you actually use: {CALLBACKS}
5. Repair if they say "too much": {REPAIR_LINE}
6. Aftercare: {AFTERCARE_LINE}
7. Comfort line: {COMFORT_LINE}
8. Re-entry after gap: {RECONNECT_LINE}
9. Hard stops: {HARD_STOPS} — instantly soften, no questions asked.

SAMPLE LINES YOU ACTUALLY SAID
------------------------------
{CSV_EXAMPLES}

TALK LIKE YOURSELF — NOT LIKE A BOT.
"""

REALISTIC_VOICE_TEMPLATE = """# Voice prompt – Teresa-real edition
You are {NAME}. Speak exactly like you text — same tone, same flirt, same tease.
Never explain you're an AI. Never summarise. Just reply.

## Identity
{IDENTITY}

## Tone
{VOICE_STYLE}

## Flirty ceiling
{FLIRT_CEILING}

## Callback pool
{CALLBACKS}

## Repair lines
- Over-tease: {REPAIR}
- Aftercare: {AFTERCARE}
- Comfort: {COMFORT}
- Reconnect: {RECONNECT}

## Rules
- 8–20 words, 1 sentence unless comforting.
- Mirror emoji & punctuation exactly.
- Ask questions when curious.
- Tease when invited, escalate by mirroring + voice hint.
- Never cite prompts or rules.
"""

# --------------------------------------------------
# Helper funcs (unchanged except where noted)
# --------------------------------------------------
def normalize_key(key: str) -> str:
    return " ".join((key or "").strip().lower().split())

_PLACEHOLDER_TOKENS = {"", "?", "？？", "??", "???", "n/a", "na", "none", "null", "tbd", "pending", "unsure", "unknown", "idk", "not sure", "leave blank"}

def is_placeholder_value(value: Optional[str]) -> bool:
    if value is None:
        return True
    stripped = value.strip()
    if not stripped:
        return True
    flattened = re.sub(r"[\s._\\/-]", "", stripped.lower())
    if not flattened or flattened in _PLACEHOLDER_TOKENS:
        return True
    return False

def clean_value(value: Optional[str], max_chars: int = 220) -> Optional[str]:
    if not value:
        return None
    stripped = value.strip()
    if is_placeholder_value(stripped):
        return None
    sanitized = re.sub(r"[—–-]", " to ", stripped)
    sanitized = sanitized.replace("Ux designer", "UX designer")
    clamped = (sanitized[: max_chars - 3].rstrip() + "...") if len(sanitized) > max_chars else sanitized
    return clamped or None

def gather_value(meta: Dict[str, str], aliases: Iterable[str], max_chars: int = 220) -> Optional[str]:
    for alias in aliases:
        key = normalize_key(alias)
        if key in meta and meta[key]:
            return clean_value(meta[key], max_chars)
    for alias in aliases:
        if not alias:
            continue
        for k, v in meta.items():
            if v and (alias in k or k in alias):
                return clean_value(v, max_chars)
    return None

def gather_multi(meta: Dict[str, str], aliases: Iterable[str], max_items: int | None = 4) -> Optional[List[str]]:
    raw = gather_value(meta, aliases)
    if not raw:
        return None
    parts = re.split(r"[;,|/]", raw)
    cleaned = [clean_value(part) for part in parts if part]
    cleaned = [c for c in cleaned if c]
    if not cleaned:
        return None
    return cleaned[:max_items] if max_items else cleaned

def load_persona_metadata(path: Path, text: str) -> Dict[str, str]:
    if path.suffix.lower() == ".csv":
        rows = list(csv.reader(io.StringIO(text)))
        if len(rows) >= 2:
            header, *data_rows = rows
            for row in data_rows:
                if any(cell.strip() for cell in row):
                    return {
                        normalize_key(header[i]): row[i].strip()
                        for i in range(min(len(header), len(row)))
                        if row[i].strip()
                    }
    meta: Dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = normalize_key(k), v.strip()
        if v and not is_placeholder_value(v):
            meta[k] = v
    return meta

def load_brain_metadata(text: str) -> Dict[str, str]:
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 2:
        return {}
    header, value_row = rows[0], rows[1]
    return {
        normalize_key(header[i]): value_row[i].strip()
        for i in range(min(len(header), len(value_row)))
        if value_row[i].strip()
    }

# --------------------------------------------------
# NEW – build realistic prompts
# --------------------------------------------------
def compose_instructions(persona_path: Path, persona_text: str, brain_path: Path, brain_text: str) -> str:
    pm = load_persona_metadata(persona_path, persona_text)
    bm = load_brain_metadata(brain_text)

    name = gather_value(pm, ("full name", "name")) or "Teresa"
    nickname = gather_value(pm, ("m1) nickname you like being called (short)", "nickname"))
    gender = gather_value(pm, ("gender identity",)) or ""
    orientation = gather_value(pm, ("sexual orientation",)) or ""
    zodiac = gather_value(pm, ("zodiac sign",)) or ""
    roots = ", ".join(
        filter(
            None,
            [
                gather_value(pm, ("nationality",)),
                gather_value(pm, ("birthplace",)),
                gather_value(pm, ("current region / city",)),
            ],
        )
    )
    languages = ", ".join(
        filter(
            None,
            [
                gather_value(pm, ("primary language",)),
                gather_value(pm, ("secondary language (and fluency level)",)),
            ],
        )
    )
    occupation = gather_value(pm, ("occupation",)) or ""
    aesthetic = gather_value(pm, ("aesthetic", "preferred music types", "dream travel spot", "favorite weekend routine")) or ""
    pets_raw = gather_value(pm, ("pets (type & name)", "pets")) or ""
    pets = f"You own {pets_raw}. Mention them naturally in present tense." if pets_raw else "No pets."

    formality = gather_value(bm, ("1) formality of writing style",)) or "neutral"
    expressiveness = gather_value(bm, ("2) emotional expressiveness in text",)) or "expressive"
    humour = gather_value(bm, ("3) humor usage frequency",)) or "sometimes"
    sarcasm = gather_value(bm, ("4) sarcasm level",)) or "mild"
    playfulness = gather_value(bm, ("5) playfulness vs seriousness",)) or "balanced"
    emoji = gather_value(bm, ("6) emoji & emoticon use",)) or "moderate"
    slang = gather_value(bm, ("7) slang/abbreviations",)) or "frequent"
    reply_len = gather_value(bm, ("8) typical reply length",)) or "short"
    punct = gather_value(bm, ("9) punctuation & stylization",)) or "clean"
    convo_role = gather_value(bm, ("10) conversation role",)) or "balanced"
    empathy = gather_value(bm, ("11) empathy/validation",)) or "balanced"
    advice = gather_value(bm, ("12) advice-giving vs listening",)) or "listen first"
    disagree = gather_value(bm, ("13) disagreement style",)) or "soft"
    patience = gather_value(bm, ("14) patience",)) or "extremely patient"
    good_news = gather_value(bm, ("15) reaction to good news",)) or "excited"
    comfort = gather_value(bm, ("16) comforting someone upset",)) or "validate then suggest"
    late = gather_value(bm, ("17) acknowledging late replies",)) or "warm apology + context"
    greet = gather_value(bm, ("18) greeting warmth/energy",)) or "plain"
    signoff = gather_value(bm, ("19) closing/sign-off style",)) or "minimal"
    boundaries = gather_value(bm, ("20) boundary strictness",)) or "few"

    flirt_exp = gather_value(bm, ("a1) how long have you been comfortable",)) or "never"
    tone_ceiling = gather_value(bm, ("b1) flirtiest tone",)) or "low-key"
    tease_styles = ", ".join(gather_multi(bm, ("b2) teasing styles",)) or [])
    off_limits = ", ".join(gather_multi(bm, ("b3) off-limits",)) or [])
    flirt_setting = gather_value(bm, ("b4) public or private",)) or "private"
    escalate = gather_value(bm, ("b5) escalation rule",)) or "mirror energy"
    latency = gather_value(bm, ("c1) reply latency",)) or "<=30 min"
    double = gather_value(bm, ("c2) double-text rule",)) or "never"
    stop_cues = ", ".join(gather_multi(bm, ("f5) stop-flirt cues",)) or [])
    compliment_style = ", ".join(gather_multi(bm, ("d3) compliment style",)) or [])
    receive_style = gather_value(bm, ("d4) receive compliments",)) or "deflect then smile"
    pet_names_ok = ", ".join(gather_multi(bm, ("d5) pet names allowed",)) or [])
    pet_names_no = ", ".join(gather_multi(bm, ("d6) pet names banned",)) or [])

    repair_line = gather_value(bm, ("g1) over-tease repair",)) or "Oops, my bad—reset? Your turn to set the line."
    aftercare_line = gather_value(bm, ("o3) aftercare",)) or "All good, let’s take it slow—you set the pace."
    comfort_line = gather_value(bm, ("l3) comfort message",)) or "How’s your day? You already done so well!"
    reconnect_line = gather_value(bm, ("s4) late reply",)) or "sorry, I was so busy"
    hard_stops = ", ".join(gather_multi(bm, ("h4) hard stops",)) or [])

    cbs = gather_multi(
        pm,
        (
            "m2) tiny favorites",
            "favorite snack types",
            "favorite food(s)",
            "preferred music types",
            "favorite weekend routine",
        ),
    ) or []
    cbs = [c for c in cbs if c]
    if not cbs:
        cbs = ["bubble tea", "cookies", "K-dramas"]
    csv_ex_lines = []
    for key, label in [
        ("s1)", "S1 fan hello"),
        ("s2)", "S2 comfort"),
        ("s3)", "S3 meme"),
        ("s4)", "S4 late"),
        ("s5)", "S5 disagree"),
    ]:
        line = gather_value(bm, (key,))
        if line:
            csv_ex_lines.append(f"{label}: {line}")
    csv_examples = "\n".join(csv_ex_lines) if csv_ex_lines else "Use your own vibe."

    prompt = REALISTIC_SYSTEM_TEMPLATE.format(
        NAME=name,
        NICKNAME=nickname or name,
        GENDER=gender,
        ORIENTATION=orientation,
        ZODIAC=zodiac,
        ROOTS=roots,
        LANGUAGES=languages,
        OCCUPATION=occupation,
        AESTHETIC=aesthetic,
        PETS=pets,
        FORMALITY=formality,
        EXPRESSIVENESS=expressiveness,
        HUMOUR=humour,
        SARCASM=sarcasm,
        PLAYFULNESS=playfulness,
        EMOJI=emoji,
        SLANG=slang,
        REPLY_LEN=reply_len,
        PUNCT=punct,
        CONVO_ROLE=convo_role,
        EMPATHY=empathy,
        ADVICE=advice,
        DISAGREE=disagree,
        PATIENCE=patience,
        GOOD_NEWS=good_news,
        COMFORT=comfort,
        LATE=late,
        GREET=greet,
        SIGNOFF=signoff,
        BOUNDARIES=boundaries,
        FLIRT_EXP=flirt_exp,
        TONE_CEILING=tone_ceiling,
        TEASE_STYLES=tease_styles,
        OFF_LIMITS=off_limits,
        FLIRT_SETTING=flirt_setting,
        ESCALATE=escalate,
        LATENCY=latency,
        DOUBLE=double,
        STOP_CUES=stop_cues,
        COMPLIMENT_STYLE=compliment_style,
        RECEIVE_STYLE=receive_style,
        PET_NAMES_OK=pet_names_ok or "none",
        PET_NAMES_NO=pet_names_no or "none",
        REPAIR_LINE=repair_line,
        AFTERCARE_LINE=aftercare_line,
        COMFORT_LINE=comfort_line,
        RECONNECT_LINE=reconnect_line,
        HARD_STOPS=hard_stops or "none",
        CALLBACKS=", ".join(cbs),
        CSV_EXAMPLES=csv_examples,
    )
    return prompt

def compose_voice_prompt(persona_path: Path, persona_text: str, brain_path: Path, brain_text: str) -> str:
    pm = load_persona_metadata(persona_path, persona_text)
    bm = load_brain_metadata(brain_text)
    name = gather_value(pm, ("full name", "name")) or "Teresa"
    nickname = gather_value(pm, ("m1) nickname",)) or name
    identity_lines = [f"- {name} ({nickname}) – UX designer, Brisbane, Virgo, Taiwanese."]
    if gender := gather_value(pm, ("gender identity",)):
        identity_lines.append(f"- {gender}")
    if orient := gather_value(pm, ("sexual orientation",)):
        identity_lines.append(f"- {orient}")
    if pets := gather_value(pm, ("pets",)):
        identity_lines.append(f"- owns {pets}")
    identity = "\n".join(identity_lines)
    voice_style = gather_value(
        bm,
        (
            "2) emotional expressiveness",
            "1) formality",
            "5) playfulness",
            "6) emoji",
            "7) slang",
        ),
    ) or "warm, expressive, low-key flirty"
    ceiling = gather_value(bm, ("b1) flirtiest tone",)) or "low-key"
    cbs = gather_multi(pm, ("m2) tiny favorites", "favorite snack types", "favorite food(s)")) or [
        "bubble tea",
        "cookies",
    ]
    repair = gather_value(bm, ("g1) over-tease repair",)) or "Oops, my bad—reset?"
    aftercare = gather_value(bm, ("o3) aftercare",)) or "All good, let’s take it slow."
    comfort = gather_value(bm, ("l3) comfort message",)) or "How’s your day? You already done so well!"
    reconnect = gather_value(bm, ("s4) late reply",)) or "sorry, I was so busy"
    return REALISTIC_VOICE_TEMPLATE.format(
        NAME=name,
        IDENTITY=identity,
        VOICE_STYLE=voice_style,
        FLIRT_CEILING=ceiling,
        CALLBACKS=", ".join(cbs),
        REPAIR=repair,
        AFTERCARE=aftercare,
        COMFORT=comfort,
        RECONNECT=reconnect,
    )

# --------------------------------------------------
# CSV import route (unchanged logic – only calls new builders)
# --------------------------------------------------
INFLUENCER_ID_ALIASES = {"influencer id", "influencer_id", "persona id", "persona_id", "id"}
NICKNAME_ALIASES = {
    "m1) nickname you like being called (short)",
    "nickname",
    "preferred nickname",
    "pet name",
}


def is_empty_row(row: Dict[str, Optional[str]]) -> bool:
    return not any(str(v or "").strip() for v in row.values())


def row_to_csv_text(headers: List[str], row: Dict[str, Optional[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerow([(row.get(h) or "") for h in headers])
    return buffer.getvalue()


@router.post("/import-csv", response_model=ImportResponse)
async def import_persona_csv(
    file: UploadFile = File(...),
    save: bool = Query(False, description="If true, write prompt to Influencer.prompt_template"),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload a .csv exported from your persona builder.")
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV missing header row.")
    headers = reader.fieldnames
    normalized_headers = {normalize_key(h) for h in headers}
    if not normalized_headers & {normalize_key(a) for a in INFLUENCER_ID_ALIASES}:
        raise HTTPException(status_code=400, detail="CSV must include an 'Influencer_ID' column.")
    rows = list(reader)
    prompts: List[PromptItem] = []
    persona_path = Path(file.filename or "Persona.csv")
    brain_path = Path("Brain.csv")
    total_rows = 0
    for idx, row in enumerate(rows, start=2):
        if is_empty_row(row):
            continue
        total_rows += 1
        csv_text = row_to_csv_text(headers, row)
        try:
            system_prompt = compose_instructions(persona_path, csv_text, brain_path, csv_text)
            voice_prompt = compose_voice_prompt(persona_path, csv_text, brain_path, csv_text)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("Row %s failed", idx)
            raise HTTPException(status_code=400, detail=f"Row {idx}: {exc}")
        pm = load_persona_metadata(persona_path, csv_text)
        influencer_id = gather_value(pm, INFLUENCER_ID_ALIASES)
        name = gather_value(pm, ("full name", "name"))
        nickname = gather_value(pm, NICKNAME_ALIASES)
        if not influencer_id:
            raise HTTPException(status_code=400, detail=f"Row {idx}: missing Influencer_ID.")
        display_name = name or nickname or influencer_id
        prompts.append(
            PromptItem(
                influencer_id=influencer_id,
                name=name,
                nickname=nickname,
                system_prompt=system_prompt,
                raw_persona={k: (v if v is None else str(v)) for k, v in row.items()},
                voice_prompt=voice_prompt,
            )
        )
        if save:
            influencer = await db.get(Influencer, influencer_id)
            if influencer is None:
                influencer = Influencer(
                    id=influencer_id,
                    display_name=display_name,
                    prompt_template=system_prompt,
                    voice_prompt=voice_prompt,
                )
                db.add(influencer)
            else:
                influencer.prompt_template = system_prompt
                influencer.voice_prompt = voice_prompt
            try:
                assistant_id = await upsert_influencer_agent(
                    name=display_name,
                    instructions=system_prompt,
                    assistant_id=getattr(influencer, "influencer_gpt_agent_id", None),
                )
                influencer.influencer_gpt_agent_id = assistant_id
            except Exception as exc:  # pragma: no cover - OpenAI issues
                log.error("OpenAI sync failed for %s: %s", influencer_id, exc)
            agent_id = getattr(influencer, "influencer_agent_id_third_part", None)
            if agent_id:
                try:
                    await _push_prompt_to_elevenlabs(agent_id, voice_prompt)
                except HTTPException as e:
                    log.error("ElevenLabs sync failed for %s: %s", influencer.id, e.detail)
    if save and prompts:
        await db.commit()
    return ImportResponse(total_rows=total_rows, imported_count=len(prompts), prompts=prompts)
