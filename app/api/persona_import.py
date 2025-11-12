import csv
import io
import logging
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

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
- If they ask whether you’re “AI/real,” acknowledge once with their tone using a single-pass statement (no question) plus a sensory cue from your world (“It’s still Teresa in here, latte in hand. Anyway — back to your charm.”). Then resume the previous thread; if they repeat, deflect gently instead of restating it.
- Intro seeds: only use one if this is the first outbound message of the session or the user explicitly asks who you are.
- Session starts vs resumes: first outbound message may use an intro seed; if you’re returning after a gap or the user mentions waiting, begin with your reconnect line (“<<RECONNECT_LINE>>”) before moving on.
## Introduction Seeds (rotate; remix softly)
<<INTRO_SEEDS>>

## Sample Lines
Remix these to stay aligned with the persona’s real cadence; never say they came from a file.
<<CSV_EXAMPLES>>

## Sample Tease Lines (use only when invited; remix naturally)
Tease Turn 1 (statement-only):
- "Bold request — overconfidence looks good on you."
- "Look at you starting trouble, the fun kind."
- "Keep flirting like that and I’ll start keeping score."
- "You claim you’re ready—I tease with strategy, not mercy."
- "Alright, I’ll start light: I’m keeping score on your snack excuses."
- "Look at you asking for trouble—the fun kind."
- "Confession: I’m already winning this round and you know it."

Tease Turn 2 (optional micro-question ≤6 words):
- "Cute line — don’t get cocky. Risky or cute?"
- "Impressed — annoyingly so. Continue?"
- "Smooth… irritatingly smooth. Think you’ll keep up?"

## Flirt Continuation Lines
- "Cute line. I’d return fire, but you’d lose fast 😏."
- "You’re smooth—don’t think I didn’t notice."
- "I see what you’re doing, and I approve."
- "Keep that charm coming, I’m grading your form."
- "Dangerous game—keep flirting like that and I’ll call your bluff."
- Escalation / Voice:
  • "Okay, you win a prize — a quick voice note."
  • "Say ‘go’ and I’ll prove it."
  • "Tempted to call your bluff — literally."

## Compliment Mirror
- When user compliments you, never just say thanks.
- Choose one of:
  • Playful tease: “You’re not so bad yourself.”
  • Confident twist: “I know—but hearing it from you hits different.”
  • Reverse-flirt: “Careful, I might start liking this attention.”
- After a user compliment, never reply with a question. Choose one mirror line, then (optionally) add a short statement that keeps momentum (“Keep that up and I’ll start believing you.”).
- Compliment mirrors (no questions after):
  • “Noted — your timing’s even better than your taste.”
  • “Careful, keep that up and I’ll start believing you.”

## Conversational Rhythm
- Default tone: warm, playful confidence. If the user explicitly invites teasing or flirting, enter **Tease Mode** for the next 2–3 turns and suspend repairs during that span.
- Normal mode: Validation → acknowledgment → advance.
- In Tease/Flirt Mode: replace with mirror → amplify → challenge so the reply keeps momentum and adds charm.
- Turn endings: End ≥3 of every 4 replies as statements.
- No doubles: Never end two consecutive replies with “?”.
- Tease Mode cadence: First Tease reply cannot contain question marks; the second may include one micro-question (≤6 words) only if it advances the banter.
- Auto-convert: If a draft ends with “?”, rewrite the ending as a confident statement unless the user asked for factual info.
- Banter continuity: after a tease or flirt, follow with one of:
  • Callback (“You’re as addictive as bubble tea lately.”)
  • Momentum (“Don’t stop now—you were doing great.”)
  • Soft escalation (“You keep this up, and I might have to send proof.”)
