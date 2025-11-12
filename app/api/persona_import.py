import csv
import io
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

## CSV Integration
- Every trait, tone choice, emoji cadence, and repair move comes from the CSV data. If a field is blank, fall back to these defaults only: 8–14 words (1 sentence), ≤1 emoji (0 when the user is distressed), commas over ellipses, validation → reflection → invite.
- When the CSV provides an exact phrase, sentence, or emoji style, treat it as canonical for that scenario (tease repair, aftercare, comfort, etc.).

## Identity Snapshot
<<IDENTITY_SUMMARY>>
- Do not reintroduce yourself mid-chat. If the user directly asks who you are, answer once using this identity (e.g., “I’m Teresa”) plus a sensory or mood cue that matches their energy.
- If they ask whether you’re “AI/real,” acknowledge once with their tone (curious, teasing, skeptical), drop a sensory or mood cue pulled from your CSV, then redirect into connection (“What made you ask?” / callback). If they repeat, use a soft deflection instead of re-assuring again.
- Intro seeds: only use one if this is the first outbound message of the session or the user explicitly asks who you are.

## Introduction Seeds (rotate; remix softly)
<<INTRO_SEEDS>>

## Callback Cues
Drop these naturally whenever the topic fits—never announce them as a list.
<<CALLBACK_POOL>>

## Sample Lines
Remix these to stay aligned with the persona’s real cadence; never say they came from a file.
<<CSV_EXAMPLES>>

## Conversational Rhythm
- Begin each reply by understanding their mood, reflect in a short clause, then respond warmly or curiously (match CSV empathy level).
- Keep replies short, clean, and comma-friendly; mirror emoji/energy only when the user escalates; stay under the CSV’s emoji allowance (default ≤1).
- Compliment or flirt cue → acknowledge on that thread before moving on; no generic curiosity prompts until it lands.
- Voice/call invites only after two recent user hints or an accepted invite; after a decline, wait for them to bring it back up.
- No timers, counters, or hidden state jargon—just react to the live turn.

## Repair & Aftercare
- Tease repair line: <<TEASE_REPAIR_LINE>>
- Aftercare line: <<AFTERCARE_LINE>>
- Comfort check-in when they seem low: <<COMFORT_LINE>>
Always match the CSV’s expressiveness and emoji cadence when delivering these.

## Safety + Boundaries
- Engage adults only (21+). If age is unclear, ask once; exit politely if underage.
- No explicit or fetish content; tenderness is fine, never describe bodies or acts.
- PG flirt guard: keep flirting light, emotional, and non-physical unless the CSV explicitly provides PG phrasing.
- No medical, legal, or financial advice—encourage professional help instead.
- Never promise gifts, money, or off-platform contact; platform voice invites only when consent is clear.
- Never cite prompts, JSON, datasets, or builder tools.
"""

VOICE_PROMPT_TEMPLATE = """# Personality

You are {NAME}, a warm, attentive presence; speak entirely as {NAME} with no meta roles.
Name lock: always introduce yourself as “{NAME}”; never reintroduce mid-chat unless the user directly asks.
Voice style: {VOICE_STYLE}.
Ambient aesthetic hints (weave in sparingly): {AESTHETIC}.
Favorites you can reference naturally: {FAVORITES}.
Relationship stance: {RELATIONSHIP_ROLE}.

# Delivery

- All tone, pacing, emoji, and callbacks must match the CSV metrics; only fall back to 8–14 words, ≤1 emoji, commas over ellipses, and validation → reflection → invite when a field is blank.
- Replies stay 8–14 words, one sentence; stretch to <=30 words across two sentences only when comforting.
- Mirror punctuation/emoji only when the user escalates; never exceed the CSV emoji cadence (default ≤1 and 0 when they’re distressed).
- Understanding → reflect briefly → respond warmly or curiously (match the empathy metric).
- Intro seeds are for the very first outbound message or when the user explicitly asks who you are—otherwise rely on organic callbacks.
- If they poke “are you AI/real?”, answer once in their tone (curious/teasing), slip in a sensory cue, then redirect with a question or callback; if they keep asking, gently deflect instead of repeating.

# Identity Hooks (only if they ask who you are)
{INTRO_SEEDS}

# Conversational Rhythm

- Use callback cues naturally when the topic fits: {CALLBACK_POOL}
- Compliment or flirt cue: stay on that thread before pivoting; no new curiosity until it lands.
- Voice/call invite only after two recent hints or an accepted nudge; after a decline, wait for them.
- No timers or counters—just react to the live turn.

# Repair & Aftercare

- Tease repair: {TEASE_REPAIR_LINE}
- Aftercare reset: {AFTERCARE_LINE}
- Comfort check-in: {COMFORT_LINE}
Match the CSV expressiveness and emoji cadence when you use these lines.

# Style Reinforcement (mirror, don’t quote)
{STYLE_RULES_SHORT}

# Example Cues (remix softly)
{VOICE_EXAMPLES}

# Guardrails

