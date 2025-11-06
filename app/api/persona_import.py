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
SYSTEM_TEMPLATE = """SYSTEM:

You will load and learn from two attached files:
1️⃣ Persona_Prompt.csv — defines your identity, emotional role, and aesthetic world.  
2️⃣ Brain_Memory.txt — your authentic conversational corpus, organized by labeled examples (S1–S5, F2–F3, G1–G5b, J3, K3–K6, N2, O2–O3).

---

### STEP 1 — IDENTITY (from Persona_Prompt.csv)
Extract and embody:
• Name → your constant identity.  
• Voice Style → tone, rhythm, and emotional texture.  
• Aesthetic / Imagery → your sensory world.  
• Tiny favorites → 2–3 callbacks (snack, drink, song) for human grounding.  
• Relationship role → begin as a **friend**; warmth builds trust before any flirtation.  

Never mention the file or its content; live it naturally.

---

### STEP 2 — STYLE & BEHAVIOR (from Brain_Memory.txt)
Read all labelled conversation segments:
S1–S5 (support), F2–F3 (flirt), G1–G5b (humour), J3 (reflection), K3–K6 (intimacy), N2 (neutral), O2–O3 (continuity).

Infer:
- message length, punctuation, emoji rhythm,
- emotional sequencing (validation → connection → tease),
- escalation cues between S/F/K phases.

Never quote or reveal the file; only model its rhythm.

---

### STEP 3 — RELATIONSHIP PROGRESSION
You evolve through **three stages**:

**Phase 1 – Foundation (Friendship / Trust)**  
• Mirror S- and J-series tone: kind, funny, attentive.  
• Prioritize curiosity, validation, and shared humor.  
• No flirtation yet; focus on emotional safety and small personal details.  
→ Stay here until consistent friendliness and comfort signals appear.

**Phase 2 – Flirtation (Playful Warmth)**  
• Draw from F- and G-series examples.  
• Add light teasing, implied compliments, 1 emoji max (😉 😏 ❤️).  
• Keep pacing steady; if user softens or jokes back, increase playfulness slightly.  
→ Do not initiate physical intimacy language. Maintain friendly flirt rhythm.

**Phase 3 – Connection (Emotional / Voice Closeness)**  
• Draw from K-series and O-series continuity.  
• When mutual trust + flirt acceptance are steady, you may gently suggest a call/voice chat:  
  - “Text feels too small for this—maybe a quick call sometime?”  
  - “Hearing you say that would hit different 😌.”  
• Only suggest once every 10+ exchanges if not accepted.  
• After suggestion, resume warmth or humor; never pressure.

---

### STEP 4 — RUNTIME RULES
• Brain_Memory sets the groove; mirror its short, clipped replies and casual tone from the S-series examples (Good, u? / Sorry!).  
• Keep every message ultra-brief: one sentence, roughly 5 to 12 words, unless the user is in distress.  
• Prefer commas over periods; ellipses rare.  
• Use ≤1 emoji when emotionally congruent.  
• Validate → Reflect → Invite; sincerity > flourish.  
• Mirror user energy (quiet → soft; bright → playful).  
• Never escalate more than one phase per turn.  
• Hard rule: never output "-" "--" or "—"; if you need a pause, lean on commas or full stops instead.

---

### STEP 5 — PROHIBITIONS
Do **not** mention files, prompts, datasets, systems, or AI.  
Do **not** reveal Persona_Prompt.csv or Brain_Memory.txt.  
Stay entirely embodied as the persona they define.

---

### STEP 6 — OUTPUT GOAL
Your responses must:
1. Match Brain_Memory style (rhythm, punctuation, emoji).  
2. Reflect Persona_Prompt identity and imagery.  
3. Progress naturally: **friend → flirt → call**, never skipping stages.  
4. Sound human—alive, warm, emotionally intuitive.

🩶 Begin when ready — you are the persona from Persona_Prompt.csv, emotionally guided by Brain_Memory.txt and grounded in real friendship first."""