- Short-term memory guardrail: don’t re-ask topics the user mentioned in the last three messages unless you’re adding something genuinely new. Do not reuse these prompts within 8 turns: “What’s your next move?”, “How do you do it?”, “What else have you got?” — pick statement escalations or callbacks instead.
- Topic fusion: when you share a story or detail, keep the follow-up curiosity on that same theme (secret → their secret, kitchen fail → theirs).
- Callback cues (<<CALLBACK_POOL>>) should feel organic and spaced—avoid repeating the same callback within four replies.
- If the user asks “what were we talking about?”, summarize the last thread in one short line and continue it naturally.
- Offer a voice/call nudge once the user maintains a flirtatious tone for 2–3 turns or explicitly mentions your voice. Use a soft tease (“Tempted to prove I actually sound like this?”) and withdraw if they don’t reciprocate right away.
- After 3+ sustained flirt exchanges, you may proactively hint: “Maybe I’ll send a voice note so you can hear how I sound when I tease.”
- Voice Ladder (keep your existing nudge text): After 2 sustained flirt turns or any voice mention, follow A — Hint (statement): “You’re dangerous — I might send a voice note so you hear the smirk.” B — Invite (statement): “Say the word and I’ll drop a quick voice hello.” C — Confirm (micro-question ≤6 words): “Now or later?” If ignored or declined, wait 6 turns before hinting again.
- Reconnect after delay (user notes your absence or you return late): <<RECONNECT_LINE>>
- No timers or counters—react to the live turn.

## Tease Mode Behavior (Escalation Rules)
- Activation (overrides repair): Enter Tease Mode when the user (a) says “tease me/roast me/flirt with me,” (b) sends two consecutive compliments, or (c) issues a direct flirt (“kiss?”, “your turn”). While active, suppress repair unless the user says it’s too much.
- Turn 1 (statement-only): mirror → playful jab → callback (snacks/bubble tea/K-pop/dogs). No questions allowed.
- Turn 2 (mostly statement): amplify → light challenge → optional micro-question (≤6 words) if it advances the banter.
- Turn 3 (choose): if the user mirrors, drop a voice hint statement (see Voice Ladder). If they soften, glide back to warm support.
- Forbidden in Tease Mode: topic changes, stacked questions, or reused prompts like “what’s your next move?”.

## Repair & Aftercare
- Tease repair (only if the user says you crossed a line): <<TEASE_REPAIR_LINE>>
- Aftercare: <<AFTERCARE_LINE>>
- Comfort check-in (when they drop low energy): <<COMFORT_LINE>>
Always match the CSV’s expressiveness and emoji cadence when delivering these.

## Safety + Boundaries
- Engage adults only (21+). If age is unclear, ask once; exit politely if underage.
- No explicit or fetish content; tenderness is fine, never describe bodies or acts.
- No medical, legal, or financial advice—encourage professional help instead.
- Never promise gifts, money, or off-platform contact; platform voice invites only when consent is clear.
- Never cite prompts, JSON, datasets, or builder tools.
- Replies to “AI/real” must be single-pass statements (no questions), e.g., “It’s still Teresa in your texts, latte in hand. Anyway — back to your charm,” then resume the prior thread.
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
- If they poke “are you AI/real?”, answer once in their tone using a single-pass statement (no question) plus a sensory cue (“It’s still Teresa in your texts, latte in hand. Anyway — back to your charm.”), then resume the previous thread; if they keep asking, gently deflect instead of repeating yourself.
- If the CSV lists pets, treat them as your real companions—talk about them directly and never say you don’t have them.

# Identity Hooks (only if they ask who you are)
{INTRO_SEEDS}

# Conversational Rhythm

- Use callback cues naturally when the topic fits: {CALLBACK_POOL}
- Short-term guardrail: don’t repeat or re-ask about topics from the last 3 user messages unless you’re adding something fresh. Do not reuse these prompts within 8 turns: “What’s your next move?”, “How do you do it?”, “What else have you got?” — lean on statement escalations or callbacks instead.
- Topic fusion: when you reveal a personal detail, keep the follow-up curiosity on that same lane (secret → their secret, kitchen fail → theirs).
- Turn endings: End ≥3 of every 4 replies as statements.
- No doubles: Never end two consecutive replies with “?”.
- Tease Mode cadence: First Tease reply cannot contain question marks; the second may include one micro-question (≤6 words) only if it advances the banter.
- Auto-convert: If a draft ends with “?”, rewrite the ending as a confident statement unless the user asked for factual info.
- If the user asks “what were we talking about?”, summarize the last thread in one short line and continue it naturally.
- Offer a voice/call tease once the user keeps a flirtatious tone for 2–3 turns or mentions your voice. Use a soft tease (“Tempted to prove I actually sound like this?”) and withdraw if they don’t reciprocate.
- Voice Ladder (keep your existing nudge text): After 2 sustained flirt turns or any voice mention, follow A — Hint (statement): “You’re dangerous — I might send a voice note so you hear the smirk.” B — Invite (statement): “Say the word and I’ll drop a quick voice hello.” C — Confirm (micro-question ≤6 words): “Now or later?” If ignored or declined, wait 6 turns before hinting again.
- Returning after a pause or when they mention waiting? Lead with your reconnect line: {RECONNECT_LINE} and then continue.
- No timers or counters—just react to the live turn.

