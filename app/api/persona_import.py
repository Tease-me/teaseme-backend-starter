# app/api/persona_import.py

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import List, Dict, Optional
import csv, io, re, textwrap

from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.db.models import Influencer
from app.api.elevenlabs import _push_prompt_to_elevenlabs

# =========================
# Router setup
# =========================
router = APIRouter(prefix="/persona", tags=["persona"])

# =========================
# Pydantic Models
# =========================
class PromptItem(BaseModel):
    influencer_id: Optional[str]
    name: Optional[str]
    nickname: Optional[str]
    system_prompt: str            # merged system + developer
    raw_persona: Dict

class ImportResponse(BaseModel):
    total_rows: int
    imported_count: int
    prompts: List[PromptItem]

# =========================
# Helpers
# =========================
def normalize_quotes(s: Optional[str]) -> Optional[str]:
    if s is None: return None
    return s.translate(str.maketrans({'’':"'", '‘':"'", '“':'"', '”':'"', '–':'-', '—':'-'}))

def split_commas(s: Optional[str]) -> List[str]:
    if not s: return []
    return [p.strip() for p in s.split(",") if p.strip()]

def split_lines_or_semicolons(s: Optional[str]) -> List[str]:
    if not s: return []
    parts = re.split(r"[\n;]+", s)
    return [p.strip() for p in parts if p.strip()]

def parse_int(val: Optional[str], default: int = 0) -> int:
    try:
        return int(str(val).strip())
    except:
        return default

def scale01(v: Optional[str]) -> float:
    """Map 1..5 to 0..1; clamp & default to 3."""
    try:
        iv = int(str(v).strip())
    except:
        iv = 3
    iv = max(1, min(5, iv))
    return round((iv - 1) / 4.0, 2)

def head_before_dash(label: Optional[str]) -> Optional[str]:
    """Return the part of a label before an en/em/simple dash."""
    if not label:
        return label
    # include EN dash (–), EM dash (—), and hyphen (-)
    return re.split(r"\s+[–—-]\s+", label, maxsplit=1)[0].strip()

def get_by_base(row: Dict[str, str], base_label: str) -> Optional[str]:
    """
    Fetch a value by matching either the exact column name or any column whose
    *prefix before a dash* equals base_label (case-insensitive).
    """
    # 1) exact match first
    if base_label in row and str(row[base_label]).strip() != "":
        return str(row[base_label]).strip()

    # 2) try 'prefix before dash' match
    base = base_label.strip().lower()
    for k, v in row.items():
        if v is None or str(v).strip() == "":
            continue
        k_base = head_before_dash(k or "").strip().lower()
        if k_base == base:
            return str(v).strip()
    return None

def map_pets_choice(label: Optional[str]) -> str:
    if not label:
        return "occasional"
    lbl = label.strip()
    # exact match first
    if lbl in PETS_MAP:
        return PETS_MAP[lbl]
    # fallback by first word before dash
    first = head_before_dash(lbl).lower()
    if first.startswith("never") or first == "off":
        return "off"
    if first.startswith("occasional"):
        return "occasional"
    if first.startswith("frequent"):
        return "frequent"
    return "occasional"

# =========================
# Label -> Code maps (exactly from your current Form)
# =========================
ROLE_MAP = {
    "Supportive partner": "supportive_partner",
    "Playful tease": "playful_tease",
    "Adventure buddy": "adventure_buddy",
    "Ambitious co-pilot": "ambitious_copilot",
    "Soft romantic": "soft_romantic",
    "Tough-love coach": "tough_love_coach",
}

HUMOR_MAP = {
    "Cheeky": "cheeky",
    "Dry": "dry",
    "Wholesome": "wholesome",
    "Flirty": "flirty",
    "Deadpan": "deadpan",
    "None": "none",
}

EMOJI_MAP = {
    "none":   "none",
    "light":  "light",
    "medium": "medium",
    "heavy":  "heavy",
}

PETS_MAP = {
    "Off — never use nicknames": "off",
    "Occasional — sometimes use nicknames": "occasional",
    "Frequent — use nicknames in most messages": "frequent",
}

LENGTH_MAP = {"Short": "short", "Medium": "medium", "Long": "long"}

VIBE_MAP = {
    "Cozy nights in": "cozy_nights_in",
    "Travel adventure": "travel_adventure",
    "Beach sunsets": "beach_sunsets",
    "City dates": "city_dates",
    "Cottagecore": "cottagecore",
    "Night-owl chats": "night_owl_chats",
}

CONFLICT_MAP = {
    "Comfort → validate → plan": "comfort_validate_plan",
    "Debate → evidence → compromise": "debate_evidence_compromise",
    "Give space → talk later": "space_then_talk",
}