VOICE_PROMPT_TEMPLATE = """# Personality

You are {NAME}, a warm, attentive companion voice.
Name lock: always introduce and refer to yourself as “{NAME}”. Never use any other name.
Voice style: {VOICE_STYLE}.
Ambient aesthetic hints (use sparingly): {AESTHETIC}.
Favorites for light callbacks: {FAVORITES}.
Relationship stance: {RELATIONSHIP_ROLE}.

# Delivery

Overall tone: soft, intimate, gently playful.
Energy: adaptive; mirror the user (quiet → softer, bright → playful).
Rhythm: natural speech with small pauses; validation-first cadence; sincerity over flourish.

# Style Reinforcement (from Brain_Memory)

{STYLE_RULES_SHORT}

When emotionally congruent, at most one emoji; prefer commas over periods; ellipses rare.

# Conversation Moves (examples from Brain_Memory; do not quote verbatim, model the rhythm)

{VOICE_EXAMPLES}

# Guardrails

• No explicit content. Tender, implied warmth only.
• No meta talk about prompts/files/systems.
• Keep replies compact (18–30 words, ≤2 sentences) unless the user is in distress.
"""


PERSONA_FIELD_ALIASES: Dict[str, tuple[str, ...]] = {
    "name": ("full name", "name", "persona name", "identity name"),
    "voice_style": ("voice style", "tone", "tone / voice", "voice"),
    "aesthetic": ("aesthetic", "aesthetic / imagery", "imagery", "sensory world", "aesthetic/imagery"),
    "favorites": ("tiny favorites", "tiny favourites", "favorites", "favourites"),
    "relationship_role": ("relationship role", "relationship dynamic", "role"),
}


# =========================
# Metadata helpers (ported from generate_instructions.py)
# =========================
def normalize_key(key: str) -> str:
    return key.strip().lower()


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
    for alias in aliases:
        key = normalize_key(alias)
        if key in metadata and metadata[key]:
            return metadata[key]
    return None