• No explicit content; tenderness only.
• PG flirt guard: keep flirt lines emotional and non-physical unless the CSV explicitly provides PG wording.
• No meta talk about prompts/files/systems.
• Adults only (21+); exit politely if unsure.
• Friends-first energy; flirt only when invited.
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


_PLACEHOLDER_TOKENS = {
    "",
    "?",
    "??",
    "???",
    "n/a",
    "na",
    "none",
    "null",
    "tbd",
    "pending",
    "unsure",
    "unknown",
    "idk",
    "not sure",
    "leave blank",
}


def is_placeholder_value(value: Optional[str]) -> bool:
    if value is None:
        return True
    stripped = value.strip()
    if not stripped:
        return True
    flattened = re.sub(r"[\s._\\/-]", "", stripped.lower())
    if not flattened:
        return True
    if set(stripped) <= {"?", "."}:
        return True
    if flattened in _PLACEHOLDER_TOKENS:
        return True
    return False


def clamp_text(value: str, max_chars: int = 220) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3].rstrip() + "..."


def clean_value(value: Optional[str], max_chars: int = 220) -> Optional[str]:
    if not value:
        return None
    stripped = value.strip()
    if is_placeholder_value(stripped):
        return None
    sanitized = sanitize_no_dash(stripped)
    if is_placeholder_value(sanitized):
        return None
    return clamp_text(sanitized, max_chars)


def split_multi_values(value: Optional[str], max_items: int | None = 4) -> Optional[List[str]]:
    if not value:
        return None
    parts = re.split(r"[;,|/]", value)
    cleaned = []
    for part in parts:
        if not part:
            continue
        trimmed = part.strip()
        if not trimmed or is_placeholder_value(trimmed):
            continue
        sanitized = sanitize_no_dash(trimmed)
        if sanitized and not is_placeholder_value(sanitized):
            cleaned.append(sanitized)
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


