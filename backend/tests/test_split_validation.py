"""corpus/split_validation.py: pre-registered split-only validation sheet (synthetic data)."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from corpus import split_validation as sv  # noqa: E402
from corpus import validation  # noqa: E402

JUDGE_BODY = "Prashant Kumar Mishra, J.\nLeave granted.\n2. This appeal by special leave is directed against. " * 5
NO_JUDGE_BODY = "1. Leave granted.\n2. This appeal by special leave is directed against the judgment. " * 5


def write_record(work: Path, doc_id: str, split_method: str, body: str, error: str | None = None) -> None:
    path = work / "text" / f"{doc_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"doc_id": doc_id, "error": error, "split_method": split_method,
                                "headnote": "H", "proceedings": "P", "body": body}), encoding="utf-8")


def work_dir(tmp_path: Path, judge: int = 40, no_judge: int = 14) -> tuple[Path, Path]:
    work = tmp_path / "work"
    ids = []
    for i in range(judge):
        ids.append((f"2025_1_{i}_{i}", sv.SPLIT_METHOD, JUDGE_BODY))
    for i in range(no_judge):
        ids.append((f"2024_2_{i}_{i}", sv.SPLIT_METHOD, NO_JUDGE_BODY))
    ids += [("2024_9_1_1", "jurisdiction", JUDGE_BODY),           # not changed by the rule
            ("2008_1_1_1", "jurisdiction+delivered", JUDGE_BODY),
            ("2025_9_dev", sv.SPLIT_METHOD, JUDGE_BODY),            # dev document
            ("2025_9_sample", sv.SPLIT_METHOD, JUDGE_BODY),         # one of the 55
            ("2025_9_cal", sv.SPLIT_METHOD, NO_JUDGE_BODY),         # calibration
            ("2025_9_failed", sv.SPLIT_METHOD, JUDGE_BODY)]         # failed PDF in the manifest
    for doc_id, method, body in ids:
        write_record(work, doc_id, method, body)
    write_record(work, "2025_9_error", sv.SPLIT_METHOD, JUDGE_BODY, error="data loss")
    all_ids = [d for d, _, _ in ids] + ["2025_9_error", "2025_9_no_text"]
    (work / "candidates.jsonl").write_text("\n".join(json.dumps(
        {"doc_id": d, "year": int(d[:4]), "title": f"T {d}", "citation": "C", "pdf_url": f"https://x.test/{d}.pdf"})
        for d in all_ids), encoding="utf-8")
    (work / "pdf_manifest.jsonl").write_text(json.dumps({"doc_id": "2025_9_failed", "status": "failed"}) + "\n",
                                             encoding="utf-8")
    (work / "validation").mkdir()
    (work / "validation" / "validation_key.json").write_text(json.dumps(
        {"seed": 1, "sample": [{"doc_id": "2025_9_sample", "stratum": "weak_split"}],
         "calibration": [{"doc_id": "2025_9_cal", "stratum": "weak_split"}]}), encoding="utf-8")
    (work / "validation" / validation.HUMAN_REST_SHEET).write_text("item,doc_id\n", encoding="utf-8")
    dev = tmp_path / "dev.json"
    dev.write_text(json.dumps({"documents": [{"doc_id": "2025_9_dev"}]}), encoding="utf-8")
    return work, dev


def test_pre_registered_constants() -> None:
    assert sv.SEED == 20261131 == validation.DEFAULT_SEED + 4
    assert sv.STRATA == ("judge_line", "no_judge_line") and sv.QUOTAS == {"judge_line": 30, "no_judge_line": 10}
    assert sv.ACCEPTANCE == {"weighted_split_accuracy": 0.90}
    assert sv.SHEET_COLUMNS == ("item", "doc_id", "title", "pdf_url", "body_starts_with", "split_correct", "notes")
    assert sv.SPLIT_METHOD == "jurisdiction+digital_heading"


@pytest.mark.parametrize("body, stratum", [
    ("Prashant Kumar Mishra, J.\nLeave granted.", "judge_line"),
    ("\n  Sanjiv Khanna, CJI.\nThis appeal", "judge_line"),
    ("B.V. NAGARATHNA, J. :\n1. Leave", "judge_line"),
    ("1. Leave granted.\n2. The appeal", "no_judge_line"),
    ("Leave granted.", "no_judge_line"),
    ("Heard learned counsel for the parties and J.", "no_judge_line"),  # J. inside a long sentence
    ("", "no_judge_line"),
])
def test_stratum_from_first_body_line(body: str, stratum: str) -> None:
    assert sv.stratum({"body": body}) == stratum


def test_population_counts_only_and_exclusions(tmp_path: Path) -> None:
    work, dev = work_dir(tmp_path)
    pop = sv.split_population(work, dev_path=dev)
    assert pop["population"] == {"judge_line": 40, "no_judge_line": 14}
    assert pop["excluded"] == {"dev_documents": 1, "validation_sample": 1, "calibration": 1,
                               "failed_or_unextracted": 3}
    assert set(pop) == {"population", "excluded", "split_method", "seed"}  # no ids, no text
    printed: list[str] = []
    assert sv.main(["--work-dir", str(work), "population", "--dev-docs", str(dev)], out=printed.append) == 0
    assert json.loads(printed[0]) == pop


def test_sheet_minimal_seeded_blind_and_recorded(tmp_path: Path) -> None:
    work, dev = work_dir(tmp_path)
    key_before = (work / "validation" / "validation_key.json").read_bytes()
    rest_before = (work / "validation" / validation.HUMAN_REST_SHEET).read_bytes()
    printed: list[str] = []
    key = sv.make_split_sheet(work, dev_path=dev, out=printed.append)
    sheet = work / sv.OUT_DIR / sv.SHEET_NAME
    assert printed == [f"Wrote {sheet}: 40 documents (judge_line 30, no_judge_line 10)"]

    with sheet.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header, rows = tuple(reader.fieldnames or []), list(reader)
    assert header == sv.SHEET_COLUMNS and len(rows) == 40
    assert all(r["split_correct"] == "" and r["notes"] == "" for r in rows)
    assert [r["item"] for r in rows] == [str(i) for i in range(1, 41)]
    excluded = {"2025_9_dev", "2025_9_sample", "2025_9_cal", "2025_9_failed", "2025_9_error", "2024_9_1_1"}
    assert not {r["doc_id"] for r in rows} & excluded
    by_id = {r["doc_id"]: r for r in rows}
    assert all(r["title"] == f"T {d}" and r["pdf_url"].endswith(f"{d}.pdf") for d, r in by_id.items())
    assert all(r["body_starts_with"] == validation._body_start({"body": JUDGE_BODY if d.startswith("2025")
                                                                  else NO_JUDGE_BODY}) for d, r in by_id.items())
    strata = [("judge_line" if d.startswith("2025") else "no_judge_line") for d in by_id]
    assert strata.count("judge_line") == 30 and strata.count("no_judge_line") == 10
    assert strata != sorted(strata) and strata != sorted(strata, reverse=True)  # order does not group strata

    saved = json.loads((work / sv.OUT_DIR / sv.KEY_NAME).read_text(encoding="utf-8"))
    assert saved == key and saved["seed"] == sv.SEED and saved["quotas"] == sv.QUOTAS
    assert saved["population"] == {"judge_line": 40, "no_judge_line": 14} and saved["short_strata"] == []
    assert {i["doc_id"]: i["stratum"] for i in saved["sample"]} == dict(zip(by_id, strata))
    assert saved["sheet_sha256"] == hashlib.sha256(sheet.read_bytes()).hexdigest()
    assert saved["text_sha256"] == {d: hashlib.sha256((work / "text" / f"{d}.json").read_bytes()).hexdigest()
                                    for d in sorted(by_id)}
    assert saved["rule"]["split_method"] == sv.SPLIT_METHOD and "Supreme" in saved["rule"]["pattern"]
    assert saved["acceptance"] == sv.ACCEPTANCE
    # validation_key.json and the 30-document sheet are not touched.
    assert (work / "validation" / "validation_key.json").read_bytes() == key_before
    assert (work / "validation" / validation.HUMAN_REST_SHEET).read_bytes() == rest_before

    # Seeded: the same inputs elsewhere give the same sheet; never overwritten.
    work2, dev2 = work_dir(tmp_path / "again")
    sv.make_split_sheet(work2, dev_path=dev2, out=lambda _: None)
    assert (work2 / sv.OUT_DIR / sv.SHEET_NAME).read_bytes() == sheet.read_bytes()
    with pytest.raises(ValueError, match="refusing to overwrite"):
        sv.make_split_sheet(work, dev_path=dev, out=lambda _: None)


def test_short_stratum_takes_all_and_is_recorded(tmp_path: Path) -> None:
    work, dev = work_dir(tmp_path, judge=35, no_judge=4)
    key = sv.make_split_sheet(work, dev_path=dev, out=lambda _: None)
    assert key["short_strata"] == ["no_judge_line"]
    assert sum(i["stratum"] == "no_judge_line" for i in key["sample"]) == 4 and len(key["sample"]) == 34


def test_report_template_states_the_non_legal_annotator_and_design() -> None:
    from string import Template

    text = sv.TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "non-legal annotator" in text and "not by the legally trained annotator" in text
    assert "item, doc_id, title,\npdf_url, body_starts_with, split_correct, notes" in text
    assert "≥ 0.90" in text and "base seed + 4" in text and "before any labelling" in text
    names = {m.group("named") or m.group("braced") for m in Template.pattern.finditer(text)
             if m.group("named") or m.group("braced")}
    assert {"seed", "population", "quotas", "excluded", "verdict", "weighted", "diff_check"} <= names
