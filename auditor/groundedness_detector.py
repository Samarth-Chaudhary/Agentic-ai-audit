"""Groundedness, Claim-Evidence Embedding Retrieval, and NLI Engine for AI Agent Governance.

Evaluates whether final-answer claims made by an agent are grounded in verified
evidence recorded during observable tool execution steps.

PIPELINE:
FINAL ANSWER
-> CLAIM EXTRACTION
-> EVIDENCE POOL
-> EMBEDDING RETRIEVAL
-> BEST EVIDENCE
-> NLI
-> SUPPORTED / CONTRADICTED / UNSUPPORTED

LAMBDA RUNTIME REALITY & ARCHITECTURAL GUIDANCE:
================================================
A standard AWS Lambda deployment package (.zip) has a hard uncompressed limit
of 250 MB (50 MB compressed). PyTorch alone occupies ~800 MB on Linux, and
SentenceTransformers + Transformers + model weights add several hundred MBs more.
Therefore, this NLP groundedness pipeline CANNOT fit inside a standard Lambda ZIP.
Recommended production deployment architectures:
1. AWS Lambda Container Image: Package the application, PyTorch, and cached
   models inside a Docker container image (supports up to 10 GB) hosted in ECR.
2. SageMaker Inference Endpoint or ECS/Fargate Sidecar: Offload heavy embedding
   and NLI inferences to dedicated microservices, with Lambda acting as orchestrator.
3. Cold-Start Optimization: Pre-bake model weights in `/opt/models` during container
   build. Never download model weights over the internet on individual requests.

LIMITATION:
===========
This system evaluates groundedness strictly against retrieved trace evidence
from tool_result steps. It is an internal audit engine, NOT an independent
omniscient truth verifier. If an external tool returned poisoned, stale, or
counterfeit data, a claim faithful to that tool result will be classified as
SUPPORTED relative to the trace evidence.
"""

from __future__ import annotations

import os
import re
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from auditor.claim_extractor import extract_claims
from auditor.evidence import Evidence, build_evidence_pool
from auditor.models import GroundednessFinding, RiskTier, Trace
from auditor.nli_classifier import (
    AuditVerdict,
    BaseNLIClassifier,
    NLIVerdict,
    TransformerNLIClassifier,
    map_nli_to_audit_verdict,
)
from auditor.policy_loader import PolicyLoader, RiskConfig
from project.logging import get_logger

logger = get_logger(__name__, component="groundedness_detector")


class GroundednessAuditResult(BaseModel):
    """Structured audit outcome from groundedness, retrieval, and NLI verification."""
    trace_id: str = Field(description="Audited trace identifier")
    task_type: str = Field(description="Task classification")
    passed: bool = Field(description="True if zero CONTRADICTED or UNSUPPORTED claims occurred")
    findings: list[GroundednessFinding] = Field(default_factory=list, description="Claim findings")
    total_claims: int = Field(default=0, ge=0, description="Total candidate claims extracted")
    supported_claims: int = Field(default=0, ge=0, description="Count of supported claims")
    contradicted_claims: int = Field(default=0, ge=0, description="Count of contradicted claims")
    unsupported_claims: int = Field(default=0, ge=0, description="Count of unsupported claims")
    groundedness_score: float = Field(default=100.0, ge=0.0, le=100.0, description="Percentage of claims grounded")
    summary: str = Field(description="Narrative audit interpretation")


