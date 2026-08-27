"""Evaluate judgment retrieval against the labeled semantic-search queries.

Run from the repository root with:
    python backend/eval/evaluate_retrieval.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_QUERIES_PATH = Path(__file__).with_name("test_queries.json")
TOP_K = 5
RETRIEVAL_COUNT = 10

# search.py uses imports relative to the backend directory.
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from search import search_judgments  # noqa: E402


def _unique_case_names(results: list[dict[str, Any]]) -> list[str]:
    """Keep each judgment once, retaining its first result position."""
    seen: set[str] = set()
    case_names: list[str] = []
    for result in results:
        case_name = result.get("case_name", "")
        if case_name and case_name not in seen:
            seen.add(case_name)
            case_names.append(case_name)
    return case_names


def _metrics(
    returned_cases: list[str], relevant_cases: set[str]
) -> tuple[float, float, float]:
    """Calculate precision@5, recall@5, and reciprocal rank."""
    top_cases = returned_cases[:TOP_K]
    relevant_at_k = sum(case_name in relevant_cases for case_name in top_cases)
    precision_at_5 = relevant_at_k / TOP_K
    recall_at_5 = relevant_at_k / len(relevant_cases) if relevant_cases else 0.0

    reciprocal_rank = 0.0
    for rank, case_name in enumerate(returned_cases, start=1):
        if case_name in relevant_cases:
            reciprocal_rank = 1 / rank
            break

    return precision_at_5, recall_at_5, reciprocal_rank


def main() -> None:
    """Run the labeled retrieval evaluation and print aggregate metrics."""
    test_queries = json.loads(TEST_QUERIES_PATH.read_text(encoding="utf-8"))
    precision_scores: list[float] = []
    recall_scores: list[float] = []
    reciprocal_ranks: list[float] = []
    zero_result_queries = 0

    for index, entry in enumerate(test_queries, start=1):
        query = entry["query"]
        relevant_cases = set(entry["relevant_cases"])
        results = search_judgments(query, n_results=RETRIEVAL_COUNT)
        returned_cases = _unique_case_names(results)

        if not results:
            zero_result_queries += 1

        precision_at_5, recall_at_5, reciprocal_rank = _metrics(
            returned_cases, relevant_cases
        )
        precision_scores.append(precision_at_5)
        recall_scores.append(recall_at_5)
        reciprocal_ranks.append(reciprocal_rank)

        print(f"{index}. {query}")
        print(f"   Expected relevant cases: {len(relevant_cases)}")
        print(f"   Returned results: {len(results)} ({len(returned_cases)} unique cases)")
        print(
            "   "
            f"precision@5={precision_at_5:.3f} "
            f"recall@5={recall_at_5:.3f} "
            f"reciprocal_rank={reciprocal_rank:.3f}"
        )

    print("\nOverall averages")
    print(f"Mean precision@5: {mean(precision_scores):.3f}")
    print(f"Mean recall@5: {mean(recall_scores):.3f}")
    print(f"MRR: {mean(reciprocal_ranks):.3f}")
    print(f"Queries with zero results: {zero_result_queries}/{len(test_queries)}")


if __name__ == "__main__":
    main()
