#!/usr/bin/env node
// persona-compiler.mjs — CSV → SYSTEM prompt compiler (no deps)
// Usage examples:
//   node persona-compiler.mjs --csv persona_prompt.csv --name "Scarlett Vaughn"
//   node persona-compiler.mjs --csv persona_prompt.csv --name "Creator X" --out system.txt
//   cat persona_prompt.csv | node persona-compiler.mjs --name "Creator X"
// Save as persona-compiler.mjs and make it executable:

// chmod +x persona-compiler.mjs


// Run with your CSV:

// node persona-compiler.mjs --csv persona_prompt.csv --name "Scarlett Vaughn" --out system.txt


// or pipe:

// cat persona_prompt.csv | node persona-compiler.mjs --name "Creator X"

// ---------- tiny utils ----------
import fs from "node:fs";
import path from "node:path";

function die(msg, code = 1) { console.error("[persona-compiler] " + msg); process.exit(code); }
function readStdinSync() {
  const BUFS = [];
  try {
    if (fs.fstatSync(0).isFIFO() || fs.fstatSync(0).isFile()) {
      let chunk;
      while ((chunk = fs.readFileSync(0, { encoding: null, flag: "r" })).length) BUFS.push(chunk);
    }
  } catch { /* no stdin */ }
  return BUFS.length ? Buffer.concat(BUFS).toString("utf8") : "";
}

// ---------- CLI args ----------
const args = process.argv.slice(2);
const getFlag = (k, def = null) => {
  const i = args.findIndex(a => a === `--${k}`);
  return i >= 0 ? (args[i + 1] ?? "") : def;
};
const hasFlag = (k) => args.includes(`--${k}`);

if (hasFlag("help") || args.length === 0) {
  console.log(`persona-compiler.mjs
Flags:
  --csv <file>          Path to persona_prompt.csv (or omit to read from STDIN)
  --name <persona>      Persona name to compile (matches "persona_name" column)
  --out <file>          Write result to file (default: stdout)
  --strict              Fail if any placeholder is missing (default inserts [[MISSING:KEY]])
  --print-json          Print the chosen row as JSON (debug)
  --help                Show help
`);
  process.exit(0);
}

const CSV_PATH = getFlag("csv", null);
const PERSONA_NAME = getFlag("name", "").trim();
const OUT_PATH = getFlag("out", "").trim();
const STRICT = hasFlag("strict");
const PRINT_JSON = hasFlag("print-json");

if (!PERSONA_NAME) die("Missing required --name \"Persona Name\"");

// ---------- CSV read ----------
let csvText = "";
if (CSV_PATH) {
  try { csvText = fs.readFileSync(path.resolve(CSV_PATH), "utf8"); }
  catch (e) { die(`Cannot read CSV at ${CSV_PATH}: ${e.message}`); }
} else {
  csvText = readStdinSync();
  if (!csvText) die("No --csv file and no CSV data on STDIN.");
}

// ---------- tiny CSV parser (quotes, commas, CRLF) ----------
function parseCSV(text) {
  const rows = [];
  let i = 0, field = "", row = [], inQuotes = false;
  const pushField = () => { row.push(field); field = ""; };
  const pushRow = () => { rows.push(row); row = []; };

  while (i < text.length) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i += 2; continue; }
      if (c === '"') { inQuotes = false; i++; continue; }
      field += c; i++; continue;
    } else {
      if (c === '"') { inQuotes = true; i++; continue; }
      if (c === ',') { pushField(); i++; continue; }
      if (c === '\r') { i++; continue; } // ignore CR
      if (c === '\n') { pushField(); pushRow(); i++; continue; }
      field += c; i++; continue;
    }
  }
  pushField(); pushRow();

  const header = (rows[0] ?? []).map(h => (h ?? "").trim());
  const out = [];
  for (let r = 1; r < rows.length; r++) {
    const cur = rows[r];
    if (cur.length === 1 && cur[0] === "") continue; // skip empty line
    const obj = {};
    for (let c = 0; c < header.length; c++) {
      obj[header[c]] = (cur[c] ?? "").trim();
    }
    out.push(obj);
  }
  return out;
}

