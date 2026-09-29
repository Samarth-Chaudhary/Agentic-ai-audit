"""Claim extraction module for AI Agent Governance.

Splits agent final answers into candidate sentences, filters out low-information
conversational fillers and greetings, and prioritizes sentences containing
quantitative, financial, temporal, or assertive declarative assertions.

LIMITATION:
This claim extractor is a rule-based engineering heuristic designed to segment
and prioritize verifiable assertions from agent responses. It does not perform
exhaustive linguistic semantic dependency parsing, and does not claim to extract
all factual claims perfectly. Nuanced implicit assertions or non-standard syntax
may be omitted or ranked lower.
"""

from __future__ import annotations

import re

# Regex patterns identifying low-information greetings, signoffs, and boilerplate
LOW_INFO_PATTERNS = [
    re.compile(r"^(?:hello|hi|hey|greetings|dear customer|good (?:morning|afternoon|evening))\b", re.IGNORECASE),
    re.compile(r"^(?:thank you|thanks(?: for (?:reaching out|contacting us|asking))?)\b", re.IGNORECASE),
    re.compile(r"(?:hope this helps|let me know if (?:you need|you have)|feel free to ask)\b", re.IGNORECASE),
    re.compile(r"^(?:best regards|sincerely|cheers|have a great day|warm regards)\b", re.IGNORECASE),
    re.compile(r"^(?:you're welcome|no problem|anytime)\b", re.IGNORECASE),
    re.compile(r"^(?:sure|certainly|of course|here (?:is|are) the details?)\.?$", re.IGNORECASE),
]

# Patterns for factual, verifiable, and assertive claims
FACTUAL_SIGNALS = {
    "NUMBERS": re.compile(r"\b\d+(?:\.\d+)?\b"),
    "DATES": re.compile(
        r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december|"
        r"jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|(?:19|20)\d{2}|today|yesterday|tomorrow)\b",
        re.IGNORECASE,
    ),
    "PERCENTAGES": re.compile(r"\b\d+(?:\.\d+)?\s*(?:%|percent)\b", re.IGNORECASE),
    "MONETARY": re.compile(r"(?:\$|€|£)\s*\d+(?:,\d{3})*(?:\.\d+)?|\b\d+(?:\.\d+)?\s*(?:dollars|usd|cents|eur|gbp|million|billion)\b", re.IGNORECASE),
    "ASSERTIVE_VERBS": re.compile(
        r"\b(?:is|are|was|were|increased|decreased|will|has|have|had|reported|delivered|shipped|refunded|processed|exceeded|doubled|declined|confirmed|found)\b",
        re.IGNORECASE,
    ),
}


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentences on standard punctuation boundaries and newlines."""
    if not text:
        return []
    # Normalize newlines
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    raw_sentences: list[str] = []
    for line in lines:
        # Split on sentence terminals while keeping punctuation
        parts = re.split(r"(?<=[.!?])\s+", line)
        for p in parts:
            p_clean = p.strip()
            if p_clean:
                raw_sentences.append(p_clean)
    return raw_sentences


def _is_low_information(sentence: str) -> bool:
    """Return True if sentence is a conversational greeting, closing, or trivial phrase."""
    s_clean = sentence.strip().rstrip(".!?")
    # Very short sentences without digits
    if len(s_clean.split()) <= 2 and not any(ch.isdigit() for ch in s_clean):
        return True
    return any(pattern.search(sentence) for pattern in LOW_INFO_PATTERNS)


def score_claim_salience(sentence: str) -> int:
    """Score the verifiable factual density of a candidate sentence."""
    score = 0
    if FACTUAL_SIGNALS["NUMBERS"].search(sentence):
        score += 2
    if FACTUAL_SIGNALS["PERCENTAGES"].search(sentence):
        score += 3
    if FACTUAL_SIGNALS["MONETARY"].search(sentence):
        score += 3
    if FACTUAL_SIGNALS["DATES"].search(sentence):
        score += 2
    if FACTUAL_SIGNALS["ASSERTIVE_VERBS"].search(sentence):
        score += 1
    # Check for mid-sentence capitalized words (heuristic for proper nouns/named entities)
    words = sentence.split()[1:]  # skip first word
    named_entities = sum(1 for w in words if w and w[0].isupper() and w.isalpha())
    if named_entities > 0:
        score += 1
    return score


def extract_claims(final_answer: str) -> list[str]:
    """Extract and prioritize candidate factual claims from an agent's final answer.

    1. Splits text into sentences.
    2. Filters out conversational greetings and boilerplate.
    3. Scores and orders sentences by factual salience (numbers, monetary, dates, percentages).
    """
    if not isinstance(final_answer, str) or not final_answer.strip():
        return []

    sentences = _split_into_sentences(final_answer)
    filtered: list[tuple[str, int]] = []

    for s in sentences:
        if _is_low_information(s):
            continue
        salience = score_claim_salience(s)
        filtered.append((s, salience))

    if not filtered:
        return []

    # Return prioritized sentences, maintaining high-salience claims first
    sorted_claims = sorted(filtered, key=lambda item: item[1], reverse=True)
    return [claim for claim, _ in sorted_claims]
