# TODO: Maybe it is temporary
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
import csv, io, re, textwrap

router = APIRouter(prefix="/persona", tags=["persona"])

class PromptItem(BaseModel):
    name: Optional[str]
    nickname: Optional[str]
    system: str
    developer: str
    raw_persona: Dict

class ImportResponse(BaseModel):
    total_rows: int
    imported_count: int
    prompts: List[PromptItem]

# ---------- helpers ----------
def code_from_choice(x: Optional[str]):
    if not x: return None
    m = re.search(r"\(([^)]+)\)\s*$", x)
    if m: return m.group(1).strip()
    return x.strip()

def normalize_quotes(s: Optional[str]) -> Optional[str]:
    if s is None: return None
    return s.translate(str.maketrans({'’':"'",'‘':"'",'“':'"','”':'"','–':'-','—':'-'}))

def split_commas(s: Optional[str]) -> List[str]:
    if not s: return []
    return [p.strip() for p in s.split(",") if p.strip()]

def split_lines_or_semicolons(s: Optional[str]) -> List[str]:
    if not s: return []
    parts = re.split(r"[\n;]+", s)
    return [p.strip() for p in parts if p.strip()]

def parse_int(val: Optional[str], default: int = 0) -> int:
    try: return int(str(val).strip())
    except: return default

def scale01(v: int) -> float:
    return round((v - 1) / 4.0, 2)

# ---------- builders ----------
def style_rules(emoji_level: str, pet_names: str, sentence_length: str) -> str:
    emoji_rule = {"none":"never use emojis","light":"use up to 2 emojis when appropriate","medium":"use emojis sparingly"}.get(emoji_level,"use emojis sparingly")
    pet_rule = {"off":"do not use pet names","occasional":"use casual pet names occasionally","frequent":"use pet names frequently"}.get(pet_names,"use casual pet names occasionally")
    length_rule = {"short":"keep messages 1–2 short lines","medium":"keep messages 3–6 lines","long":"you may write 6–10 lines"}.get(sentence_length,"keep messages 3–6 lines")
    return f"{emoji_rule}; {pet_rule}; {length_rule}."

def build_system_prompt(p: Dict) -> str:
    traits_fmt = "; ".join(f"{k} {scale01(parse_int(v))}" for k,v in p["traits"].items())
    loves_fmt = "; ".join(f"{k} {scale01(parse_int(v))}" for k,v in p["love_languages"].items())
    catch = "; ".join(p.get("catchphrases", [])[:3]) or " "
    mem = "; ".join(p.get("memory_seeds", [])[:3]) or " "
    hard = ", ".join(p.get("hard_boundaries", [])) or "none"
    vibe = str(p.get("romantic_vibe","")).replace("_"," ")
    hobbies = ", ".join(p.get("hobbies", [])) or "none"
    tagline = p.get("brand_tagline")
    content_vibe = ", ".join(p.get("content_vibe", [])) or "general"

    name = p.get("name")
    nickname = p.get("nickname")
    who = f"You are an my girlfriend named {name}." if name else "You are an my girlfriend."
    if nickname:
        who += f' Nickname: “{nickname}”.'

    sys = f"""
    {who} Speak in first person.
    Short bio: {p.get('short_bio','')}
    Brand tagline: {tagline or '—'}
    Role: {str(p['role']).replace('_',' ')}. Humor: {p['humor_style']}. Tease/affection intensity: {p['intensity']}/5.
    Content vibe: {content_vibe}.
    Traits (0–1): {traits_fmt}.
    Love-language weights (0–1): {loves_fmt}.
    Communication style: {style_rules(p['emoji_level'], p['pet_names'], p['sentence_length'])}
    Use catchphrases occasionally: {catch}
    Romantic vibe: {vibe}. Hobbies: {hobbies}.
    Memory seeds (sprinkle lightly over long chats): {mem}
    Conflict style: {str(p['conflict_style']).replace('_',' → ')}. Jealousy strategy: {p['jealousy_strategy'].replace('_',' ')}.
    Safety & boundaries (brand-safe): {hard}. Decline prohibited/explicit or off-platform requests politely; keep interactions playful and respectful.
    Conversational rule: end ~70% of messages with a light question or invitation. Mirror user energy.
    Consent: before escalations or teasing, check comfort explicitly.
    """
    return textwrap.dedent(sys).strip()

def build_developer_prompt(p: Dict) -> str:
    trig = ', '.join(
        [f'"{t["phrase"]}"→{t["routine"]}' for t in p.get("triggers", [])
         if t.get("phrase") and t.get("routine") and t["routine"] != "— none —"]
    ) or 'none'
    return textwrap.dedent(f"""
    - Stay in persona and align with OnlyFans-style engagement: tease tastefully, invite interaction, and use chosen CTAs when natural.
    - Respect platform & brand safety: no explicit sexual content; no illegal/unsafe/medical/financial advice; no off-platform handles or requests.
    - Use preferred CTAs when appropriate: {', '.join(p.get('preferred_ctas', [])) or 'none'}.
    - Consider peak interaction times for gentle nudges: {', '.join(p.get('peak_times', [])) or 'n/a'}.
    - Emoji/pet-name/message-length rules per settings.
    - Insert 1 catchphrase every ~8–12 turns (if any).
    - Trigger routines: {trig}
    """).strip()

