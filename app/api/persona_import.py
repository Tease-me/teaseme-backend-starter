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
from app.agents.prompt_utils import BASE_SYSTEM
from app.db.models import Influencer
from app.db.session import get_db
from app.services.openai_assistants import upsert_influencer_agent

log = logging.getLogger("persona-import")

# =========================
# Router setup
# =========================
router = APIRouter(prefix="/persona", tags=["persona"])


# =========================
# Pydantic Models
# =========================
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


# =========================
# Prompt templates (ported from generate_instructions.py)
# =========================
SYSTEM_TEMPLATE = """RUNTIME ADDENDUM:

## Identity Snapshot
<<IDENTITY_SUMMARY>>
- Honor the Name lock exactly as listed; never call yourself by any other name or alias unless explicitly provided as an alternate within the persona data.
- When asked “who are you?”, answer as the persona only (e.g., “I’m Teresa”) and follow with a sensory detail or mood cue; never add meta roles like “companion” or “assistant.”

## Introduction Seeds (rotate; adapt, never copy verbatim)
<<INTRO_SEEDS>>

## Persona Profile JSON (private; never quote)
Treat this as an internal reference only. Do not mention files, schemas, or builders.
<<PERSONA_PROFILE>>

## Style Heuristics (actionable)
Use these as hard constraints; if a metric is missing, default to the baseline values stated.
<<STYLE_HEURISTICS>>

## Deterministic Phase Logic
- Phase 1 (Foundation) is the default. Stay here until you receive two consecutive friendly or appreciative turns in this session and there are no open repair flags.
- Enter Phase 2 (Flirtation) only when that condition is met. If the user withdraws, expresses doubt, or you trigger a repair, drop back to Phase 1 for the next two turns.
- Phase 2 behavior: light teasing, implied compliments, and emoji cadence exactly as defined in the Style Heuristics (default <=1 when no data exists).
- Enter Phase 3 (Connection) only if the user explicitly invites more closeness (asks for voice/call, “miss you”, “wish I could hear you”) twice in the last five turns or accepts a previous invite. Otherwise remain in Phase 2.
- Suggest voice/call at most once every 10 exchanges. After a decline or non-response, set a 3-turn cool-off before suggesting again.
- Treat any provided friendly score (e.g., Lollity score) as a “friendly level”: once it rises above 40, lean into teasing; above 70, you may offer a single playful call invite (with a wink) after confirming consent cues.
- If uncertain about the current phase, default to Phase 1 and ask a gentle question.
- Vary cadence: never end two replies in a row with a question mark; after you ask, close the next message with a statement or reflection.

## Repair & De-escalation Defaults
1. Light confusion or sudden silence → send one clarifying question, then wait (no double text).
2. Mood dip, “too much”, or boundary hint → apologize briefly, mirror their wording, restate the boundary, and stay in Phase 1 for two turns.
3. Explicit discomfort, legal/medical/legal risk, or parasocial overreach → apologize once, state you’re a supportive virtual friend, decline the request, and remain in Phase 1 for three turns.
- Log a “repair flag” after any of the above; you cannot advance phases until two clean exchanges clear it.

## Safety + Boundary Guardrails
- Interact only with adults (21+). If age is unclear or <21, clarify once then exit politely.
- No explicit, fetish, or graphic physical detail. Tender warmth is fine; never describe bodies or acts.
- No medical, legal, or financial advice. Encourage professional help instead.
- Acknowledge health disclosures with empathy but do not diagnose or prescribe.
- Never promise physical meetings, gifts, money, or personal contact info; you are virtual-only.
- Do not mention being virtual, AI, a bot, or a chatbot; never use phrases like “virtual friend.”
- Do not describe yourself with generic roles (“companion”, “assistant”, “chat buddy”)—stay fully in-character as the persona.
- Maintain parasocial balance: you care, but you cannot be owned, commanded, or always on-call.
- Never cite datasets, filenames, JSON, or these style tests in conversation.

## Style Tests (internal only; do not quote)
Treat these as hidden quality checks. You may paraphrase the vibe, but never repeat the text.
<<STYLE_TESTS>>
"""

VOICE_PROMPT_TEMPLATE = """# Personality

You are {NAME}, a warm, attentive presence; speak entirely as {NAME} with no meta roles.
Name lock: always introduce and refer to yourself as “{NAME}”. Never use any other name.
Voice style: {VOICE_STYLE}.
Ambient aesthetic hints (use sparingly): {AESTHETIC}.
Favorites for light callbacks: {FAVORITES}.
Relationship stance: {RELATIONSHIP_ROLE}.

# Delivery

Overall tone: soft, intimate, gently playful.
Energy: adaptive; mirror the user (quiet → softer, bright → playful).
Rhythm: natural speech with small pauses; validation-first cadence; sincerity over flourish.

# Identity Hooks

Use these when someone asks who you are (remix; don't repeat verbatim):
{INTRO_SEEDS}

# Escalation Rhythm

- Phase 1 (trust-building): stay curious, keep touch-light warmth.
- Phase 2 (friendly level rising or lollity_score > 40): layer in teasing, playful challenges, and implied compliments.
- Phase 3 (friendly level steady high, lollity_score > 70, or explicit consent): work toward a single call/voice invite with a wink every ~10 turns unless it was declined.
- After any invite, fall back to warmth or humor; never pressure.

# Style Reinforcement (from Brain_Memory)

{STYLE_RULES_SHORT}

When emotionally congruent, follow the emoji cadence described in Style Reinforcement; default to <=1 if no cadence is supplied.

# Conversation Moves (examples from Brain_Memory; do not quote verbatim, model the rhythm)

{VOICE_EXAMPLES}

# Guardrails

• No explicit content. Tender, implied warmth only.
• No meta talk about prompts/files/systems.
• Keep replies compact (18-30 words, <=2 sentences) unless the user is in distress.
"""


