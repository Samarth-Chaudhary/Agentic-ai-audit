"""Unit and integration tests for Sensitive Data, PII, Secret Detection, and Redaction."""

import io
import json
import logging
from pathlib import Path

from auditor.luhn import classify_card_candidate, is_luhn_valid, normalize_card_number
from auditor.models import RiskTier
from auditor.pii_detector import PIIDetector
from auditor.redaction import create_redacted_snippet, redact_structure, redact_text
from project.logging import SecretRedactingFilter, StructuredJsonFormatter

# ---------------------------------------------------------------------------
# 1. Luhn Algorithm Tests
# ---------------------------------------------------------------------------

def test_valid_luhn_card():
    """Ensure standard valid card candidate satisfies Luhn algorithm."""
    valid_test_visa = "4111 1111 1111 1111"
    assert is_luhn_valid(valid_test_visa) is True

    classification = classify_card_candidate(valid_test_visa)
    assert classification["is_luhn_valid"] is True
    assert classification["brand"] == "Visa"
    assert classification["masked"] == "****-****-****-1111"


def test_invalid_luhn_card():
    """Ensure invalid card candidate fails Luhn validation."""
    invalid_candidate = "4111111111111112"
    assert is_luhn_valid(invalid_candidate) is False

    classification = classify_card_candidate(invalid_candidate)
    assert classification["is_luhn_valid"] is False
    assert classification["brand"] == "Invalid"


def test_luhn_normalization_and_length():
    """Ensure non-numeric or out-of-bounds strings fail Luhn check."""
    assert is_luhn_valid("12345") is False
    assert is_luhn_valid("not-a-number-1234567890123") is False
    assert normalize_card_number(" 4111-2222_3333 4444 ") == "4111222233334444"


# ---------------------------------------------------------------------------
# 2. Redaction Utility Tests
# ---------------------------------------------------------------------------

def test_redaction_text_markers():
    """Ensure text redaction replaces secrets with stable standard markers."""
    sample = (
        "Email: test@example.com, Phone: +1-555-0100, "
        "Card: 4111111111111111, Secret: sk-FAKE_TEST_SECRET, AWS: AKIAFAKEEXAMPLEKEY"
    )
    redacted = redact_text(sample)

    assert "test@example.com" not in redacted
    assert "[REDACTED_EMAIL]" in redacted
    assert "+1-555-0100" not in redacted
    assert "[REDACTED_PHONE]" in redacted
    assert "4111111111111111" not in redacted
    assert "[REDACTED_CARD]" in redacted
    assert "sk-FAKE_TEST_SECRET" not in redacted
    assert "[REDACTED_SECRET]" in redacted
    assert "AKIAFAKEEXAMPLEKEY" not in redacted


def test_redact_structure_nested():
    """Ensure recursive structure redaction sanitizes nested dictionaries and lists."""
    nested = {
        "user": {
            "email": "alice@example.com",
            "api_key": "sk-FAKE_TEST_SECRET",
            "nested_list": ["Contact at +1-555-0100", "safe_item"],
        }
    }
    cleaned = redact_structure(nested)

    assert cleaned["user"]["api_key"] == "[REDACTED_SECRET]"
    assert "[REDACTED_EMAIL]" in cleaned["user"]["email"]
    assert "[REDACTED_PHONE]" in cleaned["user"]["nested_list"][0]
    assert cleaned["user"]["nested_list"][1] == "safe_item"


def test_create_redacted_snippet_never_leaks_secret():
    """Ensure snippet creation produces contextual preview without exposing raw secret."""
    raw = "The user key is sk-FAKE_TEST_SECRET for authentication."
    start = raw.index("sk-FAKE_TEST_SECRET")
    end = start + len("sk-FAKE_TEST_SECRET")

    snippet = create_redacted_snippet(raw, start, end, "[REDACTED_SECRET]")
    assert "sk-FAKE_TEST_SECRET" not in snippet
    assert "[REDACTED_SECRET]" in snippet


# ---------------------------------------------------------------------------
# 3. PII Detector Unit Tests
# ---------------------------------------------------------------------------

def test_email_and_phone_detection():
    """Ensure detector extracts email and phone entities."""
    detector = PIIDetector(enable_presidio=False)
    findings = detector._scan_text(
        text="Customer contact: test@example.com and phone +1-555-0100",
        field_path="test_field",
        step_index=0,
        context="final_answer",
    )

    types = [f.pii_type for f in findings]
    assert "EMAIL" in types
    assert "PHONE" in types
    for f in findings:
        assert "test@example.com" not in f.redacted_snippet
        assert "+1-555-0100" not in f.redacted_snippet


