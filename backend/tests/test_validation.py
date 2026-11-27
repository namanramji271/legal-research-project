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


def test_gold_views() -> None:
    assert v.gold_in_scope({"in_scope": "no", "section_as_charge": "yes"}) is False
    assert v.gold_in_scope({"in_scope": "no", "section_as_charge": "yes"}, "loose") is True
    assert v.gold_in_scope({"in_scope": "unsure", "section_as_charge": "yes"}, "loose") is True
    assert v.gold_in_scope({"in_scope": "unsure", "section_as_charge": "no"}, "loose") is None
    with pytest.raises(ValueError):
        v.gold_in_scope({"in_scope": "yes"}, "other")


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


def lab(scope: str, charge: str = "no", split: str = "yes", sections: str = "") -> dict:
    return {"in_scope": scope, "section_as_charge": charge, "sections": set(sections.split(";")) - {""},
            "split_correct": split}


def option_b_key() -> dict:
    """5 explicit (detector yes) + 5 rejected_flagged (detector no); human subset e0, e1, r0, r1."""
    sample = ([{"doc_id": f"e{i}", "stratum": "explicit", "primary_sections": ["302"], "loose_sections": ["302"]}
               for i in range(5)]
              + [{"doc_id": f"r{i}", "stratum": "rejected_flagged", "primary_sections": [], "loose_sections": []}
                 for i in range(5)])
    return {"seed": 1, "population": {"explicit": 50, "rejected_flagged": 50}, "quotas": v.QUOTAS,
            "sample": sample, "human_subset": ["e0", "e1", "r0", "r1"], "human_subset_seed": 3}


def option_b_labels() -> tuple[dict, dict]:
    llm = {f"e{i}": lab("yes", sections="302") for i in range(5)} | {f"r{i}": lab("no") for i in range(5)}
    human = {d: dict(llm[d]) for d in ("e0", "e1", "r0", "r1")}
    return llm, human


def log_row(doc_id: str, field: str, human_blind: str, llm: str, final: str, note: str = "") -> dict:
    return {"doc_id": doc_id, "field": field, "human_blind": human_blind, "llm": llm, "final": final, "note": note}


def as_rows(labels: dict) -> dict:
    return {d: (x["in_scope"], x["section_as_charge"], ";".join(sorted(x["sections"])), x["split_correct"])
            for d, x in labels.items()}


def test_score_option_b_accepted_uses_llm_gold_for_the_rest() -> None:
    key = option_b_key()
    llm, human = option_b_labels()
    result = v.score(key, llm, human, human, [], resamples=200)
    assert result["agreement_llm_vs_human"]["in_scope"] == {"kappa": 1.0, "raw_agreement": 1.0}
    assert result["llm_accepted_as_annotator"] is True
    assert result["gold_sources"] == {"adjudicated_human": 4, "human_rest": 0, "llm": 6, "unused_pending_human": 0}
    assert result["main"]["documents"] == 10 and result["sensitivity_human_25"]["documents"] == 4
    assert result["sensitivity_human_25"]["per_stratum_n"]["explicit"] == 2
    assert result["main"]["primary"]["pooled_weighted"]["precision"] == 1.0
    assert result["checks"] == {"kappa": True, "weighted_precision": True, "split_accuracy": True}
    assert result["verdict"] == "ACCEPTED"


def test_score_option_b_kappa_missed_is_incomplete_and_human_wins() -> None:
    key = option_b_key()
    llm, human = option_b_labels()
    human["e1"] = lab("no")  # LLM yes / human no
    human["r1"] = lab("yes", sections="302")  # LLM no / human yes
    log = [log_row("e1", "in_scope", "no", "yes", "no", "kept"), log_row("r1", "in_scope", "yes", "no", "yes")]
    result = v.score(key, llm, human, human, log, resamples=200)
    # llm y,y,n,n vs human y,n,n,y: p_o 0.5, p_e 0.5 -> kappa 0
    assert result["agreement_llm_vs_human"]["in_scope"]["kappa"] == 0.0
    assert result["llm_accepted_as_annotator"] is False and result["checks"]["kappa"] is False
    assert result["gold_sources"] == {"adjudicated_human": 4, "human_rest": 0, "llm": 0, "unused_pending_human": 6}
    assert result["main"]["documents"] == 4  # the other 30 (here 6) are not used
    assert result["main"]["primary"]["per_stratum"]["explicit"]["fp"] == 1  # human label (no) won
    assert result["adjudication"]["disagreements"]["in_scope"] == 2
    assert result["adjudication"]["changed_from_blind_human"]["in_scope"] == 0
    assert result["verdict"].startswith("INCOMPLETE") and "6 documents await human labels" in result["verdict"]
    report = v.render_report(result, key)
    assert "Provisional (25 only)" in report and "INCOMPLETE" in report


def test_adjudication_is_enforced() -> None:
    key = option_b_key()
    llm, human = option_b_labels()
    human["e1"] = lab("yes", split="no", sections="302")  # disagreement on split_correct only
    with pytest.raises(ValueError, match="e1 split_correct.*no log row"):
        v.score(key, llm, human, human, [], resamples=10)
    # The human may adopt the LLM label after reading its reason, but only with a log row.
    adopted = {**human, "e1": lab("yes", sections="302")}
    log = [log_row("e1", "split_correct", "no", "yes", "yes", "LLM reason convincing")]
    result = v.score(key, llm, human, adopted, log, resamples=10)
    assert result["adjudication"]["changed_from_blind_human"]["split_correct"] == 1
    with pytest.raises(ValueError, match="does not match sheets"):
        v.score(key, llm, human, human, log, resamples=10)  # log says final yes, adjudicated says no
    silent = {**human, "e0": lab("no")}  # agreed label changed without a log row
    with pytest.raises(ValueError, match="e0 in_scope: adjudicated 'no' differs"):
        v.score(key, llm, human, silent, [log_row("e1", "split_correct", "no", "yes", "no")], resamples=10)
    with pytest.raises(ValueError, match="not in the human subset"):
        v.score(key, llm, human, human, [log_row("e4", "in_scope", "yes", "yes", "yes")], resamples=10)


def test_score_requires_subset_and_labels() -> None:
    key = option_b_key()
    llm, human = option_b_labels()
    with pytest.raises(ValueError, match="no human_subset"):
        v.score({**key, "human_subset": []}, llm, human, human, [], resamples=10)
    del llm["r4"]
    with pytest.raises(ValueError, match="llm:r4"):
        v.score(key, llm, human, human, [], resamples=10)


def test_score_cli_and_report_disclosure(tmp_path: Path) -> None:
    key = option_b_key()
    llm, human = option_b_labels()
    target = tmp_path / "validation"
    target.mkdir()
    (target / "validation_key.json").write_text(json.dumps(key), encoding="utf-8")
    write_labels(tmp_path / "llm.csv", as_rows(llm))
    write_labels(tmp_path / "human.csv", as_rows(human))
    write_labels(tmp_path / "adj.csv", as_rows(human))
    (tmp_path / "log.csv").write_text(",".join(v.LOG_COLUMNS) + "\n", encoding="utf-8")
    run = {"models": ["claude-sonnet-5-5"], "requested_model": "claude-sonnet-5-5",
           "prompt_template": "backend/corpus/llm_label_prompt.md", "prompt_sha256": "ab" * 32,
           "cli_version": "2.1.332 (Claude Code)", "dates": ["2026-11-26"]}
    (target / "llm_run.json").write_text(json.dumps(run), encoding="utf-8")
    assert v.main(["--work-dir", str(tmp_path), "score", "--llm", str(tmp_path / "llm.csv"), "--human",
                   str(tmp_path / "human.csv"), "--adjudicated", str(tmp_path / "adj.csv"),
                   "--log", str(tmp_path / "log.csv")]) == 0
    report = (target / "validation_report.md").read_text(encoding="utf-8")
    assert "claude-sonnet-5-5" in report and "ab" * 32 in report and "2026-11-26" in report
    assert "Pre-registered labels" in report and "Option B" in report and "not used to choose the rule" in report
    assert "Sensitivity analysis: the 25 human-labelled documents alone" in report
    assert "rests on few labels per stratum" in report and "8–15" in report
    assert "1.0 [1.0, 1.0]" in report and "Verdict: **ACCEPTED**" in report
    assert json.loads((target / "validation_result.json").read_text(encoding="utf-8"))["accepted"] is True
    # Without llm_run.json the disclosure says so instead of silently omitting it.
    result = v.score(key, llm, human, human, [], resamples=10)
    assert "NOT RECORDED" in v.render_report(result, key)


def test_read_log_requires_columns(tmp_path: Path) -> None:
    (tmp_path / "log.csv").write_text("doc_id,field\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        v.read_log(tmp_path / "log.csv")
    (tmp_path / "ok.csv").write_text(",".join(v.LOG_COLUMNS) + "\nE1,In_Scope,No,Yes,No,Kept as is\n",
                                     encoding="utf-8")
    # doc_id keeps its case (real ids are mixed-case); label values are lowercased.
    assert v.read_log(tmp_path / "ok.csv") == [log_row("E1", "in_scope", "no", "yes", "no", "Kept as is")]


# --- disagreements subcommand ---------------------------------------------------

def write_sheet_rows(path: Path, rows: list[dict], columns: tuple[str, ...]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for i, row in enumerate(rows, start=1):
            w.writerow({"item": i, "title": f"Title {row['doc_id']}", "citation": f"Cit {row['doc_id']}",
                        "pdf_url": f"https://example.test/{row['doc_id']}.pdf",
                        "body_starts_with": "SECRET JUDGMENT TEXT", **row})


def disagreement_sheets(tmp_path: Path) -> tuple[Path, Path]:
    human = [
        {"doc_id": "h1", "in_scope": "yes", "section_as_charge": "no", "split_correct": "yes",
         "sections_at_issue": "302", "notes": "clear conviction"},          # agrees
        {"doc_id": "h2", "in_scope": "unsure", "section_as_charge": "no", "split_correct": "yes",
         "sections_at_issue": "", "notes": "hard"},                         # unsure vs no
        {"doc_id": "h3", "in_scope": "no", "section_as_charge": "yes", "split_correct": "yes",
         "sections_at_issue": "304", "notes": "bail"},                      # charge only
        {"doc_id": "h4", "in_scope": "yes", "section_as_charge": "no", "split_correct": "no",
         "sections_at_issue": "300", "notes": ""},                          # split only
    ]
    llm = [
        {"doc_id": "other", "in_scope": "no", "section_as_charge": "no", "split_correct": "yes", "reason": "x"},
        {"doc_id": "h4", "in_scope": "yes", "section_as_charge": "no", "split_correct": "yes",
         "sections_at_issue": "300", "reason": "R4"},
        {"doc_id": "h3", "in_scope": "no", "section_as_charge": "no", "split_correct": "yes",
         "sections_at_issue": "", "reason": "R3"},
        {"doc_id": "h2", "in_scope": "no", "section_as_charge": "no", "split_correct": "yes",
         "sections_at_issue": "", "reason": "R2"},
        {"doc_id": "h1", "in_scope": "yes", "section_as_charge": "no", "split_correct": "yes",
         "sections_at_issue": "302", "reason": "R1"},
    ]
    write_sheet_rows(tmp_path / "human.csv", human, v.SHEET_COLUMNS)
    write_sheet_rows(tmp_path / "llm.csv", llm, v.SHEET_COLUMNS + ("reason",))
    return tmp_path / "llm.csv", tmp_path / "human.csv"


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def test_disagreements_writes_review_copy_and_log(tmp_path: Path) -> None:
    llm_path, human_path = disagreement_sheets(tmp_path)
    out_dir, printed = tmp_path / "adj", []
    summary = v.write_disagreements(llm_path, human_path, out_dir, printed.append)
    assert summary == {"in_scope": 1, "section_as_charge": 1, "split_correct": 1}

    header, review = read_csv(out_dir / v.REVIEW_FILE)
    assert tuple(header) == v.REVIEW_COLUMNS
    assert not {"doc_id", "stratum", "body_starts_with"} & set(header)
    assert "SECRET" not in (out_dir / v.REVIEW_FILE).read_text(encoding="utf-8")
    assert [(r["item"], r["field"]) for r in review] == [("2", "in_scope"), ("3", "section_as_charge"),
                                                         ("4", "split_correct")]
    r2 = review[0]
    assert (r2["title"], r2["citation"], r2["pdf_url"]) == ("Title h2", "Cit h2", "https://example.test/h2.pdf")
    assert (r2["human_in_scope"], r2["llm_in_scope"], r2["human_notes"], r2["llm_reason"]) == \
        ("unsure", "no", "hard", "R2")
    assert (review[1]["human_section_as_charge"], review[1]["llm_section_as_charge"],
            review[1]["human_sections_at_issue"], review[1]["llm_reason"]) == ("yes", "no", "304", "R3")

    header, log = read_csv(out_dir / v.LOG_FILE)
    assert tuple(header) == v.LOG_COLUMNS
    assert [(r["doc_id"], r["field"], r["human_blind"], r["llm"], r["final"], r["note"]) for r in log] == [
        ("h2", "in_scope", "unsure", "no", "", ""), ("h3", "section_as_charge", "yes", "no", "", ""),
        ("h4", "split_correct", "no", "yes", "", "")]

    assert (out_dir / v.ADJUDICATED_FILE).read_bytes() == human_path.read_bytes()
    text = "\n".join(printed)
    assert printed[0].startswith("Disagreements: 3 ")
    assert all(str(out_dir / name) in text for name in (v.REVIEW_FILE, v.ADJUDICATED_FILE, v.LOG_FILE))
    assert "unsure" not in text and "h2" not in text and "R2" not in text


def test_disagreements_log_feeds_check_adjudication(tmp_path: Path) -> None:
    llm_path, human_path = disagreement_sheets(tmp_path)
    out_dir = tmp_path / "adj"
    v.write_disagreements(llm_path, human_path, out_dir, lambda _: None)
    llm, human = v.read_labels(llm_path), v.read_labels(human_path)
    adjudicated = v.read_labels(out_dir / v.ADJUDICATED_FILE)
    subset = list(human)
    with pytest.raises(ValueError, match="does not match sheets"):  # final left empty: incomplete
        v.check_adjudication(subset, llm, human, adjudicated, v.read_log(out_dir / v.LOG_FILE))
    _, rows = read_csv(out_dir / v.LOG_FILE)
    for r in rows:
        r["final"], r["note"] = r["human_blind"], "kept the human label"
    with (out_dir / v.LOG_FILE).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=v.LOG_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    result = v.check_adjudication(subset, llm, human, adjudicated, v.read_log(out_dir / v.LOG_FILE))
    assert result["disagreements"] == {"in_scope": 1, "section_as_charge": 1, "split_correct": 1}


def test_disagreements_guards(tmp_path: Path) -> None:
    llm_path, human_path = disagreement_sheets(tmp_path)
    with pytest.raises(ValueError, match="outside the repository"):
        v.write_disagreements(llm_path, human_path, v.REPO_DIR / "backend" / "tmp_adj", lambda _: None)
    assert not (v.REPO_DIR / "backend" / "tmp_adj").exists()

    out_dir = tmp_path / "adj"
    v.write_disagreements(llm_path, human_path, out_dir, lambda _: None)
    with pytest.raises(ValueError, match="refusing to overwrite"):
        v.write_disagreements(llm_path, human_path, out_dir, lambda _: None)

    write_sheet_rows(tmp_path / "llm_short.csv",
                     [{"doc_id": "h1", "in_scope": "yes", "section_as_charge": "no", "reason": "r"}],
                     v.SHEET_COLUMNS + ("reason",))
    with pytest.raises(ValueError, match="missing 3 of the human-labelled documents"):
        v.write_disagreements(tmp_path / "llm_short.csv", human_path, tmp_path / "adj2", lambda _: None)

    write_labels(tmp_path / "bad.csv", {"h1": ("maybe", "no", "", "")})
    with pytest.raises(ValueError, match="yes/no/unsure"):
        v.write_disagreements(llm_path, tmp_path / "bad.csv", tmp_path / "adj3", lambda _: None)
    assert not (tmp_path / "adj2").exists() and not (tmp_path / "adj3").exists()


def test_disagreements_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    llm_path, human_path = disagreement_sheets(tmp_path)
    assert v.main(["disagreements", "--llm", str(llm_path), "--human", str(human_path),
                   "--out-dir", str(tmp_path / "adj")]) == 0
    printed = capsys.readouterr().out
    assert "Disagreements: 3 (in_scope 1, section_as_charge 1, split_correct 1)" in printed
    assert (tmp_path / "adj" / v.LOG_FILE).is_file()


# --- apply-adjudication ----------------------------------------------------------

def adjudication_paths(tmp_path: Path, llm_path: Path, human_path: Path) -> dict[str, Path]:
    adj = tmp_path / "adj"
    v.write_disagreements(llm_path, human_path, adj, lambda _: None)
    return {"llm": llm_path, "human": human_path, "dir": adj, "review": adj / "adjudication_review_final.csv",
            "log": adj / v.LOG_FILE, "adjudicated": adj / v.ADJUDICATED_FILE}


def adjudication_setup(tmp_path: Path) -> dict[str, Path]:
    """Synthetic sheets -> disagreements; rows: h2 in_scope, h3 section_as_charge, h4 split_correct."""
    return adjudication_paths(tmp_path, *disagreement_sheets(tmp_path))


def rewrite_csv(path: Path, header: list[str], rows: list[dict], encoding: str = "utf-8") -> None:
    with path.open("w", newline="", encoding=encoding) as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)


def write_review_final(p: dict[str, Path], finals: list[tuple[str, str]], drop: int = 0) -> None:
    """Review + final/note, item blanked, saved as Excel would (utf-8 with BOM)."""
    header, rows = read_csv(p["dir"] / v.REVIEW_FILE)
    rows = rows[: len(rows) - drop]
    rewrite_csv(p["review"], header + ["final", "note"],
                [{**row, "item": "", "final": final, "note": note} for row, (final, note) in zip(rows, finals)],
                encoding="utf-8-sig")


def apply(p: dict[str, Path], printed: list[str] | None = None) -> dict:
    sink = printed if printed is not None else []
    return v.apply_adjudication(p["review"], p["log"], p["adjudicated"], p["human"], p["llm"], sink.append)


def snapshot(p: dict[str, Path]) -> dict[str, bytes]:
    return {k: p[k].read_bytes() for k in ("log", "adjudicated")}


def bak(path: Path) -> Path:
    return path.with_name(path.name + ".bak")


GOOD_FINALS = [("No", "LLM right: acquittal only"), ("yes", "kept"), ("yes", "split is fine")]


def test_apply_adjudication_fills_log_and_changes_only_target_cells(tmp_path: Path) -> None:
    p = adjudication_setup(tmp_path)
    p["adjudicated"].write_bytes(b"\xef\xbb\xbf" + p["adjudicated"].read_bytes())  # BOM must survive
    before = snapshot(p)
    write_review_final(p, GOOD_FINALS)
    printed: list[str] = []
    assert apply(p, printed) == {"applied": 3, "changed": 2, "check_passed": True}
    assert printed == ["Applied 3 rows; 2 labels changed; check_adjudication: passed"]

    assert {k: bak(p[k]).read_bytes() for k in ("log", "adjudicated")} == before
    after = p["adjudicated"].read_bytes()
    assert after.startswith(b"\xef\xbb\xbf") and b"\r\n" in after
    _, old_rows = read_csv(p["human"])
    _, new_rows = read_csv(p["adjudicated"])
    diffs = {(o["doc_id"], k): (o[k], n[k]) for o, n in zip(old_rows, new_rows) for k in o if o[k] != n[k]}
    assert diffs == {("h2", "in_scope"): ("unsure", "no"), ("h4", "split_correct"): ("no", "yes")}

    _, log = read_csv(p["log"])
    assert [(r["final"], r["note"]) for r in log] == [("no", "LLM right: acquittal only"), ("yes", "kept"),
                                                      ("yes", "split is fine")]
    v.check_adjudication(["h1", "h2", "h3", "h4"], v.read_labels(p["llm"]), v.read_labels(p["human"]),
                         v.read_labels(p["adjudicated"]), v.read_log(p["log"]))


ABORT_CASES = [
    ("count", "has 2 rows but"),
    ("pair", r"row 2: log field/human_blind/llm do not match the review row"),
    ("human_blind", r"row 1: log human_blind does not match the blind human sheet"),
    ("empty_final", r"\[2\]"),
    ("bad_final", r"\[3\]"),
    ("empty_note", r"\[1\]"),
    ("bak", "refusing to overwrite existing backups"),
    ("edited", r"already differs from the blind human sheet for: \['h1'\]"),
    ("unknown_doc", r"doc_ids not present exactly once: \['h3'\]"),
]


@pytest.mark.parametrize("case, match", ABORT_CASES)
def test_apply_adjudication_aborts_without_changes(tmp_path: Path, case: str, match: str) -> None:
    p = adjudication_setup(tmp_path)
    finals = list(GOOD_FINALS)
    if case == "empty_final":
        finals[1] = ("", "note")
    if case == "bad_final":
        finals[2] = ("unsure", "split_correct has no unsure")
    if case == "empty_note":
        finals[0] = ("no", " ")
    write_review_final(p, finals, drop=1 if case == "count" else 0)
    if case in ("pair", "human_blind"):
        header, rows = read_csv(p["review"])
        if case == "pair":
            rows[1]["llm_section_as_charge"] = "yes"
        else:  # log and review agree with each other, but not with the blind human sheet
            rows[0]["human_in_scope"] = "yes"
            log_header, log_rows = read_csv(p["log"])
            log_rows[0]["human_blind"] = "yes"
            rewrite_csv(p["log"], log_header, log_rows)
        rewrite_csv(p["review"], header, rows, encoding="utf-8-sig")
    if case == "bak":
        bak(p["adjudicated"]).write_text("old", encoding="utf-8")
    if case in ("edited", "unknown_doc"):
        header, rows = read_csv(p["adjudicated"])
        if case == "edited":
            rows[0]["in_scope"] = "no"  # h1: hand-edited before applying
        else:
            rows = [r for r in rows if r["doc_id"] != "h3"]
        rewrite_csv(p["adjudicated"], header, rows)
    before = snapshot(p)
    with pytest.raises(ValueError, match=match):
        apply(p)
    assert snapshot(p) == before
    assert not bak(p["log"]).exists()


def test_apply_adjudication_rejects_inconsistent_result(tmp_path: Path) -> None:
    human = [{"doc_id": "h5", "in_scope": "no", "section_as_charge": "yes", "split_correct": "yes", "notes": ""}]
    llm = [{"doc_id": "h5", "in_scope": "yes", "section_as_charge": "no", "split_correct": "yes", "reason": "R"}]
    write_sheet_rows(tmp_path / "human.csv", human, v.SHEET_COLUMNS)
    write_sheet_rows(tmp_path / "llm.csv", llm, v.SHEET_COLUMNS + ("reason",))
    p = adjudication_paths(tmp_path, tmp_path / "llm.csv", tmp_path / "human.csv")
    write_review_final(p, [("yes", "court decides 302"), ("yes", "also charge")])  # yes + yes: not allowed
    before = snapshot(p)
    with pytest.raises(ValueError, match=r"break the label rules for: \['h5'\]"):
        apply(p)
    assert snapshot(p) == before
    assert not bak(p["log"]).exists()


def test_apply_adjudication_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = adjudication_setup(tmp_path)
    write_review_final(p, GOOD_FINALS)
    assert v.main(["apply-adjudication", "--review-final", str(p["review"]), "--log", str(p["log"]),
                   "--adjudicated", str(p["adjudicated"]), "--human", str(p["human"]), "--llm", str(p["llm"])]) == 0
    assert capsys.readouterr().out.strip() == "Applied 3 rows; 2 labels changed; check_adjudication: passed"


def test_readers_ignore_a_bom(tmp_path: Path) -> None:
    _, human_path = disagreement_sheets(tmp_path)
    bom_path = tmp_path / "human_bom.csv"
    bom_path.write_bytes(b"\xef\xbb\xbf" + human_path.read_bytes())
    assert v.read_labels(bom_path) == v.read_labels(human_path)
    rows = v._raw_rows(bom_path)
    assert list(rows["h2"])[0] == "item" and rows["h2"]["item"] == "2"
    log_text = ",".join(v.LOG_COLUMNS) + "\nh2,in_scope,unsure,no,no,n\n"
    (tmp_path / "log.csv").write_bytes(b"\xef\xbb\xbf" + log_text.encode("utf-8"))
    assert v.read_log(tmp_path / "log.csv")[0]["doc_id"] == "h2"


# --- mixed-case doc_ids (real ids look like S_2004_3_785_791) ---------------------

MIXED_IDS = ("S_2004_3_785_791", "S_1999_1_10_20", "lower_id")


def mixed_case_sheets(tmp_path: Path) -> tuple[Path, Path]:
    """Disagreements: S_2004... in_scope (yes vs no), S_1999... section_as_charge (yes vs no); lower_id agrees."""
    human = [
        {"doc_id": "S_2004_3_785_791", "in_scope": "yes", "section_as_charge": "no", "split_correct": "yes"},
        {"doc_id": "S_1999_1_10_20", "in_scope": "no", "section_as_charge": "yes", "split_correct": "yes"},
        {"doc_id": "lower_id", "in_scope": "yes", "section_as_charge": "no", "split_correct": "yes"},
    ]
    llm = [
        {"doc_id": "lower_id", "in_scope": "yes", "section_as_charge": "no", "split_correct": "yes", "reason": "a"},
        {"doc_id": "S_1999_1_10_20", "in_scope": "no", "section_as_charge": "no", "split_correct": "yes",
         "reason": "b"},
        {"doc_id": "S_2004_3_785_791", "in_scope": "no", "section_as_charge": "no", "split_correct": "yes",
         "reason": "c"},
    ]
    write_sheet_rows(tmp_path / "human.csv", human, v.SHEET_COLUMNS)
    write_sheet_rows(tmp_path / "llm.csv", llm, v.SHEET_COLUMNS + ("reason",))
    return tmp_path / "llm.csv", tmp_path / "human.csv"


MIXED_FINALS = [("no", "LLM right"), ("yes", "kept")]


def test_read_log_and_check_adjudication_keep_doc_id_case(tmp_path: Path) -> None:
    text = ",".join(v.LOG_COLUMNS) + "\nS_2004_3_785_791,IN_SCOPE,Yes,NO,No,Note Kept\n"
    (tmp_path / "log.csv").write_text(text, encoding="utf-8")
    log = v.read_log(tmp_path / "log.csv")
    assert log == [log_row("S_2004_3_785_791", "in_scope", "yes", "no", "no", "Note Kept")]
    subset = list(MIXED_IDS)
    human = {d: lab("yes") for d in subset}
    llm = {**human, "S_2004_3_785_791": lab("no")}
    adjudicated = {**human, "S_2004_3_785_791": lab("no")}
    result = v.check_adjudication(subset, llm, human, adjudicated, log)
    assert result["disagreements"]["in_scope"] == 1 and result["changed_from_blind_human"]["in_scope"] == 1


def test_apply_adjudication_with_mixed_case_doc_ids(tmp_path: Path) -> None:
    p = adjudication_paths(tmp_path, *mixed_case_sheets(tmp_path))
    _, log = read_csv(p["log"])
    assert [r["doc_id"] for r in log] == ["S_2004_3_785_791", "S_1999_1_10_20"]
    write_review_final(p, MIXED_FINALS)
    printed: list[str] = []
    assert apply(p, printed) == {"applied": 2, "changed": 1, "check_passed": True}
    assert printed == ["Applied 2 rows; 1 labels changed; check_adjudication: passed"]
    assert v.read_labels(p["adjudicated"])["S_2004_3_785_791"]["in_scope"] == "no"


def test_score_path_with_mixed_case_doc_ids(tmp_path: Path) -> None:
    """disagreements -> apply-adjudication -> score, all through the CLI on mixed-case ids."""
    llm_path, human_path = mixed_case_sheets(tmp_path)
    adj = tmp_path / "adj"
    assert v.main(["disagreements", "--llm", str(llm_path), "--human", str(human_path), "--out-dir", str(adj)]) == 0
    p = {"dir": adj, "review": adj / "adjudication_review_final.csv"}
    write_review_final(p, MIXED_FINALS)
    assert v.main(["apply-adjudication", "--review-final", str(p["review"]), "--log", str(adj / v.LOG_FILE),
                   "--adjudicated", str(adj / v.ADJUDICATED_FILE), "--human", str(human_path),
                   "--llm", str(llm_path)]) == 0
    sample = [{"doc_id": "S_2004_3_785_791", "stratum": "explicit", "primary_sections": ["302"],
               "loose_sections": ["302"]},
              {"doc_id": "S_1999_1_10_20", "stratum": "rejected_flagged", "primary_sections": [],
               "loose_sections": []},
              {"doc_id": "lower_id", "stratum": "explicit", "primary_sections": ["302"], "loose_sections": ["302"]}]
    key = {"seed": 1, "population": {"explicit": 20, "rejected_flagged": 10}, "quotas": v.QUOTAS,
           "sample": sample, "human_subset": list(MIXED_IDS), "human_subset_seed": 3}
    work = tmp_path / "work"
    (work / "validation").mkdir(parents=True)
    (work / "validation" / "validation_key.json").write_text(json.dumps(key), encoding="utf-8")
    assert v.main(["--work-dir", str(work), "score", "--llm", str(llm_path), "--human", str(human_path),
                   "--adjudicated", str(adj / v.ADJUDICATED_FILE), "--log", str(adj / v.LOG_FILE)]) == 0
    result = json.loads((work / "validation" / "validation_result.json").read_text(encoding="utf-8"))
    assert result["adjudication"]["disagreements"] == {"in_scope": 1, "section_as_charge": 1, "split_correct": 0}
    assert result["adjudication"]["changed_from_blind_human"]["in_scope"] == 1
    assert result["adjudication"]["logged_rows"] == 2


# --- the other 30: human-sheet-rest and score(human_rest) --------------------------

import hashlib  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

SCORED_AT = "2026-11-27T10:00:00+00:00"


def rest_work_dir(tmp_path: Path, result: dict | None = None) -> dict:
    """A synthetic work dir with a 55 + 25 key and a kappa-missed validation_result.json."""
    candidates = []
    for kind in BODIES:
        for i in range(20):
            doc_id = f"{kind}_{i:02d}"
            candidates.append({"doc_id": doc_id, "year": 1975, "title": f"T {doc_id}", "citation": "C",
                               "pdf_url": f"https://example.test/{doc_id}.pdf"})
            path = tmp_path / "text" / f"{doc_id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record(doc_id, kind)), encoding="utf-8")
    (tmp_path / "candidates.jsonl").write_text("\n".join(json.dumps(c) for c in candidates), encoding="utf-8")
    dev = tmp_path / "dev.json"
    dev.write_text(json.dumps({"documents": []}), encoding="utf-8")
    key = v.make_sheets(tmp_path, seed=3, dev_path=dev, out=lambda _: None)
    if result is None:
        result = {"llm_accepted_as_annotator": False,
                  "agreement_llm_vs_human": {"in_scope": {"kappa": 0.41, "raw_agreement": 0.72}},
                  "scored_at": SCORED_AT}
    (tmp_path / "validation" / "validation_result.json").write_text(json.dumps(result), encoding="utf-8")
    return key


def rest_paths(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "validation" / v.HUMAN_REST_SHEET, tmp_path / "validation" / "validation_key.json"


def test_human_rest_sheet_written_blind_seeded_and_recorded(tmp_path: Path) -> None:
    key0 = rest_work_dir(tmp_path / "a")
    printed: list[str] = []
    key = v.make_human_rest_sheet(tmp_path / "a", out=printed.append)
    sheet, key_path = rest_paths(tmp_path / "a")
    assert printed == [f"Wrote {sheet}: 30 documents"]

    header, rows = read_csv(sheet)
    assert tuple(header) == v.HUMAN_REST_COLUMNS
    assert "passing_sections" not in header and "stratum" not in header and "reason" not in header
    rest = [i["doc_id"] for i in key0["sample"] if i["doc_id"] not in set(key0["human_subset"])]
    assert len(rows) == 30 and {r["doc_id"] for r in rows} == set(rest)
    assert [r["item"] for r in rows] == [str(i) for i in range(1, 31)]
    fill = ("in_scope", "section_as_charge", "sections_at_issue", "split_correct", "notes")
    assert all(r[c] == "" for r in rows for c in fill)
    texts = {d: json.loads((tmp_path / "a" / "text" / f"{d}.json").read_text(encoding="utf-8")) for d in rest}
    assert all(r["body_starts_with"] == v._body_start(texts[r["doc_id"]]) for r in rows)
    assert all(r["title"] == f"T {r['doc_id']}" and r["pdf_url"].endswith(f"{r['doc_id']}.pdf") for r in rows)
    # Shuffled: neither key order nor grouped by stratum.
    order = [r["doc_id"] for r in rows]
    assert order != rest and order != sorted(rest)
    strata = {i["doc_id"]: i["stratum"] for i in key0["sample"]}
    assert len({strata[d] for d in order[:6]}) > 1

    # Recorded in the key; sample and human subset untouched.
    saved = json.loads(key_path.read_text(encoding="utf-8"))
    assert saved == key
    assert saved["sample"] == key0["sample"] and saved["human_subset"] == key0["human_subset"]
    assert saved["human_rest"] == sorted(rest) and saved["human_rest_seed"] == 3 + v.HUMAN_REST_SEED_OFFSET == 6
    assert saved["human_rest_sheet_sha256"] == hashlib.sha256(sheet.read_bytes()).hexdigest()
    assert saved["human_rest_text_sha256"] == {
        d: hashlib.sha256((tmp_path / "a" / "text" / f"{d}.json").read_bytes()).hexdigest() for d in rest}
    assert saved["human_rest_basis"] == {"llm_accepted_as_annotator": False, "kappa": 0.41, "scored_at": SCORED_AT}
    assert datetime.fromisoformat(saved["human_rest_created_at"]).tzinfo is not None

    # Same inputs elsewhere -> byte-identical sheet (seeded).
    rest_work_dir(tmp_path / "b")
    v.make_human_rest_sheet(tmp_path / "b", out=lambda _: None)
    assert rest_paths(tmp_path / "b")[0].read_bytes() == sheet.read_bytes()


def test_human_rest_sheet_snapshot_guard(tmp_path: Path) -> None:
    rest_work_dir(tmp_path)
    key = v.make_human_rest_sheet(tmp_path, out=lambda _: None)
    sheet, key_path = rest_paths(tmp_path)
    original = sheet.read_bytes()

    printed: list[str] = []
    v.make_human_rest_sheet(tmp_path, out=printed.append)  # rerun: no-op
    assert sheet.read_bytes() == original and printed == [f"{sheet} already written; unchanged"]

    filled = original.replace(b",,,,,\r\n", b",yes,no,302,yes,\r\n", 1)  # annotator filled it in
    sheet.write_bytes(filled)
    v.make_human_rest_sheet(tmp_path, out=lambda _: None)  # never overwritten
    assert sheet.read_bytes() == filled

    sheet.unlink()  # lost before labelling: regenerated byte-identically from the same text
    v.make_human_rest_sheet(tmp_path, out=lambda _: None)
    assert sheet.read_bytes() == original

    d = key["human_rest"][0]  # a later re-extraction must not change what the annotator sees
    text = tmp_path / "text" / f"{d}.json"
    text.write_text(json.dumps({**json.loads(text.read_text(encoding="utf-8")), "body": "RE-SPLIT"}), encoding="utf-8")
    key_before = key_path.read_bytes()
    with pytest.raises(ValueError, match="re-extracted"):
        v.make_human_rest_sheet(tmp_path, out=lambda _: None)
    assert sheet.read_bytes() == original and key_path.read_bytes() == key_before


def test_human_rest_sheet_refuses_an_unrecorded_sheet(tmp_path: Path) -> None:
    rest_work_dir(tmp_path)
    sheet, _ = rest_paths(tmp_path)
    sheet.write_text("item,doc_id\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not recorded in validation_key.json"):
        v.make_human_rest_sheet(tmp_path, out=lambda _: None)
    assert sheet.read_text(encoding="utf-8") == "item,doc_id\n"


GUARD_CASES = [
    ("missing", "validation_result.json not found"),
    ({"llm_accepted_as_annotator": True, "agreement_llm_vs_human": {"in_scope": {"kappa": 0.8}},
      "scored_at": SCORED_AT}, "only after kappa missed"),
    ({"agreement_llm_vs_human": {"in_scope": {"kappa": 0.4}}, "scored_at": SCORED_AT}, "only after kappa missed"),
    ({"llm_accepted_as_annotator": False, "agreement_llm_vs_human": {"in_scope": {"kappa": None}},
      "scored_at": SCORED_AT}, "no kappa value"),
    ({"llm_accepted_as_annotator": False, "agreement_llm_vs_human": {}, "scored_at": SCORED_AT}, "no kappa value"),
    ({"llm_accepted_as_annotator": False, "agreement_llm_vs_human": {"in_scope": {"kappa": 0.4}}}, "no scored_at"),
    ("no_subset", "no human_subset"),
]


@pytest.mark.parametrize("result, match", GUARD_CASES)
def test_human_rest_sheet_protocol_guards(tmp_path: Path, result: object, match: str) -> None:
    rest_work_dir(tmp_path)
    sheet, key_path = rest_paths(tmp_path)
    result_path = tmp_path / "validation" / "validation_result.json"
    if result == "missing":
        result_path.unlink()
    elif result == "no_subset":
        key = json.loads(key_path.read_text(encoding="utf-8"))
        del key["human_subset"]
        key_path.write_text(json.dumps(key), encoding="utf-8")
    else:
        result_path.write_text(json.dumps(result), encoding="utf-8")
    key_before = key_path.read_bytes()
    with pytest.raises(ValueError, match=match):
        v.make_human_rest_sheet(tmp_path, out=lambda _: None)
    assert not sheet.exists() and key_path.read_bytes() == key_before


def rest_key() -> dict:
    """option_b_key plus a human_rest record as human-sheet-rest writes it."""
    key = option_b_key()
    rest = sorted(i["doc_id"] for i in key["sample"] if i["doc_id"] not in key["human_subset"])
    return {**key, "human_rest": rest, "human_rest_seed": 4, "human_rest_created_at": "2026-11-27T11:00:00+00:00",
            "human_rest_basis": {"llm_accepted_as_annotator": False, "kappa": 0.0, "scored_at": SCORED_AT}}


def kappa_missed_labels() -> tuple[dict, dict, list]:
    """LLM e*: yes, r*: no; blind human disagrees on e1 (no) and r1 (yes): kappa 0 on the 4."""
    llm, human = option_b_labels()
    human["e1"] = lab("no")
    human["r1"] = lab("yes", sections="302")
    log = [log_row("e1", "in_scope", "no", "yes", "no", "kept"), log_row("r1", "in_scope", "yes", "no", "yes", "kept")]
    return llm, human, log


def test_score_with_human_rest_uses_human_gold_for_all() -> None:
    key = rest_key()
    llm, human, log = kappa_missed_labels()
    rest = {d: dict(llm[d]) for d in key["human_rest"]}
    rest["r4"] = lab("no", split="no")  # one LLM-human disagreement on the 30 (split only)
    result = v.score(key, llm, human, human, log, resamples=200, human_rest=rest)
    assert result["agreement_llm_vs_human"]["in_scope"]["kappa"] == 0.0  # pre-registered 25 unchanged
    assert result["llm_accepted_as_annotator"] is False and result["checks"]["kappa"] is False
    assert result["gold_sources"] == {"adjudicated_human": 4, "human_rest": 6, "llm": 0, "unused_pending_human": 0}
    # kappa over all 10: llm y5 n5, blind human y5 n5, 8 agree -> p_o 0.8, p_e 0.5 -> 0.6
    all55 = result["agreement_llm_vs_human_all"]
    assert all55["documents"] == 10
    assert all55["in_scope"] == {"kappa": 0.6, "raw_agreement": 0.8}
    assert all55["split_correct"]["raw_agreement"] == 0.9
    assert result["human_rest_disagreements_llm_vs_human"] == {"in_scope": 0, "section_as_charge": 0,
                                                               "split_correct": 1}
    main = result["main"]
    assert main["documents"] == 10
    assert main["primary"]["per_stratum"]["explicit"] == {**main["primary"]["per_stratum"]["explicit"],
                                                          "tp": 4, "fp": 1}  # e1: human no won
    assert main["split"]["judged"] == 10 and main["split"]["accuracy"] == 0.9
    assert result["sensitivity_human_25"]["documents"] == 4
    assert result["sensitivity_blind_human_all"]["documents"] == 10
    # Inclusion misses (weighted precision 0.8), split passes: separate verdicts.
    assert result["checks"]["weighted_precision"] is False and result["checks"]["split_accuracy"] is True
    assert result["verdict_inclusion"].startswith("NOT ACCEPTED") and "fresh 55" in result["verdict_inclusion"]
    assert result["verdict_split"] == "ACCEPTED"
    assert result["verdict"] == f"Inclusion {result['verdict_inclusion']}; split ACCEPTED"
    assert result["accepted"] is False


def test_score_with_human_rest_inclusion_accepted_split_not() -> None:
    key = rest_key()
    llm, human, log = kappa_missed_labels()
    adopted = {**human, "e1": lab("yes", sections="302"), "r1": lab("no")}  # human adopts the LLM after reasons
    log = [log_row("e1", "in_scope", "no", "yes", "yes", "LLM right"),
           log_row("r1", "in_scope", "yes", "no", "no", "LLM right")]
    rest = {d: dict(llm[d]) for d in key["human_rest"]}
    rest["r3"], rest["r4"] = lab("no", split="no"), lab("no", split="no")
    result = v.score(key, llm, human, adopted, log, resamples=200, human_rest=rest)
    assert result["checks"] == {"kappa": False, "weighted_precision": True, "split_accuracy": False}
    assert result["verdict_inclusion"] == "ACCEPTED"
    assert result["verdict_split"].startswith("NOT ACCEPTED") and "split only" in result["verdict_split"]
    assert "fresh 55" not in result["verdict_split"]
    assert result["verdict"] == f"Inclusion ACCEPTED; split {result['verdict_split']}"
    # Blind-human sensitivity uses the unadjudicated 25: e1 is no there.
    blind = result["sensitivity_blind_human_all"]["primary"]["per_stratum"]["explicit"]
    assert (blind["tp"], blind["fp"]) == (4, 1)


def test_score_verdicts_without_human_rest() -> None:
    key = option_b_key()
    llm, human = option_b_labels()
    accepted = v.score(key, llm, human, human, [], resamples=50)
    assert (accepted["verdict"], accepted["verdict_inclusion"], accepted["verdict_split"]) == (
        "ACCEPTED", "ACCEPTED", "ACCEPTED")
    assert accepted["gold_sources"]["human_rest"] == 0 and accepted["agreement_llm_vs_human_all"] is None
    llm2, human2, log = kappa_missed_labels()
    incomplete = v.score(key, llm2, human2, human2, log, resamples=50)
    assert incomplete["verdict"].startswith("INCOMPLETE")
    assert incomplete["verdict_inclusion"] == incomplete["verdict_split"] == "INCOMPLETE"
    assert incomplete["sensitivity_blind_human_all"] is None


def test_score_human_rest_errors() -> None:
    key = rest_key()
    llm, human, log = kappa_missed_labels()
    rest = {d: dict(llm[d]) for d in key["human_rest"]}
    with pytest.raises(ValueError, match="missing.*r4"):
        v.score(key, llm, human, human, log, resamples=10, human_rest={d: x for d, x in rest.items() if d != "r4"})
    with pytest.raises(ValueError, match="unexpected.*e0"):
        v.score(key, llm, human, human, log, resamples=10, human_rest={**rest, "e0": lab("yes")})
    with pytest.raises(ValueError, match="no human_rest record"):
        v.score(option_b_key(), llm, human, human, log, resamples=10, human_rest=rest)
    with pytest.raises(ValueError, match="does not match the key's human_rest"):
        v.score({**key, "human_rest": key["human_rest"][:-1] + ["e0"]}, llm, human, human, log, resamples=10,
                human_rest=rest)
    llm_ok, human_ok = option_b_labels()  # kappa met: the LLM labels are gold for the rest
    with pytest.raises(ValueError, match="LLM was accepted"):
        v.score(key, llm_ok, human_ok, human_ok, [], resamples=10, human_rest=rest)


def test_report_states_the_30_and_the_clarification() -> None:
    key = rest_key()
    llm, human, log = kappa_missed_labels()
    rest = {d: dict(llm[d]) for d in key["human_rest"]}
    result = {**v.score(key, llm, human, human, log, resamples=50, human_rest=rest), "scored_at": "2026-11-28T09:00:00+00:00"}
    report = v.render_report(result, key)
    assert "Scored at 2026-11-28T09:00:00+00:00" in report
    assert "κ on the pre-registered 4 was 0.0 (< 0.7)" in report
    assert "a legally trained human then labelled the other 6 blind" in report
    assert "sheet generated 2026-11-27T11:00:00+00:00, after the scoring run of 2026-11-27T10:00:00+00:00" in report
    assert "These 6 were not adjudicated against the LLM" in report
    assert "read the LLM's reasons for the 4" in report
    assert "κ **0.6**" in report and "descriptive" in report
    assert "4 adjudicated human, 6 blind human (labelled after κ missed), 0 LLM, 0 unused" in report
    assert "Sensitivity analysis: blind human labels on all 10" in report
    assert "All 10 (adjudicated human 4 + blind human 6)" in report
    assert "Clarification of the protocol" in report and "split-only" in report
    assert f"Inclusion: **{result['verdict_inclusion']}**" in report and "Split: **ACCEPTED**" in report
    # Without the 30 the kappa-missed report stays provisional and has no such section.
    plain = {**v.score(option_b_key(), llm, human, human, log, resamples=50)}
    plain_report = v.render_report(plain, option_b_key())
    assert "Provisional (25 only)" in plain_report and "INCOMPLETE" in plain_report
    assert "labelled the other" not in plain_report and "Scored at NOT RECORDED" in plain_report


def test_score_cli_writes_scored_at_and_otherwise_score_output(tmp_path: Path) -> None:
    key = rest_key()
    llm, human, log = kappa_missed_labels()
    rest = {d: dict(llm[d]) for d in key["human_rest"]}
    target = tmp_path / "validation"
    target.mkdir()
    (target / "validation_key.json").write_text(json.dumps(key), encoding="utf-8")
    write_labels(tmp_path / "llm.csv", as_rows(llm))
    write_labels(tmp_path / "human.csv", as_rows(human))
    write_labels(tmp_path / "adj.csv", as_rows(human))
    write_labels(tmp_path / "rest.csv", as_rows(rest))
    with (tmp_path / "log.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=v.LOG_COLUMNS)
        w.writeheader()
        w.writerows(log)
    before = datetime.now(timezone.utc).replace(microsecond=0)
    assert v.main(["--work-dir", str(tmp_path), "score", "--llm", str(tmp_path / "llm.csv"), "--human",
                   str(tmp_path / "human.csv"), "--adjudicated", str(tmp_path / "adj.csv"),
                   "--log", str(tmp_path / "log.csv"), "--human-rest", str(tmp_path / "rest.csv")]) == 0
    written = json.loads((target / "validation_result.json").read_text(encoding="utf-8"))
    scored_at = datetime.fromisoformat(written.pop("scored_at"))
    assert scored_at.utcoffset().total_seconds() == 0 and before <= scored_at <= datetime.now(timezone.utc)
    direct = v.score(key, v.read_labels(tmp_path / "llm.csv"), v.read_labels(tmp_path / "human.csv"),
                     v.read_labels(tmp_path / "adj.csv"), v.read_log(tmp_path / "log.csv"),
                     human_rest=v.read_labels(tmp_path / "rest.csv"))
    assert written == json.loads(json.dumps(direct))  # only scored_at was added
    report = (target / "validation_report.md").read_text(encoding="utf-8")
    assert f"Scored at {scored_at.isoformat()}" in report
