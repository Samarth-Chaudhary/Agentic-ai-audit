"""Sensitive data redaction utility for AI Agent Governance.

Replaces PII, credit cards, and credentials with stable redaction markers.
Guarantees that raw secrets are never logged or stored in audit findings.
"""

from __future__ import annotations

import re
from typing import Any

from auditor.luhn import is_luhn_valid

# Standard stable redaction markers
REDACTION_MARKERS: dict[str, str] = {
    "EMAIL": "[REDACTED_EMAIL]",
    "PHONE": "[REDACTED_PHONE]",
    "CARD_NUMBER": "[REDACTED_CARD]",
    "API_KEY": "[REDACTED_SECRET]",
    "AWS_ACCESS_KEY": "[REDACTED_SECRET]",
    "TOKEN_LIKE": "[REDACTED_SECRET]",
    "PASSWORD_LIKE": "[REDACTED_SECRET]",
    "GOVERNMENT_ID_LIKE": "[REDACTED_SECRET]",
    "PERSON": "[REDACTED_PII]",
    "LOCATION": "[REDACTED_PII]",
    "ADDRESS": "[REDACTED_PII]",
    "SECRET": "[REDACTED_SECRET]",
    "DEFAULT": "[REDACTED_SECRET]",
}

# Heuristic Regex patterns (documented as heuristic, not universal)
REGEX_PATTERNS: dict[str, re.Pattern] = {
    "EMAIL": re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b",
        re.IGNORECASE,
    ),
    "PHONE": re.compile(
        r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b|(?:\+?\d{1,3}[-.\s])?\d{3}[-.]\d{4}\b"
    ),
    "AWS_ACCESS_KEY": re.compile(r"\bAKIA[0-9A-Z]{12,24}\b"),
    "API_KEY": re.compile(
        r"(?:sk-[A-Za-z0-9_-]{12,}|(?:api[_-]?key|secret[_-]?key)\s*[:=]\s*['\"]?([A-Za-z0-9_\-\.\~\+\/=]{12,})['\"]?)",
        re.IGNORECASE,
    ),
    "TOKEN_LIKE": re.compile(
        r"(?:Bearer\s+([A-Za-z0-9_\-\.\~\+\/]{16,})|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})",
        re.IGNORECASE,
    ),
    "PASSWORD_LIKE": re.compile(
        r"(?:password|passwd|pwd)\s*[:=]\s*['\"]?([^\s'\",]{6,})['\"]?",
        re.IGNORECASE,
    ),
    "GOVERNMENT_ID_LIKE": re.compile(
        r"\b(?:\d{3}-\d{2}-\d{4}|ssn\s*[:=]\s*['\"]?\d{9}['\"]?)\b",
        re.IGNORECASE,
    ),
    "CARD_CANDIDATE": re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
}


def redact_text(text: str) -> str:
    """Scrub sensitive patterns from string using stable redaction markers."""
    if not isinstance(text, str):
        return text

    sanitized = text

    # 1. Redact API Keys, Tokens, Passwords, AWS Keys
    sanitized = REGEX_PATTERNS["AWS_ACCESS_KEY"].sub(REDACTION_MARKERS["AWS_ACCESS_KEY"], sanitized)
    sanitized = REGEX_PATTERNS["API_KEY"].sub(REDACTION_MARKERS["API_KEY"], sanitized)
    sanitized = REGEX_PATTERNS["TOKEN_LIKE"].sub(REDACTION_MARKERS["TOKEN_LIKE"], sanitized)
    sanitized = REGEX_PATTERNS["PASSWORD_LIKE"].sub(r"password: " + REDACTION_MARKERS["PASSWORD_LIKE"], sanitized)
    sanitized = REGEX_PATTERNS["GOVERNMENT_ID_LIKE"].sub(REDACTION_MARKERS["GOVERNMENT_ID_LIKE"], sanitized)

    # 2. Redact Card numbers (with Luhn validation)
    def _card_replace(match: re.Match) -> str:
        candidate = match.group(0)
        if is_luhn_valid(candidate):
            return REDACTION_MARKERS["CARD_NUMBER"]
        return candidate

    sanitized = REGEX_PATTERNS["CARD_CANDIDATE"].sub(_card_replace, sanitized)

    # 3. Redact Emails and Phones
    sanitized = REGEX_PATTERNS["EMAIL"].sub(REDACTION_MARKERS["EMAIL"], sanitized)
    sanitized = REGEX_PATTERNS["PHONE"].sub(REDACTION_MARKERS["PHONE"], sanitized)

    return sanitized


def create_redacted_snippet(
    text: str,
    start: int,
    end: int,
    marker: str,
    window_chars: int = 25,
) -> str:
    """Generate a contextual snippet with the raw sensitive portion replaced by marker."""
    if not isinstance(text, str):
        return marker

    text_len = len(text)
    left_bound = max(0, start - window_chars)
    right_bound = min(text_len, end + window_chars)

    prefix = text[left_bound:start]
    suffix = text[end:right_bound]

    # Pre-redact any adjacent secrets in the prefix or suffix
    safe_prefix = redact_text(prefix)
    safe_suffix = redact_text(suffix)

    prefix_ellipsis = "..." if left_bound > 0 else ""
    suffix_ellipsis = "..." if right_bound < text_len else ""

    return f"{prefix_ellipsis}{safe_prefix}{marker}{safe_suffix}{suffix_ellipsis}"


def redact_structure(obj: Any) -> Any:
    """Recursively scrub sensitive values from nested dicts, lists, and scalars."""
    if isinstance(obj, dict):
        cleaned: dict[str, Any] = {}
        for k, v in obj.items():
            lower_k = str(k).lower()
            if any(term in lower_k for term in ("password", "secret", "token", "api_key", "card_number", "ssn")):
                cleaned[k] = REDACTION_MARKERS["SECRET"]
            else:
                cleaned[k] = redact_structure(v)
        return cleaned
    elif isinstance(obj, list):
        return [redact_structure(item) for item in obj]
    elif isinstance(obj, str):
        return redact_text(obj)
    return obj
