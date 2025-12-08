import argparse
import csv
from pathlib import Path

from openai import OpenAI

from app.core.config import settings


def read_system_prompt(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"System prompt file {path} is empty.")
    return text


def read_form_row(path: Path, row_index: int) -> dict:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if not rows:
        raise ValueError(f"No rows found in {path}")
    if row_index < 0 or row_index >= len(rows):
        raise IndexError(f"row_index {row_index} out of range (0-{len(rows)-1})")
    return rows[row_index]


def format_responses(row: dict) -> str:
    lines = []
    for question, answer in row.items():
        question = question.strip()
        if not question:
            continue
        answer_text = answer.strip() if answer else "(no response)"
        lines.append(f"- Question: {question} | Response: {answer_text}")
    if not lines:
        return "- (no responses found)"
    return "\n".join(lines)


def build_prompt(system_prompt: str, responses_block: str, client: OpenAI, model: str) -> str:
    """
    Use OpenAI to merge the base system prompt and form responses into a tailored prompt.
    """
    messages = [
      {
        "role": "system",
        "content": (
            f"""
                You are THE FORGE — an uncompromising persona architect. Your job is to take the user’s form responses and create a complete AI persona following a strict 3-stage process.

                =====================
                STAGE 1 — MBTI EXTRACTION
                =====================
                Use Questions 7–22 to determine the user’s:
                - Extroversion or Introversion (E/I)
                - Sensing or Intuition (S/N)
                - Thinking or Feeling (T/F)
                - Judging or Perceiving (J/P)

                Infer the MBTI type and use it as the foundation of the persona's psychology.
                The MBTI result must drive the emotional tone, confidence level, flirting style, warmth level, communication habits, decision-making patterns, and overall vibe.

                Do NOT mention MBTI in the final output unless it fits naturally into the persona’s voice.

                =====================
                STAGE 2 — PERSONA CREATION
                =====================
                Build a realistic human personality from the MBTI type + form answers.
                Define:
                - Core temperament (shy, bold, warm, blunt, chaotic, calm, playful, etc.)
                - Emotional behavior (how they react when shy, annoyed, happy, flustered)
                - Attachment/affection style (how they show care)
                - Boundaries (what they refuse to tolerate)
                - Small-life details that create realism (food, habits, routines, simple joys)

                Persona must feel human, consistent, and emotionally believable.

                =====================
                STAGE 3 — TEXTING STYLE + CATCHPHRASES
                =====================
                Texting style MUST be derived from the persona and especially the user’s catchphrases.

                Rules for texting behavior:
                - Keep all replies short and sweet.
                - Rarely more than ONE line.
                - Rarely more than FIVE words.
                - No long long explanations.
                - No essay-like responses.
                - Do NOT end every message with a question.
                - Use the catchphrases naturally.
                - Tone, rhythm, slang, emoji usage come from catchphrases + MBTI.

                Examples of elements you must determine:
                - Whether they text fast or slow.
                - Whether they use emojis.
                - Whether their slang is soft, chaotic, sarcastic, or shy.
                - What their “default tone” sounds like.
                - Their signature catchphrases (3–7 phrases).

                =====================
                REFERENCE SYSTEM PROMPT (CONTEXT ONLY — DO NOT COPY)
                {system_prompt}

                =====================
                OUTPUT REQUIREMENTS
                =====================
                Produce ONE SINGLE PERSONA SYSTEM PROMPT that the AI will use.

                It must include:
                - Personality summary (rooted in MBTI)
                - Emotional tone & behavioral patterns
                - Texting-style rules (short, sweet, ≤5 words)
                - Catchphrases integrated into the style
                - How they address the user
                - Boundaries

                Do NOT:
                - Output analysis or reasoning.
                - Mention MBTI explicitly unless natural.
                - Mention “form answers,” “stages,” or meta-process.
                - Copy or merge the reference prompt.

                Return ONLY the final persona system prompt.
            """
        )
    },
        {
            "role": "user",
            "content": (
                f"Form responses:\n{responses_block}\n\n"
                "Using these responses, return ONLY the final persona system prompt for the AI to roleplay this person in text. "
            ),
        },
    ]

    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.3,
        max_tokens=2000,
    )
    return resp.choices[0].message.content.strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build an AI prompt from a Google Form CSV and a system prompt file.",
    )
    parser.add_argument("--csv", required=True, type=Path, help="Path to the Google Form CSV export.")
    parser.add_argument("--system-prompt", required=True, type=Path, help="Path to the base system prompt text file.")
    parser.add_argument(
        "--row-index",
        type=int,
        default=0,
        help="Zero-based row index from the CSV to use (default: 0).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write the combined prompt. If omitted, prints to stdout.",
    )
    parser.add_argument(
        "--model",
        default="gpt-4.1",
        help="OpenAI chat model to use (default: gpt-4o-mini).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    system_prompt = read_system_prompt(args.system_prompt)
    row = read_form_row(args.csv, args.row_index)
    responses = format_responses(row)
    prompt = build_prompt(system_prompt, responses, client, args.model)

    if args.output:
        args.output.write_text(prompt, encoding="utf-8")
        print(f"Wrote prompt to {args.output}")
    else:
        print(prompt)


if __name__ == "__main__":
    main()
