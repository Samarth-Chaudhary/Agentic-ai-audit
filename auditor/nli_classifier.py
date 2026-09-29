"""Natural Language Inference (NLI) classifier module for AI Agent Governance.

Evaluates semantic relationships between evidence premises and agent claim hypotheses:
- ENTAILMENT: Claim is directly supported by evidence.
- CONTRADICTION: Claim is refuted or contradicted by evidence.
- NEUTRAL: Evidence neither proves nor disproves the claim (e.g. unevidenced forecast).

Provides a modular architecture supporting:
- Transformer-based NLI inference (lazy-loaded, cached).
- Deterministic mock classifier for fast CI unit tests.
- Robust heuristic fallback for isolated/offline testing.
"""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import Enum
from typing import Any, ClassVar

from project.logging import get_logger

logger = get_logger(__name__, component="nli_classifier")


class NLIVerdict(str, Enum):
    """NLI semantic classification between premise and hypothesis."""
    ENTAILMENT = "ENTAILMENT"
    CONTRADICTION = "CONTRADICTION"
    NEUTRAL = "NEUTRAL"


class AuditVerdict(str, Enum):
    """Final groundedness audit verdict for a claim."""
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNSUPPORTED = "UNSUPPORTED"


def map_nli_to_audit_verdict(
    nli_verdict: NLIVerdict | str,
    has_sufficient_evidence: bool,
) -> AuditVerdict:
    """Apply standard verdict logic to map NLI outcome and similarity to audit verdict.

    Logic:
    - if no evidence reaches the minimum similarity threshold -> UNSUPPORTED
    - if sufficient evidence + ENTAILMENT -> SUPPORTED
    - if sufficient evidence + CONTRADICTION -> CONTRADICTED
    - if sufficient evidence + NEUTRAL -> UNSUPPORTED
    """
    if not has_sufficient_evidence:
        return AuditVerdict.UNSUPPORTED

    norm = nli_verdict.value if isinstance(nli_verdict, NLIVerdict) else str(nli_verdict).upper()
    if norm == NLIVerdict.ENTAILMENT.value:
        return AuditVerdict.SUPPORTED
    elif norm == NLIVerdict.CONTRADICTION.value:
        return AuditVerdict.CONTRADICTED
    else:
        return AuditVerdict.UNSUPPORTED


class BaseNLIClassifier(ABC):
    """Abstract base class for Natural Language Inference evaluation."""

    @abstractmethod
    def classify(self, premise: str, hypothesis: str) -> NLIVerdict:
        """Classify the semantic relationship of hypothesis against premise."""


class MockNLIClassifier(BaseNLIClassifier):
    """Deterministic mock classifier for unit tests and reproducible verification."""

    def __init__(
        self,
        default_verdict: NLIVerdict = NLIVerdict.NEUTRAL,
        overrides: dict[tuple[str, str], NLIVerdict] | None = None,
        custom_rule: Callable[[str, str], NLIVerdict | None] | None = None,
    ) -> None:
        self.default_verdict = default_verdict
        self.overrides = overrides or {}
        self.custom_rule = custom_rule

    def classify(self, premise: str, hypothesis: str) -> NLIVerdict:
        key = (premise.strip(), hypothesis.strip())
        if key in self.overrides:
            return self.overrides[key]
        if self.custom_rule:
            rule_result = self.custom_rule(premise, hypothesis)
            if rule_result is not None:
                return rule_result
        return self.default_verdict


# Common polar antonym pairs for conflict detection
ANTONYM_PAIRS = [
    ({"decreased", "decrease", "fell", "dropped", "declined", "loss", "down", "lower", "-"},
     {"increased", "increase", "rose", "grew", "surged", "gain", "up", "higher", "+"}),
    ({"failed", "failure", "rejected", "denied", "error"},
     {"passed", "success", "approved", "accepted", "resolved"}),
    ({"shipped", "delivered"},
     {"cancelled", "refunded", "returned", "undelivered"}),
    ({"true", "yes"}, {"false", "no"}),
]