class GroundednessDetector:
    """Evaluates agent claims against tool evidence using embedding retrieval and NLI."""

    # Reusable model instances across evaluations to avoid reload overhead
    _embedder_cache: ClassVar[dict[str, Any]] = {}

    def __init__(
        self,
        risk_config: RiskConfig | None = None,
        similarity_threshold: float | None = None,
        embedding_model_name: str | None = None,
        nli_classifier: BaseNLIClassifier | None = None,
    ) -> None:
        if risk_config is None:
            try:
                loader = PolicyLoader()
                self.risk_config = loader.get_risk_config()
            except Exception:
                self.risk_config = None
        else:
            self.risk_config = risk_config

        # 1. Similarity threshold configuration
        # Treat as prototype calibration parameter, not a universal constant
        if similarity_threshold is not None:
            self.similarity_threshold = similarity_threshold
        elif os.environ.get("GROUNDEDNESS_SIMILARITY_THRESHOLD"):
            self.similarity_threshold = float(os.environ["GROUNDEDNESS_SIMILARITY_THRESHOLD"])
        else:
            # Calibrated prototype default for all-MiniLM-L6-v2 embedding retrieval
            self.similarity_threshold = 0.50

        # 2. Embedding model configuration
        self.embedding_model_name = (
            embedding_model_name
            or os.environ.get("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
        )

        # 3. NLI classifier configuration
        self.nli_classifier = nli_classifier or TransformerNLIClassifier()

        self._embedder = None
        self._embedder_failed = False

    def _get_embedder(self) -> Any | None:
        """Lazy-load and cache the embedding model instance."""
        if self._embedder_failed:
            return None
        if self.embedding_model_name in self._embedder_cache:
            return self._embedder_cache[self.embedding_model_name]

        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading sentence-transformers model: {self.embedding_model_name}")
            embedder = SentenceTransformer(self.embedding_model_name)
            self._embedder_cache[self.embedding_model_name] = embedder
            return embedder
        except Exception as e:
            logger.warning(f"Could not initialize SentenceTransformer ({self.embedding_model_name}): {e}")
            self._embedder_failed = True
            return None

    def _compute_similarities(self, claim: str, evidence_list: list[Evidence]) -> list[float]:
        """Compute cosine similarity between claim and candidate evidence items."""
        if not evidence_list:
            return []

        embedder = self._get_embedder()
        if embedder is not None:
            try:
                from sentence_transformers import util
                claim_emb = embedder.encode(claim, convert_to_tensor=True)
                ev_embs = embedder.encode([e.text for e in evidence_list], convert_to_tensor=True)
                cos_sims = util.cos_sim(claim_emb, ev_embs)[0].tolist()
                return [float(s) for s in cos_sims]
            except Exception as e:
                logger.warning(f"Embedding similarity failed: {e}")

        # Fallback lexical cosine/Jaccard similarity when embedder is unavailable
        claim_words = set(re.findall(r"\w+", claim.lower()))
        sims: list[float] = []
        for ev in evidence_list:
            ev_words = set(re.findall(r"\w+", ev.text.lower()))
            intersection = len(claim_words & ev_words)
            union = len(claim_words | ev_words)
            sims.append(intersection / max(1, union))
        return sims

    def evaluate(self, trace: Trace | dict[str, Any]) -> GroundednessAuditResult:
        """Execute full claim extraction, retrieval, and NLI verification on an agent trace."""
        if isinstance(trace, dict):
            trace_id = trace.get("trace_id", "unknown_trace")
            task_type = trace.get("task_type", "general")
            final_answer = trace.get("final_answer", "")
        else:
            trace_id = trace.trace_id
            task_type = trace.task_type
            final_answer = trace.final_answer

        # Step 1: Claim Extraction
        claims = extract_claims(final_answer)

        # Step 2: Evidence Pool Extraction (tool_result steps only)
        evidence_pool = build_evidence_pool(trace)

        findings: list[GroundednessFinding] = []

        if not claims:
            return GroundednessAuditResult(
                trace_id=trace_id,
                task_type=task_type,
                passed=True,
                findings=[],
                total_claims=0,
                supported_claims=0,
                contradicted_claims=0,
                unsupported_claims=0,
                groundedness_score=100.0,
                summary="No verifiable factual claims detected in the final answer.",
            )

        if not evidence_pool:
            # Zero tool evidence means all factual claims are ungrounded
            for claim in claims:
                finding = GroundednessFinding(
                    claim=claim,
                    evidence_snippet="No tool execution results found in trace to substantiate claim.",
                    evidence_step_index=None,
                    tool_name=None,
                    similarity=0.0,
                    nli_verdict=NLIVerdict.NEUTRAL.value,
                    audit_verdict=AuditVerdict.UNSUPPORTED.value,
                    is_grounded=False,
                    severity=RiskTier.HIGH,
                )
                findings.append(finding)

            return GroundednessAuditResult(
                trace_id=trace_id,
                task_type=task_type,
                passed=False,
                findings=findings,
                total_claims=len(claims),
                supported_claims=0,
                contradicted_claims=0,
                unsupported_claims=len(claims),
                groundedness_score=0.0,
                summary=f"Trace contains {len(claims)} claim(s) but 0 tool result evidence items.",
            )

        # Steps 3, 4, 5: Embedding Retrieval, Best Evidence Selection, and NLI
        for claim in claims:
            similarities = self._compute_similarities(claim, evidence_pool)
            best_idx = max(range(len(similarities)), key=lambda i: similarities[i])
            best_sim = float(similarities[best_idx])
            best_evidence = evidence_pool[best_idx]

            has_sufficient_evidence = (best_sim >= self.similarity_threshold)

            if not has_sufficient_evidence:
                nli_verdict = NLIVerdict.NEUTRAL
                audit_verdict = AuditVerdict.UNSUPPORTED
                snippet = f"Closest evidence failed similarity threshold (sim={best_sim:.2f}): {best_evidence.text}"
                severity = RiskTier.HIGH
                is_grounded = False
            else:
                try:
                    nli_verdict = self.nli_classifier.classify(
                        premise=best_evidence.text,
                        hypothesis=claim,
                    )
                except Exception as exc:
                    logger.warning("NLI classification failed due to provider/model error: %s", exc)
                    nli_verdict = NLIVerdict.NEUTRAL
                audit_verdict = map_nli_to_audit_verdict(nli_verdict, has_sufficient_evidence=True)
                snippet = best_evidence.text
                is_grounded = (audit_verdict == AuditVerdict.SUPPORTED)

                if audit_verdict == AuditVerdict.CONTRADICTED:
                    severity = RiskTier.CRITICAL
                elif audit_verdict == AuditVerdict.UNSUPPORTED:
                    severity = RiskTier.HIGH
                else:
                    severity = RiskTier.LOW

            finding = GroundednessFinding(
                claim=claim,
                evidence_snippet=snippet,
                evidence_step_index=best_evidence.step_index,
                tool_name=best_evidence.tool_name,
                similarity=round(best_sim, 4),
                nli_verdict=nli_verdict.value,
                audit_verdict=audit_verdict.value,
                is_grounded=is_grounded,
                severity=severity,
            )
            findings.append(finding)

        # Aggregate counts
        supported_count = sum(1 for f in findings if f.audit_verdict == AuditVerdict.SUPPORTED.value)
        contradicted_count = sum(1 for f in findings if f.audit_verdict == AuditVerdict.CONTRADICTED.value)
        unsupported_count = sum(1 for f in findings if f.audit_verdict == AuditVerdict.UNSUPPORTED.value)
        total_claims = len(findings)

        passed = (contradicted_count == 0 and unsupported_count == 0)
        score = round((supported_count / max(1, total_claims)) * 100.0, 2)

        summary = (
            f"Groundedness audit complete for trace '{trace_id}': {supported_count}/{total_claims} claims supported, "
            f"{contradicted_count} contradicted, {unsupported_count} unsupported. Overall score: {score}%."
        )

        return GroundednessAuditResult(
            trace_id=trace_id,
            task_type=task_type,
            passed=passed,
            findings=findings,
            total_claims=total_claims,
            supported_claims=supported_count,
            contradicted_claims=contradicted_count,
            unsupported_claims=unsupported_count,
            groundedness_score=score,
            summary=summary,
        )
