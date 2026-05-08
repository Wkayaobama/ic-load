"""
phone_normalise — E.164 phone number normalization for IC'ALPS data.

This module normalizes French-origin phone numbers to E.164 international format (+33XXXXXXXXX).
Handles various input formats commonly found in IC'ALPS source data.

## Supported Input Formats

1. Already E.164: +33612345678 -> +33612345678
2. French international: 0033612345678 -> +33612345678
3. French local: 0612345678 -> +33612345678
4. Bare 9-digit (dropped leading 0): 612345678 -> +33612345678
5. With formatting: 06 12 34 56 78, 06-12-34-56-78, 06.12.34.56.78 -> +33612345678

## Usage

>>> from context.algorithms.phone_normalise import normalise_phone_e164
>>> normalise_phone_e164("06 12 34 56 78")
'+33612345678'
>>> normalise_phone_e164(None)
None
>>> normalise_phone_e164("invalid")
None

## Public API

normalise_phone_e164(raw: str | None) -> str | None
    Main entry point for phone normalization.
"""
from __future__ import annotations

import re
from typing import Optional


def normalise_phone_e164(raw: Optional[str]) -> Optional[str]:
    """Normalise a French-origin phone number to E.164 (+33XXXXXXXXX).

    Args:
        raw: Raw phone number string in any common format, or None.

    Returns:
        E.164 formatted phone number (+33XXXXXXXXX) or None if invalid/empty.

    Examples:
        >>> normalise_phone_e164("06 12 34 56 78")
        '+33612345678'
        >>> normalise_phone_e164("0033612345678")
        '+33612345678'
        >>> normalise_phone_e164("+33612345678")
        '+33612345678'
        >>> normalise_phone_e164("612345678")
        '+33612345678'
        >>> normalise_phone_e164(None)
        >>> normalise_phone_e164("")
        >>> normalise_phone_e164("invalid")
    """
    if not raw or not isinstance(raw, str):
        return None

    # Strip spaces, dots, dashes, parentheses, slashes
    digits = re.sub(r"[\s.\-()\/]", "", raw.strip())

    if not digits:
        return None

    # Already E.164 format
    if digits.startswith("+"):
        return digits if len(digits) >= 8 else None

    # French 0033... international prefix
    if digits.startswith("0033"):
        return "+" + digits[2:]

    # French local 0X... (10 digits)
    if digits.startswith("0") and len(digits) == 10:
        return "+33" + digits[1:]

    # Bare 9-digit (dropped leading 0)
    if len(digits) == 9 and digits[0] in "123456789":
        return "+33" + digits

    # Fallback: return as-is if at least 7 digits (international minimum)
    return digits if len(digits) >= 7 else None


def is_valid_e164(phone: Optional[str]) -> bool:
    """Check if a phone number is in valid E.164 format.

    Args:
        phone: Phone number to validate.

    Returns:
        True if valid E.164 format (+XXXXXXXXXXX), False otherwise.
    """
    if not phone or not isinstance(phone, str):
        return False
    return bool(re.match(r"^\+[1-9]\d{6,14}$", phone))


def normalise_phone_batch(phones: list[Optional[str]]) -> list[Optional[str]]:
    """Batch normalize a list of phone numbers.

    Args:
        phones: List of raw phone numbers.

    Returns:
        List of normalized E.164 phone numbers (or None for invalid entries).
    """
    return [normalise_phone_e164(p) for p in phones]


__all__ = [
    "normalise_phone_e164",
    "is_valid_e164",
    "normalise_phone_batch",
]

from context.algorithms._instrumentation import log_debug, log_info_with_artifact  # noqa: E402

normalise_phone_e164 = log_debug(
    normalise_phone_e164,
    stat_fn=lambda result, raw, **_: {
        "call_count": 1,
        "null_input_count": 1 if not raw else 0,
        "normalized_count": 1 if result is not None else 0,
        "null_output_count": 1 if result is None else 0,
    },
    sample_fn=lambda result, raw, **_: {
        "input": raw,
        "output": result,
    },
)
is_valid_e164 = log_debug(
    is_valid_e164,
    stat_fn=lambda result, phone, **_: {
        "call_count": 1,
        "valid_count": 1 if result else 0,
        "invalid_count": 0 if result else 1,
    },
    sample_fn=lambda result, phone, **_: {
        "input": phone,
        "valid": result,
    },
)

normalise_phone_batch = log_info_with_artifact(
    description="Batch E.164 normalization for French-origin phone numbers.",
    artifact_builder=lambda result, phones, **kw: {
        "input_count": len(phones),
        "normalized_count": sum(1 for p in result if p is not None),
        "null_count": sum(1 for p in result if p is None),
        "success_rate": round(
            sum(1 for p in result if p is not None) / len(phones), 4
        ) if phones else 0,
    },
)(normalise_phone_batch)