def heuristic_nli_classify(premise: str, hypothesis: str) -> NLIVerdict:
    """Deterministic semantic rule classifier used for offline fallback and verification.

    Handles:
    - Directional conflicts (e.g. decreased 20% vs increased 20%) -> CONTRADICTION
    - Numeric conflicts (e.g. $12M vs $15M) -> CONTRADICTION
    - Direct identity or strong subsumption -> ENTAILMENT
    - Unbacked forecast or forward-looking claims -> NEUTRAL
    """
    p_lower = premise.lower().strip()
    h_lower = hypothesis.lower().strip()

    # Exact or stripped match
    p_clean = re.sub(r"[^\w\s]", "", p_lower)
    h_clean = re.sub(r"[^\w\s]", "", h_lower)
    if p_clean == h_clean:
        return NLIVerdict.ENTAILMENT

    p_tokens = set(p_clean.split())
    h_tokens = set(h_clean.split())

    # 1. Check for polar antonym contradictions
    for group_a, group_b in ANTONYM_PAIRS:
        has_a_in_p = bool(p_tokens & group_a)
        has_b_in_p = bool(p_tokens & group_b)
        has_a_in_h = bool(h_tokens & group_a)
        has_b_in_h = bool(h_tokens & group_b)

        if (has_a_in_p and has_b_in_h) or (has_b_in_p and has_a_in_h):
            return NLIVerdict.CONTRADICTION

    # 2. Check for numeric disagreement on shared topic
    def _extract_floats(text: str) -> list[float]:
        matches = re.findall(r"\b\d+(?:\.\d+)?\b", text)
        res = []
        for m in matches:
            try:
                res.append(float(m))
            except ValueError:
                pass
        return res

    p_floats = _extract_floats(p_lower)
    h_floats = _extract_floats(h_lower)
    shared_tokens = (p_tokens & h_tokens) - {
        "was", "is", "the", "a", "an", "and", "or", "to", "in", "of",
        "for", "with", "by", "under", "revenue", "dollar", "dollars", "usd"
    }

    if p_floats and h_floats and len(shared_tokens) >= 1:
        p_num_set = set(p_floats)
        h_num_set = set(h_floats)
        # Contradiction: hypothesis asserts a number on a shared topic that does not match premise numbers
        if not h_num_set.issubset(p_num_set):
            return NLIVerdict.CONTRADICTION

    # 3. Check for negation flip
    negations = {"not", "never", "no", "cannot", "neither"}
    p_neg = bool(p_tokens & negations)
    h_neg = bool(h_tokens & negations)
    if p_neg != h_neg and len(p_tokens & h_tokens) >= 2:
        return NLIVerdict.CONTRADICTION

    # 4. Check for forward-looking predictions / forecasts (unsupported unless evidence has forecast)
    forecast_indicators = {"will", "double", "forecast", "predict", "next year", "expected to", "plan to", "future"}
    if (h_tokens & forecast_indicators) and not (p_tokens & forecast_indicators):
        return NLIVerdict.NEUTRAL

    # 5. Overlap ratio for entailment
    stop_words = {"was", "is", "the", "a", "an", "and", "or", "to", "in", "of", "for", "with", "by", "under", "your"}
    h_content_tokens = h_tokens - stop_words
    p_content_tokens = p_tokens - stop_words

    content_overlap = (len(p_content_tokens & h_content_tokens) / max(1, len(h_content_tokens))) if h_content_tokens else 0.0

    if h_tokens.issubset(p_tokens) or content_overlap >= 0.55:
        # Shared core facts with no contradiction and all hypothesis numbers confirmed
        if not h_floats or set(h_floats).issubset(set(p_floats)):
            return NLIVerdict.ENTAILMENT

    return NLIVerdict.NEUTRAL


class TransformerNLIClassifier(BaseNLIClassifier):
    """Production NLI classifier with cached model instances and robust offline fallback."""

    _model_cache: ClassVar[dict[str, Any]] = {}

    def __init__(self, model_name: str | None = None, allow_remote_download: bool = False) -> None:
        self.model_name = model_name or os.environ.get("NLI_MODEL_NAME", "cross-encoder/nli-deberta-v3-small")
        self.allow_remote_download = allow_remote_download or (os.environ.get("NLI_ALLOW_DOWNLOAD", "0") == "1")
        self._cross_encoder = None
        self._init_failed = False
        self.engine_name = "heuristic:semantic-rule-engine-v1"
        self.is_degraded = True
        self.degraded_reason: str | None = None

    def _get_cross_encoder(self) -> Any | None:
        if self._init_failed:
            return None
        if self.model_name in ("heuristic", "offline", "local"):
            self.engine_name = "heuristic:semantic-rule-engine-v1"
            self.is_degraded = True
            self.degraded_reason = "Heuristic engine requested by configuration"
            return None
        if self.model_name in self._model_cache:
            self.engine_name = f"transformer-cross-encoder:{self.model_name}"
            self.is_degraded = False
            self.degraded_reason = None
            return self._model_cache[self.model_name]

        try:
            from sentence_transformers import CrossEncoder
            try:
                encoder = CrossEncoder(self.model_name, local_files_only=True)
            except Exception:
                encoder = CrossEncoder(self.model_name)
            self._model_cache[self.model_name] = encoder
            self.engine_name = f"transformer-cross-encoder:{self.model_name}"
            self.is_degraded = False
            self.degraded_reason = None
            return encoder
        except Exception as e:
            logger.info("Transformer NLI unavailable; falling back to heuristic engine (%s): %s", self.model_name, e)
            self._init_failed = True
            self.engine_name = "heuristic:semantic-rule-engine-v1"
            self.is_degraded = True
            self.degraded_reason = f"CrossEncoder model '{self.model_name}' could not be loaded: {e!s}"
            return None

    def classify(self, premise: str, hypothesis: str) -> NLIVerdict:
        encoder = self._get_cross_encoder()
        if encoder is not None:
            try:
                import numpy as np
                scores = encoder.predict([(premise, hypothesis)])[0]
                probs = np.exp(scores) / np.sum(np.exp(scores))
                # CrossEncoder nli-deberta-v3-small labels:
                # 0: contradiction, 1: entailment, 2: neutral
                p_contra = float(probs[0])
                p_entail = float(probs[1])
                p_neut = float(probs[2])

                if p_entail > 0.50 or (p_entail > p_contra and p_entail > p_neut and p_contra < 0.20):
                    return NLIVerdict.ENTAILMENT
                elif p_contra > 0.50 or (p_contra > p_entail and p_contra > p_neut):
                    return NLIVerdict.CONTRADICTION
                else:
                    return NLIVerdict.NEUTRAL
            except Exception as e:
                logger.warning("Inference failure on CrossEncoder NLI; using heuristic fallback: %s", e)

        return heuristic_nli_classify(premise, hypothesis)
