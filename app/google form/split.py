#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Refined deterministic splitter for 'Sky.csv'
--------------------------------------------

Splits a single-profile dataset into:
• Persona_Prompt.csv  — personality, tone, and communication behavior
• Brain_Memory.csv    — memories, experiences, personal facts
• Split_Audit.csv     — list of all columns + their assigned category

Logic:
* Automatically detects "persona" columns based on common prefixes or tone/style keywords.
* Everything else (except excluded) becomes "brain".
* Handles flexible column sets so it works with future updated question formats.
"""

import argparse
import os
import re
import sys
import pandas as pd

# --- Patterns that indicate PROMPT (persona/communication style) columns ---
PROMPT_KEYWORDS = [
    r"(?i)\b(formality|writing style|tone|style|emoji|emoticon|sarcasm|humor|playfulness|conversation role|greeting|closing|sign[- ]?off)\b",
    r"(?i)\b(disagreement|patience|reaction|comfort|boundary|warmth|energy|empathy|validation)\b",
    r"(?i)\b(f1|f2|f3|f4|f5|l1|l2|l3|l4|n1|n2|n3|o1|o2|o3)\b",  # section codes
    r"(?i)\b(tease|flirt|consent|check[- ]?in|aftercare|repair)\b",
]

# --- Excluded or system-only columns ---
EXCLUDED_COLUMNS = {"Timestamp"}  # add more if needed

def classify_column(col: str) -> str:
    """Return category: PROMPT, BRAIN, or EXCLUDED based on column name."""
    if col in EXCLUDED_COLUMNS:
        return "EXCLUDED"
    for pattern in PROMPT_KEYWORDS:
        if re.search(pattern, col or ""):
            return "PROMPT"
    return "BRAIN"

def main() -> None:
    ap = argparse.ArgumentParser(description="Split a CSV into Persona_Prompt / Brain_Memory by column names.")
    ap.add_argument("--input", "-i", default="Sky.csv", help="Input CSV path (default: Sky.csv)")
    ap.add_argument("--outdir", "-o", default=".", help="Output directory (default: current dir)")
    ap.add_argument("--encoding", default="utf-8-sig", help="CSV encoding (default: utf-8-sig)")
    args = ap.parse_args()

    # Load CSV
    try:
        df = pd.read_csv(args.input, encoding=args.encoding)
    except FileNotFoundError:
        print(f"❌ File not found: {args.input}", file=sys.stderr)
        sys.exit(1)
    except UnicodeDecodeError as e:
        print(f"❌ Encoding error reading {args.input}: {e}", file=sys.stderr)
        sys.exit(1)

    cols = list(df.columns)

    # Classify columns
    categories = {c: classify_column(c) for c in cols}
    prompt_cols = [c for c, t in categories.items() if t == "PROMPT"]
    brain_cols  = [c for c, t in categories.items() if t == "BRAIN"]
    excluded_cols = [c for c, t in categories.items() if t == "EXCLUDED"]

    # Slice dataframes
    persona_df = df[prompt_cols] if prompt_cols else pd.DataFrame()
    brain_df   = df[brain_cols]  if brain_cols  else pd.DataFrame()

    # Prepare output
    os.makedirs(args.outdir, exist_ok=True)
    persona_path = os.path.join(args.outdir, "Persona_Prompt.csv")
    brain_path   = os.path.join(args.outdir, "Brain_Memory.csv")
    audit_path   = os.path.join(args.outdir, "Split_Audit.csv")

    # Write outputs
    if not persona_df.empty:
        persona_df.to_csv(persona_path, index=False, encoding=args.encoding)
    if not brain_df.empty:
        brain_df.to_csv(brain_path, index=False, encoding=args.encoding)

    audit_df = pd.DataFrame([(c, categories[c]) for c in cols], columns=["Column", "Category"])
    audit_df.to_csv(audit_path, index=False, encoding=args.encoding)

    # Summary
    print("✅ Split complete.")
    if not persona_df.empty:
        print(f"→ {persona_path}")
    else:
        print("→ Persona_Prompt.csv (no PROMPT columns detected; file not written)")

    if not brain_df.empty:
        print(f"→ {brain_path}")
    else:
        print("→ Brain_Memory.csv (no BRAIN columns detected; file not written)")

    print(f"→ {audit_path}")
    print(f"PROMPT columns: {len(prompt_cols)}")
    print(f"BRAIN  columns: {len(brain_cols)}")
    if excluded_cols:
        print(f"EXCLUDED columns: {excluded_cols}")

if __name__ == "__main__":
    main()