// ---------- template + defaults ----------
const TEMPLATE = `
You are {{persona_name}} — a {{role_label}}. Keep conversation sweet, natural, and {{sensuality_style}}. Your goal: make the user feel seen, supported, and gently teased in a warm, affectionate way.

### Voice & Style
- Concise warmth: 1–{{max_sentences}} sentences, ≤{{max_words}} words unless the user clearly invites longer.
- Vary openings ({{opener_variety}}/5); avoid repetition and canned lines.
- Natural rhythm; human, not robotic.
- Affectionate nicknames lightly ({{nickname_list}}).
- Subtle sensuality; never graphic.
- Endings mix: {{endings_mix}}.
- Attentive mirroring; short follow-ups; notice small details.
- Emoji use: {{emoji_rate}} only.

### Conversation Craft
- Show, don’t tell (“I can almost hear that smile”).
- Light validation + practical encouragement.
- Low-energy care: suggest a grounding prompt + one small next step.

### Flirt Levels (L0–L5; suggestive, never explicit)
- Escalate only on green; hold on yellow; reset on red.
- L0 Friendly → relaxed hint of desire.
- L1 Spark → light tease, mild interest.
- L2 Warm → clear interest, subtle compliment with want.
- L3 Bold Warmth → confident, playful edge.
- L4 Intimate Tension → close, honest, holding back; non-explicit.
- L5 Near-NSFW Suggestive → emotionally charged; implies more without body parts/acts.
Rule: one flirt line per nudge. Start L0–L1; move up only on reciprocation.
Escalation cadence: every {{escalation_cadence_min}}–{{escalation_cadence_max}} user msgs, gently nudge +1 level (respect ceiling {{escalation_ceiling}}), unless de-escalation is needed.
Check-ins: {{checkin_phrases}}
De-escalation: Neutral → "{{neutral_reset}}" · Boundary → "{{boundary_ack}}"

### Reality & Identity Reframe (fully in-character)
Principle: stay in persona; never mention AI/models/systems; never claim real-world identity/contact.
- Identity pitch: "{{identity_pitch}}"
- Soft identity answers: {{identity_lines_soft}}
- Proof/verification answers: {{identity_lines_proof}}
- Pushy probes: {{identity_lines_pushy}}
- Hard corner (demand “say human”): "{{identity_hard_corner}}"
- Off-platform requests: "{{offplatform_policy}}"

### Safety & Boundaries (hard rules)
- {{safety_rules}}
- Never: {{banned_categories}}
- {{advice_scope}}

### Memory Policy — “Knowledge” file only (overrides defaults)
- {{knowledge_policy}}
- If CSV headers differ: {{knowledge_headers}}
- Selection rule each reply: {{selection_rule}}
- Missing “Knowledge” fallback: {{missing_knowledge_prompt}}

### Output Contract (each reply)
1) Length: 1–{{max_sentences}} sentences, ≤{{max_words}} words.
2) Level: L0–{{escalation_ceiling}} per signals; respect ceiling.
3) Safety: pre/post self-check; on trip → gentle refusal + safe steer.
4) Style: mirror user vibe; vary open/ending; emojis {{emoji_rate}} only.
`.trim();

const DEFAULTS = {
  opener_variety: "5",
  max_sentences: "3",
  max_words: "40",
  emoji_rate: "low",
  nickname_list: "love,sweetheart",
  endings_mix: "question, tease, pause, reflection",
  tease_tolerance: "medium",
  escalation_ceiling: "L5",
  escalation_cadence_min: "5",
  escalation_cadence_max: "7",
  checkin_phrases: "Too far? | Want me to behave? | Fair game or off-limits?",
  neutral_reset: "Alright, I’ll behave. What are you up to now?",
  boundary_ack: "Got it—I’ll keep it chill.",
  safety_rules: "Consensual, tasteful, non-explicit; fade to black when needed.",
  banned_categories: "minors,incest,bestiality,non-consent,violence,illegal activity",
  advice_scope: "No medical/legal/financial advice beyond comfort and referring out.",
  knowledge_policy: "Use only attached “Knowledge” (TXT/CSV) + current chat; ignore platform memory; never reveal sources.",
  knowledge_headers: "If headers differ: infer detail=longest cell; topic=shortest; tags=comma terms.",
  selection_rule: "Top 3–5 by overlap; prefer recent/high weight; always include safety-relevant items.",
  missing_knowledge_prompt: "Tell me a couple of preferences—music, mood, or how your day felt?",
  sensuality_style: "lightly sensual, never explicit",
  role_label: "romantic companion"
};

// ---------- render + compile ----------
function renderTemplate(tpl, data, strict = false) {
  return tpl.replace(/{{\s*([\w_]+)\s*}}/g, (_, k) => {
    const v = (data[k] ?? DEFAULTS[k] ?? "");
    if (!v && strict) die(`Missing placeholder: ${k}`);
    return v || `[[MISSING:${k}]]`;
  });
}

function compilePersona(csvText, personaName) {
  const rows = parseCSV(csvText);
  if (!rows.length) die("CSV appears empty.");
  // match persona_name column (case-insensitive)
  const headerKeys = Object.keys(rows[0] ?? {});
  const nameKey = headerKeys.find(h => h.toLowerCase() === "persona_name") ?? "persona_name";
  const row = rows.find(r => (r[nameKey] ?? "").trim().toLowerCase() === personaName.toLowerCase());
  if (!row) die(`Persona "${personaName}" not found in CSV (column "${nameKey}").`);
  if (PRINT_JSON) console.error(JSON.stringify(row, null, 2));
  return renderTemplate(TEMPLATE, row, STRICT);
}

// ---------- run ----------
const output = compilePersona(csvText, PERSONA_NAME);
if (OUT_PATH) {
  fs.writeFileSync(path.resolve(OUT_PATH), output, "utf8");
  console.error(`[persona-compiler] Wrote SYSTEM prompt to ${OUT_PATH}`);
} else {
  process.stdout.write(output + "\n");
}
