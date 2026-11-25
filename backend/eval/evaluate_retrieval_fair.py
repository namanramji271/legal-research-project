"""Fair chunk-depth, case-level comparison of the available retrievers.

Run from the repository root with:
    python backend/eval/evaluate_retrieval_fair.py

The hybrid weights are exploratory: they are reported on the same 15 queries
used here and are not an independent validation set.
"""

from __future__ import annotations

import hashlib
import json
import sys
import warnings
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
EVAL_DIR = Path(__file__).resolve().parent
TEST_QUERIES_PATH = EVAL_DIR / "test_queries.json"
CORPUS_PATH = BACKEND_DIR / "data" / "judgments.jsonl"
OUTPUT_JSON = EVAL_DIR / "results" / "fair_retrieval.json"
OUTPUT_MARKDOWN = EVAL_DIR / "fair_retrieval_findings.md"
CHUNK_DEPTH = 100
TOP_K = 5
BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 0

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from bm25_search import bm25_search_chunks, get_bm25_index  # noqa: E402
from embeddings import (  # noqa: E402
    BGE_CHROMA_DB_PATH,
    BGE_MODEL_NAME,
    CHROMA_DB_PATH,
    MODEL_NAME,
)
from eval.metrics import (  # noqa: E402
    bootstrap_mean_ci,
    collapse_cases,
    hit_at_k,
    mean_reciprocal_rank,
    ndcg_at_k,
    paired_bootstrap_ci,
    precision_at_k,
    recall_at_k,
    weighted_rrf,
)
from search import search_judgments, search_judgments_bge  # noqa: E402


METRIC_FUNCTIONS: dict[str, Callable[[list[str], set[str]], float]] = {
    "precision@5": lambda ranked, relevant: precision_at_k(ranked, relevant, TOP_K),
    "recall@5": lambda ranked, relevant: recall_at_k(ranked, relevant, TOP_K),
    "MRR": mean_reciprocal_rank,
    "nDCG@5": lambda ranked, relevant: ndcg_at_k(ranked, relevant, TOP_K),
    "Hit@5": lambda ranked, relevant: hit_at_k(ranked, relevant, TOP_K),
}


def _case_names(chunks: list[dict[str, Any]]) -> list[str]:
    return [str(result["case_name"]) for result in collapse_cases(chunks)]


def _evaluate_method(
    queries: list[dict[str, Any]],
    retrieve: Callable[[str], list[dict[str, Any]]],
) -> dict[str, list[float]]:
    scores = {name: [] for name in METRIC_FUNCTIONS}
    for entry in queries:
        ranked_cases = _case_names(retrieve(entry["query"]))
        relevant_cases = set(entry["relevant_cases"])
        for metric_name, metric_function in METRIC_FUNCTIONS.items():
            scores[metric_name].append(metric_function(ranked_cases, relevant_cases))
    return scores


