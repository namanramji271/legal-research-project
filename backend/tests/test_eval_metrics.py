from __future__ import annotations

import math
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

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


def test_case_level_collapse_preserves_first_occurrence_order() -> None:
    records = [
        {"case_name": "A", "chunk_text": "first A chunk"},
        {"case_name": "A", "chunk_text": "later A chunk"},
        {"case_name": "B"},
        {"case_name": ""},
        {"case_name": "C"},
    ]
    assert [item["case_name"] for item in collapse_cases(records)] == ["A", "B", "C"]
    assert collapse_cases(records)[0]["chunk_text"] == "first A chunk"


def test_precision_recall_mrr_ndcg_and_hit_hand_computed() -> None:
    ranked = ["A", "B", "C", "D"]
    relevant = {"B", "D"}
    assert precision_at_k(ranked, relevant, 5) == 2 / 5
    assert recall_at_k(ranked, relevant, 5) == 1.0
    assert mean_reciprocal_rank(ranked, relevant) == 0.5
    expected_ndcg = (1 / math.log2(3) + 1 / math.log2(5)) / (
        1 + 1 / math.log2(3)
    )
    assert math.isclose(ndcg_at_k(ranked, relevant, 5), expected_ndcg)
    assert hit_at_k(ranked, relevant, 1) == 0.0
    assert hit_at_k(ranked, relevant, 2) == 1.0


def test_weighted_rrf_uses_k_60_and_first_case_ranks() -> None:
    rankings = {
        "bm25": [
            {"case_name": "A"},
            {"case_name": "A"},
            {"case_name": "B"},
        ],
        "dense": [{"case_name": "B"}, {"case_name": "A"}],
    }
    fused = weighted_rrf(rankings, {"bm25": 2, "dense": 1})
    assert [item["case_name"] for item in fused] == ["A", "B"]
    assert math.isclose(fused[0]["rrf_score"], 2 / 61 + 1 / 62)
    assert math.isclose(fused[1]["rrf_score"], 2 / 62 + 1 / 61)


def test_bootstrap_confidence_intervals_are_deterministic_and_paired() -> None:
    result = bootstrap_mean_ci([0.25, 0.25, 0.25], n_resamples=1000, seed=0)
    assert result == {"estimate": 0.25, "lower": 0.25, "upper": 0.25}

    paired = paired_bootstrap_ci(
        [0.5, 0.5, 0.5], [0.25, 0.25, 0.25], n_resamples=1000, seed=0
    )
    assert paired == {"estimate": 0.25, "lower": 0.25, "upper": 0.25}
