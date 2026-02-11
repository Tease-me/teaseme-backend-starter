import re
from html import unescape

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
    # Use a unique placeholder that won't be modified by sanitization
    # Format: V3TAGXXX where XXX is a unique number
    tag_placeholders = {}
    def _store_tag(m):
        idx = len(tag_placeholders)
        # Use a format that's very unlikely to appear in normal text
        tag_key = f"V3TAG{idx:03d}V3"
        tag_placeholders[tag_key] = m.group(0)  # Store the full tag like [chuckles]
        return tag_key
    
    text = _V3_TAG_RE.sub(_store_tag, text)
    
    text = unescape(text)
    text = re.sub(r'[ \t]+', ' ', text).strip()
    text = re.sub(r'[\U0001F300-\U0001FAFF\U00002700-\U000027BF]+', '', text)
    # Remove markdown formatting characters only (not as a character class that would remove letters)
    # Note: Don't remove characters that are part of our placeholder
    text = re.sub(r'[*_`~#>]', '', text)
    # Remove math display markers if present
    text = re.sub(r'\$begin:math:display\$\$end:math:display\$\$begin:math:text\$\$end:math:text\$', '', text)

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

    for placeholder, original_tag in sorted(tag_placeholders.items(), reverse=True):
        if placeholder in text:
            text = text.replace(placeholder, original_tag)
        else:
            # If placeholder was modified, try to find and restore it
            # This handles cases where the placeholder might have been partially modified
            import logging
            log = logging.getLogger(__name__)
            log.warning(f"Placeholder {placeholder} not found in text, tag {original_tag} may be lost")

    # Clean up any leftover placeholders (from old format or failed restorations)
    # Remove patterns like V3TAG0, V3TAG000V3, etc.
    text = re.sub(r'V3TAG\d+V3?', '', text)
    # Also clean up old format placeholders if any
    text = re.sub(r'__V3_TAG_\d+__', '', text)

    text = text.strip()
    return text if text else "…"