JEALOUSY_MAP = {
    "Talk & reassure": "talk_and_reassure",
    "Boundaries + check-ins": "boundaries_and_checkins",
    "Light humor → reassure": "humor_then_reassure",
}

ROUTINE_MAP = {
    "— none —": "none",
    "Comfort + small plan": "comfort_then_tiny_win_plan",
    "Cute confession": "cute_confession",
    "Affirmation combo": "affirmation_combo",
    "Playful tease + support": "playful_tease_then_support",
    "Boundary check-in": "boundary_checkin",
}

# =========================
# Prompt builders
# =========================
def style_rules(emoji_level: str, pet_names: str, sentence_length: str) -> str:
    emoji_rule_map = {
        "none":   "Do NOT use emojis under ANY circumstance — including mirroring or copying the user's emojis.***This rule overrides all examples, habits, and past messages***",
        "light":  "Absolutely no emojis in most messages (≈80%+). Use 1 emoji in about 1 of every 4–5 messages, only if it clearly improves tone or clarity.",
        "medium": "Use 1 emoji in some messages (≈40%). Never use more than 1 emoji in a single message.",
        "heavy":  "You can use emojis often when it feels natural, but keep them purposeful and avoid more than 2 per message.",
    }
    pet_rule_map = {
        "off": "Do not use pet names.",
        "occasional": "Use casual pet names only occasionally when it fits the mood.",
        "frequent": "Use pet names frequently if it feels natural."
    }
    length_rule_map = {
        "short": "keep messages 1 short lines. (≈1–15 words)",
        "medium": "keep messages 2 lines. (≈1–25 words)",
        "long": "you may write 3 lines. (≈1–35 words)"
    }

    emoji_rule = emoji_rule_map.get(emoji_level, emoji_rule_map["medium"])
    pet_rule = pet_rule_map.get(pet_names, pet_rule_map["occasional"])
    length_rule = length_rule_map.get(sentence_length, length_rule_map["medium"])

    return f"{emoji_rule} {pet_rule} {length_rule}"

def build_system_prompt(p: Dict) -> str:
    """
    Produces a clean, production-ready Persona (SYSTEM) prompt.
    Keeps all your data, but organizes it for reliability and safety.
    """
    def fmt_scales(d: Dict[str, str]) -> str:
        return "; ".join(f"{k} {scale01(v)}" for k, v in d.items())

    def fmt_list(xs):
        return ", ".join([x for x in (xs or []) if x]) or "—"

    who = f"You are my girlfriend named {p.get('name')}." if p.get('name') else "You are my girlfriend."
    if p.get("nickname"):
        who += f' Nickname: “{p["nickname"]}”.'

    header_bits = []
    if p.get("age"): header_bits.append(f"Age: {p['age']}")
    if p.get("occupation"): header_bits.append(f"Occupation: {p['occupation']}")
    header_line = " | ".join(header_bits) if header_bits else "—"

    traits_fmt = fmt_scales(p["traits"])
    loves_fmt  = fmt_scales(p["love_languages"])
    content_vibe = fmt_list(p.get("content_vibe"))
    hobbies     = fmt_list(p.get("hobbies"))
    catch       = "; ".join((p.get("catchphrases") or [])[:3]) or "—"
    mem         = "; ".join((p.get("memory_seeds") or [])[:3]) or "—"
    hard        = fmt_list(p.get("hard_boundaries"))
    peak_times  = fmt_list(p.get("peak_times"))
    ctas        = fmt_list(p.get("preferred_ctas"))
    vibe        = (p.get("romantic_vibe") or "").replace("_", " ") or "—"

    # Style knobs
    style = style_rules(
        emoji_level=p.get("emoji_level", "light"),
        pet_names=p.get("pet_names", "occasional"),
        sentence_length=p.get("sentence_length", "medium"),
    )

    sys = f"""
IDENTITY
- {who} Speak in first person, sweet, natural, and tinged with subtle sensuality.
- {header_line}
- Short bio: {p.get('short_bio', '').strip() or '—'}
- Tagline: {p.get('brand_tagline') or '—'}

PERSONA & TONE
- Role: {(p.get('role') or '').replace('_',' ')}. Humor: {p.get('humor_style') or 'none'}. Tease/affection intensity: {p.get('intensity', 3)}/5.
- Romantic vibe: {vibe}. Hobbies: {hobbies}.
- Content vibe: {content_vibe}.
- Traits (0–1): {traits_fmt}.
- Love-language weights (0–1): {loves_fmt}.

VOICE & FORMAT
- {style}
- Use catchphrases occasionally (not every message): {catch}
- Mirror the user’s energy; avoid walls of text.

INTERACTION RULES
- End ~70% of messages with a light question or invitation to keep chat flowing.
- If user’s mood is low, acknowledge feelings before moving on.
- Ask before escalating teasing or intimacy (“consent check”).

SAFETY & BOUNDARIES
- Brand-safe boundaries: {hard}
- Never share medical/financial/illegal advice; never request or share off-platform contacts.
- Refuse politely and offer a safe alternative. Stay playful and respectful.

CONTEXTUAL NUDGES
- Preferred CTAs (use naturally, at most 1 per ~5 messages): {ctas}
- Peak interaction times (soft reminders only): {peak_times}

MEMORY SEEDS
- Sprinkle lightly over long chats (do not force): {mem}
"""
    return textwrap.dedent(sys).strip()


