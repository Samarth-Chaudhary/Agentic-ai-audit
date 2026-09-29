"""Foundation tests for common structured logging and secret redaction."""

import io
import json
import logging

from project.logging import (
    AuditLogger,
    SecretRedactingFilter,
    StructuredJsonFormatter,
    ctx_task_type,
    ctx_trace_id,
    redact_secrets_from_string,
    sanitize_payload,
)


def test_redact_secrets_from_string():
    """Ensure sensitive tokens and keys in strings are properly scrubbed."""
    text_with_openai_key = "Using key sk-abcdef1234567890abcdef1234567890 to connect"
    scrubbed = redact_secrets_from_string(text_with_openai_key)
    assert "sk-abcdef" not in scrubbed
    assert "[REDACTED_SECRET]" in scrubbed

    text_with_bearer = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    scrubbed_bearer = redact_secrets_from_string(text_with_bearer)
    assert "eyJhbGciOi" not in scrubbed_bearer
    assert "[REDACTED_SECRET]" in scrubbed_bearer


def test_sanitize_payload_dictionary():
    """Ensure sensitive keys in dictionaries are scrubbed."""
    payload = {
        "user": "alice",
        "api_key": "secret-12345-value",
        "password": "my_password_xyz",
        "nested": {
            "token": "bearer-abc",
            "safe_metric": 42
        }
    }
    sanitized = sanitize_payload(payload)
    assert sanitized["user"] == "alice"
    assert sanitized["api_key"] == "[REDACTED_SECRET]"
    assert sanitized["password"] == "[REDACTED_SECRET]"
    assert sanitized["nested"]["token"] == "[REDACTED_SECRET]"
    assert sanitized["nested"]["safe_metric"] == 42


def test_structured_json_logger_output():
    """Ensure AuditLogger outputs valid JSON containing trace_id, task_type, component, event, status."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredJsonFormatter())
    handler.addFilter(SecretRedactingFilter())

    logger_instance = logging.getLogger("test_logger")
    logger_instance.handlers = [handler]
    logger_instance.setLevel(logging.INFO)

    audit_logger = AuditLogger(logger_instance, component="test_component")

    # Set context vars
    t_token = ctx_trace_id.set("tr-test-123")
    task_token = ctx_task_type.set("customer_support")

    try:
        audit_logger.info_event(
            event="tool_execution",
            status="success",
            message="Invoked tool with api_key sk-12345678901234567890",
            extra_data={"order_id": "ORD-123", "secret": "shh"}
        )
    finally:
        ctx_trace_id.reset(t_token)
        ctx_task_type.reset(task_token)

    output = stream.getvalue().strip()
    log_json = json.loads(output)

    assert log_json["component"] == "test_component"
    assert log_json["event"] == "tool_execution"
    assert log_json["status"] == "success"
    assert log_json["trace_id"] == "tr-test-123"
    assert log_json["task_type"] == "customer_support"
    assert "sk-12345" not in log_json["message"]
    assert log_json["data"]["secret"] == "[REDACTED_SECRET]"
    assert log_json["data"]["order_id"] == "ORD-123"
