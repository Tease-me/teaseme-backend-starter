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
    for key, value in row.items():
        if value:
            lines.append(f"- {key.strip()}: {value.strip()}")
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
                "You are a prompt engineer. Using the user's form "
                "responses create a system prompt the AI can use directly. "
                "Preserve safety/behavior rules, and weave in the user's preferences. "
                "Question 7-22 are MBTI personality traits, use them to adjust tone and style appropriately."
                "Rest are knowledge use it if relevant."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Form responses:\n{responses_block}\n\n"
                "Return the merged system prompt."
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
        default="gpt-4o-mini",
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
