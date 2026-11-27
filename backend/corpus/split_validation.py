"""Split-only validation of the Digital SCR headnote/body rule (jurisdiction+digital_heading).

PRE-REGISTERED DESIGN (committed with this generator, before any labelling)
---------------------------------------------------------------------------
Why: the frozen split rule failed on 4 of 5 weak_split documents in the 25
human-labelled validation documents, all 2024-25 Digital SCR judgments split
by the jurisdiction line alone. Those 4 are development documents
(corpus/dev_docs.json). The rule was changed (pdf_pipeline.DIGITAL_HEADING,
split_method ``jurisdiction+digital_heading``) and is validated here, on
fresh documents, for the split only. The inclusion rule is not touched: its
inputs are unchanged on every document the new rule affects.

Population: extracted candidates whose re-extracted record has
split_method ``jurisdiction+digital_heading``, excluding
  - development documents (corpus/dev_docs.json),
  - the 55 validation documents and the 5 calibration documents
    (validation/validation_key.json, read only),
  - failed, missing or extraction_failed PDFs and records with an
    extraction error.

Strata, by the first non-empty line of the new body:
  judge_line     it ends with ", J." or ", CJI." (optionally ":"), i.e. the
                 authoring judge's name line, e.g. "Abhay S. Oka, J."
  no_judge_line  anything else (e.g. "1. Leave granted."): the riskier shape,
                 oversampled
Quotas: judge_line 30, no_judge_line 10 (a stratum with fewer documents is
taken whole and recorded as short). Seed 20261131 (the validation base seed
20261127 + 4; +1 calibration, +2 human subset, +3 the other-30 sheet). One
random.Random(seed): each stratum's members are sorted by doc_id, shuffled
and the first quota taken, in stratum order; the combined rows are then
shuffled for the sheet, so the order does not reveal the strata.

Annotation: one non-legal annotator (the project author) fills in only
``split_correct`` (and optional ``notes``) on a minimal sheet:
item, doc_id, title, pdf_url, body_starts_with, split_correct, notes.
``body_starts_with`` is the first 150 characters of the new body.
Rule for the annotator, from the PDF: ``yes`` if body_starts_with begins
where the judgment itself begins: the authoring judge's name line, or, when
no judge is named before it, the first line of the judgment text (e.g.
"1. Leave granted."); ``no`` if it begins inside the headnote, the case
details or the counsel list, or later than the start of the judgment;
``na`` only if the PDF has no headnote. No legal judgment is needed; the
5-document weak_split calibration is replaced by the 4 development
documents, inspected jointly as worked examples and not scored.

Statistic and acceptance: per-stratum share of judged (yes/no) documents
that are ``yes``, with 95% Wilson intervals; pooled accuracy weighted by
stratum population (sum N_s * acc_s / sum N_s) with a 95% stratified
percentile bootstrap (10,000 resamples, seed 20261131). The rule is ACCEPTED
if the weighted pooled accuracy is >= 0.90 (point estimate, as in the main
protocol); otherwise NOT ACCEPTED: these documents become development
documents and any further change is validated on a fresh draw.

Reporting (corpus/split_validation_report_template.md): the rule change,
counts by split_method and year, the extraction diff check (every other
record unchanged apart from extraction timestamps), the inclusion-unchanged
check, the residual known-weak splits (2024-26 documents still
``jurisdiction`` and the pre-2024 ``jurisdiction``-only documents), the
annotator (non-legal), per-stratum and weighted accuracy, and the verdict.

Files go to <work-dir>/validation_split/: split_validation_key.json (sample,
strata, population, seed, rule, sheet and text SHA-256) and
split_validation_sheet.csv. validation/ is never written.

Usage:
    python backend/corpus/split_validation.py population   # N_s after exclusions (counts only)
    python backend/corpus/split_validation.py sheet        # draws and writes the sheet once
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import re
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from corpus import sc_source  # noqa: E402
from corpus.pdf_pipeline import DIGITAL_HEADING, excluded_ids, load_dev_ids, load_records  # noqa: E402
from corpus.validation import DEFAULT_SEED, _body_start  # noqa: E402

SPLIT_METHOD = "jurisdiction+digital_heading"
SEED = DEFAULT_SEED + 4  # 20261131
STRATA = ("judge_line", "no_judge_line")
QUOTAS = {"judge_line": 30, "no_judge_line": 10}
ACCEPTANCE = {"weighted_split_accuracy": 0.90}
BOOTSTRAP_RESAMPLES = 10_000
SHEET_COLUMNS = ("item", "doc_id", "title", "pdf_url", "body_starts_with", "split_correct", "notes")
OUT_DIR = "validation_split"
SHEET_NAME = "split_validation_sheet.csv"
KEY_NAME = "split_validation_key.json"
TEMPLATE_PATH = Path(__file__).with_name("split_validation_report_template.md")
JUDGE_LINE = re.compile(r",[ \t]*(?:J|CJI)\.?[ \t]*:?[ \t]*$")  # "Abhay S. Oka, J." / "Sanjiv Khanna, CJI."


def stratum(record: dict[str, Any]) -> str:
    first = next((line.strip() for line in record.get("body", "").splitlines() if line.strip()), "")
    return "judge_line" if JUDGE_LINE.search(first) else "no_judge_line"


def _eligible(work_dir: Path, dev_path: Path | None) -> tuple[dict[str, list[str]], dict[str, int], dict, dict]:
    """(doc_ids per stratum, exclusion counts, candidate metadata, raw text bytes). Read only."""
    candidates = {r["doc_id"]: r for r in load_records(work_dir / "candidates.jsonl")}
    failed = excluded_ids(work_dir)
    dev = load_dev_ids(dev_path) if dev_path else load_dev_ids()
    key = json.loads((work_dir / "validation" / "validation_key.json").read_text(encoding="utf-8"))
    sample = {i["doc_id"] for i in key.get("sample", [])}
    calibration = {i["doc_id"] for i in key.get("calibration", [])}
    members: dict[str, list[str]] = {s: [] for s in STRATA}
    excluded = {"dev_documents": 0, "validation_sample": 0, "calibration": 0, "failed_or_unextracted": 0}
    raw: dict[str, bytes] = {}
    for doc_id in sorted(candidates):
        path = work_dir / "text" / f"{doc_id}.json"
        data = path.read_bytes() if path.is_file() else None
        record = json.loads(data.decode("utf-8")) if data else None
        if doc_id in failed or record is None or record.get("error"):
            excluded["failed_or_unextracted"] += 1  # any candidate, whatever its split
            continue
        if record.get("split_method") != SPLIT_METHOD:
            continue
        if doc_id in dev:
            excluded["dev_documents"] += 1
        elif doc_id in sample:
            excluded["validation_sample"] += 1
        elif doc_id in calibration:
            excluded["calibration"] += 1
        else:
            members[stratum(record)].append(doc_id)
            raw[doc_id] = data
    return members, excluded, candidates, raw


def split_population(work_dir: Path, dev_path: Path | None = None) -> dict[str, Any]:
    """Stratum sizes N_s after the exclusions, and the exclusion counts. Counts only."""
    members, excluded, _, _ = _eligible(work_dir, dev_path)
    return {"split_method": SPLIT_METHOD, "seed": SEED,
            "population": {s: len(members[s]) for s in STRATA}, "excluded": excluded}


def make_split_sheet(work_dir: Path, dev_path: Path | None = None,
                     out: Callable[[str], None] = print) -> dict[str, Any]:
    """Draw the pre-registered sample and write the minimal blind sheet and its key, once."""
    target = work_dir / OUT_DIR
    sheet_path, key_path = target / SHEET_NAME, target / KEY_NAME
    existing = [str(p) for p in (sheet_path, key_path) if p.exists()]
    if existing:
        raise ValueError(f"refusing to overwrite {existing}")
    members, excluded, candidates, raw = _eligible(work_dir, dev_path)
    rng = random.Random(SEED)
    sample = []
    for s in STRATA:
        ids = sorted(members[s])
        rng.shuffle(ids)
        sample += [{"doc_id": d, "stratum": s} for d in ids[: QUOTAS[s]]]
    rows = list(sample)
    rng.shuffle(rows)  # blind: strata cannot be read off the order

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=SHEET_COLUMNS, restval="")
    writer.writeheader()
    for i, item in enumerate(rows, start=1):
        meta = candidates.get(item["doc_id"], {})
        record = json.loads(raw[item["doc_id"]].decode("utf-8"))
        writer.writerow({"item": i, "doc_id": item["doc_id"], "title": meta.get("title", ""),
                         "pdf_url": meta.get("pdf_url", ""), "body_starts_with": _body_start(record)})
    sheet = buf.getvalue().encode("utf-8")
    population = {s: len(members[s]) for s in STRATA}
    key = {
        "seed": SEED, "split_method": SPLIT_METHOD,
        "rule": {"split_method": SPLIT_METHOD, "pattern": DIGITAL_HEADING.pattern},
        "strata": {"judge_line": "first non-empty body line ends with ', J.' or ', CJI.' (optionally ':')",
                   "no_judge_line": "anything else"},
        "quotas": QUOTAS, "population": population,
        "short_strata": [s for s in STRATA if population[s] < QUOTAS[s]], "excluded": excluded,
        "acceptance": ACCEPTANCE, "acceptance_on": "weighted pooled point estimate",
        "bootstrap_resamples": BOOTSTRAP_RESAMPLES, "annotator": "non-legal (project author)",
        "sample": sample,
        "sheet_sha256": hashlib.sha256(sheet).hexdigest(),
        "text_sha256": {i["doc_id"]: hashlib.sha256(raw[i["doc_id"]]).hexdigest()
                        for i in sorted(sample, key=lambda i: i["doc_id"])},
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    target.mkdir(parents=True, exist_ok=True)
    key_path.write_text(json.dumps(key, indent=1) + "\n", encoding="utf-8")
    sheet_path.write_bytes(sheet)
    counts = ", ".join(f"{s} {sum(i['stratum'] == s for i in sample)}" for s in STRATA)
    out(f"Wrote {sheet_path}: {len(sample)} documents ({counts})")
    return key


def main(argv: list[str] | None = None, out: Callable[[str], None] = print) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work-dir", type=Path, default=sc_source.DEFAULT_WORK_DIR)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (("population", "stratum sizes after exclusions (counts only)"),
                       ("sheet", "draw the pre-registered sample and write the sheet once")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--dev-docs", type=Path, default=None, help="default corpus/dev_docs.json")
    args = parser.parse_args(argv)
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    work_dir = args.work_dir.expanduser()
    if args.command == "population":
        out(json.dumps(split_population(work_dir, args.dev_docs)))
    else:
        make_split_sheet(work_dir, args.dev_docs, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