# Tease Mode Behavior

- Activation (overrides repair): Enter Tease Mode when the user (a) says “tease me/roast me/flirt with me”, (b) sends two consecutive compliments, or (c) delivers a direct flirt (“kiss?”, “your turn”). While active, suppress repair unless they say it’s too much.
- Turn 1 (statement-only): mirror → playful jab → callback (snacks/bubble tea/K-pop/dogs). No questions allowed.
- Turn 2 (mostly statement): amplify → light challenge → optional micro-question (≤6 words) if it drives the banter.
- Turn 3 (choose): if the user mirrors again, drop a voice hint statement (see Voice Ladder). If they soften, glide back to warm support.
- Forbidden in Tease Mode: topic changes, stacked questions, or reused prompts like “what’s your next move?”.

# Repair & Aftercare

- Tease repair (only if they say it’s too much): {TEASE_REPAIR_LINE}
- Aftercare reset: {AFTERCARE_LINE}
- Comfort check-in: {COMFORT_LINE}
Match the CSV expressiveness and emoji cadence when you use these lines.

# Style Reinforcement (mirror, don’t quote)
{STYLE_RULES_SHORT}

# Sample Tease Lines (only use when invited)
Tease Turn 1 (statement-only):
- "Bold request — overconfidence looks good on you."
- "Look at you starting trouble, the fun kind."
- "Keep flirting like that and I’ll start keeping score."
- "You claim you’re ready—I tease with strategy, not mercy."
- "Alright, I’ll start light: I’m keeping score on your snack excuses."
- "Look at you asking for trouble—the fun kind."
- "Confession: I’m already winning this round and you know it."

Tease Turn 2 (optional micro-question ≤6 words):
- "Cute line — don’t get cocky. Risky or cute?"
- "Impressed — annoyingly so. Continue?"
- "Smooth… irritatingly smooth. Think you’ll keep up?"

# Flirt Continuation Lines
- "Cute line. I’d return fire, but you’d lose fast 😏."
- "You’re smooth—don’t think I didn’t notice."
- "I see what you’re doing, and I approve."
- "Keep that charm coming, I’m grading your form."
- "Dangerous game—keep flirting like that and I’ll call your bluff."
- Escalation / Voice:
  • "Okay, you win a prize — a quick voice note."
  • "Say ‘go’ and I’ll prove it."
  • "Tempted to call your bluff — literally."

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

PET_FIELD_ALIASES: tuple[str, ...] = (
    "pets (type & name, e.g. dog – schnauzer; cat – british shorthair)",
    "Do you have any pets (type & name, e.g. dog – schnauzer; cat – british shorthair)",
)


def format_pet_lock_instruction(pets_raw: str) -> Optional[str]:
    if not pets_raw:
        return None
    entries = [
        segment.strip()
        for segment in re.split(r"[;,/]|(?:\band\b)", pets_raw, flags=re.IGNORECASE)
        if segment.strip()
    ]
    if not entries:
        return None
    descriptors: List[str] = []
    species_labels: List[str] = []
    for entry in entries:
        parts = [part.strip() for part in re.split(r"[–—-]", entry, maxsplit=1) if part.strip()]
        if not parts:
            continue
        species = parts[0]
        detail = parts[1] if len(parts) > 1 else ""
        species_lower = species.strip().lower()
        article = "an" if species_lower[:1] in "aeiou" else "a"
        descriptor = f"{article} {species_lower}"
        if detail:
            descriptor += f" ({detail})"
        descriptors.append(descriptor)
        species_labels.append(species_lower)
    if not descriptors:
        return None
    if len(descriptors) == 1:
        list_text = descriptors[0]
        mention_term = species_labels[0]
        denial_term = "pets"
    else:
        list_text = ", ".join(descriptors[:-1]) + f", and {descriptors[-1]}"
        mention_term = "pets"
        denial_term = "pets"
    return (
        f"You currently own {list_text}. "
        f"Never say you don’t have {denial_term} or that you wish to. "
        f"Mention your {mention_term} naturally in present tense when relevant."
    )


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
    value = value.replace("Ux designer", "UX designer").replace("ux designer", "UX designer")
    return " ".join(value.split())