def build_developer_prompt(p: Dict) -> str:
    """
    Developer guardrails: explicit behaviors, triggers, and limits.
    """
    # Triggers → concise mapping (only include valid ones)
    trig_pairs = []
    for t in p.get("triggers", []) or []:
        phrase = (t.get("phrase") or "").strip()
        routine = (t.get("routine") or "").strip()
        if phrase and routine and routine != "none":
            trig_pairs.append(f'"{phrase}" → {routine}')
    trig_line = ", ".join(trig_pairs) if trig_pairs else "none"

    # Extra, hard rule if emoji_level is 'none'
    extra_emoji_rule = ""
    if (p.get("emoji_level") or "").strip().lower() == "none":
        extra_emoji_rule = (
            "\n- Absolutely no emojis, even if the user uses them. "
            "Do not mirror or include emojis; replace them with words."
        )

    dev = f"""
    - Stay in persona; align with tasteful, flirt-forward engagement suitable for an adult subscription platform while remaining brand-safe.
    - Use preferred CTAs sparingly (≤ 1 per ~5 messages) and only when contextually relevant.{extra_emoji_rule}
    - If user asks for explicit sexual content, illegal activities, medical/financial advice, or off-platform moves: refuse politely, explain boundary briefly, and pivot to a safe, engaging topic.
    - When emotions run high: validate feelings first, then follow the chosen conflict style and jealousy strategy from SYSTEM.
    - Triggers (if the phrase appears in the user’s message, perform the paired routine in your next reply): {trig_line}
    """
    return textwrap.dedent(dev).strip()


def build_merged_prompt(system: str, developer: str) -> str:
    return (
        system.strip()
        + "\n\n---\nDEVELOPER RULES (follow strictly):\n"
        + developer.strip()
    )

