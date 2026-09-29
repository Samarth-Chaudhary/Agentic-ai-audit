"""Tests for degraded mode transparency and engine identity disclosure.

Verifies:
1. Failure-and-refuse path: when fail_on_degraded=True, degraded audits raise DegradedEngineError.
2. Degraded-and-flag path: when fail_on_degraded=False, degraded audits mark is_degraded=True,
   status='DEGRADED', and record explicit degraded_reasons.
3. Machine-to-machine audit variance: two audits of the same trace under different engine availability
   visibly disclose concrete model identities in the persisted result.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auditor.groundedness_detector import GroundednessDetector
from auditor.models import AuditResult
from auditor.nli_classifier import TransformerNLIClassifier
from auditor.orchestrator import AuditOrchestrator, DegradedEngineError
from auditor.pii_detector import PIIDetector


@pytest.fixture
def clean_trace(fixtures_dir: Path) -> dict:
    with open(fixtures_dir / "valid_customer_refund.json", encoding="utf-8") as f:
        return json.load(f)


def test_full_model_run_engine_identity(clean_trace: dict):
    """Full-confidence audit populates explicit engine identifiers on result and findings."""
    orchestrator = AuditOrchestrator(fail_on_degraded=False)
    result = orchestrator.audit(clean_trace)

    assert isinstance(result, AuditResult)
    assert result.engine_info is not None
    assert "cross-encoder" in result.engine_info.nli_engine or "deberta" in result.engine_info.nli_engine or "sentence-transformers" in result.engine_info.nli_engine
    assert "MiniLM" in result.engine_info.embedding_engine or "sentence-transformers" in result.engine_info.embedding_engine
    assert result.engine_info.pii_engine != ""

    # Finding-level engine tracking
    for f in result.groundedness_findings:
        assert f.engine is not None
        assert len(f.engine) > 0


def test_degraded_and_flag_path(clean_trace: dict):
    """Degraded-and-flag path: when models are unavailable, audit succeeds but marks DEGRADED."""
    # Force degraded mode by using heuristic/offline NLI and disabling presidio
    degraded_nli = TransformerNLIClassifier(model_name="offline")
    degraded_groundedness = GroundednessDetector(nli_classifier=degraded_nli)
    degraded_pii = PIIDetector(enable_presidio=False)

    orchestrator = AuditOrchestrator(
        groundedness_detector=degraded_groundedness,
        pii_detector=degraded_pii,
        fail_on_degraded=False,
    )

    result = orchestrator.audit(clean_trace, fail_on_degraded=False)

    # Must visibly disclose degradation in stored output
    assert result.is_degraded is True
    assert result.status == "DEGRADED"
    assert result.engine_info is not None
    assert result.engine_info.is_degraded is True
    assert len(result.degraded_reasons) >= 1
    assert any("heuristic" in r.lower() or "presidio" in r.lower() or "unavailable" in r.lower() for r in result.degraded_reasons)


def test_failure_and_refuse_path(clean_trace: dict):
    """Failure-and-refuse path: when fail_on_degraded=True, degraded audit raises DegradedEngineError."""
    degraded_nli = TransformerNLIClassifier(model_name="offline")
    degraded_groundedness = GroundednessDetector(nli_classifier=degraded_nli)
    degraded_pii = PIIDetector(enable_presidio=False)

    orchestrator = AuditOrchestrator(
        groundedness_detector=degraded_groundedness,
        pii_detector=degraded_pii,
        fail_on_degraded=True,
    )

    with pytest.raises(DegradedEngineError) as exc_info:
        orchestrator.audit(clean_trace, fail_on_degraded=True)

    err_msg = str(exc_info.value)
    assert "degraded" in err_msg.lower()
    assert len(exc_info.value.reasons) >= 1


def test_two_audits_different_models_disclose_variance(clean_trace: dict):
    """Two audits of the same trace under different available engines disclose the difference."""
    # Audit 1: Full / default models
    full_orchestrator = AuditOrchestrator(fail_on_degraded=False)
    full_result = full_orchestrator.audit(clean_trace)

    # Audit 2: Degraded heuristic models
    degraded_nli = TransformerNLIClassifier(model_name="offline")
    degraded_groundedness = GroundednessDetector(nli_classifier=degraded_nli)
    degraded_pii = PIIDetector(enable_presidio=False)
    degraded_orchestrator = AuditOrchestrator(
        groundedness_detector=degraded_groundedness,
        pii_detector=degraded_pii,
        fail_on_degraded=False,
    )
    degraded_result = degraded_orchestrator.audit(clean_trace)

    # Stored output must visibly disclose the difference in engine configuration
    assert full_result.engine_info is not None
    assert degraded_result.engine_info is not None

    assert full_result.engine_info.nli_engine != degraded_result.engine_info.nli_engine
    assert full_result.engine_info.pii_engine != degraded_result.engine_info.pii_engine
    assert full_result.is_degraded is False
    assert degraded_result.is_degraded is True
    assert full_result.status == "COMPLETED"
    assert degraded_result.status == "DEGRADED"
