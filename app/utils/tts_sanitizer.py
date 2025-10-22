import re
from html import unescape

_ALLOWED_AUDIO_TAGS = {"whispers","softly","sighs","giggles","laughs","gasp"}
_BREAK_RE = re.compile(r'<\s*break\s+time\s*=\s*"([0-2](?:\.\d)?s)"\s*/\s*>', re.IGNORECASE)

def sanitize_tts_text(text: str) -> str:
    if not text:
        return ""
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

    text = text.strip()
    return text if text else "…"