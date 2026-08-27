"""Compare MiniLM and BGE-M3 retrieval against the labeled test queries.

Run from the repository root with:
    python backend/eval/evaluate_retrieval_comparison.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean
from typing import Any, Callable


BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_QUERIES_PATH = Path(__file__).with_name("test_queries.json")
TOP_K = 5
RETRIEVAL_COUNT = 10

# search.py uses imports relative to the backend directory.
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from search import search_judgments, search_judgments_bge  # noqa: E402


SearchFunction = Callable[[str, int], list[dict[str, Any]]]


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


def _evaluate_query(
    search_function: SearchFunction, query: str, relevant_cases: set[str]
) -> tuple[int, int, tuple[float, float, float]]:
    """Retrieve, deduplicate case names, and calculate metrics for one query."""
    results = search_function(query, n_results=RETRIEVAL_COUNT)
    returned_cases = _unique_case_names(results)
    return len(results), len(returned_cases), _metrics(returned_cases, relevant_cases)


def _print_model_metrics(
    model_name: str,
    result_count: int,
    unique_case_count: int,
    metrics: tuple[float, float, float],
) -> None:
    """Print one model's retrieval counts and metrics in the comparison format."""
    precision_at_5, recall_at_5, reciprocal_rank = metrics
    print(
        f"   {model_name:<6} results={result_count:<2} unique_cases={unique_case_count:<2} "
        f"precision@5={precision_at_5:.3f} recall@5={recall_at_5:.3f} "
        f"reciprocal_rank={reciprocal_rank:.3f}"
    )


def main() -> None:
    """Run the labeled retrieval comparison and print per-query and mean metrics."""
    test_queries = json.loads(TEST_QUERIES_PATH.read_text(encoding="utf-8"))
    models: tuple[tuple[str, SearchFunction], ...] = (
        ("MiniLM", search_judgments),
        ("BGE-M3", search_judgments_bge),
    )
    model_scores: dict[str, dict[str, list[float]]] = {
        name: {"precision": [], "recall": [], "reciprocal_rank": []}
        for name, _search_function in models
    }

    for index, entry in enumerate(test_queries, start=1):
        query = entry["query"]
        relevant_cases = set(entry["relevant_cases"])
        print(f"{index}. {query}")
        print(f"   Expected relevant cases: {len(relevant_cases)}")

        for model_name, search_function in models:
            result_count, unique_case_count, metrics = _evaluate_query(
                search_function, query, relevant_cases
            )
            precision_at_5, recall_at_5, reciprocal_rank = metrics
            model_scores[model_name]["precision"].append(precision_at_5)
            model_scores[model_name]["recall"].append(recall_at_5)
            model_scores[model_name]["reciprocal_rank"].append(reciprocal_rank)
            _print_model_metrics(
                model_name, result_count, unique_case_count, metrics
            )

    print("\nOverall averages")
    for model_name, _search_function in models:
        scores = model_scores[model_name]
        print(
            f"{model_name}: "
            f"mean precision@5={mean(scores['precision']):.3f} "
            f"mean recall@5={mean(scores['recall']):.3f} "
            f"MRR={mean(scores['reciprocal_rank']):.3f}"
        )


if __name__ == "__main__":
    main()