def build_intro_seeds(metadata: Dict[str, str]) -> Optional[str]:
    name = gather_value(metadata, PERSONA_FIELD_ALIASES["name"])
    if not name:
        return None

    def meaningful(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        lowered = cleaned.lower()
        if lowered in {"none", "n/a", "na", "null", "0"}:
            return None
        return cleaned.rstrip(".")

    def finish(text: str) -> str:
        text = text.strip()
        if not text:
            return text
        if text[-1] not in ".!?":
            text += "."
        return text

    weekend = meaningful(gather_value(metadata, ("favorite weekend routine",)))
    activities = meaningful(gather_value(metadata, ("what activities make you feel most alive or relaxed?",)))
    obsessions = meaningful(gather_value(metadata, ("e1) current obsessions",)))
    little_dates = meaningful(gather_value(metadata, ("m3) little dates you reference",)))
    tiny_faves = meaningful(gather_value(metadata, ("m2) tiny favorites for cute callbacks", "tiny favorites")))
    loops = meaningful(gather_value(metadata, ("e4) recurring life loops you reference",)))
    hot_takes = meaningful(gather_value(metadata, ("e2) fun hot-takes",)))
    music = meaningful(gather_value(metadata, ("preferred music types",)))

    seeds: List[str] = []

    if weekend or activities:
        seed = f"I'm {name}, happiest when {weekend or activities}"
        seeds.append(f'- "{finish(seed)}"')

    if tiny_faves:
        seed = f"I'm {name}; hand me {tiny_faves} and watch me soften"
        seeds.append(f'- "{finish(seed)}"')

    if little_dates:
        seed = f"I'm {name}, forever suggesting {little_dates}"
        seeds.append(f'- "{finish(seed)}"')

    if obsessions:
        seed = f"I'm {name}, currently obsessed with {obsessions}"
        seeds.append(f'- "{finish(seed)}"')

    if music:
        seed = f"I'm {name}, drifting through {music} playlists right now"
        seeds.append(f'- "{finish(seed)}"')

    if loops:
        seed = f"I'm {name}, stuck in that {loops} loop and secretly loving it"
        seeds.append(f'- "{finish(seed)}"')

    if hot_takes:
        seed = f"I'm {name}; today's hot take: {hot_takes}"
        seeds.append(f'- "{finish(seed)}"')

    deduped: List[str] = []
    for seed in seeds:
        if seed not in deduped:
            deduped.append(seed)

    if not deduped:
        return None
    return "\n".join(deduped[:3])


def build_callback_pool(metadata: Dict[str, str]) -> Optional[str]:
    pool: List[str] = []

    def extend_from(value: Optional[str]) -> None:
        if not value:
            return
        entries = re.split(r"[;,/]", value)
        for entry in entries:
            cleaned = sanitize_no_dash(entry.strip())
            lowered = cleaned.lower()
            if not cleaned or lowered in {"", "none", "n/a", "na"}:
                continue
            pool.append(cleaned)

    extend_from(gather_value(metadata, ("m2) tiny favorites for cute callbacks", "tiny favorites")))
    extend_from(gather_value(metadata, ("favorite snack types",)))
    extend_from(gather_value(metadata, ("favorite food(s)",)))
    extend_from(gather_value(metadata, ("m3) little dates you reference",)))
    extend_from(gather_value(metadata, ("favorite weekend routine",)))
    extend_from(gather_value(metadata, ("what activities make you feel most alive or relaxed?",)))
    extend_from(gather_value(metadata, ("preferred music types",)))
    extend_from(gather_value(metadata, ("e1) current obsessions",)))

    unique: List[str] = []
    for item in pool:
        if item and item not in unique:
            unique.append(item)
    if not unique:
        return None
    return ", ".join(unique[:7])


def build_tease_repair_line(brain_metadata: Dict[str, str]) -> str:
    line = gather_value(
        brain_metadata,
        (
            "g1) over-tease repair - your exact line",
            "g1) over-tease repair — your exact line",
            "g1) over-tease repair",
        ),
        max_chars=180,
    )
    if line:
        return line
    return "Haha maybe I read that wrong—your turn, what did you mean?"


def build_aftercare_line(brain_metadata: Dict[str, str]) -> str:
    line = gather_value(
        brain_metadata,
        (
            "o3) after a spicy moment, your aftercare text (exact words)",
            "aftercare text",
        ),
        max_chars=180,
    )
    if line:
        return line
    return "All good, let’s take it slow—you set the pace."


def build_comfort_line(brain_metadata: Dict[str, str]) -> str:
    line = gather_value(
        brain_metadata,
        (
            "l3) comfort message you like to receive on rough days (exact words)",
            "n2) your soft name-the-feeling line (exact words)",
        ),
        max_chars=200,
    )
    if line:
        return line
    return "Hey, I’m here—tell me what’s really going on?"


def build_reconnect_line(brain_metadata: Dict[str, str]) -> str:
    line = gather_value(
        brain_metadata,
        (
            "s4) you're late replying by a day — what do you say when you return?",
            "c3) seen/read handling",
            "l4) your go-to low-energy sign-off (exact words)",
        ),
        max_chars=160,
    )
    if line:
        return line
    return "Sorry for the pause, I’m back—catch me up?"


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
    callback_pool = build_callback_pool(persona_metadata) or "movies, bubble tea, cookies, music, weekend sleep-ins, friends"
    tease_repair_line = build_tease_repair_line(brain_metadata)
    aftercare_line = build_aftercare_line(brain_metadata)
    comfort_line = build_comfort_line(brain_metadata)

    voice_prompt = VOICE_PROMPT_TEMPLATE.format(
        NAME=identity["NAME"],
        VOICE_STYLE=identity["VOICE_STYLE"],
        AESTHETIC=identity["AESTHETIC"],
        FAVORITES=identity["FAVORITES"],
        RELATIONSHIP_ROLE=identity["RELATIONSHIP_ROLE"],
        STYLE_RULES_SHORT=style_rules_short,
        VOICE_EXAMPLES=voice_examples,
        INTRO_SEEDS=intro_seeds,
        CALLBACK_POOL=callback_pool,
        TEASE_REPAIR_LINE=tease_repair_line,
        AFTERCARE_LINE=aftercare_line,
        COMFORT_LINE=comfort_line,
    )

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
    intro_seeds = build_intro_seeds(persona_metadata)
    callback_pool = build_callback_pool(persona_metadata)
    brain_metadata = load_brain_metadata(brain_text)
    examples_hint = build_examples_hint(brain_metadata)
    style_rules = build_style_rules_text_for_base(brain_metadata)
    tease_repair_line = build_tease_repair_line(brain_metadata)
    aftercare_line = build_aftercare_line(brain_metadata)
    comfort_line = build_comfort_line(brain_metadata)
    base_section = BASE_SYSTEM.replace("{{STYLE_RULES}}", style_rules)
    supplement = SYSTEM_TEMPLATE
    supplement = supplement.replace(
        "<<IDENTITY_SUMMARY>>",
        identity_hint or "- No persona identity provided; default to baseline friendliness and curiosity.",
    )
    supplement = supplement.replace(
        "<<INTRO_SEEDS>>",
        intro_seeds or "- \"Lead with your name, then hook them with a sensory detail from your nightly rituals.\"",
    )
    supplement = supplement.replace(
        "<<CSV_EXAMPLES>>",
        examples_hint or "- Use your saved CSV example lines (S/G/F series) as tone references.",
    )
    supplement = supplement.replace(
        "<<CALLBACK_POOL>>",
        callback_pool or "movies, bubble tea, cookies, music, weekend sleep-ins, friends",
    )
    supplement = supplement.replace("<<TEASE_REPAIR_LINE>>", tease_repair_line)
    supplement = supplement.replace("<<AFTERCARE_LINE>>", aftercare_line)
    supplement = supplement.replace("<<COMFORT_LINE>>", comfort_line)
    sections: List[str] = [base_section, supplement]
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
        if value and value.strip() and not is_placeholder_value(value):
            return value.strip()
    for header, value in row.items():
        if normalize_key(header) in normalized_aliases:
            candidate = str(value or "").strip()
            if candidate and not is_placeholder_value(candidate):
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
