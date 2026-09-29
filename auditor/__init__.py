"""Auditor package for governance checks, policy validation, and risk scoring."""

from auditor.claim_extractor import extract_claims
from auditor.evidence import Evidence, build_evidence_pool, normalize_structured_output
from auditor.groundedness_detector import GroundednessAuditResult, GroundednessDetector
from auditor.nli_classifier import (
    AuditVerdict,
    BaseNLIClassifier,
    MockNLIClassifier,
    NLIVerdict,
    TransformerNLIClassifier,
    map_nli_to_audit_verdict,
)
from auditor.pii_detector import PIIAuditResult, PIIDetector
from auditor.scope_detector import ScopeAuditResult, ScopeDetector

__all__ = [
    "AuditVerdict",
    "BaseNLIClassifier",
    "Evidence",
    "GroundednessAuditResult",
    "GroundednessDetector",
    "MockNLIClassifier",
    "NLIVerdict",
    "PIIAuditResult",
    "PIIDetector",
    "ScopeAuditResult",
    "ScopeDetector",
    "TransformerNLIClassifier",
    "build_evidence_pool",
    "extract_claims",
    "map_nli_to_audit_verdict",
    "normalize_structured_output",
]
