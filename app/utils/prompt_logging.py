import re
import logging
from typing import Any, Iterable


_EMAIL_RE = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
_JWT_RE = re.compile(r"eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+")


def _redact(text: str, extra_patterns: Iterable[re.Pattern[str]] | None = None) -> str:
    if not text:
        return text
    redacted = _EMAIL_RE.sub("<redacted_email>", text)
    redacted = _JWT_RE.sub("<redacted_token>", redacted)
    if extra_patterns:
        for pat in extra_patterns:
            redacted = pat.sub("<redacted>", redacted)
    return redacted


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head
    return f"{text[:head]}\n...<truncated>...\n{text[-tail:]}"


def log_prompt(
    log: logging.Logger,
    prompt,
    *,
    cid: str = "",
    max_chars: int = 8000,
    redact_patterns: Iterable[re.Pattern[str]] | None = None,
    **kwargs: Any,
) -> None:
    try:
        rendered = prompt.format_prompt(**kwargs).to_string()
    except Exception as exc:
        log.info("[%s] Prompt render failed: %s", cid, exc)
        return

    rendered = _redact(rendered, redact_patterns)
    rendered = _truncate(rendered, max_chars)
    log.info("[%s] ==== FULL PROMPT ====\n%s", cid, rendered)
