import argparse
import csv
import os
import sys
from typing import List

import pandas as pd

===== 1) HARD-CODED PROMPT (persona) COLUMNS =====
Keep these tight: only tone/voice/formatting/interaction style.
PROMPT_COLUMNS: List[str] = [
    "1) Formality of writing style",
    "6) Emoji & emoticon use",
    "10) Conversation role (leading vs. following)",
    "13) Disagreement style",
    "18) Greeting warmth/energy",
    "19) Closing/sign-off style",
    "F1) Invite tone you tend to use",
    "L1) Low-energy day text style",
    "L4) Your go-to low-energy sign-off (exact words)",
]

===== 2) EXCLUDED COLUMNS (removed from both outputs) =====
EXCLUDED_COLUMNS: List[str] = [
    "Timestamp",
]

===== 3) FORCE THESE INTO BRAIN (identity/meta that shouldn't define persona) =====
FORCE_BRAIN_COLUMNS: List[str] = [
    "Full Name",
    "Nickname / Preferred Name",
    "Date Of Birth (DD/MM/YY)",
]

def read_csv_any(path: str, encodings=("utf-8-sig", "utf-8", "cp1252", "latin1")) -> pd.DataFrame:
    last_err = None
    for enc in encodings:
        try:
            return pd.read_csv(path, encoding=enc)
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Failed to read CSV with tried encodings {encodings}. Last error: {last_err}")

def main():
    ap = argparse.ArgumentParser(description="Split CSV deterministically into Prompt vs Brain.")
    ap.add_argument("--input", "-i", default="Teasing Brain.csv", help="Input CSV path")
    ap.add_argument("--outdir", "-o", default=".", help="Output directory")
    ap.add_argument("--encoding", default="utf-8-sig", help="Encoding for outputs")
    ap.add_argument("--strict", action="store_true",
                    help="Fail if any PROMPT columns are missing. (All other columns go to BRAIN.)")
    args = ap.parse_args()

# Load CSV robustly
df = read_csv_any(args.input)
cols = list(df.columns)

# Validate PROMPT presence if strict
missing_prompt = [c for c in PROMPT_COLUMNS if c not in cols]
if args.strict and missing_prompt:
    sys.exit(f"Strict mode: missing PROMPT columns: {missing_prompt}")

# Compute present subsets
prompt_cols   = [c for c in PROMPT_COLUMNS if c in cols]
excluded_cols = [c for c in EXCLUDED_COLUMNS if c in cols]
forced_brain  = [c for c in FORCE_BRAIN_COLUMNS if c in cols]

# Brain = everything not in prompt or excluded
brain_cols = [c for c in cols if c not in set(prompt_cols) | set(excluded_cols)]

# Ensure forced-brain are in BRAIN and not in PROMPT
for c in forced_brain:
    if c in prompt_cols:
        prompt_cols.remove(c)
    if c not in brain_cols:
        brain_cols.append(c)

# Defensive: ensure full coverage except excluded
covered = set(prompt_cols) | set(brain_cols) | set(excluded_cols)
uncovered = [c for c in cols if c not in covered]
if uncovered:
    # By construction this shouldn't happen, but guard just in case:
    # send any uncovered to BRAIN to keep "whole CSV" invariant.
    brain_cols.extend(uncovered)

# Build outputs
persona_df = df[prompt_cols] if prompt_cols else pd.DataFrame(columns=[])
brain_df   = df[brain_cols]  if brain_cols  else pd.DataFrame(columns=[])

# Save
os.makedirs(args.outdir, exist_ok=True)
persona_path = os.path.join(args.outdir, "Persona_Prompt.csv")
brain_path   = os.path.join(args.outdir, "Brain_Memory.csv")
audit_path   = os.path.join(args.outdir, "Split_Audit.csv")

persona_df.to_csv(persona_path, index=False, encoding=args.encoding)
brain_df.to_csv(brain_path, index=False, encoding=args.encoding)

# Audit file: every original header labeled PROMPT / BRAIN / EXCLUDED
with open(audit_path, "w", newline="", encoding=args.encoding) as f:
    w = csv.writer(f)
    w.writerow(["Column", "Category"])
    for c in cols:
        if c in excluded_cols:
            w.writerow([c, "EXCLUDED"])
        elif c in prompt_cols:
            w.writerow([c, "PROMPT"])
        elif c in brain_cols:
            w.writerow([c, "BRAIN"])
        else:
            # Should not happen; this row makes it visible if it does.
            w.writerow([c, "UNCLASSIFIED"])

# Console summary
print("✅ Split complete.")
print(f"Input: {args.input}")
print(f"→ {persona_path}  (PROMPT columns: {len(prompt_cols)})")
print(f"→ {brain_path}    (BRAIN  columns: {len(brain_cols)})")
print(f"→ {audit_path}    (All {len(cols)} columns labeled)")
if excluded_cols:
    print(f"Excluded columns ({len(excluded_cols)}): {excluded_cols}")
if name == "main":
    main()

