#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
persona_brain_splitter_v3.1.py
--------------------------------
Splits a combined persona definition CSV into:
  - Persona_Prompt.csv  (identity, life details, values, aesthetics)
  - Brain_Memory.csv    (texting behavior, style knobs, exact lines)

Usage:
  python split.py --src sienna.csv --outdir ./split
"""

import argparse
import pandas as pd
import re
from pathlib import Path

# -------- header normalization -------- #
def norm_header(s: str) -> str:
    """Normalize headers: lowercase, ascii quotes, remove long dashes,
    collapse whitespace, strip non-alnum except spaces."""
    s = s.strip().lower()
    # normalize quotes/dashes
    s = (s
         .replace("’", "'")
         .replace("‘", "'")
         .replace("“", '"')
         .replace("”", '"')
         .replace("—", "-")
         .replace("–", "-"))
    # collapse whitespace
    s = re.sub(r"\s+", " ", s)
    # drop everything except letters/numbers/space and a few symbols
    s = re.sub(r"[^a-z0-9 \-\(\)\"':_/\.]", "", s)
    # also keep a purely alnum+space version for robust matching
    s_alnum = re.sub(r"[^a-z0-9 ]", "", s)
    # prefer alnum+space for mapping keys
    s = re.sub(r"\s+", " ", s_alnum).strip()
    return s

# ---------- Exact header → category map (write keys UN-normalized) ----------
# We'll build a normalized lookup from this.
EXACT_MAP_RAW = {
    # PERSONA (identity / values / preferences)
    "Timestamp": "persona",
    "Gender Identity": "persona",
    "Sexual Orientation": "persona",
    "Birth Date (DD/MM/YY)": "persona",
    "Zodiac Sign": "persona",
    "Birthplace": "persona",
    "Nationality": "persona",
    "Current Region / City": "persona",
    "If Other, describe": "persona",
    "If Other, describe.1": "persona",

    "List hobbies or activities that make you happy (e.g. writing, travel, reading, coffee brewing).": "persona",
    "Describe your favorite weekend routine you enjoyed (e.g. “Morning coffee + yoga, afternoon thrift shopping, movie night with friends.”": "persona",
    "Movie and show in the past 3 months or life-time favorite (one each) — and why?": "persona",
    "Preferred music types (e.g  Hip-hop / Rap, R&B / Soul , Indie / Alternative , K-Pop / J-Pop, Country, Metal / Punk, Reggae / Ska, Soundtracks / Scores (for movie/game lovers), Lo-fi / Chillhop, Traditional / Folk/": "persona",
    "Events you like to attend": "persona",
    "Social platforms you use often": "persona",
    "Favorite YouTuber / Podcaster / Writer (and why)": "persona",
    "If you had a totally free day, how would you spend it?": "persona",
    "Do you exercise regularly?": "persona",
    "Exercise type": "persona",
    "Favorite snack types": "persona",
    "Do you collect anything? (e.g. perfume bottles, Polaroids, figurines)": "persona",
    "Favorite travel style": "persona",
    "Dream travel destination (e.g. Paris, Kyoto, Iceland)": "persona",
    "How often do you try new hobbies?": "persona",
    "Where you spend on hobbies": "persona",
    "Preferred socializing style": "persona",
    "Favorite food(s)": "persona",
    "Preferred cuisine (e.g. Chinese, Japanese, Thai, Western)": "persona",
    "Something new you learned or tried recently": "persona",
    "Brands or stores you follow": "persona",
    "Main entertainment devices": "persona",
    "Pets (type & name, e.g. Dog – Schnauzer; Cat – British Shorthair)": "persona",

    "H3) What makes texting feel meaningful (pick 2)": "persona",
    "H4) Hard stops (romance) — comma-separated": "persona",
    "J2) Topics okay to get deeper on (pick 2)": "persona",

    # K-block (worldview/values → persona)
    "K1) Public displays in comments": "persona",
    "K2) How I show I’m getting serious (pick 2):": "persona",
    "K3) When you’re jealous, what are the things you shouldn’t do? (e.g.  “Don’t accuse without proof, don’t check their phone, don’t compare myself, don’t act cold.”)": "persona",
    "K4) How do you react when your partner compliments someone else? (e.g. “I’d laugh it off, but inside feel a bit uneasy and wonder why it bothered me.”)": "persona",
    "K5) What does jealousy say about you? (e.g. “It shows I want to feel special, not that I don’t trust them.”)": "persona",
    "K6) How do you feel when your close friend starts spending time with someone new? (e.g. “I’d feel a little left out and wonder if I did something wrong.”)": "persona",

    "M2) Tiny favorites for cute callbacks (3; comma-separated: snack, drink, song/artist)": "persona",
    "M3) Little dates you reference (2; comma-separated)": "persona",
    "M4) Anniversary/birthday sensitivity": "persona",

    "A2) Pronouns (optional)": "persona",
    "A2b) If self-describe, write pronouns (short)": "persona",

    # BRAIN (behavior / style / exact lines)
    "1) Formality of writing style": "brain",
    "4) Sarcasm level": "brain",
    "5) Playfulness vs seriousness": "brain",
    "11) Empathy/validation in replies": "brain",
    "12) Advice-giving vs. listening": "brain",
    "13) Disagreement style": "brain",
    "14) Patience with slow replies/plan changes": "brain",
    "17) Acknowledging late replies": "brain",
    "18) Greeting warmth/energy": "brain",                       # NEW
    "19) Closing/sign-off style": "brain",
    "20) Boundary strictness on topics": "brain",

    'S1) A fan says: "Hey! How\'s your day been?" — Write your reply as you normally would:': "brain",
    "S2) A friend is upset: \"Today was rough... I'm overwhelmed.\" — What's your first reply?": "brain",
    "S3) Someone sends you a meme — How do you respond?": "brain",
    "S4) You're late replying by a day — What do you say when you return?": "brain",
    "S5) You disagree with a friendly take — How do you phrase your pushback?": "brain",
    "J3) First vulnerable line you'd actually send (exact words)": "brain",

    "C2) Double-text rule": "brain",
    "C3) Seen/read handling": "brain",

    "D1) Opener archetypes you actually use (pick 2)": "brain",
    "D2a) Opener fill-in (day-rating): add your tag (e.g. 'no decimals :)')": "brain",
    "D2b) Opener fill-in (playful curiosity): What’s the most __ thing you did today? (fill __)": "brain",
    "D3) Compliment style you prefer to give (pick 2)": "brain",
    "D4) How you usually receive compliments": "brain",
    "D5) Pet names allowed (optional; comma-separated)": "brain",
    "D6) Pet names banned (optional; comma-separated)": "brain",

    "F2) Accepting plans — your default short phrase (exact words)": "brain",
    "F3) Declining plans — polite line + alternative (exact words)": "brain",
    "F4) Micro-date options you like (pick up to 3)": "persona",  # preferences live in persona

    "G1) Over-tease repair — your exact line": "brain",
    "G2) Vibe stalled — your go-to restart approach (pick 1)": "brain",
    "G2b) Optional — a quick restart line you'd actually send": "brain",
    "G3) If you're wrong — apology line (own-it style; exact words)": "brain",
    "G5) Last-minute cancel — your default response style": "brain",  # NEW

    "H2) Pace preference": "brain",                                   # NEW

    "I1) How you show affection in text (pick 2)": "brain",
    "I2) What you like to receive (pick 2)": "brain",

    "J4) After you share, preferred response from them": "brain",     # NEW

    "L1) Low-energy day text style": "brain",                          # NEW
    "L2) Busy streak handling": "brain",

    "N1) If tension rises, you prefer": "brain",
    "N2) Your soft name-the-feeling line (exact words)": "brain",
    "N3) Repair signature (how you reconnect)": "brain",

    "O3) After a spicy moment, your aftercare text (exact words)": "brain",

    "Consent to use these responses to replicate your communication style in a GPT-based AI?": "persona",  # consent meta -> persona
    "Unnamed: 132": "unknown",
}

# ---------- Build normalized lookup ----------
EXACT_MAP = {norm_header(k): v for k, v in EXACT_MAP_RAW.items()}

# ---------- Keyword fallbacks ----------
IDENTITY_KEYS = [
    "full name","nickname","preferred name","age","date of birth","occupation","role",
    "voice","tone","values","philosophy","personality","traits","motifs","imagery","aesthetic",
    "boundaries","bio","story","background","core goal","gender","sexual orientation","zodiac",
    "birthplace","nationality","region","city","hobby","weekend","movie","music","event","platform",
    "youtuber","podcaster","writer","free day","exercise","snack","collect","travel","destination",
    "socializing","food","cuisine","learned","brands","stores","devices","pets","favorites",
    "tiny favorites","little dates","anniversary","birthday","public displays","serious","jealousy",
    "debate topics","obsessions","inside joke","loops","consent"
]

BEHAVIOR_KEYS = [
    "expressive","slang","abbreviation","emoji","reply length","punctuation","stylization",
    "latency","double text","double-text","affirming","phrases","teasing","flirt","escalat",
    "cadence","support","reaction","comfort","repair","restart","apology","closing","sign off",
    "boundary strictness","late","disagree","meaningful texting","affection in text","vulnerable line",
    "plans","opener","meme","fan says","friend is upset","aftercare","busy streak","seen/read",
    "tension rises","name the feeling","pace preference","greeting warmth","low energy day",
    "last minute cancel","preferred response"
]

def classify_column(col: str) -> str:
    nh = norm_header(col)
    # 1) normalized exact map
    if nh in EXACT_MAP:
        return EXACT_MAP[nh]
    # 2) heuristic
    if any(k in nh for k in IDENTITY_KEYS):
        return "persona"
    if any(k in nh for k in BEHAVIOR_KEYS):
        return "brain"
    return "unknown"

def split_dataframe(df: pd.DataFrame):
    persona_cols, brain_cols, unknown_cols = [], [], []
    for c in df.columns:
        cat = classify_column(c)
        if cat == "persona":
            persona_cols.append(c)
        elif cat == "brain":
            brain_cols.append(c)
        else:
            # ignore totally empty junk columns silently
            if not c.lower().startswith("unnamed:") or df[c].notna().any():
                unknown_cols.append(c)
    return df[persona_cols], df[brain_cols], unknown_cols

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="Path to the combined CSV file")
    ap.add_argument("--outdir", default=".", help="Output directory for split files")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(args.src)

    persona_df, brain_df, unknown = split_dataframe(df)

    persona_path = outdir / "Persona_Prompt.csv"
    brain_path   = outdir / "Brain_Memory.csv"
    unsorted_path = outdir / "unsorted_columns.txt"

    persona_df.to_csv(persona_path, index=False)
    brain_df.to_csv(brain_path, index=False)

    if unknown:
        with open(unsorted_path, "w", encoding="utf-8") as f:
            for col in unknown:
                f.write(col + "\n")

    print(f"[✓] Persona_Prompt.csv → {persona_path}")
    print(f"[✓] Brain_Memory.csv  → {brain_path}")
    if unknown:
        print(f"[!] {len(unknown)} unclassified columns → {unsorted_path}")
    else:
        print("[✓] No unclassified columns 🎉")

if __name__ == "__main__":
    main()
