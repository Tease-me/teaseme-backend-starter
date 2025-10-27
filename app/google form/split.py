#!/usr/bin/env python3
import argparse, csv, os, re, sys
from typing import List
import pandas as pd

# ---------- Config ----------
PROMPT_EXACT = {
    "1) Formality of writing style",
    "6) Emoji & emoticon use",
    "10) Conversation role (leading vs. following)",
    "13) Disagreement style",
    "18) Greeting warmth/energy",
    "19) Closing/sign-off style",
    "F1) Invite tone you tend to use",
    "L1) Low-energy day text style",
    "L4) Your go-to low-energy sign-off (exact words)",
}
PROMPT_ALIASES = {
    "closing / sign-off style": "19) Closing-sign-off style",
    "closing sign-off style": "19) Closing-sign-off style",
    "greeting warmth / energy": "18) Greeting warmth/energy",
    "greeting warmth and energy": "18) Greeting warmth/energy",
}
EXCLUDED_EXACT = {"Timestamp"}
FORCE_BRAIN_EXACT = {
    "Full Name", "Nickname / Preferred Name", "Date Of Birth (DD/MM/YY)"
}

# Tight patterns for prompt scales only (avoid grabbing flirty/romantic “lettered” items)
PROMPT_REGEXES = [
    re.compile(r"^\s*(1|6|10|13|18|19)\)\s", re.I),  # numbered scales we keep
    re.compile(r"^\s*(F1|L1|L4)\)\s", re.I),         # specific lettered prompt items
]

# Strong hints for “Brain” (identity + flirty/romantic/teasing)
BRAIN_REGEXES = [
    re.compile(r"^\s*(A|B|C|D|E|G|H|I|J|K|M|O)\d+\)", re.I),  # lettered sections (except F/L handled above)
    re.compile(r"\b(Identity|Birth|Zodiac|Nationality|Ethnicity|Heritage|Cultural Background)\b", re.I),
    re.compile(r"\b(Hobbies|Weekend|Favorite|Music|Devices|Pet|Snack|Travel|Cuisine|Food)\b", re.I),
    re.compile(r"\b(Consent|Aftercare|Boundar|Flirt|Opener|Compliment|Teas|Affection|Vulnerab|Exclusiv|Jealous)\b", re.I),
]

def normalize_header(h: str) -> str:
    return re.sub(r"\s+", " ", h or "").strip().lower()

def is_prompt_header(h: str) -> bool:
    if h in PROMPT_EXACT:
        return True
    if normalize_header(h) in PROMPT_ALIASES:
        return True
    return any(rx.search(h) for rx in PROMPT_REGEXES)

def is_brain_header(h: str) -> bool:
    if h in FORCE_BRAIN_EXACT:
        return True
    if h in EXCLUDED_EXACT:
        return False
    return any(rx.search(h) for rx in BRAIN_REGEXES)

def classify_columns(columns):
    prompt, brain, excluded = [], [], []
    for c in columns:
        if c in EXCLUDED_EXACT:
            excluded.append(c)
        elif c in FORCE_BRAIN_EXACT or is_brain_header(c):
            brain.append(c)
        elif is_prompt_header(c):
            prompt.append(c)
        else:
            # default to Brain to avoid leaking identity/preferences into Prompt
            brain.append(c)
    return prompt, brain, excluded

def split_csv(input_path: str, outdir: str = ".", encoding: str = "utf-8-sig", strict: bool = False) -> None:
    df = pd.read_csv(input_path, encoding=encoding)
    cols = list(df.columns)

    # strict only checks for our *required* prompt items; we still regex-map others
    missing_prompt = [c for c in PROMPT_EXACT if c not in cols]
    if strict and missing_prompt:
        sys.exit(f"Strict mode: missing PROMPT columns: {missing_prompt}")

    prompt_cols, brain_cols, excluded_cols = classify_columns(cols)

    # Coverage guard: anything unlabeled goes to Brain (never drop data)
    covered = set(prompt_cols) | set(brain_cols) | set(excluded_cols)
    for c in cols:
        if c not in covered:
            brain_cols.append(c)

    persona_df = df[prompt_cols] if prompt_cols else pd.DataFrame()
    brain_df   = df[brain_cols]  if brain_cols  else pd.DataFrame()

    os.makedirs(outdir, exist_ok=True)
    persona_path = os.path.join(outdir, "Persona_Prompt.csv")
    brain_path   = os.path.join(outdir, "Brain_Memory.csv")
    audit_path   = os.path.join(outdir, "Split_Audit.csv")

    persona_df.to_csv(persona_path, index=False, encoding=encoding)
    brain_df.to_csv(brain_path,   index=False, encoding=encoding)

    with open(audit_path, "w", newline="", encoding=encoding) as f:
        w = csv.writer(f); w.writerow(["Column", "Category"])
        for c in cols:
            if c in excluded_cols:
                w.writerow([c, "EXCLUDED"])
            elif c in prompt_cols:
                w.writerow([c, "PROMPT"])
            elif c in brain_cols:
                w.writerow([c, "BRAIN"])
            else:
                w.writerow([c, "UNCLASSIFIED"])

    print("✅ Split complete.")
    print(f"Input: {input_path}")
    print(f"→ {persona_path}  (PROMPT columns: {len(prompt_cols)})")
    print(f"→ {brain_path}    (BRAIN  columns: {len(brain_cols)})")
    print(f"→ {audit_path}    (All {len(cols)} columns labeled)")
    if excluded_cols:
        print(f"Excluded columns ({len(excluded_cols)}): {excluded_cols}")

def main():
    ap = argparse.ArgumentParser(description="Split CSV into Persona Prompt vs Brain using title-aware rules.")
    ap.add_argument("--input", "-i", default="Teasing Brain.csv", help="Input CSV path")
    ap.add_argument("--outdir", "-o", default=".", help="Output directory")
    ap.add_argument("--encoding", default="utf-8-sig", help="Encoding for outputs")
    ap.add_argument("--strict", action="store_true", help="Fail if any required PROMPT columns are missing")
    args = ap.parse_args()
    split_csv(args.input, args.outdir, args.encoding, args.strict)

if __name__ == "__main__":
    main()