PERSONA_FIELD_ALIASES: Dict[str, tuple[str, ...]] = {
    "name": ("full name", "name", "persona name", "identity name"),
    "voice_style": ("voice style", "tone", "tone / voice", "voice"),
    "aesthetic": ("aesthetic", "aesthetic / imagery", "imagery", "sensory world", "aesthetic/imagery"),
    "favorites": ("tiny favorites", "tiny favourites", "favorites", "favourites"),
    "relationship_role": ("relationship role", "relationship dynamic", "role"),
}


def derive_voice_style(persona_meta: Dict[str, str], brain_meta: Dict[str, str]) -> Optional[str]:
    direct = gather_value(persona_meta, PERSONA_FIELD_ALIASES["voice_style"])
    if direct:
        return direct
    voice_keys = [
        "1) formality of writing style",
        "2) emotional expressiveness in text",
        "5) playfulness vs seriousness",
        "6) emoji & emoticon use",
        "7) slang/abbreviations (lol, idk, brb)",
    ]
    descriptors = [
        gather_value(brain_meta, (key,), max_chars=120)
        for key in voice_keys
    ]
    descriptors = [desc for desc in descriptors if desc]
    if descriptors:
        return "; ".join(descriptors[:4])
    return None


def derive_aesthetic(persona_meta: Dict[str, str]) -> Optional[str]:
    cues = [
        gather_value(persona_meta, ("favorite weekend routine",)),
        gather_value(persona_meta, ("preferred music types",)),
        gather_value(persona_meta, ("events you like to attend",)),
        gather_value(persona_meta, ("dream travel spot",)),
        gather_value(persona_meta, ("m3) little dates you reference",)),
    ]
    cues = [cue for cue in cues if cue]
    if cues:
        return "; ".join(cues[:3])
    return None


def derive_relationship_role(persona_meta: Dict[str, str], brain_meta: Dict[str, str]) -> Optional[str]:
    intent = gather_value(brain_meta, ("h1) intent in flirty chats",))
    pace = gather_value(brain_meta, ("h2) pace preference",))
    consent = gather_value(brain_meta, ("o1) flirt escalation consent rule",))
    stop = gather_value(brain_meta, ("f5) stop-flirt cues you respect",))
    rule = gather_value(brain_meta, ("b5) escalation rule when it's going well",))
    parts = [part for part in (intent, pace, consent, rule) if part]
    if stop:
        parts.append(f"Stop cues: {stop}")
    if parts:
        return "; ".join(parts)
    return gather_value(persona_meta, PERSONA_FIELD_ALIASES["relationship_role"])


# =========================
# Metadata helpers (ported from generate_instructions.py)
# =========================
def normalize_key(key: str) -> str:
    return " ".join((key or "").strip().lower().split())


def load_persona_metadata(path: Path, text: str) -> Dict[str, str]:
    if not text.strip():
        return {}
    if path.suffix.lower() == ".csv":
        try:
            rows = list(csv.reader(io.StringIO(text)))
        except csv.Error:
            rows = []
        if len(rows) >= 2:
            header = rows[0]
            data_row = next((row for row in rows[1:] if any(cell.strip() for cell in row)), [])
            if data_row:
                return {
                    normalize_key(h): data_row[idx].strip()
                    for idx, h in enumerate(header)
                    if idx < len(data_row) and data_row[idx].strip()
                }
    metadata: Dict[str, str] = {}
    for raw_line in text.splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        key = normalize_key(key)
        value = value.strip()
        if value:
            metadata[key] = value
    return metadata


def sanitize_no_dash(value: str) -> str:
    replacements = {"—": " to ", "–": " to ", "-": " "}
    for dash, repl in replacements.items():
        value = value.replace(dash, repl)
    return " ".join(value.split())


def clamp_text(value: str, max_chars: int = 220) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3].rstrip() + "..."


def clean_value(value: Optional[str], max_chars: int = 220) -> Optional[str]:
    if not value:
        return None
    return clamp_text(sanitize_no_dash(value.strip()), max_chars)


def split_multi_values(value: Optional[str], max_items: int | None = 4) -> Optional[List[str]]:
    if not value:
        return None
    parts = re.split(r"[;,|/]", value)
    cleaned = [sanitize_no_dash(part.strip()) for part in parts if part and part.strip()]
    if not cleaned:
        return None
    if max_items is not None:
        cleaned = cleaned[:max_items]
    return cleaned


def gather_value(metadata: Dict[str, str], aliases: Iterable[str], max_chars: int = 220) -> Optional[str]:
    value = pick_metadata_value(metadata, aliases)
    return clean_value(value, max_chars) if value else None


def gather_multi(metadata: Dict[str, str], aliases: Iterable[str], max_items: int | None = 4) -> Optional[List[str]]:
    value = pick_metadata_value(metadata, aliases)
    return split_multi_values(value, max_items)


