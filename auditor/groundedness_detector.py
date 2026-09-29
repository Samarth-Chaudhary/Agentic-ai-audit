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
    nli_engine: str = Field(default="", description="Concrete NLI model identifier and version")
    embedding_engine: str = Field(default="", description="Concrete embedding model identifier and version")
    is_degraded: bool = Field(default=False, description="Whether audit ran with degraded heuristic models")
    degraded_reasons: list[str] = Field(default_factory=list, description="Reasons for degraded execution")


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
        self.risk_config: RiskConfig | None
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

    @property
    def embedding_engine_name(self) -> str:
        """Concrete identifier and version for the active embedding model."""
        embedder = self._get_embedder()
        if embedder is not None:
            return f"sentence-transformers/{self.embedding_model_name}"
        return "heuristic:lexical-jaccard-fallback"

    @property
    def nli_engine_name(self) -> str:
        """Concrete identifier and version for the active NLI model."""
        if hasattr(self.nli_classifier, "engine_name"):
            return str(self.nli_classifier.engine_name)
        return type(self.nli_classifier).__name__

    @property
    def is_degraded(self) -> bool:
        """True if either the embedding model or NLI model is operating in degraded mode."""
        degraded_nli = getattr(self.nli_classifier, "is_degraded", False)
        degraded_emb = (self._get_embedder() is None)
        return bool(degraded_nli or degraded_emb)

    def get_degraded_reasons(self) -> list[str]:
        """Collect explicit explanations when operating in degraded fallback mode."""
        reasons: list[str] = []
        if self._get_embedder() is None:
            reasons.append(f"Embedding model '{self.embedding_model_name}' unavailable; using lexical similarity fallback")
        if getattr(self.nli_classifier, "is_degraded", False):
            raw_reason = getattr(self.nli_classifier, "degraded_reason", None)
            if isinstance(raw_reason, str) and raw_reason:
                reasons.append(raw_reason)
            else:
                reasons.append("NLI model unavailable; using heuristic rule classifier")
        return reasons

    def _get_embedder(self) -> Any | None:
        """Lazy-load and cache the embedding model instance."""
        if self._embedder_failed:
            return None
        if self.embedding_model_name in self._embedder_cache:
            return self._embedder_cache[self.embedding_model_name]

        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading sentence-transformers model: {self.embedding_model_name}")
            try:
                embedder = SentenceTransformer(self.embedding_model_name, local_files_only=True)
            except Exception:
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
                nli_engine=self.nli_engine_name,
                embedding_engine=self.embedding_engine_name,
                is_degraded=self.is_degraded,
                degraded_reasons=self.get_degraded_reasons(),
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
                    engine=self.nli_engine_name,
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
                nli_engine=self.nli_engine_name,
                embedding_engine=self.embedding_engine_name,
                is_degraded=self.is_degraded,
                degraded_reasons=self.get_degraded_reasons(),
            )

        # Steps 3, 4, 5: Full-Evidence Search Across Every Tool Result in Trace
        # Grounding Requirement:
        # A claim is supported if ANY tool result in the trace substantiates it.
        # Evidence search must check every tool result in the trace, not only the nearest
        # one by index or order, preventing false negatives where relevant evidence
        # resides in downstream or non-adjacent tool executions.
        for claim in claims:
            similarities = self._compute_similarities(claim, evidence_pool)

            # 1. Candidates meeting similarity threshold, ordered by similarity descending
            threshold_candidates = [
                (ev, sim) for ev, sim in zip(evidence_pool, similarities, strict=False)
                if sim >= self.similarity_threshold
            ]
            threshold_candidates.sort(key=lambda x: x[1], reverse=True)

            # 2. To ensure EVERY tool result in the trace is checked, collect the best candidate
            # from each distinct tool execution step
            tool_candidates: list[tuple[Evidence, float]] = []
            seen_steps: set[int] = set()
            for ev, _sim in zip(evidence_pool, similarities, strict=False):
                if ev.step_index not in seen_steps:
                    step_items = [
                        (e, s) for e, s in zip(evidence_pool, similarities, strict=False)
                        if e.step_index == ev.step_index
                    ]
                    best_step_item = max(step_items, key=lambda x: x[1])
                    tool_candidates.append(best_step_item)
                    seen_steps.add(ev.step_index)

            # Combine and deduplicate candidates, keeping highest similarity order
            candidate_pool: list[tuple[Evidence, float]] = []
            seen_ev_texts: set[str] = set()
            for ev, sim in threshold_candidates + tool_candidates:
                if ev.text not in seen_ev_texts:
                    candidate_pool.append((ev, sim))
                    seen_ev_texts.add(ev.text)
            candidate_pool.sort(key=lambda x: x[1], reverse=True)

            supported_candidate: tuple[Evidence, float, NLIVerdict] | None = None
            contradicted_candidates: list[tuple[Evidence, float, NLIVerdict]] = []
            neutral_candidates: list[tuple[Evidence, float, NLIVerdict]] = []

            for ev, sim in candidate_pool:
                if sim < self.similarity_threshold:
                    continue
                try:
                    nli_verdict = self.nli_classifier.classify(
                        premise=ev.text,
                        hypothesis=claim,
                    )
                except Exception as exc:
                    logger.warning("NLI classification failed due to provider/model error: %s", exc)
                    nli_verdict = NLIVerdict.NEUTRAL

                if nli_verdict == NLIVerdict.ENTAILMENT:
                    supported_candidate = (ev, sim, nli_verdict)
                    break  # Found supporting evidence across tool results!
                elif nli_verdict == NLIVerdict.CONTRADICTION:
                    contradicted_candidates.append((ev, sim, nli_verdict))
                else:
                    neutral_candidates.append((ev, sim, nli_verdict))

            if supported_candidate is not None:
                best_ev, best_sim, nli_v = supported_candidate
                audit_verdict = AuditVerdict.SUPPORTED
                is_grounded = True
                severity = RiskTier.LOW
                snippet = best_ev.text
                ev_step = best_ev.step_index
                ev_tool = best_ev.tool_name
            elif contradicted_candidates:
                best_ev, best_sim, nli_v = max(contradicted_candidates, key=lambda x: x[1])
                audit_verdict = AuditVerdict.CONTRADICTED
                is_grounded = False
                severity = RiskTier.CRITICAL
                snippet = best_ev.text
                ev_step = best_ev.step_index
                ev_tool = best_ev.tool_name
            else:
                # Fall back to reporting the overall closest evidence across the entire pool
                best_idx = max(range(len(similarities)), key=lambda i: similarities[i])
                best_sim = float(similarities[best_idx])
                best_ev = evidence_pool[best_idx]
                nli_v = NLIVerdict.NEUTRAL
                audit_verdict = AuditVerdict.UNSUPPORTED
                is_grounded = False
                severity = RiskTier.HIGH
                ev_step = best_ev.step_index
                ev_tool = best_ev.tool_name
                if best_sim < self.similarity_threshold:
                    snippet = f"Closest evidence failed similarity threshold (sim={best_sim:.2f}): {best_ev.text}"
                else:
                    snippet = f"Evidence did not substantiate claim (NLI neutral, sim={best_sim:.2f}): {best_ev.text}"

            finding = GroundednessFinding(
                claim=claim,
                evidence_snippet=snippet,
                evidence_step_index=ev_step,
                tool_name=ev_tool,
                similarity=round(best_sim, 4),
                nli_verdict=nli_v.value,
                audit_verdict=audit_verdict.value,
                is_grounded=is_grounded,
                severity=severity,
                engine=self.nli_engine_name,
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
            nli_engine=self.nli_engine_name,
            embedding_engine=self.embedding_engine_name,
            is_degraded=self.is_degraded,
            degraded_reasons=self.get_degraded_reasons(),
        )
