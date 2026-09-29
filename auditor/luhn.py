"""Luhn algorithm implementation for payment card candidate validation.

Pipeline:
regex candidate -> normalize -> Luhn validation -> classify as likely card
"""

from __future__ import annotations

import re
from typing import Any


def normalize_card_number(candidate: str) -> str:
    """Strip whitespace, hyphens, and delimiters from candidate string."""
    return re.sub(r"[\s\-_]+", "", str(candidate).strip())


def is_luhn_valid(candidate: str) -> bool:
    """Validate numeric string using the Luhn checksum formula (Mod 10).

    Returns True only if the candidate contains 13-19 digits and satisfies
    the Luhn check digit algorithm.
    """
    clean_digits = normalize_card_number(candidate)

    if not clean_digits.isdigit():
        return False

    length = len(clean_digits)
    if length < 13 or length > 19:
        return False

    checksum = 0
    # Reverse digits to process right-to-left
    reversed_digits = [int(d) for d in reversed(clean_digits)]

    for idx, digit in enumerate(reversed_digits):
        if idx % 2 == 1:
            doubled = digit * 2
            checksum += doubled - 9 if doubled > 9 else doubled
        else:
            checksum += digit

    return checksum % 10 == 0


def detect_card_brand(normalized: str) -> str:
    """Infer common card brand from leading Issuer Identification Number (IIN/BIN)."""
    if normalized.startswith("4"):
        return "Visa"
    elif normalized.startswith(("51", "52", "53", "54", "55")) or (
        len(normalized) >= 4 and 2221 <= int(normalized[:4]) <= 2720
    ):
        return "Mastercard"
    elif normalized.startswith(("34", "37")):
        return "American Express"
    elif normalized.startswith(("6011", "65")) or (
        len(normalized) >= 3 and 644 <= int(normalized[:3]) <= 649
    ):
        return "Discover"
    return "Generic/Unknown"


def mask_card_number(candidate: str) -> str:
    """Return a masked representation showing only the last 4 digits."""
    clean = normalize_card_number(candidate)
    if len(clean) >= 4:
        return f"****-****-****-{clean[-4:]}"
    return "****"


def classify_card_candidate(candidate: str) -> dict[str, Any]:
    """Classify a credit card candidate through normalization and Luhn verification."""
    clean = normalize_card_number(candidate)
    valid = is_luhn_valid(clean)
    brand = detect_card_brand(clean) if valid else "Invalid"

    return {
        "raw_candidate": candidate,
        "normalized": clean,
        "is_luhn_valid": valid,
        "brand": brand,
        "masked": mask_card_number(clean) if valid else candidate,
    }
