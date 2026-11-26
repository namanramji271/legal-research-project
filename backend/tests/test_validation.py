"""corpus/validation.py: strata, sampling, blind sheets, kappa and metrics (synthetic data)."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from corpus import validation as v  # noqa: E402

IPC = "The appellant was tried under the Indian Penal Code. "
BODIES = {
    "explicit": IPC + "Convicted under section 302 Indian Penal Code. The conviction under section 302 stands.",
    "implicit_only": IPC + "Convicted under section 302 for murder. The conviction under section 302 stands.",
    # One implicit mention: below the primary rule (CPC s.100 here would be a collision instead).
    "rejected_flagged": IPC + "The prosecution referred once to section 302 for murder.",
    "collision": IPC + "Reliance on section 106 to shift the burden. Convicted under section 302 for murder.",
    "no_marker": IPC + "Convicted under section 302 Indian Penal Code. Section 302 applies.",
}


def record(doc_id: str, kind: str) -> dict:
    return {"doc_id": doc_id, "body": BODIES[kind], "headnote": "",
            "split_method": "none" if kind == "no_marker" else "jurisdiction+delivered"}


def test_features_and_stratum_priority() -> None:
    assert {k: v.stratum(v.features(record("x", k))) for k in BODIES} == {k: k for k in BODIES}
    # no_marker wins over everything else; collision over rejected/implicit/explicit.
    both = {**record("y", "collision"), "split_method": "delivered"}
    assert v.stratum(v.features(both)) == "no_marker"


def pool(per_stratum: int = 30) -> list[dict]:
    items = []
    for kind in BODIES:
        for i in range(per_stratum):
            f = v.features(record(f"{kind}_{i:02d}", kind))
            f["stratum"] = v.stratum(f)
            items.append(f)
    return items


def test_draw_quotas_calibration_disjoint_dev_excluded_and_seeded() -> None:
    items = pool()
    dev = {"explicit_00", "collision_03"}
    sample, calibration, population = v.draw(items, seed=7, exclude=dev)
    assert len(sample) == 50 and len(calibration) == 5
    assert {s: sum(i["stratum"] == s for i in sample) for s in v.STRATA} == v.QUOTAS
    assert sorted(i["stratum"] for i in calibration) == sorted(v.STRATA)
    ids = {i["doc_id"] for i in sample}
    assert not ids & {i["doc_id"] for i in calibration} and not ids & dev
    assert population["explicit"] == 29 and population["implicit_only"] == 30
    again, _, _ = v.draw(list(reversed(items)), seed=7, exclude=dev)
    assert [i["doc_id"] for i in again] == [i["doc_id"] for i in sample]


def test_make_sheets_end_to_end_blind(tmp_path: Path) -> None:
    candidates, n = [], 0
    for kind in BODIES:
        for i in range(16):
            doc_id = f"{kind}_{i:02d}"
            candidates.append({"doc_id": doc_id, "year": 1975, "title": f"T {doc_id}", "citation": "C"})
            path = tmp_path / "text" / f"{doc_id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record(doc_id, kind)), encoding="utf-8")
            n += 1
    (tmp_path / "candidates.jsonl").write_text("\n".join(json.dumps(c) for c in candidates), encoding="utf-8")
    dev = tmp_path / "dev.json"
    dev.write_text(json.dumps({"documents": [{"doc_id": "explicit_00"}]}), encoding="utf-8")

    key = v.make_sheets(tmp_path, seed=3, dev_path=dev, out=lambda _: None)

    out = tmp_path / "validation"
    rows_a = list(csv.DictReader((out / "validation_sheet_A.csv").open(encoding="utf-8")))
    rows_b = list(csv.DictReader((out / "validation_sheet_B.csv").open(encoding="utf-8")))
    assert rows_a == rows_b and len(rows_a) == 50
    assert tuple(rows_a[0]) == v.SHEET_COLUMNS
    assert all(r["in_scope"] == "" and "stratum" not in r for r in rows_a)  # blind and empty
    assert "explicit_00" not in {r["doc_id"] for r in rows_a}
    assert len(list(csv.DictReader((out / "calibration_sheet.csv").open(encoding="utf-8")))) == 5
    assert key["short_strata"] == [] and key["excluded_dev_documents"] == 1
    # The shuffled order does not group strata.
    strata = {i["doc_id"]: i["stratum"] for i in key["sample"]}
    first_ten = {strata[r["doc_id"]] for r in rows_a[:10]}
    assert len(first_ten) > 1


def test_cohen_kappa_hand_computed() -> None:
    a = ["yes"] * 6 + ["no"] * 4
    b = ["yes"] * 5 + ["no"] + ["no"] * 3 + ["yes"]
    # p_o = 0.8; p_e = 0.6*0.6 + 0.4*0.4 = 0.52; kappa = 0.28 / 0.48
    assert v.cohen_kappa(a, b) == round(0.28 / 0.48, 4)
    assert v.cohen_kappa(["yes", "no"], ["yes", "no"]) == 1.0
    assert v.cohen_kappa(["yes", "yes"], ["yes", "yes"]) is None
    with pytest.raises(ValueError):
        v.cohen_kappa(["yes"], [])


def test_metrics_per_stratum_weighted_and_sensitivity() -> None:
    items = [
        {"doc_id": "e1", "stratum": "explicit", "primary_sections": ["302"], "loose_sections": ["302"]},
        {"doc_id": "e2", "stratum": "explicit", "primary_sections": ["302"], "loose_sections": ["302"]},
        {"doc_id": "r1", "stratum": "rejected_flagged", "primary_sections": [], "loose_sections": ["304"]},
        {"doc_id": "r2", "stratum": "rejected_flagged", "primary_sections": [], "loose_sections": []},
    ]
    gold = {"e1": {"in_scope": "yes", "sections": {"302"}, "split_correct": "yes"},
            "e2": {"in_scope": "no", "sections": set(), "split_correct": "no"},
            "r1": {"in_scope": "yes", "sections": {"304"}, "split_correct": "yes"},
            "r2": {"in_scope": "unsure", "sections": set(), "split_correct": "na"}}
    population = {"explicit": 100, "rejected_flagged": 10}
    m = v.detector_metrics(items, gold, population, "primary")
    assert m["per_stratum"]["explicit"] == {"n": 2, "tp": 1, "fp": 1, "fn": 0, "tn": 0, "precision": 0.5, "recall": 1.0}
    assert m["per_stratum"]["rejected_flagged"]["fn"] == 1 and m["unsure_excluded"] == 1
    # weights: explicit 100/2 = 50, rejected 10/1 = 10 -> TP 50, FP 50, FN 10
    assert m["pooled_weighted"] == {"precision": 0.5, "recall": round(50 / 60, 4)}
    assert m["section_level_unweighted"]["304"]["fn"] == 1
    loose = v.detector_metrics(items, gold, population, "loose")
    assert loose["per_stratum"]["rejected_flagged"]["tp"] == 1
    assert v.split_accuracy(items, gold)["accuracy"] == round(2 / 3, 4)


def write_labels(path: Path, labels: dict[str, tuple[str, str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=v.SHEET_COLUMNS)
        w.writeheader()
        for i, (doc_id, (scope, sections, split)) in enumerate(labels.items(), start=1):
            w.writerow({"item": i, "doc_id": doc_id, "in_scope": scope, "sections_at_issue": sections,
                        "split_correct": split})


def test_score_and_report_end_to_end(tmp_path: Path) -> None:
    key = {"seed": 1, "population": {"explicit": 20, "implicit_only": 20}, "quotas": v.QUOTAS,
           "sample": [{"doc_id": f"d{i}", "stratum": "explicit" if i < 2 else "implicit_only",
                       "primary_sections": ["302"], "loose_sections": ["302"]} for i in range(4)]}
    labels = {f"d{i}": ("yes", "302", "yes") for i in range(4)}
    for name in ("a", "b", "adj"):
        write_labels(tmp_path / f"{name}.csv", labels)
    result = v.score(key, *(v.read_labels(tmp_path / f"{n}.csv") for n in ("a", "b", "adj")))
    assert result["kappa"] is None  # all identical labels: kappa undefined, check fails
    assert result["checks"] == {"kappa": False, "weighted_precision": True, "split_accuracy": True}
    report = v.render_report(result, key)
    assert "Pre-registered rule" in report and "not used to choose the rule" in report
    assert "NOT ACCEPTED" in report and "fresh 50" in report


def test_read_labels_validates_values(tmp_path: Path) -> None:
    write_labels(tmp_path / "bad.csv", {"d1": ("maybe", "", "")})
    with pytest.raises(ValueError, match="yes/no/unsure"):
        v.read_labels(tmp_path / "bad.csv")
