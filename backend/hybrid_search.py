"""Hybrid dense and BM25 judgment retrieval using reciprocal rank fusion."""

from __future__ import annotations

from typing import Any

from bm25_search import bm25_search
from search import search_judgments


CANDIDATE_COUNT = 15
RRF_K = 60


def _unique_case_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep each named case once, retaining its first result position."""
    seen_case_names: set[str] = set()
    unique_results: list[dict[str, Any]] = []
    for result in results:
        case_name = str(result.get("case_name", ""))
        if not case_name or case_name in seen_case_names:
            continue
        seen_case_names.add(case_name)
        unique_results.append(result)
    return unique_results


def hybrid_search(query: str, n_results: int = 5) -> list[dict[str, Any]]:
    """Fuse dense and BM25 case rankings with reciprocal rank fusion."""
    if not query.strip():
        raise ValueError("query must not be empty")
    if n_results <= 0:
        raise ValueError("n_results must be positive")

    ranked_lists = (
        _unique_case_results(search_judgments(query, n_results=CANDIDATE_COUNT)),
        _unique_case_results(bm25_search(query, n_results=CANDIDATE_COUNT)),
    )
    fused_scores: dict[str, float] = {}
    records_by_case: dict[str, dict[str, Any]] = {}

    for ranked_results in ranked_lists:
        for rank, result in enumerate(ranked_results, start=1):
            case_name = str(result.get("case_name", ""))
            fused_scores[case_name] = fused_scores.get(case_name, 0.0) + 1 / (
                RRF_K + rank
            )
            records_by_case.setdefault(case_name, result)

    ranked_case_names = sorted(
        fused_scores, key=lambda case_name: fused_scores[case_name], reverse=True
    )
    return [records_by_case[case_name] for case_name in ranked_case_names[:n_results]]