def _confidence_summaries(scores: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    return {
        metric_name: bootstrap_mean_ci(
            values, n_resamples=BOOTSTRAP_RESAMPLES, seed=BOOTSTRAP_SEED
        )
        for metric_name, values in scores.items()
    }


def _markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Fair Retrieval Evaluation Findings",
        "",
        "## Protocol",
        "",
        f"- Labeled queries: {payload['metadata']['query_count']}",
        f"- Corpus chunks: {payload['metadata']['chunk_count']}",
        f"- Corpus SHA-256: `{payload['metadata']['judgments_sha256']}`",
        f"- Candidates: up to {CHUNK_DEPTH} positive-score BM25 chunks or dense chunks with `distance_threshold=None`.",
        "- All rankings are collapsed to unique case names in first-occurrence order before scoring.",
        f"- Bootstrap: {BOOTSTRAP_RESAMPLES} paired query resamples, seed {BOOTSTRAP_SEED}; percentile 95% CIs.",
        "- Hybrid RRF weights are exploratory because they are compared on these same 15 queries.",
        "",
        "## Model names",
        "",
        f"- MiniLM dense: `{MODEL_NAME}`",
        f"- BGE-M3 dense: `{BGE_MODEL_NAME}`",
        "- BM25: `rank_bm25.BM25Okapi` over the existing chunk text",
        "",
        "## Mean metrics (95% bootstrap CI)",
        "",
        "| Method | P@5 | R@5 | MRR | nDCG@5 | Hit@5 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for method, summaries in payload["metrics"].items():
        cells = [method]
        for metric_name in METRIC_FUNCTIONS:
            result = summaries[metric_name]
            cells.append(
                f"{result['estimate']:.3f} [{result['lower']:.3f}, {result['upper']:.3f}]"
            )
        lines.append("| " + " | ".join(cells) + " |")

    lines.extend(
        [
            "",
            "## Paired differences vs BM25 (95% bootstrap CI)",
            "",
            "Positive values favor the candidate method.",
            "",
            "| Method | P@5 | R@5 | MRR | nDCG@5 | Hit@5 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for method, summaries in payload["paired_differences_vs_bm25"].items():
        cells = [method]
        for metric_name in METRIC_FUNCTIONS:
            result = summaries[metric_name]
            cells.append(
                f"{result['estimate']:+.3f} [{result['lower']:+.3f}, {result['upper']:+.3f}]"
            )
        lines.append("| " + " | ".join(cells) + " |")

    lines.extend(
        [
            "",
            "## Ceiling and skipped methods",
            "",
            f"- Mean achievable P@5 ceiling from the labels: {payload['ceiling']['mean_max_p_at_5']:.3f}.",
        ]
    )
    if payload["warnings"]:
        lines.extend(f"- {warning}" for warning in payload["warnings"])
    else:
        lines.append("- No methods were skipped.")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    queries = json.loads(TEST_QUERIES_PATH.read_text(encoding="utf-8"))
    if not CORPUS_PATH.is_file():
        raise SystemExit(f"Judgment corpus missing: {CORPUS_PATH}")

    corpus_sha256 = hashlib.sha256(CORPUS_PATH.read_bytes()).hexdigest()
    chunk_count = len(get_bm25_index().documents)
    warnings_list: list[str] = []

    methods: dict[str, Callable[[str], list[dict[str, Any]]]] = {
        "MiniLM": lambda query: search_judgments(
            query, n_results=CHUNK_DEPTH, distance_threshold=None
        ),
        "BM25": lambda query: bm25_search_chunks(query, n_chunks=CHUNK_DEPTH),
    }

    if BGE_CHROMA_DB_PATH.exists():
        methods["BGE-M3"] = lambda query: search_judgments_bge(
            query, n_results=CHUNK_DEPTH, distance_threshold=None
        )
    else:
        warning = (
            "BGE-M3 skipped: backend/data/chroma_db_bge was not found. "
            "Build it with scripts/build_embeddings_bge.py to include this method."
        )
        warnings.warn(warning, RuntimeWarning)
        warnings_list.append(warning)

    raw_rankings: dict[str, dict[str, list[dict[str, Any]]]] = {}
    raw_scores: dict[str, dict[str, list[float]]] = {}
    for method_name, retrieve in methods.items():
        raw_rankings[method_name] = {}
        for entry in queries:
            raw_rankings[method_name][entry["query"]] = retrieve(entry["query"])
        raw_scores[method_name] = _evaluate_method(
            queries, lambda query, rankings=raw_rankings[method_name]: rankings[query]
        )

    hybrid_weights = {"1:1": {"bm25": 1.0, "dense": 1.0},
                      "2:1": {"bm25": 2.0, "dense": 1.0},
                      "3:1": {"bm25": 3.0, "dense": 1.0}}
    dense_rankings = raw_rankings["MiniLM"]
    bm25_rankings = raw_rankings["BM25"]
    for ratio, weights in hybrid_weights.items():
        method_name = f"RRF BM25:dense {ratio}"
        raw_rankings[method_name] = {
            entry["query"]: weighted_rrf(
                {
                    "bm25": bm25_rankings[entry["query"]],
                    "dense": dense_rankings[entry["query"]],
                },
                weights,
                k=60,
                limit=CHUNK_DEPTH,
            )
            for entry in queries
        }
        raw_scores[method_name] = _evaluate_method(
            queries, lambda query, rankings=raw_rankings[method_name]: rankings[query]
        )

    metrics = {
        method: _confidence_summaries(scores)
        for method, scores in raw_scores.items()
    }
    bm25_scores = raw_scores["BM25"]
    paired_differences = {
        method: {
            metric_name: paired_bootstrap_ci(
                values,
                bm25_scores[metric_name],
                n_resamples=BOOTSTRAP_RESAMPLES,
                seed=BOOTSTRAP_SEED,
            )
            for metric_name, values in scores.items()
        }
        for method, scores in raw_scores.items()
    }
    ceiling_values = [
        min(TOP_K, len(entry["relevant_cases"])) / TOP_K for entry in queries
    ]

    payload = {
        "metadata": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "query_count": len(queries),
            "chunk_count": chunk_count,
            "chunk_depth": CHUNK_DEPTH,
            "top_k": TOP_K,
            "judgments_file": CORPUS_PATH.relative_to(BACKEND_DIR).as_posix(),
            "judgments_sha256": corpus_sha256,
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "model_names": {
                "MiniLM": MODEL_NAME,
                "BGE-M3": BGE_MODEL_NAME,
                "BM25": "rank_bm25.BM25Okapi",
            },
            "hybrid_weights_bm25_dense": hybrid_weights,
            "hybrid_weights_exploratory": True,
            "rrf_k": 60,
        },
        "metrics": metrics,
        "paired_differences_vs_bm25": paired_differences,
        "ceiling": {"mean_max_p_at_5": sum(ceiling_values) / len(ceiling_values)},
        "warnings": warnings_list,
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    OUTPUT_MARKDOWN.write_text(_markdown_report(payload), encoding="utf-8")

    print(f"Fair retrieval evaluation complete: {len(queries)} queries, {chunk_count} chunks")
    print(f"Corpus SHA-256: {corpus_sha256}")
    print(f"Results JSON: {OUTPUT_JSON}")
    print(f"Findings: {OUTPUT_MARKDOWN}")
    for warning in warnings_list:
        print(f"WARNING: {warning}")


if __name__ == "__main__":
    main()
