import re
from html import unescape

# ElevenLabs V3 expression tags that should be preserved
_ALLOWED_AUDIO_TAGS = {
    # Emotions
    "sad", "angry", "happily", "sorrowful",
    # Delivery styles
    "whispers", "shouts", "slowly", "quickly", "softly",
    # Non-verbal sounds
    "laughs", "chuckles", "sighs", "coughs", "gulps", "giggles", "gasp"
}
_BREAK_RE = re.compile(r'<\s*break\s+time\s*=\s*"([0-2](?:\.\d)?s)"\s*/\s*>', re.IGNORECASE)
# Regex to match ElevenLabs V3 expression tags: [tag]
_V3_TAG_RE = re.compile(r'\[(' + '|'.join(re.escape(tag) for tag in _ALLOWED_AUDIO_TAGS) + r')\]', re.IGNORECASE)

def sanitize_tts_text(text: str) -> str:
    if not text:
        return ""
    
    # Preserve ElevenLabs V3 tags by temporarily replacing them
    tag_placeholders = {}
    def _store_tag(m):
        tag_key = f"__V3_TAG_{len(tag_placeholders)}__"
        tag_placeholders[tag_key] = m.group(0)  # Store the full tag like [chuckles]
        return tag_key
    
    text = _V3_TAG_RE.sub(_store_tag, text)
    
    text = unescape(text)
    text = re.sub(r'[ \t]+', ' ', text).strip()
    text = re.sub(r'[\U0001F300-\U0001FAFF\U00002700-\U000027BF]+', '', text)
    text = re.sub(r'[*_`~#>$begin:math:display$$end:math:display$$begin:math:text$$end:math:text$]', '', text)

    def _audio_tag_filter(m):
        tag = m.group(1).lower().strip()
        return f'[{tag}]' if tag in _ALLOWED_AUDIO_TAGS else ''
    text = re.sub(r'$begin:math:display$([^\\[$end:math:display$]+)\]', _audio_tag_filter, text)

    def _break_filter(m):
        t = m.group(1)
        try:
            val = float(t[:-1])
            if 0.1 <= val <= 2.0:
                return f'<break time="{val:.1f}s"/>'
        except:
            pass
        return ''
    text = _BREAK_RE.sub(_break_filter, text)
    text = re.sub(r'</?[^>]+>', '', text)

    # Restore ElevenLabs V3 tags
    for placeholder, original_tag in tag_placeholders.items():
        text = text.replace(placeholder, original_tag)

    text = text.strip()
    return text if text else "…"