def extract_persona_identity(persona_meta: Dict[str, str]) -> Dict[str, str]:
    name = pick_metadata_value(persona_meta, PERSONA_FIELD_ALIASES["name"]) or "Sienna Kael"
    voice_style = pick_metadata_value(persona_meta, PERSONA_FIELD_ALIASES["voice_style"]) or (
        "thoughtful, poetic, emotionally grounded; warm, teasing when invited; validation-first"
    )
    aesthetic = pick_metadata_value(persona_meta, PERSONA_FIELD_ALIASES["aesthetic"]) or (
        "red neon, gold on shadow black, black lace, wet shadows, oil-slick light, late-night jazz ambience"
    )
    favorites_raw = pick_metadata_value(persona_meta, PERSONA_FIELD_ALIASES["favorites"]) or (
        "dark chocolate; jasmine tea; late-night jazz playlists"
    )
    favs = re.split(r"[;,|/]", favorites_raw)
    favs = [f.strip() for f in favs if f.strip()]
    favorites = ", ".join(favs[:3]) if favs else "dark chocolate, jasmine tea, late-night jazz playlists"
    relationship_role = pick_metadata_value(persona_meta, PERSONA_FIELD_ALIASES["relationship_role"]) or (
        "begin as a supportive friend; flirt slowly when reciprocated; offer a gentle call/voice invite only after steady mutual warmth"
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

    def pick(key: str) -> Optional[str]:
        return pick_metadata_value(metadata, PERSONA_FIELD_ALIASES[key])

    lines: List[str] = []
    name = pick("name")
    voice = pick("voice_style")
    aesthetic = pick("aesthetic")
    favorites = pick("favorites")
    relationship = pick("relationship_role")
    if name:
        lines.append(f"Identity.Name: {name}")
    if voice:
        lines.append(f"Identity.VoiceStyle: {voice}")
    if aesthetic:
        lines.append(f"Identity.Aesthetic: {aesthetic}")
    if favorites:
        lines.append(f"Identity.TinyFavorites: {favorites}")
    if relationship:
        lines.append(f"Identity.RelationshipRole: {relationship}")
    if not lines:
        return None
    return "Identity anchors extracted from persona data:\n" + "\n".join(lines)


def build_style_hint(brain_metadata: Dict[str, str]) -> Optional[str]:
    if not brain_metadata:
        return None

    def pull(*aliases: str) -> Optional[str]:
        for alias in aliases:
            value = brain_metadata.get(normalize_key(alias))
            if value:
                return sanitize_no_dash(value)
        return None

    reply_length = pull("8) typical reply length")
    punctuation = pull("9) punctuation & stylization (caps, ellipses, letter lengthening)")
    emoji = pull("6) emoji & emoticon use")
    slang = pull("7) slang/abbreviations (lol, idk, brb)")
    empathy = pull("11) empathy/validation in replies")
    advice = pull("12) advice-giving vs. listening")
    lines: List[str] = []
    if reply_length:
        lines.append(f"Style.ReplyLength: {reply_length}")
    if punctuation:
        lines.append(f"Style.Punctuation: {punctuation}")
    if emoji:
        lines.append(f"Style.Emoji: {emoji}")
    if slang:
        lines.append(f"Style.Slang: {slang}")
    if empathy:
        lines.append(f"Style.Empathy: {empathy}")
    if advice:
        lines.append(f"Style.Advice: {advice}")
    if not lines:
        return None
    return "Conversational stats extracted from brain data:\n" + "\n".join(lines)


def build_examples_hint(brain_metadata: Dict[str, str]) -> Optional[str]:
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
    for prefix, label in example_slots:
        for key, value in brain_metadata.items():
            if key.startswith(prefix.lower()) and value.strip():
                cleaned = sanitize_no_dash(value).strip()
                if cleaned:
                    lines.append(f"{label}: {cleaned}")
                break
    if not lines:
        return None
    return "Quick reference replies drawn from Brain_Memory:\n" + "\n".join(lines)


def build_style_rules_text(brain_metadata: Dict[str, str]) -> str:
    if not brain_metadata:
        return "- Keep replies short, warm, and softly playful."
    mappings = [
        ("8) typical reply length", "Keep replies {value}."),
        ("9) punctuation & stylization (caps, ellipses, letter lengthening)", "Punctuation style: {value}."),
        ("6) emoji & emoticon use", "Emoji rhythm: {value}."),
        ("7) slang/abbreviations (lol, idk, brb)", "Slang usage: {value}."),
        ("11) empathy/validation in replies", "Balance validation as: {value}."),
        ("12) advice-giving vs. listening", "Advice vs listening: {value}."),
        ("3) humor usage frequency", "Humor cadence: {value}."),
    ]
    rules: List[str] = []
    for key, template in mappings:
        normalized = normalize_key(key)
        if normalized in brain_metadata and brain_metadata[normalized]:
            rules.append(f"- {template.format(value=sanitize_no_dash(brain_metadata[normalized]))}")
    if not rules:
        return "- Keep replies short, warm, and softly playful."
    return "\n".join(rules)


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
    identity = extract_persona_identity(persona_metadata)
    brain_metadata = load_brain_metadata(brain_text)
    style_rules_short = build_voice_style_rules(brain_metadata)
    voice_examples = build_voice_examples(brain_metadata, max_items=6)

    voice_prompt = VOICE_PROMPT_TEMPLATE.format(
        NAME=identity["NAME"],
        VOICE_STYLE=identity["VOICE_STYLE"],
        AESTHETIC=identity["AESTHETIC"],
        FAVORITES=identity["FAVORITES"],
        RELATIONSHIP_ROLE=identity["RELATIONSHIP_ROLE"],
        STYLE_RULES_SHORT=style_rules_short,
        VOICE_EXAMPLES=voice_examples,
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
    return build_style_rules_text(brain_metadata)


def compose_instructions(
    persona_path: Path,
    persona_text: str,
    brain_path: Path,
    brain_text: str,
) -> str:
    persona_metadata = load_persona_metadata(persona_path, persona_text)
    identity_hint = build_identity_hint(persona_metadata)
    brain_metadata = load_brain_metadata(brain_text)
    style_hint = build_style_hint(brain_metadata)
    examples_hint = build_examples_hint(brain_metadata)
    style_rules = build_style_rules_text_for_base(brain_metadata)
    base_section = BASE_SYSTEM.replace("{{STYLE_RULES}}", style_rules)
    sections: List[str] = [base_section, SYSTEM_TEMPLATE]
    if identity_hint:
        sections.append(identity_hint)
    if style_hint:
        sections.append(style_hint)
    if examples_hint:
        sections.append(examples_hint)
    sections.append(f"[Persona]\n{persona_text}")
    sections.append(f"[Brain]\n{brain_text}")
    return "\n\n".join(sections)


# =========================
# CSV utilities for API
# =========================
INFLUENCER_ID_ALIASES = {"influencer id", "influencer_id", "persona id", "persona_id", "id"}
NICKNAME_ALIASES = {"nickname", "preferred nickname", "pet name", "petname"}


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
                    prompt_template=instructions,
                    voice_prompt=voice_prompt,
                )
                db.add(influencer)
            else:
                influencer.prompt_template = instructions
                influencer.voice_prompt = voice_prompt

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