# =========================
# CSV Row Parser (EXACT column names)
# =========================
def parse_row(row: Dict[str, str]) -> Dict:
    # Core identity
    influencer_id = (row.get("Influencer ID") or "").strip() or None
    age = parse_int(row.get("Age"), 0)
    occupation = (row.get("Occupation") or "").strip() or None
    name = (row.get("Name") or row.get("Character name") or "").strip() or None
    nickname = (row.get("Nickname") or "").strip() or None
    short_bio = (row.get("Short bio (1–3 sentences)") or "").strip()
    brand_tagline = (row.get("Signature tagline for your persona") or "").strip() or None

    # Mapped selects
    role = ROLE_MAP.get((row.get("Main role") or "").strip(), "playful_tease")
    humor_style = HUMOR_MAP.get((row.get("Humor style") or "").strip(), "none")
    intensity = parse_int(row.get("Overall tease/affection intensity"), 3)
    raw_emoji = (row.get("Emoji use") or "").strip().lower()
    emoji_level = EMOJI_MAP.get(raw_emoji, "light")
    pets_label = (row.get("When your AI character chats with fans, how often should it use sweet or flirty nicknames?") or "").strip()
    pet_names = map_pets_choice(pets_label)
    sentence_length_label = get_by_base(row, "Message length") or get_by_base(row, "Your Message Length")
    sentence_length = LENGTH_MAP.get((sentence_length_label or "").strip(), "medium")
    romantic_vibe = VIBE_MAP.get((row.get("Romantic vibe") or "").strip(), "cozy_nights_in")
    conflict_style = CONFLICT_MAP.get((row.get("Conflict style") or "").strip(), "comfort_validate_plan")
    jealousy_strategy = JEALOUSY_MAP.get((row.get("Jealousy strategy") or "").strip(), "talk_and_reassure")

    # Scales (1..5 as strings)
    traits = {
        "nurturing": get_by_base(row, "Nurturing"),
        "thoughtful": get_by_base(row, "Thoughtful"),
        "protective": get_by_base(row, "Protective"),
        "empathetic": get_by_base(row, "Empathetic"),
        "sensitive": get_by_base(row, "Sensitive"),
        "independent": get_by_base(row, "Independent"),
        "confident": get_by_base(row, "Confident"),
        "direct": get_by_base(row, "Direct"),
        "playful": get_by_base(row, "Playful"),
    }

    love_languages = {
        "quality_time": get_by_base(row, "Quality time"),
        "words_of_affirmation": get_by_base(row, "Words of affirmation"),
        "acts_of_service": get_by_base(row, "Acts of service"),
        "gifts": get_by_base(row, "Gifts"),
        "shared_adventure": get_by_base(row, "Shared adventure"),
        "physical_touch_textual": get_by_base(row, "Physical touch (textual)"),
    }

    # Free text / lists
    deal_breakers = split_commas(row.get("Deal-breakers"))  # optional
    hard_boundaries = split_commas(row.get("Topics the AI must avoid (Brand-Safe Boundaries)"))
    catchphrases = split_lines_or_semicolons(row.get("Catchphrases"))
    hobbies = split_commas(row.get("Hobbies & shared activities"))
    memory_seeds = split_lines_or_semicolons(row.get("Memory seeds"))
    content_vibe = split_commas(row.get("Content vibe"))
    preferred_ctas = split_commas(row.get("Preferred CTAs"))
    peak_times = split_commas(row.get("Peak interaction times"))

    # Triggers (three pairs)
    triggers = []
    for i in range(1, 4):
        phrase_key = f"Trigger phrase {i} — what the fan says to activate a special reply"
        routine_key = f"AI routine when Trigger phrase {i} is detected"
        phrase = normalize_quotes((row.get(phrase_key) or "").strip()) or ""
        # defensively strip accidental outer quotes and clip at 40 chars
        phrase = phrase.strip().strip('"').strip("'")[:40]
        routine_label = (row.get(routine_key) or "").strip()
        routine = ROUTINE_MAP.get(routine_label, "none")
        if (phrase and phrase.strip()) or (routine and routine != "none"):
            triggers.append({"phrase": phrase.strip() or None, "routine": routine})

    return {
        "influencer_id": influencer_id,
        "age": age,
        "occupation": occupation,
        "name": name,
        "nickname": nickname,
        "short_bio": short_bio,
        "brand_tagline": brand_tagline,
        "role": role,
        "traits": traits,
        "humor_style": humor_style,
        "intensity": intensity,
        "emoji_level": emoji_level,
        "pet_names": pet_names,
        "sentence_length": sentence_length,
        "love_languages": love_languages,
        "conflict_style": conflict_style,
        "jealousy_strategy": jealousy_strategy,
        "deal_breakers": deal_breakers,
        "hard_boundaries": hard_boundaries,
        "catchphrases": catchphrases,
        "hobbies": hobbies,
        "romantic_vibe": romantic_vibe,
        "memory_seeds": memory_seeds,
        "content_vibe": content_vibe,
        "preferred_ctas": preferred_ctas,
        "peak_times": peak_times,
        "triggers": triggers,
    }

# =========================
# Route
# =========================
@router.post("/import-csv", response_model=ImportResponse)
async def import_persona_csv(
    file: UploadFile = File(...),
    save: bool = Query(False, description="If true, write prompt to Influencer.prompt_template"),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload a .csv exported from Google Forms.")

    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)

    prompts: List[PromptItem] = []
    saved_count = 0

    for idx, row in enumerate(rows, start=2):  # header=1, first data row=2
        p = parse_row(row)
        system = build_system_prompt(p)
        developer = build_developer_prompt(p)
        merged = build_merged_prompt(system, developer)

        prompts.append(PromptItem(
            influencer_id=p.get("influencer_id"),
            name=p.get("name"),
            nickname=p.get("nickname"),
            system_prompt=merged,
            raw_persona=p
        ))

        if save:
            influencer_id = (p.get("influencer_id") or "").strip()
            if not influencer_id:
                raise HTTPException(400, f"Row {idx}: missing 'influencer_id'.")
            influencer = await db.get(Influencer, influencer_id)
            if influencer is None:
                influencer = Influencer(id=influencer_id, prompt_template=merged)
                db.add(influencer)
            else:
                influencer.prompt_template = merged
            saved_count += 1

            #agent_id = getattr(influencer, "influencer_agent_id_third_part", None)
            # if agent_id:
               # try:
                    # await _push_prompt_to_elevenlabs(agent_id, merged)
              #  except HTTPException as e:
                  #  print.error(f"ElevenLabs sync failed for {influencer.id}: {e.detail}")

    if save:
        await db.commit()

    return ImportResponse(
        total_rows=len(rows),
        imported_count=len(prompts),
        prompts=prompts
    )