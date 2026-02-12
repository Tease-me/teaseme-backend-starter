"""Relationship dynamics and signal detection prompts."""

import json
from pathlib import Path
from app.constants import prompt_keys

# Relationship signal extraction
RELATIONSHIP_SIGNAL_PROMPT = """Return ONLY valid JSON with keys:
support, affection, flirt, respect, apology, commitment_talk,
rude, boundary_push, dislike, hate,
accepted_exclusive, accepted_girlfriend.

Influencer preferences:
Likes: {persona_likes}
Dislikes: {persona_dislikes}

Guidance:
- If the user message aligns with Likes -> raise affection/support/respect.
- If the user message aligns with Dislikes -> raise dislike (mild), not hate.
- Use hate only for strong hostility ("I hate you", slurs, wishing harm).

Context:
{recent_ctx}

User message:
{message}""".strip()

# Load relationship stage prompts from JSON config
_CONFIGS_DIR = Path(__file__).resolve().parent.parent / "configs"
RELATIONSHIP_STAGE_PROMPTS = json.loads(
    (_CONFIGS_DIR / "relationship_stage_prompts.json").read_text()
)

# Load relationship dimensions config from JSON
RELATIONSHIP_DIMENSIONS = json.loads(
    (_CONFIGS_DIR / "relationship_dimensions.json").read_text()
)

# Load MBTI definitions from JSON config
MBTI_JSON = (_CONFIGS_DIR / "mbti_definitions.json").read_text()

# Load survey questions from JSON config
SURVEY_QUESTIONS_JSON = (_CONFIGS_DIR / "survey_questions.json").read_text()

# Prompt registry for relationship prompts
PROMPTS = {
    prompt_keys.RELATIONSHIP_SIGNAL_PROMPT: {
        "name": "Relationship Signal Classification",
        "description": "Prompt for classifying relationship signals.",
        "prompt": RELATIONSHIP_SIGNAL_PROMPT,
        "type": "normal"
    },
    prompt_keys.RELATIONSHIP_STAGE_PROMPTS: {
        "name": "Relationship Stage Prompts",
        "description": "Stage-specific behavior guidance for relationship states.",
        "prompt": json.dumps(RELATIONSHIP_STAGE_PROMPTS),
        "type": "normal"
    },
    prompt_keys.RELATIONSHIP_DIMENSIONS_CONFIG: {
        "name": "Relationship Dimensions Configuration",
        "description": "Stage-specific descriptions for relationship dimensions (trust, closeness, attraction, safety). Used by frontend to explain what each dimension means at each relationship stage.",
        "prompt": json.dumps(RELATIONSHIP_DIMENSIONS),
        "type": "normal"
    },
    prompt_keys.MBTI_JSON: {
        "name": "MBTI Personality Definitions JSON",
        "description": "MBTI personality definitions used for profiling and prompt generation.",
        "prompt": MBTI_JSON,
        "type": "normal"
    },
    prompt_keys.SURVEY_QUESTIONS_JSON: {
        "name": "Influencer Onboarding Survey Questions JSON",
        "description": "JSON survey questions used for influencer onboarding.",
        "prompt": SURVEY_QUESTIONS_JSON,
        "type": "others"
    },
}
