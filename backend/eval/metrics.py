"""Shared case-level retrieval metrics and deterministic bootstrap intervals."""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from typing import Any


def collapse_cases(results: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one result per non-empty case name in first-occurrence order."""
    seen: set[str] = set()
    collapsed: list[dict[str, Any]] = []
    for result in results:
        case_name = str(result.get("case_name", ""))
        if not case_name or case_name in seen:
            continue
        seen.add(case_name)
        collapsed.append(result)
    return collapsed


def precision_at_k(ranked_cases: Sequence[str], relevant: set[str], k: int = 5) -> float:
    _validate_k(k)
    return sum(case in relevant for case in ranked_cases[:k]) / k


def recall_at_k(ranked_cases: Sequence[str], relevant: set[str], k: int = 5) -> float:
    _validate_k(k)
    if not relevant:
        return 0.0
    return sum(case in relevant for case in ranked_cases[:k]) / len(relevant)


def mean_reciprocal_rank(ranked_cases: Sequence[str], relevant: set[str]) -> float:
    for rank, case_name in enumerate(ranked_cases, start=1):
        if case_name in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(ranked_cases: Sequence[str], relevant: set[str], k: int = 5) -> float:
    _validate_k(k)
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, case_name in enumerate(ranked_cases[:k], start=1)
        if case_name in relevant
    )
    ideal_hits = min(k, len(relevant))
    if ideal_hits == 0:
        return 0.0
    ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / ideal_dcg


def hit_at_k(ranked_cases: Sequence[str], relevant: set[str], k: int = 5) -> float:
    _validate_k(k)
    return float(any(case in relevant for case in ranked_cases[:k]))


def weighted_rrf(
    rankings: Mapping[str, Sequence[dict[str, Any]]],
    weights: Mapping[str, float],
    k: int = 60,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Fuse case rankings with weighted reciprocal rank fusion.

    Duplicate chunks are collapsed to their first case occurrence in each
    input ranking before assigning RRF ranks.
    """
    if k < 0:
        raise ValueError("k must be non-negative")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive when provided")

    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    record_by_case: dict[str, dict[str, Any]] = {}
    next_order = 0

    for source, results in rankings.items():
        weight = float(weights.get(source, 0.0))
        if weight < 0:
            raise ValueError("RRF weights must be non-negative")
        for rank, result in enumerate(collapse_cases(results), start=1):
            case_name = str(result["case_name"])
            if case_name not in first_seen:
                first_seen[case_name] = next_order
                record_by_case[case_name] = result
                next_order += 1
            scores[case_name] = scores.get(case_name, 0.0) + weight / (k + rank)

    ordered = sorted(scores, key=lambda name: (-scores[name], first_seen[name]))
    if limit is not None:
        ordered = ordered[:limit]
    return [
        {**record_by_case[name], "rrf_score": scores[name]}
        for name in ordered
        if scores[name] > 0
    ]


def bootstrap_mean_ci(
    values: Sequence[float],
    n_resamples: int = 1000,
    seed: int = 0,
    confidence: float = 0.95,
) -> dict[str, float]:
    """Return the mean and percentile bootstrap confidence interval."""
    _validate_bootstrap(values, n_resamples, confidence)
    samples = list(map(float, values))
    rng = random.Random(seed)
    means = [
        sum(rng.choices(samples, k=len(samples))) / len(samples)
        for _ in range(n_resamples)
    ]
    return {
        "estimate": sum(samples) / len(samples),
        "lower": _percentile(means, (1.0 - confidence) / 2.0),
        "upper": _percentile(means, 1.0 - (1.0 - confidence) / 2.0),
    }


def paired_bootstrap_ci(
    candidate: Sequence[float],
    baseline: Sequence[float],
    n_resamples: int = 1000,
    seed: int = 0,
    confidence: float = 0.95,
) -> dict[str, float]:
    """Bootstrap the paired per-query mean difference (candidate - baseline)."""
    if len(candidate) != len(baseline):
        raise ValueError("paired samples must have equal length")
    differences = [float(a) - float(b) for a, b in zip(candidate, baseline)]
    return bootstrap_mean_ci(differences, n_resamples, seed, confidence)


def _validate_k(k: int) -> None:
    if k <= 0:
        raise ValueError("k must be positive")


def _validate_bootstrap(values: Sequence[float], n_resamples: int, confidence: float) -> None:
    if not values:
        raise ValueError("bootstrap values must not be empty")
    if n_resamples <= 0:
        raise ValueError("n_resamples must be positive")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between 0 and 1")


def _percentile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction
