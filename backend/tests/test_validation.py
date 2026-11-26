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
    "weak_split": IPC + "Convicted under section 302 Indian Penal Code. Section 302 applies.",
}


def record(doc_id: str, kind: str) -> dict:
    return {"doc_id": doc_id, "body": BODIES[kind], "headnote": "",
            "split_method": "none" if kind == "weak_split" else "jurisdiction+delivered"}


def test_features_and_stratum_priority() -> None:
    assert {k: v.stratum(v.features(record("x", k))) for k in BODIES} == {k: k for k in BODIES}
    # weak_split wins over everything else; collision over rejected/implicit/explicit.
    both = {**record("y", "collision"), "split_method": "delivered"}
    assert v.stratum(v.features(both)) == "weak_split"


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
    assert len(sample) == v.SAMPLE_SIZE == 55 and len(calibration) == 5
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
        for i in range(20):
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
    assert not (out / "validation_sheet_A.csv").exists() and not (out / "validation_sheet_B.csv").exists()
    assert len(key["sample"]) == 55 and "explicit_00" not in {i["doc_id"] for i in key["sample"]}
    assert len(list(csv.DictReader((out / "calibration_sheet.csv").open(encoding="utf-8")))) == 5
    assert key["short_strata"] == [] and key["excluded_dev_documents"] == 1
    assert key["human_subset"] == v.draw_human_subset(key["sample"], 3) and key["human_subset_seed"] == 5

    # The human sheet: 25 blind, empty rows from the recorded subset; sample unchanged.
    sample_before = json.loads((out / "validation_key.json").read_text(encoding="utf-8"))["sample"]
    v.make_human_sheet(tmp_path, out=lambda _: None)
    rows = list(csv.DictReader((out / v.HUMAN_SHEET).open(encoding="utf-8")))
    assert len(rows) == 25 and tuple(rows[0]) == v.SHEET_COLUMNS
    assert all(r["in_scope"] == "" and r["section_as_charge"] == "" and "stratum" not in r for r in rows)
    assert {r["doc_id"] for r in rows} == set(key["human_subset"])
    assert json.loads((out / "validation_key.json").read_text(encoding="utf-8"))["sample"] == sample_before
    # The shuffled order does not group strata.
    strata = {i["doc_id"]: i["stratum"] for i in key["sample"]}
    assert len({strata[r["doc_id"]] for r in rows[:8]}) > 1


def test_human_subset_seeded_per_stratum_and_guarded(tmp_path: Path) -> None:
    sample, _, _ = v.draw(pool(), seed=7, exclude=set())
    subset = v.draw_human_subset(sample, 7)
    strata = {i["doc_id"]: i["stratum"] for i in sample}
    assert len(subset) == 25 and set(subset) <= set(strata)
    assert {s: sum(strata[d] == s for d in subset) for s in v.STRATA} == {s: 5 for s in v.STRATA}
    assert v.draw_human_subset(list(reversed(sample)), 7) == subset  # order-independent
    assert v.draw_human_subset(sample, 8) != subset  # depends on the seed
    # Adding the subset to a key without one; refusing a key whose subset differs.
    (tmp_path / "validation").mkdir()
    (tmp_path / "candidates.jsonl").write_text("", encoding="utf-8")
    for d in subset:
        (tmp_path / "text").mkdir(exist_ok=True)
        (tmp_path / "text" / f"{d}.json").write_text(json.dumps({"doc_id": d, "body": "B"}), encoding="utf-8")
    key_path = tmp_path / "validation" / "validation_key.json"
    key_path.write_text(json.dumps({"seed": 7, "sample": sample}), encoding="utf-8")
    key = v.make_human_sheet(tmp_path, out=lambda _: None)
    assert key["human_subset"] == subset and key["human_subset_seed"] == 9
    assert json.loads(key_path.read_text(encoding="utf-8"))["human_subset"] == subset
    v.make_human_sheet(tmp_path, out=lambda _: None)  # idempotent
    key_path.write_text(json.dumps({**key, "human_subset": subset[::-1]}), encoding="utf-8")
    with pytest.raises(ValueError, match="different human_subset"):
        v.make_human_sheet(tmp_path, out=lambda _: None)


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
    gold = {"e1": {"in_scope": "yes", "section_as_charge": "no", "sections": {"302"}, "split_correct": "yes"},
            "e2": {"in_scope": "no", "section_as_charge": "yes", "sections": set(), "split_correct": "no"},
            "r1": {"in_scope": "yes", "section_as_charge": "no", "sections": {"304"}, "split_correct": "yes"},
            "r2": {"in_scope": "unsure", "section_as_charge": "no", "sections": set(), "split_correct": "na"}}
    population = {"explicit": 100, "rejected_flagged": 10}
    m = v.detector_metrics(items, gold, population, "primary")
    assert m["per_stratum"]["explicit"] == {"n": 2, "tp": 1, "fp": 1, "fn": 0, "tn": 0,
                                            "precision": 0.5, "precision_ci": [0.0945, 0.9055],
                                            "recall": 1.0, "recall_ci": [0.2065, 1.0]}
    assert m["per_stratum"]["rejected_flagged"]["fn"] == 1 and m["unsure_excluded"] == 1
    # weights: explicit 100/2 = 50, rejected 10/1 = 10 -> TP 50, FP 50, FN 10
    assert (m["pooled_weighted"]["precision"], m["pooled_weighted"]["recall"]) == (0.5, round(50 / 60, 4))
    assert m["section_level_unweighted"]["304"]["fn"] == 1
    loose = v.detector_metrics(items, gold, population, "loose")
    assert loose["per_stratum"]["rejected_flagged"]["tp"] == 1
    # Loose gold label: e2 (charge only) counts as in scope, so the explicit stratum is all TP.
    lab = v.detector_metrics(items, gold, population, "primary", label="loose")
    assert lab["label"] == "loose" and lab["per_stratum"]["explicit"]["precision"] == 1.0
    assert lab["pooled_weighted"]["precision"] == 1.0 and lab["pooled_weighted"]["precision_ci"] == [1.0, 1.0]
    assert v.split_accuracy(items, gold)["accuracy"] == round(2 / 3, 4)


def write_labels(path: Path, labels: dict[str, tuple[str, str, str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=v.SHEET_COLUMNS)
        w.writeheader()
        for i, (doc_id, (scope, charge, sections, split)) in enumerate(labels.items(), start=1):
            w.writerow({"item": i, "doc_id": doc_id, "in_scope": scope, "section_as_charge": charge,
                        "sections_at_issue": sections, "split_correct": split})


def test_score_and_report_end_to_end(tmp_path: Path) -> None:
    key = {"seed": 1, "population": {"explicit": 20, "implicit_only": 20}, "quotas": v.QUOTAS,
           "sample": [{"doc_id": f"d{i}", "stratum": "explicit" if i < 2 else "implicit_only",
                       "primary_sections": ["302"], "loose_sections": ["302"]} for i in range(4)]}
    labels = {f"d{i}": ("yes", "no", "302", "yes") for i in range(4)}
    for name in ("a", "b", "adj"):
        write_labels(tmp_path / f"{name}.csv", labels)
    result = v.score(key, *(v.read_labels(tmp_path / f"{n}.csv") for n in ("a", "b", "adj")))
    assert result["agreement"]["in_scope"]["kappa"] is None  # all identical labels: kappa undefined, check fails
    assert result["agreement"]["section_as_charge"] == {"kappa": None, "raw_agreement": 1.0}
    assert result["checks"] == {"kappa": False, "weighted_precision": True, "split_accuracy": True}
    report = v.render_report(result, key)
    assert "Pre-registered labels" in report and "not used to choose the rule" in report
    assert "against the loose label" in report and "section_as_charge" in report
    assert "rests on few labels per stratum" in report and "8–15" in report
    assert "1.0 [1.0, 1.0]" in report and "stratified bootstrap" in report
    assert result["acceptance_on"] == "point estimates"
    assert "NOT ACCEPTED" in report and "fresh 55" in report


def test_read_labels_validates_values(tmp_path: Path) -> None:
    write_labels(tmp_path / "bad.csv", {"d1": ("maybe", "no", "", "")})
    with pytest.raises(ValueError, match="yes/no/unsure"):
        v.read_labels(tmp_path / "bad.csv")
    write_labels(tmp_path / "blank.csv", {"d1": ("no", "", "", "")})
    with pytest.raises(ValueError, match="section_as_charge must be yes/no"):
        v.read_labels(tmp_path / "blank.csv")
    write_labels(tmp_path / "both.csv", {"d1": ("yes", "yes", "302", "")})
    with pytest.raises(ValueError, match="must be no when in_scope is yes"):
        v.read_labels(tmp_path / "both.csv")


def test_gold_views_and_kappa_on_both_fields(tmp_path: Path) -> None:
    assert v.gold_in_scope({"in_scope": "no", "section_as_charge": "yes"}) is False
    assert v.gold_in_scope({"in_scope": "no", "section_as_charge": "yes"}, "loose") is True
    assert v.gold_in_scope({"in_scope": "unsure", "section_as_charge": "yes"}, "loose") is True
    assert v.gold_in_scope({"in_scope": "unsure", "section_as_charge": "no"}, "loose") is None
    with pytest.raises(ValueError):
        v.gold_in_scope({"in_scope": "yes"}, "other")
    key = {"seed": 1, "population": {"explicit": 10}, "quotas": v.QUOTAS,
           "sample": [{"doc_id": f"d{i}", "stratum": "explicit", "primary_sections": ["302"],
                       "loose_sections": ["302"]} for i in range(4)]}
    a = {"d0": ("yes", "no", "302", "yes"), "d1": ("no", "yes", "", "yes"),
         "d2": ("no", "yes", "", "yes"), "d3": ("no", "no", "", "yes")}
    b = {**a, "d3": ("no", "yes", "", "yes")}  # disagree on section_as_charge only
    for name, labels in (("a", a), ("b", b), ("adj", a)):
        write_labels(tmp_path / f"{name}.csv", labels)
    result = v.score(key, *(v.read_labels(tmp_path / f"{n}.csv") for n in ("a", "b", "adj")))
    assert result["agreement"]["in_scope"]["kappa"] == 1.0
    # section_as_charge: a = n,y,y,n; b = n,y,y,y -> p_o 0.75, p_e 0.5*0.25 + 0.5*0.75 = 0.5
    assert result["agreement"]["section_as_charge"] == {"kappa": 0.5, "raw_agreement": 0.75}
    assert result["primary"]["pooled_weighted"]["precision"] == 0.25
    assert result["secondary_loose_label"]["pooled_weighted"]["precision"] == 0.75
    assert result["checks"]["weighted_precision"] is False  # acceptance uses the strict label


def test_quotas_and_failed_pdfs_are_excluded(tmp_path: Path) -> None:
    assert v.QUOTAS == {"weak_split": 8, "collision": 10, "rejected_flagged": 10, "implicit_only": 12, "explicit": 15}
    assert sum(v.QUOTAS.values()) == 55
    candidates = []
    for kind in BODIES:
        for i in range(20):
            doc_id = f"{kind}_{i:02d}"
            candidates.append({"doc_id": doc_id, "year": 1975})
            path = tmp_path / "text" / f"{doc_id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record(doc_id, kind)), encoding="utf-8")
    (tmp_path / "candidates.jsonl").write_text("\n".join(json.dumps(c) for c in candidates), encoding="utf-8")
    (tmp_path / "pdf_manifest.jsonl").write_text(
        json.dumps({"doc_id": "explicit_01", "status": "ok"}) + "\n"
        + json.dumps({"doc_id": "explicit_01", "status": "extraction_failed"}) + "\n", encoding="utf-8")
    dev = tmp_path / "dev.json"
    dev.write_text(json.dumps({"documents": []}), encoding="utf-8")
    key = v.make_sheets(tmp_path, seed=3, dev_path=dev, out=lambda _: None)
    drawn = {i["doc_id"] for i in key["sample"] + key["calibration"]}
    assert "explicit_01" not in drawn and key["excluded_failed_pdfs"] == ["explicit_01"]
    assert key["population"]["explicit"] == 19


def test_pool_summary_aggregates_only(tmp_path: Path) -> None:
    candidates = []
    for kind in BODIES:
        for i in range(3):
            doc_id = f"{kind}_{i}"
            candidates.append({"doc_id": doc_id, "year": 1975 if i else 2015})
            path = tmp_path / "text" / f"{doc_id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record(doc_id, kind)), encoding="utf-8")
    (tmp_path / "candidates.jsonl").write_text("\n".join(json.dumps(c) for c in candidates), encoding="utf-8")
    dev = tmp_path / "dev.json"
    dev.write_text(json.dumps({"documents": [{"doc_id": "explicit_0"}]}), encoding="utf-8")
    summary = v.pool_summary(tmp_path, dev_path=dev)
    assert summary["extracted"] == 15
    assert summary["strata_all"] == {s: 3 for s in v.STRATA}
    assert summary["strata_eligible_excluding_dev"]["explicit"] == 2
    assert summary["in_scope_by_group_and_era"]["302"]["total"] == summary["in_scope_primary"]
    assert "doc_id" not in json.dumps(summary)


def test_wilson_hand_computed() -> None:
    assert v.wilson(1, 2) == [0.0945, 0.9055]
    assert v.wilson(1, 1) == [0.2065, 1.0]
    assert v.wilson(8, 10) == [0.4902, 0.9433]
    assert v.wilson(0, 10) == [0.0, 0.2775]
    assert v.wilson(0, 0) is None


def test_stratified_bootstrap_seeded_fixed_weights_and_undefined() -> None:
    population = {"explicit": 70, "implicit_only": 30}
    stat = lambda g: v._weighted_pr(g, population)  # noqa: E731
    mixed = {"explicit": [(True, True)] * 12 + [(True, False)] * 3,
             "implicit_only": [(True, True)] * 10 + [(False, True)] * 2}
    first = v.stratified_bootstrap(mixed, stat, seed=11, resamples=2000)
    assert first == v.stratified_bootstrap(mixed, stat, seed=11, resamples=2000)
    # weights 70/15 and 30/12: TP 56 + 25, FP 14 -> 81 / 95
    point = stat(mixed)["precision"]
    assert round(point, 4) == round(81 / 95, 4)
    lo, hi = first["precision"]["ci"]
    assert lo < point < hi and hi <= 1.0
    # Homogeneous strata: every replicate equals the point, so weights really stay fixed.
    pure = {"explicit": [(True, True)] * 15, "implicit_only": [(True, False)] * 12}
    assert v.stratified_bootstrap(pure, stat, seed=1, resamples=200)["precision"]["ci"] == [0.7, 0.7]
    # Undefined replicates are dropped and counted: precision is None when no draw is predicted positive.
    sparse = {"explicit": [(True, True), (False, True)]}
    out = v.stratified_bootstrap(sparse, stat, seed=3, resamples=400)
    assert 0 < out["precision"]["undefined_replicates"] < 400
    assert out["recall"]["undefined_replicates"] == 0


def test_split_accuracy_intervals() -> None:
    items = [{"doc_id": f"s{i}", "stratum": "weak_split" if i < 4 else "explicit"} for i in range(10)]
    gold = {f"s{i}": {"split_correct": "no" if i in (0, 1) else "yes"} for i in range(10)}
    out = v.split_accuracy(items, gold, seed=5, resamples=2000)
    assert out["accuracy"] == 0.8
    lo, hi = out["accuracy_ci"]
    assert lo < 0.8 < hi
    assert out["per_stratum"]["weak_split"] == 0.5 and out["per_stratum_ci"]["weak_split"] == v.wilson(2, 4)
    assert out["per_stratum_ci"]["collision"] is None