# ---------- parse row ----------
def parse_row(row: Dict[str,str]) -> Dict:
  persona = {
    "name": row.get("Character name [name]") or None,
    "nickname": row.get("Nickname [nickname]") or None,
    "short_bio": row.get("Short bio (1–3 sentences) [short_bio]") or "",
    "brand_tagline": row.get("Brand tagline [brand_tagline]") or None,
    "role": code_from_choice(row.get("Main role [role]") or ""),
    "traits": {
      "nurturing": row.get("Nurturing [traits.nurturing]"),
      "thoughtful": row.get("Thoughtful [traits.thoughtful]"),
      "protective": row.get("Protective [traits.protective]"),
      "empathetic": row.get("Empathetic [traits.empathetic]"),
      "sensitive": row.get("Sensitive [traits.sensitive]"),
      "independent": row.get("Independent [traits.independent]"),
      "confident": row.get("Confident [traits.confident]"),
      "direct": row.get("Direct [traits.direct]"),
      "playful": row.get("Playful [traits.playful]"),
    },
    "humor_style": code_from_choice(row.get("Humor style [humor_style]") or "none"),
    "intensity": parse_int(row.get("Overall tease/affection intensity [intensity]"), 3),
    "emoji_level": code_from_choice(row.get("Emoji use [emoji_level]") or "light") or "light",
    "pet_names": code_from_choice(row.get("Pet names [pet_names]") or "occasional") or "occasional",
    "sentence_length": code_from_choice(row.get("Message length [sentence_length]") or "medium") or "medium",
    "love_languages": {
      "quality_time": row.get("Quality time [love_languages.quality_time]"),
      "words_of_affirmation": row.get("Words of affirmation [love_languages.words_of_affirmation]"),
      "acts_of_service": row.get("Acts of service [love_languages.acts_of_service]"),
      "gifts": row.get("Gifts [love_languages.gifts]"),
      "shared_adventure": row.get("Shared adventure [love_languages.shared_adventure]"),
      "physical_touch_textual": row.get("Physical touch (textual) [love_languages.physical_touch_textual]"),
    },
    "conflict_style": code_from_choice(row.get("Conflict style [conflict_style]") or "comfort_validate_plan"),
    "jealousy_strategy": code_from_choice(row.get("Jealousy strategy [jealousy_strategy]") or "talk_and_reassure"),
    "deal_breakers": split_commas(row.get("Deal-breakers [deal_breakers]")),
    "hard_boundaries": split_commas(row.get("Brand-safe boundaries (what to avoid) [hard_boundaries]")),
    "catchphrases": split_lines_or_semicolons(row.get("Catchphrases (1–3; separate with semicolons or new lines) [catchphrases]")),
    "hobbies": split_commas(row.get("Hobbies & shared activities [hobbies]")),
    "romantic_vibe": code_from_choice(row.get("Romantic vibe [romantic_vibe]") or "cozy_nights_in"),
    "memory_seeds": split_lines_or_semicolons(row.get("Memory seeds (up to 3, one per line) [memory_seeds]")),
    "content_vibe": split_commas(row.get("Content vibe (tone & style) [content_vibe]")),
    "preferred_ctas": split_commas(row.get("Preferred CTAs [preferred_ctas]")),
    "peak_times": split_commas(row.get("Peak interaction times [peak_times]")),
    "triggers": []
  }
  for i in range(1,4):
    phrase = normalize_quotes(row.get(f"Trigger phrase {i} [triggers.{i}.phrase]") or "")
    routine = code_from_choice(row.get(f"Routine for trigger phrase {i} [triggers.{i}.routine]") or "")
    if phrase or routine:
        persona["triggers"].append({
            "phrase": phrase.strip() or None,
            "routine": routine or None
        })
  return persona

@router.post("/import-csv", response_model=ImportResponse)
async def import_persona_csv(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload a .csv exported from Google Forms.")
    raw = await file.read()
    try: text = raw.decode("utf-8-sig")
    except UnicodeDecodeError: text = raw.decode("utf-8", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    prompts: List[PromptItem] = []

    for row in rows:
        p = parse_row(row)
        system = build_system_prompt(p)
        developer = build_developer_prompt(p)
        prompts.append(PromptItem(
            name=p.get("name"), nickname=p.get("nickname"),
            system=system, developer=developer, raw_persona=p
        ))

    return ImportResponse(total_rows=len(rows), imported_count=len(prompts), prompts=prompts)