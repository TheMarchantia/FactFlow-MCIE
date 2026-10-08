from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

try:
    import spacy
    _NLP = spacy.load("en_core_web_sm")
except Exception:
    _NLP = None

_STATUS_NOISE_TOKENS = {
    "rec", "aqi", "gold", "dhavarpada", "sur", "indiantelevision", "com",
    "wifi", "volte", "lte", "google", "subscribe", "share", "remix", "shorts",
}

_COMMON_VERBS = {
    "is", "was", "are", "were", "has", "have", "had", "will", "did", "do",
    "released", "launched", "announced", "killed", "injured", "died", "struck",
    "hit", "bought", "acquired", "cured", "cures", "caused", "causes",
    "resigned", "arrested", "elected", "banned", "discovered", "confirmed",
    "warned", "investing", "won", "giving", "gives", "gave",
}


def _clean_words(text: str) -> List[str]:
    return [w.lower() for w in re.findall(r"\b[a-zA-Z]+\b", text)]


def _noise_penalty(text: str) -> float:
    words = _clean_words(text)
    if not words:
        return 1.0

    noise_count = sum(1 for w in words if w in _STATUS_NOISE_TOKENS)
    noise_ratio = noise_count / len(words)

    # Penalty if lots of symbols or clock strings
    colon_count = text.count(":")
    clock_penalty = min(0.4, colon_count * 0.1)

    return min(1.0, (noise_ratio * 1.5) + clock_penalty)


def _grammatical_score(text: str) -> float:
    words = _clean_words(text)
    if not words:
        return 0.0

    score = 0.0
    # Length check: 4 to 35 words is ideal
    if 4 <= len(words) <= 35:
        score += 0.3
    elif len(words) > 35:
        score += 0.1

    # Check for presence of common verbs / assertions
    if any(v in words for v in _COMMON_VERBS):
        score += 0.3

    # Capitalization & punctuation
    text_strip = text.strip()
    if text_strip and text_strip[0].isupper():
        score += 0.1
    if text_strip.endswith((".", "!", "?")):
        score += 0.1

    # spaCy entity check
    if _NLP is not None:
        try:
            doc = _NLP(text[:250])
            if any(ent.label_ in {"GPE", "LOC", "ORG", "PERSON", "FAC", "DATE", "MONEY"} for ent in doc.ents):
                score += 0.2
        except Exception:
            pass

    return min(1.0, score)


def score_candidate(claim: Dict[str, Any]) -> float:
    text = claim.get("text", "").strip()
    if not text:
        return 0.0

    source = claim.get("source", "unknown")
    grammatical = _grammatical_score(text)
    noise = _noise_penalty(text)

    # Base score combines grammatical completeness and penalizes noise
    score = grammatical - noise

    # Source bonus: implied claims synthesized by LLM are generally clearer sentences
    if source == "implied":
        score += 0.25

    return round(max(0.0, min(1.0, score)), 3)


def _subsumes(clean_claim: str, noisy_claim: str) -> bool:
    """True if clean_claim shares major content words with noisy_claim but is cleaner."""
    w_clean = set(_clean_words(clean_claim))
    w_noisy = set(_clean_words(noisy_claim))

    if not w_clean or not w_noisy:
        return False

    intersection = w_clean & w_noisy
    # If clean claim contains at least 3 significant words from the noisy claim
    content_overlap = [w for w in intersection if len(w) > 3 and w not in _STATUS_NOISE_TOKENS]
    return len(content_overlap) >= 3


async def run(
    ecd_out: Dict[str, Any],
    icd_out: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Multimodal Claim Arbitrator & Ranker.

    Collects explicit rule-based and implied LLM-synthesized claims,
    scores each for factual clarity, well-formedness, and noise resistance,
    and returns a ranked list with a single designated primary_claim.
    """
    explicit_claims = ecd_out.get("explicit_claims") or []
    implied_claims = icd_out.get("implied_claims") or []

    all_candidates: List[Dict[str, Any]] = []

    # Include explicit claims
    for c in explicit_claims:
        if isinstance(c, dict) and c.get("text"):
            all_candidates.append({
                "text": c["text"].strip(),
                "source": c.get("source", "explicit"),
                "base_confidence": c.get("confidence", 0.7),
            })

    # Include implied claims
    for c in implied_claims:
        if isinstance(c, dict) and c.get("text"):
            all_candidates.append({
                "text": c["text"].strip(),
                "source": c.get("source", "implied"),
                "base_confidence": 0.85,
            })
        elif isinstance(c, str) and c.strip():
            all_candidates.append({
                "text": c.strip(),
                "source": "implied",
                "base_confidence": 0.85,
            })

    if not all_candidates:
        return {
            "primary_claim": None,
            "ranked_claims": [],
        }

    # Score each candidate
    scored: List[Dict[str, Any]] = []
    for cand in all_candidates:
        s = score_candidate(cand)
        scored.append({
            **cand,
            "rank_score": s,
        })

    # If an implied claim cleanly subsumes a noisy explicit claim, give the implied claim a priority bump
    for cand in scored:
        if cand["source"] == "implied":
            for other in scored:
                if other["source"] != "implied" and _subsumes(cand["text"], other["text"]):
                    cand["rank_score"] = min(1.0, cand["rank_score"] + 0.2)
                    other["rank_score"] = max(0.0, other["rank_score"] - 0.2)

    # Sort descending by rank_score
    scored.sort(key=lambda x: x["rank_score"], reverse=True)

    # Filter out exact duplicate claim texts
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in scored:
        norm = item["text"].lower().strip()
        if norm not in seen:
            seen.add(norm)
            deduped.append(item)

    primary = deduped[0] if deduped else None

    return {
        "primary_claim": primary,
        "ranked_claims": deduped,
    }
