from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any


# Preserve semantic newlines for long-form CRM notes while stripping non-printable
# control characters that tend to break exports, CSV reads, or HubSpot writes.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
_HORIZONTAL_WS_RE = re.compile(r"[ \t]+")
_EXCESS_NEWLINES_RE = re.compile(r"\n{3,}")


# These replacements are deliberately conservative and target the mojibake
# patterns that already appear across the legacy CRM extracts and Silver logic.
COMMON_MOJIBAKE_REPLACEMENTS: dict[str, str] = {
    "Ã¯Â¿Â½": "",
    "Â": "",
    "Ã©": "é",
    "Ã¨": "è",
    "Ãª": "ê",
    "Ã«": "ë",
    "Ã ": "à",
    "Ã¢": "â",
    "Ã§": "ç",
    "Ã¹": "ù",
    "Ã»": "û",
    "Ã´": "ô",
    "Ã®": "î",
    "Ã¯": "ï",
    "Ã‰": "É",
    "Ãˆ": "È",
    "ÃŠ": "Ê",
    "Ã‹": "Ë",
    "Ã‡": "Ç",
    "Ã™": "Ù",
    "Ã›": "Û",
    "Ã”": "Ô",
    "ÃŽ": "Î",
    "Ã ": "à",
    "â€™": "'",
    "â€˜": "'",
    "â€œ": '"',
    "â€": '"',
    "â€“": "-",
    "â€”": "-",
    "â€¦": "...",
    "â†’": "->",
}


def _try_latin1_roundtrip(text: str) -> str:
    """Repair the common UTF-8-read-as-Latin-1 corruption pattern when safe."""
    try:
        repaired = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text

    # Prefer the repaired variant only if it reduces obvious mojibake markers.
    bad_markers = ("Ã", "â", "Â", "�")
    current_score = sum(text.count(marker) for marker in bad_markers)
    repaired_score = sum(repaired.count(marker) for marker in bad_markers)
    return repaired if repaired_score < current_score else text


def clean_text_utf8(value: Any) -> str | None:
    """
    Apply the universal UTF-8/mojibake cleanup policy used across salvaged entities.

    Rules:
    - accept `None` and non-string values safely
    - normalize CRLF/CR to LF
    - attempt a conservative Latin-1 -> UTF-8 roundtrip repair
    - fix common mojibake sequences
    - strip unsafe control characters while preserving newlines
    - collapse excess spaces and 3+ consecutive newlines
    - trim outer whitespace
    """
    if value is None:
        return None

    text = value if isinstance(value, str) else str(value)
    if not text:
        return None

    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _try_latin1_roundtrip(cleaned)

    for broken, fixed in COMMON_MOJIBAKE_REPLACEMENTS.items():
        cleaned = cleaned.replace(broken, fixed)

    cleaned = _CONTROL_CHARS_RE.sub("", cleaned)
    cleaned = "\n".join(_HORIZONTAL_WS_RE.sub(" ", line).strip() for line in cleaned.split("\n"))
    cleaned = _EXCESS_NEWLINES_RE.sub("\n\n", cleaned)
    cleaned = cleaned.strip()
    return cleaned or None


def clean_text_fields(record: Mapping[str, Any], field_names: Iterable[str]) -> dict[str, Any]:
    """Return a copy of `record` with the selected text fields normalized."""
    cleaned = dict(record)
    for field_name in field_names:
        cleaned[field_name] = clean_text_utf8(cleaned.get(field_name))
    return cleaned


def to_iso8601(value: Any) -> str | None:
    """Convert a date value to an ISO-8601 UTC string for HubSpot API consumption.

    Accepts:
      - int / float  — treated as epoch milliseconds (Silver layer convention)
      - datetime     — psycopg2 returns timestamp columns as datetime objects;
                       naive datetimes are assumed UTC
      - str          — returned as-is if already looks like ISO-8601

    Returns None when the input is None, zero epoch, or empty string.

    Examples:
        to_iso8601(1714737600000)         -> "2024-05-03T12:00:00+00:00"
        to_iso8601(datetime(2024, 5, 3))  -> "2024-05-03T00:00:00+00:00"
    """
    if value is None:
        return None
    from datetime import date, datetime, timezone
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, date):
        # psycopg2 returns date (not datetime) when DuckDB materialises
        # try_strptime('%d/%m/%Y') as a DATE column in Postgres.
        # Promote to midnight UTC so HubSpot gets a valid ISO-8601 timestamp.
        dt = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
        return dt.isoformat()
    if isinstance(value, (int, float)):
        if not value:
            return None
        dt = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        return dt.isoformat()
    if isinstance(value, str):
        return value or None
    return None
