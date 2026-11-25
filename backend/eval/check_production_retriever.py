"""Check that the production retriever reproduces the fair-evaluation numbers.

Run from the repository root, once per retriever:
    RETRIEVER=bm25  python backend/eval/check_production_retriever.py
    RETRIEVER=dense python backend/eval/check_production_retriever.py

The check calls the production ``search.retrieve_chunks()`` at the fair-eval
setup (100 chunks, dense ``distance_threshold=None``), collapses to cases, and
compares P@5, R@5 and MRR with ``results/fair_retrieval.json``:
``bm25`` against the "BM25 + stopwords" row, ``dense`` against "MiniLM".
It exits non-zero on any mismatch. The production defaults are reported
separately and are not compared. A BM25 score report follows for the labeled
queries, the out-of-corpus QA questions and gibberish queries.

No Gemini calls are made. Re-run evaluate_retrieval_fair.py first if the
corpus changed.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
EVAL_DIR = Path(__file__).resolve().parent
TEST_QUERIES_PATH = EVAL_DIR / "test_queries.json"
QA_QUESTIONS_PATH = EVAL_DIR / "test_qa_questions.json"
FAIR_RESULTS_PATH = EVAL_DIR / "results" / "fair_retrieval.json"
CHECK_DEPTH = 100
TOP_K = 5
TOLERANCE = 5e-4  # published numbers are rounded to 3 decimals
EXPECTED_ROW = {"bm25": "BM25 + stopwords", "dense": "MiniLM"}
CHECKED_METRICS = ("precision@5", "recall@5", "MRR")
GIBBERISH_QUERIES = ("xqzv blorf plimt", "asdkjh qwpoeiru zmxncb", "dgadfad sdfsdf")

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import config  # noqa: E402
from bm25_search import _tokenize, bm25_search_chunks  # noqa: E402
from eval.metrics import (  # noqa: E402
    collapse_cases,
    mean_reciprocal_rank,
    precision_at_k,
    recall_at_k,
)
from explainability import STOPWORDS  # noqa: E402
from search import retrieve_cases, retrieve_chunks  # noqa: E402


def _mean_metrics(
    queries: list[dict[str, Any]], retrieve: Callable[[str], list[dict[str, Any]]]
) -> dict[str, float]:
    totals = dict.fromkeys(CHECKED_METRICS, 0.0)
    for entry in queries:
        ranked = [str(r["case_name"]) for r in collapse_cases(retrieve(entry["query"]))]
        relevant = set(entry["relevant_cases"])
        totals["precision@5"] += precision_at_k(ranked, relevant, TOP_K)
        totals["recall@5"] += recall_at_k(ranked, relevant, TOP_K)
        totals["MRR"] += mean_reciprocal_rank(ranked, relevant)
    return {name: value / len(queries) for name, value in totals.items()}


def _format(metrics: dict[str, float]) -> str:
    return "  ".join(f"{name}={metrics[name]:.3f}" for name in CHECKED_METRICS)


def _score_report(title: str, queries: list[str], relevant: list[set[str]] | None) -> list[float]:
    """Print BM25 production scores and return each query's top-1 score (0 if none)."""
    print(f"\n### {title}")
    top_scores: list[float] = []
    for index, query in enumerate(queries):
        kept_tokens = [t for t in _tokenize(query) if t not in STOPWORDS]
        chunks = (
            bm25_search_chunks(
                query,
                n_chunks=CHECK_DEPTH,
                min_score=config.SETTINGS.bm25_min_score,
                stopwords=STOPWORDS,
            )
            if kept_tokens
            else []
        )
        cases = collapse_cases(chunks)[:TOP_K]
        top_scores.append(cases[0]["score"] if cases else 0.0)
        print(f"\n[{index + 1}] {query}")
        print(f"    tokens after stopwords: {kept_tokens}")
        print(f"    chunks above BM25_MIN_SCORE: {len(chunks)} (cap {CHECK_DEPTH})")
        if not cases:
            print("    top-5 cases: none")
            continue
        for rank, case in enumerate(cases, start=1):
            mark = ""
            if relevant is not None:
                mark = "  RELEVANT" if case["case_name"] in relevant[index] else ""
            print(f"    {rank}. {case['score']:7.3f}  {case['case_name']}{mark}")
    return top_scores


def _summarise(name: str, scores: list[float]) -> None:
    print(
        f"  {name:<22} n={len(scores):<3} top-1 score "
        f"min={min(scores):.3f}  median={statistics.median(scores):.3f}  max={max(scores):.3f}"
    )


def main() -> int:
    retriever = config.SETTINGS.retriever
    queries = json.loads(TEST_QUERIES_PATH.read_text(encoding="utf-8"))
    print(f"RETRIEVER={retriever}  BM25_MIN_SCORE={config.SETTINGS.bm25_min_score}")
    print(f"Labeled retrieval queries: {len(queries)}")

    print("\n## Production check (fair-eval setup: 100 chunks, dense threshold off)")
    checked = _mean_metrics(
        queries,
        lambda q: retrieve_chunks(q, n_chunks=CHECK_DEPTH, distance_threshold=None),
    )
    print(f"  production:        {_format(checked)}")

    status = 0
    expected_row = EXPECTED_ROW.get(retriever)
    if expected_row is None:
        print(f"  no fair-eval row is defined for RETRIEVER={retriever}; nothing to compare")
    else:
        fair = json.loads(FAIR_RESULTS_PATH.read_text(encoding="utf-8"))
        expected = {
            name: fair["metrics"][expected_row][name]["estimate"] for name in CHECKED_METRICS
        }
        print(f"  fair eval '{expected_row}': {_format(expected)}")
        mismatches = {
            name: (checked[name], expected[name])
            for name in CHECKED_METRICS
            if abs(checked[name] - expected[name]) > TOLERANCE
        }
        if mismatches:
            status = 1
            for name, (got, want) in mismatches.items():
                print(f"  MISMATCH {name}: production {got:.4f} vs fair eval {want:.4f}")
        else:
            print("  MATCH: production reproduces the fair-eval row")

    print("\n## Production defaults (reported only, not compared)")
    default_cases = _mean_metrics(queries, lambda q: retrieve_cases(q, n_cases=TOP_K))
    print(
        "  /search and /ask default (50-chunk over-fetch, top 5 cases, "
        f"dense threshold {0.65}):\n    {_format(default_cases)}"
    )
    five_chunks = _mean_metrics(queries, lambda q: retrieve_chunks(q, n_chunks=TOP_K))
    print(
        "  former 5-chunk default (5 chunks, no over-fetch, dense threshold 0.65):\n"
        f"    {_format(five_chunks)}"
    )

    print("\n## BM25 score report (production BM25: stopwords filtered, BM25_MIN_SCORE applied)")
    labeled_top = _score_report(
        "Labeled retrieval queries",
        [entry["query"] for entry in queries],
        [set(entry["relevant_cases"]) for entry in queries],
    )
    qa_questions = json.loads(QA_QUESTIONS_PATH.read_text(encoding="utf-8"))
    out_of_corpus = [e["question"] for e in qa_questions if not e["expected_answerable"]]
    ooc_top = _score_report("Out-of-corpus QA questions", out_of_corpus, None)
    gibberish_top = _score_report("Gibberish queries", list(GIBBERISH_QUERIES), None)

    print("\n### Top-1 BM25 score summary")
    _summarise("labeled", labeled_top)
    _summarise("out-of-corpus", ooc_top)
    _summarise("gibberish", gibberish_top)

    print(f"\nExit status: {status}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