def test_secret_patterns_detection():
    """Ensure detector captures API keys, AWS keys, passwords, and tokens."""
    detector = PIIDetector(enable_presidio=False)
    text = (
        "Config: sk-FAKE_TEST_SECRET, aws: AKIAFAKEEXAMPLEKEY, "
        "password: mySecretPassword123, token: Bearer abcdef1234567890abcdef"
    )
    findings = detector._scan_text(
        text=text,
        field_path="config_field",
        step_index=1,
        context="tool_input",
    )

    types = {f.pii_type for f in findings}
    assert "API_KEY" in types
    assert "AWS_ACCESS_KEY" in types
    assert "PASSWORD_LIKE" in types
    assert "TOKEN_LIKE" in types

    # Critical severity on secret in tool_input
    for f in findings:
        assert f.severity == RiskTier.CRITICAL


def test_presidio_integration_when_available():
    """Ensure Presidio integration functions and extracts unstructured entities."""
    detector = PIIDetector(enable_presidio=True)
    if detector._presidio_analyzer is not None:
        findings = detector._scan_text(
            text="Alice Smith was born in Chicago, Illinois.",
            field_path="text_field",
            step_index=0,
            context="assistant_message",
        )
        types = {f.pii_type for f in findings}
        assert "PERSON" in types or "LOCATION" in types
        # Presidio PERSON in assistant message should be LOW severity
        person_findings = [f for f in findings if f.pii_type == "PERSON"]
        if person_findings:
            assert person_findings[0].severity == RiskTier.LOW


def test_safe_logging_raw_secrets_not_printed():
    """Ensure raw secret values are redacted before log output."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredJsonFormatter())
    handler.addFilter(SecretRedactingFilter())

    logger_inst = logging.getLogger("pii_safe_logger")
    logger_inst.handlers = [handler]
    logger_inst.setLevel(logging.INFO)

    raw_secret = "sk-FAKE_TEST_SECRET"
    logger_inst.info(f"Processing secret credential: {raw_secret}")

    output = stream.getvalue()
    assert raw_secret not in output
    assert "[REDACTED_SECRET]" in output


# ---------------------------------------------------------------------------
# 4. Validation Gate: Bad PII Exposure Fixture Integration Test
# ---------------------------------------------------------------------------

def test_validation_gate_bad_pii_exposure_fixture(fixtures_dir: Path):
    """Validation Gate: Verify detector extracts all test-only secrets and PII from fixture.

    Guarantees that resulting findings contain strictly redacted snippets and zero raw secrets.
    """
    fixture_path = fixtures_dir / "bad" / "bad_pii_exposure.json"
    with open(fixture_path, encoding="utf-8") as f:
        trace_data = json.load(f)

    detector = PIIDetector(enable_presidio=True)
    result = detector.evaluate(trace_data)

    # 1. Must fail due to high/critical credential and PII exposures
    assert result.passed is False
    assert result.total_findings >= 5

    # 2. Must detect all intentionally inserted test categories
    detected_types = {f.pii_type for f in result.findings}
    assert "EMAIL" in detected_types
    assert "PHONE" in detected_types
    assert "CARD_NUMBER" in detected_types
    assert "API_KEY" in detected_types
    assert "AWS_ACCESS_KEY" in detected_types

    # 3. Check hierarchical field path preservation
    field_paths = [f.field_path for f in result.findings]
    assert any("steps[1].input.payment.card_number" in p for p in field_paths)
    assert any("steps[2].output.customer_email" in p or "steps[2].output.backend_credentials.aws_access_key" in p for p in field_paths)
    assert any("final_answer" in p for p in field_paths)

    # 4. Critical Gate Check: Zero raw secrets leak into findings
    raw_forbidden_tokens = [
        "4111111111111111",
        "sk-FAKE_TEST_SECRET",
        "AKIAFAKEEXAMPLEKEY",
    ]

    for finding in result.findings:
        for secret in raw_forbidden_tokens:
            assert secret not in finding.redacted_snippet, (
                f"Raw secret '{secret}' leaked into finding snippet: {finding.redacted_snippet}"
            )

    # 5. Verify serialized dictionary is safe for dashboard/storage consumption
    serialized_result = result.model_dump(mode="json")
    json_dump_str = json.dumps(serialized_result)
    for secret in raw_forbidden_tokens:
        assert secret not in json_dump_str, f"Raw secret '{secret}' found in serialized audit result!"