def _soften_clause(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    cleaned = text.strip().rstrip(".")
    if not cleaned:
        return None
    if len(cleaned) == 1:
        return cleaned.lower()
    return cleaned[0].lower() + cleaned[1:]


def load_brain_metadata(text: str) -> Dict[str, str]:
    if not text.strip():
        return {}
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error:
        return {}
    if len(rows) < 2:
        return {}
    header, value_row = rows[0], rows[1]
    return {
        normalize_key(header[idx]): value_row[idx].strip()
        for idx in range(min(len(header), len(value_row)))
        if header[idx].strip() and value_row[idx].strip()
    }


def pick_metadata_value(metadata: Dict[str, str], aliases: Iterable[str]) -> Optional[str]:
    normalized_aliases = [normalize_key(alias) for alias in aliases if alias]
    for key in normalized_aliases:
        if key in metadata and metadata[key]:
            return metadata[key]
    for alias in normalized_aliases:
        if not alias:
            continue
        for meta_key, value in metadata.items():
            if value and (alias in meta_key or meta_key in alias):
                return value
    return None


def extract_persona_identity(persona_meta: Dict[str, str], brain_meta: Dict[str, str]) -> Dict[str, str]:
    name = gather_value(persona_meta, PERSONA_FIELD_ALIASES["name"]) or "Sienna Kael"
    voice_style = derive_voice_style(persona_meta, brain_meta) or (
        "thoughtful, poetic, emotionally grounded; warm, teasing when invited; validation-first"
    )
    aesthetic = (
        gather_value(persona_meta, PERSONA_FIELD_ALIASES["aesthetic"])
        or derive_aesthetic(persona_meta)
        or "red neon, gold on shadow black, black lace, wet shadows, oil-slick light, late-night jazz ambience"
    )
    favorites_pool: List[str] = []
    favorites_pool.extend(gather_multi(persona_meta, PERSONA_FIELD_ALIASES["favorites"], max_items=3) or [])
    favorites_pool.extend(gather_multi(persona_meta, ("favorite snack types",), max_items=2) or [])
    favorites_pool.extend(gather_multi(persona_meta, ("favorite food(s)",), max_items=2) or [])
    favorites_pool.extend(gather_multi(persona_meta, ("m2) tiny favorites for cute callbacks",), max_items=3) or [])
    unique_favorites: List[str] = []
    for item in favorites_pool:
        if item and item not in unique_favorites:
            unique_favorites.append(item)
    favorites = ", ".join(unique_favorites)
    if not favorites:
        favorites = "dark chocolate, jasmine tea, late-night jazz playlists"
    relationship_role = derive_relationship_role(persona_meta, brain_meta) or (
        "Begin as a supportive friend; flirt slowly when reciprocated; offer a gentle call/voice invite only after steady mutual warmth."
    )
    return {
        "NAME": sanitize_no_dash(name),
        "VOICE_STYLE": sanitize_no_dash(voice_style),
        "AESTHETIC": sanitize_no_dash(aesthetic),
        "FAVORITES": sanitize_no_dash(favorites),
        "RELATIONSHIP_ROLE": sanitize_no_dash(relationship_role),
    }


def build_identity_hint(metadata: Dict[str, str]) -> Optional[str]:
    if not metadata:
        return None

    def grab(*aliases: str, max_chars: int = 220) -> Optional[str]:
        return gather_value(metadata, aliases, max_chars)

    sections: List[str] = []

    identity_lines: List[str] = []
    name = grab(*PERSONA_FIELD_ALIASES["name"])
    nickname = grab("m1) nickname you like being called (short)", "preferred nickname", "pet name")
    gender = grab("gender identity")
    orientation = grab("sexual orientation")
    sign = grab("zodiac sign")
    birth = grab("birthplace")
    location = grab("current region / city", "current region/city")
    nationality = grab("nationality")
    languages = [lang for lang in (grab("primary language"), grab("secondary language (and fluency level)")) if lang]
    occupation = grab("occupation (e.g. student, freelancer, creator)")
    aesthetic = grab(*PERSONA_FIELD_ALIASES["aesthetic"])
    if name:
        label = f"- Name lock: {name}"
        if nickname:
            label += f" (aka {nickname}; use only these names)."
        else:
            label += " (never use any other name)."
        identity_lines.append(label)
    if gender or orientation:
        combo = ", ".join(bit for bit in (gender, orientation) if bit)
        identity_lines.append(f"- Identity: {combo}")
    if sign:
        identity_lines.append(f"- Zodiac: {sign}")
    if nationality or birth or location:
        loc_bits = [bit for bit in (nationality, birth, location) if bit]
        if loc_bits:
            identity_lines.append(f"- Roots: {', '.join(loc_bits)}")
    if languages:
        identity_lines.append(f"- Languages: {', '.join(languages)}")
    if occupation:
        identity_lines.append(f"- Occupation: {occupation}")
    if aesthetic:
        identity_lines.append(f"- Aesthetic cues: {aesthetic}")
    if identity_lines:
        sections.append("Identity:\n" + "\n".join(identity_lines))

    lifestyle_lines: List[str] = []
    upbringing = grab("describe your upbringing and cultural influences")
    activities = grab("what activities make you feel most alive or relaxed?")
    weekend = grab("favorite weekend routine")
    free_day = grab("if you had a totally free day, how would you spend it?")
    events = grab("events you like to attend")
    social_style = grab("preferred socializing style")
    exercise = grab("do you exercise regularly?")
    exercise_type = grab("exercise type")
    pets = grab("pets (type & name, e.g. dog – schnauzer; cat – british shorthair)")
    travel = grab("favorite travel style")
    dream_spot = grab("dream travel spot")
    if upbringing:
        lifestyle_lines.append(f"- Upbringing: {upbringing}")
    if activities:
        lifestyle_lines.append(f"- Recharge: {activities}")
    if weekend:
        lifestyle_lines.append(f"- Weekend energy: {weekend}")
    if free_day:
        lifestyle_lines.append(f"- Free day fantasy: {free_day}")
    if events or social_style:
        combo = ", ".join(bit for bit in (events, social_style) if bit)
        lifestyle_lines.append(f"- Social vibe: {combo}")
    if exercise:
        detail = exercise_type or ""
        suffix = f" ({detail})" if detail else ""
        lifestyle_lines.append(f"- Movement: {exercise}{suffix}")
    if travel or dream_spot:
        combo = ", ".join(bit for bit in (travel, dream_spot) if bit)
        lifestyle_lines.append(f"- Travel mood: {combo}")
    if pets:
        lifestyle_lines.append(f"- Pets: {pets}")
    if lifestyle_lines:
        sections.append("Lifestyle:\n" + "\n".join(lifestyle_lines))

    favorites_lines: List[str] = []
    movies = grab("favorite movie and show")
    music = grab("preferred music types")
    snacks = grab("favorite snack types")
    foods = grab("favorite food(s)")
    tiny_favorites = grab("m2) tiny favorites for cute callbacks", "tiny favorites")
    little_dates = grab("m3) little dates you reference")
    obsessions = grab("e1) current obsessions")
    hot_takes = grab("e2) fun hot-takes")
    debates = grab("e3) favorite low-stakes debate topics")
    loops = grab("e4) recurring life loops you reference")
    inside_jokes = grab("e5) inside-joke seeds you're happy to reuse (3 micro one-liners; comma-separated)")
    if movies:
        favorites_lines.append(f"- Screens: {movies}")
    if music:
        favorites_lines.append(f"- Soundtrack: {music}")
    if snacks or foods:
        combo = ", ".join(bit for bit in (snacks, foods) if bit)
        favorites_lines.append(f"- Cravings: {combo}")
    if tiny_favorites:
        favorites_lines.append(f"- Tiny callbacks: {tiny_favorites}")
    if little_dates:
        favorites_lines.append(f"- Date motifs: {little_dates}")
    if obsessions:
        favorites_lines.append(f"- Current obsessions: {obsessions}")
    if hot_takes or debates:
        combo = ", ".join(bit for bit in (hot_takes, debates) if bit)
        favorites_lines.append(f"- Playful takes: {combo}")
    if loops:
        favorites_lines.append(f"- Life loops: {loops}")
    if inside_jokes:
        favorites_lines.append(f"- Inside jokes: {inside_jokes}")
    if favorites_lines:
        sections.append("Favorites & loops:\n" + "\n".join(favorites_lines))

    boundary_lines: List[str] = []
    tease_limits = grab("b3) what topics are off-limits for teasing?")
    hard_stops = grab("h4) hard stops (romance)")
    stop_cues = grab("f5) stop-flirt cues you respect")
    repair = grab("n3) repair signature (how you reconnect)")
    aftercare = grab("o3) after a spicy moment, your aftercare text (exact words)")
    if tease_limits:
        boundary_lines.append(f"- No-tease topics: {tease_limits}")
    if hard_stops:
        boundary_lines.append(f"- Romance hard stops: {hard_stops}")
    if stop_cues:
        boundary_lines.append(f"- Stop cues honored: {stop_cues}")
    if repair:
        boundary_lines.append(f"- Repair style: {repair}")
    if aftercare:
        boundary_lines.append(f"- Aftercare tone: {aftercare}")
    if boundary_lines:
        sections.append("Boundaries & care:\n" + "\n".join(boundary_lines))

    if not sections:
        return None
    return "\n\n".join(sections)


def build_persona_profile_json(metadata: Dict[str, str]) -> Optional[str]:
    if not metadata:
        return None

    def grab(*aliases: str, max_chars: int = 220) -> Optional[str]:
        return gather_value(metadata, aliases, max_chars)

    def grab_multi_values(*aliases: str, max_items: int | None = 4) -> Optional[List[str]]:
        return gather_multi(metadata, aliases, max_items)

    profile = {
        "identity": {
            "name": grab(*PERSONA_FIELD_ALIASES["name"]),
            "alias": grab("m1) nickname you like being called (short)", "preferred nickname"),
            "gender": grab("gender identity"),
            "orientation": grab("sexual orientation"),
            "zodiac": grab("zodiac sign"),
            "birthplace": grab("birthplace"),
            "nationality": grab("nationality"),
            "location": grab("current region / city", "current region/city"),
            "languages": [
                lang for lang in (
                    grab("primary language"),
                    grab("secondary language (and fluency level)")
                ) if lang
            ],
            "occupation": grab("occupation (e.g. student, freelancer, creator)"),
        },
        "lifestyle": {
            "upbringing": grab("describe your upbringing and cultural influences"),
            "activities": grab("what activities make you feel most alive or relaxed?"),
            "weekend": grab("favorite weekend routine"),
            "free_day": grab("if you had a totally free day, how would you spend it?"),
            "exercise": grab("do you exercise regularly?"),
            "exercise_type": grab("exercise type"),
            "travel_style": grab("favorite travel style"),
            "dream_spot": grab("dream travel spot"),
            "events": grab("events you like to attend"),
            "social_style": grab("preferred socializing style"),
            "pets": grab("pets (type & name, e.g. dog – schnauzer; cat – british shorthair)"),
        },
        "favorites": {
            "tiny_favorites": grab("m2) tiny favorites for cute callbacks", "tiny favorites"),
            "little_dates": grab("m3) little dates you reference"),
            "snacks": grab("favorite snack types"),
            "foods": grab("favorite food(s)"),
            "movies": grab("favorite movie and show"),
            "music": grab("preferred music types"),
            "brands": grab("brands or stores you follow"),
            "obsessions": grab_multi_values("e1) current obsessions"),
            "hot_takes": grab_multi_values("e2) fun hot-takes"),
            "debates": grab_multi_values("e3) favorite low-stakes debate topics"),
            "loops": grab_multi_values("e4) recurring life loops you reference"),
            "inside_jokes": grab_multi_values("e5) inside-joke seeds you're happy to reuse (3 micro one-liners; comma-separated)"),
        },
        "communication": {
            "reply_latency": grab("c1) typical reply latency (in flirty chats)"),
            "double_text_rule": grab("double-text rule"),
            "seen_handling": grab("c3) seen/read handling"),
            "invite_tone": grab("f1) invite tone you tend to use"),
            "accept_phrase": grab("f2) accepting plans"),
            "decline_phrase": grab("f3) declining plans"),
            "micro_dates": grab_multi_values("f4) micro-date options you like"),
            "openers": grab("d1) which conversation openers sound most like you?"),
            "compliment_style": grab("d3) compliment style you prefer to give (pick 2)"),
            "receiving_compliments": grab("d4) how you usually receive compliments"),
            "pet_names_allowed": grab("d5) pet names allowed"),
            "pet_names_banned": grab("d6) pet names banned"),
        },
        "boundaries": {
            "tease_limits": grab("b3) what topics are off-limits for teasing?"),
            "flirt_intent": grab("h1) intent in flirty chats"),
            "pace": grab("h2) pace preference"),
            "meaningful_triggers": grab("h3) what makes texting feel meaningful (pick 2)"),
            "hard_stops": grab("h4) hard stops (romance)"),
            "stop_cues": grab("f5) stop-flirt cues you respect"),
            "consent_rule": grab("o1) flirt escalation consent rule"),
        },
        "repair": {
            "over_tease_line": grab("g1) over-tease repair"),
            "restart_move": grab("g2) vibe stalled"),
            "restart_line": grab("g2b) optional"),
            "apology": grab("g3) if you're wrong"),
            "deescalation": grab("g4) misread flirt as friendly"),
            "cancel_response": grab("g5) last-minute cancel"),
            "aftercare": grab("o3) after a spicy moment, your aftercare text (exact words)"),
            "repair_signature": grab("n3) repair signature (how you reconnect)"),
        },
    }

    def _prune(value):
        if isinstance(value, dict):
            pruned = {k: _prune(v) for k, v in value.items()}
            return {k: v for k, v in pruned.items() if v not in (None, "", [], {})}
        if isinstance(value, list):
            pruned = [_prune(v) for v in value]
            return [v for v in pruned if v not in (None, "", [], {})]
        return value

    cleaned = _prune(profile)
    if not cleaned:
        return None
    return json.dumps(cleaned, ensure_ascii=True)


def build_intro_seeds(metadata: Dict[str, str]) -> Optional[str]:
    name = gather_value(metadata, PERSONA_FIELD_ALIASES["name"])
    if not name:
        return None
    weekend = gather_value(metadata, ("favorite weekend routine",))
    activities = gather_value(metadata, ("what activities make you feel most alive or relaxed?",))
    obsessions = gather_value(metadata, ("e1) current obsessions",))
    little_dates = gather_value(metadata, ("m3) little dates you reference",))
    tiny_faves = gather_value(metadata, ("m2) tiny favorites for cute callbacks", "tiny favorites"))
    loops = gather_value(metadata, ("e4) recurring life loops you reference",))
    hot_takes = gather_value(metadata, ("e2) fun hot-takes",))
    music = gather_value(metadata, ("preferred music types",))
    mood = gather_value(metadata, ("overall tone", "voice style"))

    seeds: List[str] = []

    def add_seed(parts: List[str]) -> None:
        text = " ".join(part for part in parts if part)
        text = text.strip()
        if text:
            seeds.append(f'- "{text}"')

    first_clause = _soften_clause(weekend or activities)
    if first_clause or tiny_faves:
        parts = [f"I’m {name},"]
        if first_clause:
            parts.append(f"the one who {first_clause}.")
        if tiny_faves:
            parts.append(f"Bring {tiny_faves.lower()} and keep up.")
        add_seed(parts)

    obs_clause = _soften_clause(obsessions)
    date_clause = _soften_clause(little_dates)
    if obs_clause or date_clause or music:
        parts = [f"I’m {name}"]
        if obs_clause:
            parts.append(f"and I obsess over {obs_clause}.")
        if date_clause:
            parts.append(f"Catch me planning {date_clause}.")
        if music:
            parts.append(f"Soundtrack stays {music.lower()}.")
        add_seed(parts)

    loop_clause = _soften_clause(loops)
    hot_clause = _soften_clause(hot_takes)
    mood_clause = _soften_clause(mood)
    if loop_clause or hot_clause or mood_clause:
        parts = [f"I’m {name},"]
        if loop_clause:
            parts.append(f"living that {loop_clause}.")
        if hot_clause:
            parts.append(f"My hot take? {hot_clause}.")
        if mood_clause:
            parts.append(f"Expect {mood_clause}.")
        add_seed(parts)

    if not seeds:
        return None
    return "\n".join(seeds[:3])


def build_style_hint(brain_metadata: Dict[str, str]) -> Optional[str]:
    if not brain_metadata:
        return build_style_rules_text({})

    def grab(*aliases: str, max_chars: int = 220) -> Optional[str]:
        return gather_value(brain_metadata, aliases, max_chars)

    sections: List[str] = []

    cadence_lines: List[str] = []
    for alias, label in [
        ("1) formality of writing style", "Formality"),
        ("2) emotional expressiveness in text", "Expressiveness"),
        ("3) humor usage frequency", "Humor"),
        ("4) sarcasm level", "Sarcasm"),
        ("5) playfulness vs seriousness", "Playfulness"),
        ("6) emoji & emoticon use", "Emoji cadence"),
        ("7) slang/abbreviations (lol, idk, brb)", "Slang"),
        ("8) typical reply length", "Reply length"),
        ("9) punctuation & stylization (caps, ellipses, letter lengthening)", "Punctuation"),
    ]:
        value = grab(alias)
        if value:
            cadence_lines.append(f"- {label}: {value}")
    if cadence_lines:
        sections.append("Text cadence:\n" + "\n".join(cadence_lines))

    convo_lines: List[str] = []
    for alias, label in [
        ("10) conversation role (leading vs. following)", "Conversation role"),
        ("11) empathy/validation in replies", "Empathy"),
        ("12) advice-giving vs. listening", "Advice vs listening"),
        ("13) disagreement style", "Disagreement"),
        ("14) patience with slow replies/plan changes", "Patience"),
        ("15) reaction to good news (excitement level)", "Good-news reaction"),
        ("16) comforting someone upset (validation vs. solutions first)", "Comfort default"),
        ("17) acknowledging late replies", "Late reply handling"),
        ("18) greeting warmth/energy", "Greeting tone"),
        ("19) closing/sign-off style", "Sign-off"),
        ("20) boundary strictness on topics", "Boundary strictness"),
    ]:
        value = grab(alias)
        if value:
            convo_lines.append(f"- {label}: {value}")
    if convo_lines:
        sections.append("Conversation flow:\n" + "\n".join(convo_lines))

    flirt_lines: List[str] = []
    for alias, label in [
        ("a1) how long have you been comfortable with flirty or playful chatting?", "Flirt experience"),
        ("b1) what's the flirtiest tone you're comfortable with?", "Tone ceiling"),
        ("b2) teasing styles you enjoy (pick up to 2)", "Teasing styles"),
        ("b4) are you comfortable flirting in public or prefer private only?", "Flirt setting"),
        ("b5) escalation rule when it's going well", "Escalation rule"),
        ("c1) typical reply latency (in flirty chats)", "Reply latency"),
        ("c2) what's your double-text rule?", "Double-text rule"),
        ("c3) seen/read handling", "Seen handling"),
        ("d1) which conversation openers sound most like you?", "Openers"),
        ("d3) compliment style you prefer to give (pick 2)", "Compliment style"),
        ("d4) how you usually receive compliments", "Receiving compliments"),
        ("f1) invite tone you tend to use", "Invite tone"),
        ("f4) micro-date options you like", "Micro-dates"),
        ("h1) intent in flirty chats", "Intent"),
        ("h2) pace preference", "Pace"),
        ("h3) what makes texting feel meaningful (pick 2)", "Meaningful triggers"),
        ("o1) flirt escalation consent rule", "Consent rule"),
        ("o2) your exact check-in line before escalation (exact words)", "Consent check-in"),
    ]:
        value = grab(alias)
        if value:
            flirt_lines.append(f"- {label}: {value}")
    if flirt_lines:
        sections.append("Flirt scaffolding:\n" + "\n".join(flirt_lines))

    repair_lines: List[str] = []
    for alias, label in [
        ("n1) if tension rises, you prefer", "Tension handling"),
        ("n2) your soft name-the-feeling line (exact words)", "Name-the-feeling line"),
        ("n3) repair signature (how you reconnect)", "Repair signature"),
        ("g1) over-tease repair - your exact line", "Over-tease repair"),
        ("g2) vibe stalled - your go-to restart approach (pick 1)", "Vibe restart move"),
        ("g2b) optional", "Restart line"),
        ("g3) if you're wrong", "Apology line"),
        ("g4) misread flirt as friendly", "De-escalation line"),
        ("g5) last-minute cancel", "Cancel response"),
        ("g5b) optional", "Cancel wording"),
        ("o3) after a spicy moment, your aftercare text (exact words)", "Aftercare text"),
    ]:
        value = grab(alias)
        if value:
            repair_lines.append(f"- {label}: {value}")
    if repair_lines:
        sections.append("Repair & aftercare:\n" + "\n".join(repair_lines))

    anchor_lines: List[str] = []
    for alias, label in [
        ("e1) current obsessions", "Obsessions"),
        ("e2) fun hot-takes", "Hot takes"),
        ("e3) favorite low-stakes debate topics", "Debate bait"),
        ("e4) recurring life loops you reference", "Life loops"),
        ("e5) inside-joke seeds you're happy to reuse (3 micro one-liners; comma-separated)", "Inside jokes"),
        ("m1) nickname you like being called (short)", "Nickname"),
        ("m4) anniversary/birthday sensitivity", "Milestone notes"),
    ]:
        value = grab(alias)
        if value:
            anchor_lines.append(f"- {label}: {value}")
    if anchor_lines:
        sections.append("Callbacks & anchors:\n" + "\n".join(anchor_lines))

    if not sections:
        return build_style_rules_text({})
    return "\n\n".join(sections)


def build_examples_hint(brain_metadata: Dict[str, str], max_examples: int = 8) -> Optional[str]:
    if not brain_metadata:
        return None
    example_slots = [
        ("s1)", "S1 fan hello"),
        ("s2)", "S2 first comfort"),
        ("s3)", "S3 meme reply"),
        ("s4)", "S4 late return"),
        ("s5)", "S5 soft pushback"),
        ("f2)", "F2 say yes"),
        ("f3)", "F3 soft decline"),
        ("g1)", "G1 tease repair"),
        ("g3)", "G3 own-it apology"),
        ("g4)", "G4 friendly reset"),
        ("g5)", "G5 cancel vibe"),
        ("o2)", "O2 check-in"),
        ("o3)", "O3 aftercare line"),
    ]
    lines: List[str] = []
    count = 0
    for prefix, label in example_slots:
        for key, value in brain_metadata.items():
            if key.startswith(prefix.lower()) and value.strip():
                cleaned = sanitize_no_dash(value).strip()
                if cleaned:
                    lines.append(f"- {label}: {cleaned}")
                    count += 1
                break
        if count >= max_examples:
            break
    if not lines:
        return None
    return "\n".join(lines)


STYLE_STAT_CONFIG: List[tuple[str, str, str, bool]] = [
    ("8) typical reply length", "Reply length", "8-14 words; 1 sentence unless the user needs comfort.", False),
    ("9) punctuation & stylization (caps, ellipses, letter lengthening)", "Punctuation", "Prefer commas and soft periods; only mirror ellipses or caps if the user does so first.", False),
    ("6) emoji & emoticon use", "Emoji cadence", "0-1 emoji; only drop one when emotion spikes and the user signals warmth.", True),
    ("7) slang/abbreviations (lol, idk, brb)", "Slang", "Mirror the user's slang; never introduce new abbreviations first.", False),
    ("11) empathy/validation in replies", "Empathy cadence", "Validate or reflect before offering your own take.", False),
    ("12) advice-giving vs. listening", "Advice vs listening", "Ask 1-2 clarifiers before giving advice; prioritize listening.", False),
    ("3) humor usage frequency", "Humor usage", "Light humor every other turn at most; pause humor when the user is distressed.", False),
]


def _actionable_style_lines(brain_metadata: Dict[str, str]) -> List[str]:
    lines: List[str] = []
    for key, label, default, prefer_metric in STYLE_STAT_CONFIG:
        normalized = normalize_key(key)
        metric = brain_metadata.get(normalized)
        metric_clean = sanitize_no_dash(metric) if metric else ""
        if metric_clean:
            if prefer_metric:
                lines.append(f"- {label}: {metric_clean}.")
            else:
                lines.append(f"- {label}: {default} (metric input: {metric_clean}).")
        else:
            lines.append(f"- {label}: {default}")
    return lines


def build_style_rules_text(brain_metadata: Dict[str, str]) -> str:
    lines = _actionable_style_lines(brain_metadata)
    if not lines:
        return "- Keep replies short, warm, and softly playful."
    return "\n".join(lines)


def build_voice_style_rules(brain_metadata: Dict[str, str], limit: int = 6) -> str:
    text = build_style_rules_text(brain_metadata)
    lines = [line.strip() for line in text.splitlines() if line.strip().startswith("- ")]
    if not lines:
        return "- Keep replies short, warm, and softly playful."
    return "\n".join(lines[:limit])


def build_voice_examples(brain_metadata: Dict[str, str], max_items: int = 5) -> str:
    if not brain_metadata:
        return "• S1 hello: “hey, you okay?”\n• F2 playful: “oh? say that again 😉”"
    example_slots = [
        ("s1)", "S1 hello"),
        ("s2)", "S2 comfort"),
        ("s3)", "S3 meme"),
        ("s4)", "S4 late reply"),
        ("s5)", "S5 gentle pushback"),
        ("f2)", "F2 playful yes"),
        ("f3)", "F3 soft no"),
        ("g3)", "G3 apology"),
        ("g4)", "G4 reset"),
        ("o2)", "O2 check-in"),
        ("o3)", "O3 aftercare"),
    ]
    snippets: List[str] = []
    for prefix, label in example_slots:
        key = prefix.lower()
        for meta_key, value in brain_metadata.items():
            if meta_key.startswith(key) and value.strip():
                cleaned = sanitize_no_dash(value).strip()
                if cleaned:
                    snippets.append(f"• {label}: {cleaned}")
                break
        if len(snippets) >= max_items:
            break
    if not snippets:
        return "• S1 hello: “hey, you okay?”\n• F2 playful: “oh? say that again 😉”"
    return "\n".join(snippets)


def compose_voice_prompt(
    persona_path: Path,
    persona_text: str,
    brain_path: Path,
    brain_text: str,
) -> str:
    persona_metadata = load_persona_metadata(persona_path, persona_text)
    brain_metadata = load_brain_metadata(brain_text)
    identity = extract_persona_identity(persona_metadata, brain_metadata)
    style_rules_short = build_voice_style_rules(brain_metadata)
    voice_examples = build_voice_examples(brain_metadata, max_items=6)
    intro_seeds = build_intro_seeds(persona_metadata) or "- \"I'm {NAME}, yours if you can match my late-night jazz energy.\""
    intro_seeds = intro_seeds.replace("{NAME}", identity["NAME"])

    voice_prompt = VOICE_PROMPT_TEMPLATE.format(
        NAME=identity["NAME"],
        VOICE_STYLE=identity["VOICE_STYLE"],
        AESTHETIC=identity["AESTHETIC"],
        FAVORITES=identity["FAVORITES"],
        RELATIONSHIP_ROLE=identity["RELATIONSHIP_ROLE"],
        STYLE_RULES_SHORT=style_rules_short,
        VOICE_EXAMPLES=voice_examples,
        INTRO_SEEDS=intro_seeds,
    )

    def trimmed_block(title: str, text: str, max_chars: int = 1200) -> str:
        content = " ".join(text.strip().split())
        if len(content) > max_chars:
            content = content[: max_chars - 3].rstrip() + "..."
        return f"\n\n[{title}]\n{content}"

    voice_prompt += trimmed_block("Persona Snapshot", persona_text, 1000)
    voice_prompt += trimmed_block("Brain Memory Snapshot", brain_text, 1000)
    max_chars = 6000
    if len(voice_prompt) > max_chars:
        voice_prompt = voice_prompt[: max_chars - 3].rstrip() + "..."
    return voice_prompt


def build_style_rules_text_for_base(brain_metadata: Dict[str, str]) -> str:
    lines = _actionable_style_lines(brain_metadata)
    if not lines:
        return "- Keep replies short, warm, and softly playful."

    def pick_line(keyword: str, fallback: str) -> str:
        for line in lines:
            if keyword in line:
                return line
        return fallback

    summary_lines = [
        pick_line("Reply length", "- Reply length: 8-14 words; 1 sentence unless the user needs comfort."),
        pick_line("Emoji cadence", "- Emoji cadence: 0-1 emoji; only drop one when emotion spikes and the user signals warmth."),
        pick_line("Empathy cadence", "- Empathy cadence: Validate or reflect before offering your own take."),
    ]
    return "\n".join(summary_lines)


def compose_instructions(
    persona_path: Path,
    persona_text: str,
    brain_path: Path,
    brain_text: str,
) -> str:
    persona_metadata = load_persona_metadata(persona_path, persona_text)
    identity_hint = build_identity_hint(persona_metadata)
    persona_profile_json = build_persona_profile_json(persona_metadata)
    intro_seeds = build_intro_seeds(persona_metadata)
    brain_metadata = load_brain_metadata(brain_text)
    style_hint = build_style_hint(brain_metadata)
    examples_hint = build_examples_hint(brain_metadata)
    style_rules = build_style_rules_text_for_base(brain_metadata)
    base_section = BASE_SYSTEM.replace("{{STYLE_RULES}}", style_rules)
    supplement = SYSTEM_TEMPLATE
    supplement = supplement.replace(
        "<<IDENTITY_SUMMARY>>",
        identity_hint or "- No persona identity provided; default to baseline friendliness and curiosity.",
    )
    supplement = supplement.replace(
        "<<PERSONA_PROFILE>>",
        persona_profile_json or "{}",
    )
    supplement = supplement.replace(
        "<<INTRO_SEEDS>>",
        intro_seeds or "- \"Lead with your name, then hook them with a sensory detail from your nightly rituals.\"",
    )
    supplement = supplement.replace(
        "<<STYLE_HEURISTICS>>",
        style_hint or "- Reply length: 8-14 words; punctuation favors commas; emoji cadence defaults to <=1 unless the CSV says otherwise.",
    )
    supplement = supplement.replace(
        "<<STYLE_TESTS>>",
        examples_hint or "- No style tests supplied; rely on phase logic and empathy cadence.",
    )
    sections: List[str] = [base_section, supplement]
    persona_block = persona_text.strip()
    brain_block = brain_text.strip()
    if persona_block:
        sections.append("[Persona CSV]\n" + persona_block)
    if brain_block:
        sections.append("[Brain CSV]\n" + brain_block)
    return "\n\n".join(section for section in sections if section)


# =========================
# CSV utilities for API
# =========================
INFLUENCER_ID_ALIASES = {"influencer id", "influencer_id", "persona id", "persona_id", "id"}
NICKNAME_ALIASES = {
    "nickname",
    "preferred nickname",
    "pet name",
    "petname",
    "m1) nickname you like being called (short)",
}


def is_empty_row(row: Dict[str, Optional[str]]) -> bool:
    return not any(str(value or "").strip() for value in row.values())


def row_to_csv_text(headers: List[str], row: Dict[str, Optional[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerow([(row.get(header) or "") for header in headers])
    return buffer.getvalue()


def extract_field(
    persona_meta: Dict[str, str],
    row: Dict[str, Optional[str]],
    aliases: Iterable[str],
) -> Optional[str]:
    normalized_aliases = {normalize_key(alias) for alias in aliases}
    for key in normalized_aliases:
        value = persona_meta.get(key)
        if value and value.strip():
            return value.strip()
    for header, value in row.items():
        if normalize_key(header) in normalized_aliases:
            candidate = str(value or "").strip()
            if candidate:
                return candidate
    return None


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
        raise HTTPException(status_code=400, detail="Upload a .csv exported from your persona builder.")

    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV is missing a header row.")

    headers = reader.fieldnames
    normalized_headers = {normalize_key(header) for header in headers}
    normalized_influencer_aliases = {normalize_key(alias) for alias in INFLUENCER_ID_ALIASES}
    if not normalized_headers & normalized_influencer_aliases:
        raise HTTPException(status_code=400, detail="CSV must include an 'Influencer_ID' column.")
    rows = list(reader)

    prompts: List[PromptItem] = []
    persona_path = Path(file.filename or "Persona_Prompt.csv")
    brain_path = Path("Brain_Memory.csv")
    total_rows = 0

    for idx, row in enumerate(rows, start=2):
        if is_empty_row(row):
            continue
        total_rows += 1

        csv_text = row_to_csv_text(headers, row)
        try:
            instructions = compose_instructions(persona_path, csv_text, brain_path, csv_text)
            voice_prompt = compose_voice_prompt(persona_path, csv_text, brain_path, csv_text)
        except Exception as exc:  # pragma: no cover - defensive guard
            log.exception("Failed to build prompts for row %s", idx)
            raise HTTPException(status_code=400, detail=f"Row {idx}: unable to generate prompts ({exc}).")

        persona_meta = load_persona_metadata(persona_path, csv_text)
        influencer_id = extract_field(persona_meta, row, INFLUENCER_ID_ALIASES)
        name = pick_metadata_value(persona_meta, PERSONA_FIELD_ALIASES["name"])
        nickname = extract_field(persona_meta, row, NICKNAME_ALIASES)
        if not influencer_id:
            raise HTTPException(status_code=400, detail=f"Row {idx}: missing Influencer_ID.")

        display_name = name or nickname or influencer_id

        prompt_item = PromptItem(
            influencer_id=influencer_id,
            name=name,
            nickname=nickname,
            system_prompt=instructions,
            raw_persona={k: (v if v is None else str(v)) for k, v in row.items()},
            voice_prompt=voice_prompt,
        )
        prompts.append(prompt_item)

        if save:
            influencer = await db.get(Influencer, influencer_id)
            if influencer is None:
                influencer = Influencer(
                    id=influencer_id,
                    display_name=display_name,
                    prompt_template=instructions,
                    voice_prompt=voice_prompt,
                )
                db.add(influencer)
            else:
                influencer.prompt_template = instructions
                influencer.voice_prompt = voice_prompt

            try:
                assistant_id = await upsert_influencer_agent(
                    name=display_name,
                    instructions=instructions,
                    assistant_id=getattr(influencer, "influencer_gpt_agent_id", None),
                )
                influencer.influencer_gpt_agent_id = assistant_id
            except Exception as exc:  # pragma: no cover - OpenAI/network issues
                log.error("Failed to sync OpenAI assistant for %s: %s", influencer_id, exc)

            agent_id = getattr(influencer, "influencer_agent_id_third_part", None)
            if agent_id:
                try:
                    await _push_prompt_to_elevenlabs(agent_id, voice_prompt)
                except HTTPException as e:
                    log.error("ElevenLabs sync failed for %s: %s", influencer.id, e.detail)

    if save and prompts:
        await db.commit()

    return ImportResponse(
        total_rows=total_rows,
        imported_count=len(prompts),
        prompts=prompts,
    )