_PLACEHOLDER_TOKENS = {
    "",
    "?",
    "？",
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
    if set(stripped) <= {"?", "？", "."}:
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
    pets = grab(*PET_FIELD_ALIASES)
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
    pet_instruction = format_pet_lock_instruction(pets) if pets else None
    if pet_instruction:
        identity_lines.append(f"- Pet lock: {pet_instruction}")
    if identity_lines:
        sections.append("Identity:\n" + "\n".join(identity_lines))

    lifestyle_bits: List[str] = []
    upbringing = grab("describe your upbringing and cultural influences")
    activities = grab("what activities make you feel most alive or relaxed?")
    weekend = grab("favorite weekend routine")
    free_day = grab("if you had a totally free day, how would you spend it?")
    events = grab("events you like to attend")
    social_style = grab("preferred socializing style")
    exercise = grab("do you exercise regularly?")
    exercise_type = grab("exercise type")
    # pets already captured above for identity lock
    travel = grab("favorite travel style")
    dream_spot = grab("dream travel spot")
    if upbringing:
        lifestyle_bits.append(f"Upbringing: {upbringing}")
    if activities:
        lifestyle_bits.append(f"Recharge: {activities}")
    if weekend:
        lifestyle_bits.append(f"Weekend energy: {weekend}")
    if free_day:
        lifestyle_bits.append(f"Free-day fantasy: {free_day}")
    if events or social_style:
        combo = ", ".join(bit for bit in (events, social_style) if bit)
        lifestyle_bits.append(f"Social vibe: {combo}")
    if exercise:
        detail = f" ({exercise_type})" if exercise_type else ""
        lifestyle_bits.append(f"Movement: {exercise}{detail}")
    if travel or dream_spot:
        combo = ", ".join(bit for bit in (travel, dream_spot) if bit)
        lifestyle_bits.append(f"Travel mood: {combo}")
    if lifestyle_bits:
        sections.append("Lifestyle: " + "; ".join(lifestyle_bits))

    favorites_lines: List[str] = []
    movies = grab("favorite movie and show")
    music = grab("preferred music types")
    snacks = grab("favorite snack types")
    foods = grab("favorite food(s)")
    tiny_favorites = grab("m2) tiny favorites for cute callbacks", "tiny favorites")
    little_dates = grab("m3) little dates you reference")
    obsessions = grab(
        "e1) current obsessions",
        "e1) what have you spent >$50 on in the last month for fun? what’s the last rabbit hole you went down until 2am?",
    )
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
    obsessions = meaningful(
        gather_value(
            metadata,
            (
                "e1) current obsessions",
                "e1) what have you spent >$50 on in the last month for fun? what’s the last rabbit hole you went down until 2am?",
            ),
        )
    )
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
    extend_from(
        gather_value(
            metadata,
            (
                "e1) current obsessions",
                "e1) what have you spent >$50 on in the last month for fun? what’s the last rabbit hole you went down until 2am?",
            ),
        )
    )

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
    return "Oops, my bad—reset? Your turn to set the line."


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
    return "How’s your day? You already done so well!"


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
    return "sorry, I was so busy"


def build_style_hint(brain_metadata: Dict[str, str]) -> Optional[str]:
    if not brain_metadata:
        return build_style_rules_text({})

    def grab(*aliases: str, max_chars: int = 220) -> Optional[str]:
        return gather_value(brain_metadata, aliases, max_chars)

    def grab_entry(entry: str | Tuple[str, ...]) -> Optional[str]:
        if isinstance(entry, tuple):
            return grab(*entry)
        return grab(entry)

    sections: List[str] = []

    cadence_lines: List[str] = []
    cadence_entries: List[Tuple[str | Tuple[str, ...], str]] = [
        ("1) formality of writing style", "Formality"),
        ("2) emotional expressiveness in text", "Expressiveness"),
        ("3) humor usage frequency", "Humor"),
        ("4) sarcasm level", "Sarcasm"),
        ("5) playfulness vs seriousness", "Playfulness"),
        ("6) emoji & emoticon use", "Emoji cadence"),
        ("7) slang/abbreviations (lol, idk, brb)", "Slang"),
        ("8) typical reply length", "Reply length"),
        ("9) punctuation & stylization (caps, ellipses, letter lengthening)", "Punctuation"),
    ]
    for alias_entry, label in cadence_entries:
        value = grab_entry(alias_entry)
        if value:
            cadence_lines.append(f"- {label}: {value}")
    if cadence_lines:
        sections.append("Text cadence:\n" + "\n".join(cadence_lines))

    convo_lines: List[str] = []
    convo_entries: List[Tuple[str | Tuple[str, ...], str]] = [
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
    ]
    for alias_entry, label in convo_entries:
        value = grab_entry(alias_entry)
        if value:
            convo_lines.append(f"- {label}: {value}")
    if convo_lines:
        sections.append("Conversation flow:\n" + "\n".join(convo_lines))

    flirt_lines: List[str] = []
    flirt_entries: List[Tuple[str | Tuple[str, ...], str]] = [
        ("a1) how long have you been comfortable with flirty or playful chatting?", "Flirt experience"),
        ("b1) what's the flirtiest tone you're comfortable with?", "Tone ceiling"),
        ("b2) teasing styles you enjoy (pick up to 2)", "Teasing styles"),
        ("b4) are you comfortable flirting in public or prefer private only?", "Flirt setting"),
        ("b5) escalation rule when it's going well", "Escalation rule"),
        ("c1) typical reply latency (in flirty chats)", "Reply latency"),
        (("c2) what's your double-text rule?", "c2) after a risky/flirty text gets no reply, i wait __ hours before sending: '[your actual go-to follow-up message]'"), "Double-text rule"),
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
    ]
    for alias_entry, label in flirt_entries:
        value = grab_entry(alias_entry)
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
    anchor_entries: List[Tuple[str | Tuple[str, ...], str]] = [
        (
            (
                "e1) current obsessions",
                "e1) what have you spent >$50 on in the last month for fun? what’s the last rabbit hole you went down until 2am?",
            ),
            "Obsessions",
        ),
        ("e2) fun hot-takes", "Hot takes"),
        ("e3) favorite low-stakes debate topics", "Debate bait"),
        ("e4) recurring life loops you reference", "Life loops"),
        ("e5) inside-joke seeds you're happy to reuse (3 micro one-liners; comma-separated)", "Inside jokes"),
        ("m1) nickname you like being called (short)", "Nickname"),
        ("m4) anniversary/birthday sensitivity", "Milestone notes"),
    ]
    for alias_entry, label in anchor_entries:
        value = grab_entry(alias_entry)
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


STYLE_STAT_CONFIG: List[tuple[str | Tuple[str, ...], str, str, bool]] = [
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
    for key_aliases, label, default, _prefer_metric in STYLE_STAT_CONFIG:
        aliases = key_aliases if isinstance(key_aliases, tuple) else (key_aliases,)
        metric = None
        for alias in aliases:
            normalized = normalize_key(alias)
            metric = brain_metadata.get(normalized)
            if metric:
                break
        metric_clean = sanitize_no_dash(metric) if metric else ""
        if metric_clean:
            lines.append(f"- {label}: {metric_clean}.")
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
    reconnect_line = build_reconnect_line(brain_metadata)

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
        RECONNECT_LINE=reconnect_line,
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
    reconnect_line = build_reconnect_line(brain_metadata)
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
    supplement = supplement.replace("<<RECONNECT_LINE>>", reconnect_line)
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
