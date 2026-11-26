"""Hand validation of the corpus v2 IPC detector and headnote/body split.

PRE-REGISTERED INCLUSION RULE (fixed before any labelling)
----------------------------------------------------------
Primary rule (``ipc_detect.include_sections`` defaults): a document is in
scope if some in-scope section (IPC 96-106, 299-304) has at least 2 accepted
body mentions, or a headnote mention plus at least 1 *explicit* body mention.

The looser variant (``headnote_needs_explicit_body=False``: headnote mention
plus any accepted body mention) is reported only as a sensitivity analysis
on the same 50 documents. It is never used to choose the rule.

Acceptance thresholds: Cohen's kappa >= 0.70 between the two annotators
(document-level in scope / not in scope), weighted inclusion precision of
the primary rule >= 0.90, headnote/body split accuracy >= 0.90. If the
primary rule misses a threshold, the rule is changed and validated on a
fresh 50 documents; the first 50 then count as development documents.

Sample design
-------------
50 documents from the extracted candidates, excluding corpus/dev_docs.json,
in five disjoint strata. Each document is assigned to the first stratum it
matches, in this priority order:
  weak_split (8)         any headnote/body split other than both markers
                         (jurisdiction+delivered) or jurisdiction+heading:
                         split_method none, delivered or jurisdiction only
  collision (10)         any IPC-range mention of 96-106 (accepted or rejected)
  rejected_flagged (10)  headnote pre-filter candidate the detector rejects
  implicit_only (15)     in scope only through implicit body mentions
  explicit (7)           in scope with an explicit body mention
Documents whose PDF failed (pdf_pipeline.excluded_ids: failed, missing,
extraction_failed) are excluded, as are the development documents.
The split rules are frozen: they are not tuned on candidate documents any
more, and any document inspected outside this protocol is added to
corpus/dev_docs.json.
The sample is therefore NOT natural prevalence. Per-stratum metrics are
primary; pooled estimates are weighted by stratum population (N_s / n_s).

A separate 5-document calibration set (one per stratum, disjoint from the 50
and from the dev documents) is labelled jointly first; it is not scored.

Both annotators label the same 50 independently, blind to the detector
output, following corpus/annotation_guideline.md.

Usage (run only after the full extraction has finished):
    python backend/corpus/validation.py sheet
    python backend/corpus/validation.py score --a <sheet_A.csv> --b <sheet_B.csv> --adjudicated <adjudicated.csv>

Files go to <work-dir>/validation/ (titles and IDs; no judgment text).
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path
from string import Template
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from corpus import sc_source  # noqa: E402
from corpus.ipc_detect import PRIVATE_DEFENCE_RANGE, detect, include_sections  # noqa: E402
from corpus.pdf_pipeline import excluded_ids, load_dev_ids, load_records  # noqa: E402
from corpus.prefilter import section_group  # noqa: E402

STRATA = ("weak_split", "collision", "rejected_flagged", "implicit_only", "explicit")
QUOTAS = {"weak_split": 8, "collision": 10, "rejected_flagged": 10, "implicit_only": 15, "explicit": 7}
FULL_SPLITS = ("jurisdiction+delivered", "jurisdiction+heading")
DEFAULT_SEED = 20261127
ACCEPTANCE = {"kappa": 0.70, "weighted_precision": 0.90, "split_accuracy": 0.90}
TEMPLATE_PATH = Path(__file__).with_name("validation_report_template.md")

SHEET_COLUMNS = (
    "item", "doc_id", "title", "citation", "pdf_url", "body_starts_with",
    # Annotator fields:
    "in_scope", "sections_at_issue", "passing_sections", "split_correct", "notes",
)
LABEL_VALUES = {"in_scope": ("yes", "no", "unsure"), "split_correct": ("yes", "no", "na")}


# --- features and strata ------------------------------------------------------

def features(record: dict[str, Any]) -> dict[str, Any]:
    """Detector output for one extracted record (text/<doc_id>.json)."""
    body, head = detect(record.get("body", "")), detect(record.get("headnote", ""))
    primary = include_sections(body, head)
    loose = include_sections(body, head, headnote_needs_explicit_body=False)
    counts = body.counts()
    return {
        "doc_id": record["doc_id"],
        "split_method": record.get("split_method"),
        "primary_sections": primary,
        "loose_sections": loose,
        "explicit_in_body": any(counts.get(s, {}).get("explicit", 0) for s in primary),
        "private_defence_range_mention": any(m.section in PRIVATE_DEFENCE_RANGE for m in body.mentions + head.mentions),
    }


def stratum(f: dict[str, Any]) -> str:
    if f["split_method"] not in FULL_SPLITS:
        return "weak_split"
    if f["private_defence_range_mention"]:
        return "collision"
    if not f["primary_sections"]:
        return "rejected_flagged"
    return "explicit" if f["explicit_in_body"] else "implicit_only"


def draw(pool: list[dict[str, Any]], seed: int, exclude: set[str]) -> tuple[list[dict], list[dict], dict[str, int]]:
    """(sample of 50, calibration of 5, stratum population sizes). Seeded, order-independent."""
    rng = random.Random(seed)
    eligible = sorted((f for f in pool if f["doc_id"] not in exclude), key=lambda f: f["doc_id"])
    by_stratum = {s: [f for f in eligible if f["stratum"] == s] for s in STRATA}
    population = {s: len(by_stratum[s]) for s in STRATA}
    sample, calibration = [], []
    for s in STRATA:
        members = list(by_stratum[s])
        rng.shuffle(members)
        sample += members[: QUOTAS[s]]
        calibration += members[QUOTAS[s]: QUOTAS[s] + 1]
    return sample, calibration, population


def pool_summary(work_dir: Path, dev_path: Path | None = None) -> dict[str, Any]:
    """Aggregate detector counts over all extracted candidates. No per-document output."""
    from corpus.prefilter import era  # local: keeps the module import light

    candidates = {r["doc_id"]: r for r in load_records(work_dir / "candidates.jsonl")}
    failed = excluded_ids(work_dir)
    dev = load_dev_ids(dev_path) if dev_path else load_dev_ids()
    groups = ("private_defence", "299-301", "302", "303", "304")
    eras = sorted({era(int(r["year"])) for r in candidates.values()})
    by_group_era = {g: Counter() for g in groups}
    mentions = Counter()
    strata_all, strata_eligible, split_methods = Counter(), Counter(), Counter()
    in_scope = in_scope_loose = extracted = 0
    for doc_id, meta in candidates.items():
        path = work_dir / "text" / f"{doc_id}.json"
        if doc_id in failed or not path.is_file():
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("error"):
            continue
        extracted += 1
        body = detect(record.get("body", ""))
        for m in body.accepted():
            mentions[m.kind] += 1
        f = features(record)
        s = stratum(f)
        strata_all[s] += 1
        strata_eligible[s] += doc_id not in dev
        split_methods[record.get("split_method")] += 1
        in_scope += bool(f["primary_sections"])
        in_scope_loose += bool(f["loose_sections"])
        for g in {section_group(x) for x in f["primary_sections"]}:
            by_group_era[g][era(int(meta["year"]))] += 1
    return {
        "candidates": len(candidates), "excluded_failed_pdfs": len(failed), "extracted": extracted,
        "in_scope_primary": in_scope, "in_scope_loose_sensitivity": in_scope_loose,
        "in_scope_by_group_and_era": {g: {e: by_group_era[g][e] for e in eras} | {"total": sum(by_group_era[g].values())}
                                      for g in groups},
        "accepted_body_mentions": dict(mentions),
        "split_methods": dict(split_methods),
        "strata_all": {s: strata_all[s] for s in STRATA},
        "strata_eligible_excluding_dev": {s: strata_eligible[s] for s in STRATA},
    }


def _body_start(record: dict[str, Any], chars: int = 150) -> str:
    return re.sub(r"\s+", " ", record.get("body", ""))[:chars]


def write_sheet(path: Path, items: list[dict[str, Any]], metadata: dict[str, dict], texts: dict[str, dict],
                seed: int) -> None:
    rows = list(items)
    random.Random(seed).shuffle(rows)  # blind: strata cannot be read off the order
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SHEET_COLUMNS)
        writer.writeheader()
        for i, item in enumerate(rows, start=1):
            meta = metadata.get(item["doc_id"], {})
            writer.writerow({
                "item": i, "doc_id": item["doc_id"], "title": meta.get("title", ""),
                "citation": meta.get("citation", ""), "pdf_url": meta.get("pdf_url", ""),
                "body_starts_with": _body_start(texts[item["doc_id"]]),
                "in_scope": "", "sections_at_issue": "", "passing_sections": "", "split_correct": "", "notes": "",
            })


def make_sheets(work_dir: Path, seed: int = DEFAULT_SEED, dev_path: Path | None = None,
                out: Callable[[str], None] = print) -> dict[str, Any]:
    candidates = {r["doc_id"]: r for r in load_records(work_dir / "candidates.jsonl")}
    failed = excluded_ids(work_dir)
    texts, pool = {}, []
    for doc_id in candidates:
        if doc_id in failed:
            continue
        path = work_dir / "text" / f"{doc_id}.json"
        if not path.is_file():
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("error"):
            continue
        texts[doc_id] = record
        f = features(record)
        f["stratum"] = stratum(f)
        pool.append(f)
    exclude = load_dev_ids(dev_path) if dev_path else load_dev_ids()
    sample, calibration, population = draw(pool, seed, exclude)
    short = [s for s in STRATA if sum(f["stratum"] == s for f in sample) < QUOTAS[s]]

    target = work_dir / "validation"
    for name in ("A", "B"):
        write_sheet(target / f"validation_sheet_{name}.csv", sample, candidates, texts, seed)
    write_sheet(target / "calibration_sheet.csv", calibration, candidates, texts, seed + 1)
    key = {
        "seed": seed, "rule": "primary: >=2 body mentions, or headnote + >=1 explicit body mention",
        "population": population, "quotas": QUOTAS, "short_strata": short,
        "excluded_dev_documents": len(exclude), "excluded_failed_pdfs": sorted(failed),
        "sample": sample, "calibration": calibration,
    }
    (target / "validation_key.json").write_text(json.dumps(key, indent=1) + "\n", encoding="utf-8")
    out(f"Pool: {len(pool)} extracted candidates; excluded {len(exclude)} dev documents")
    out(f"Stratum populations: {population}")
    out(f"Sample: {len(sample)} ({dict(Counter(f['stratum'] for f in sample))}); calibration: {len(calibration)}")
    if short:
        out(f"WARNING: strata below quota: {short}")
    out(f"Wrote {target}/validation_sheet_A.csv, _B.csv, calibration_sheet.csv, validation_key.json "
        "(keep the key away from the annotators)")
    return key


# --- labels and metrics ---------------------------------------------------------

def read_labels(path: Path) -> dict[str, dict[str, Any]]:
    labels = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            in_scope = row["in_scope"].strip().lower()
            split = row.get("split_correct", "").strip().lower()
            if in_scope not in LABEL_VALUES["in_scope"]:
                raise ValueError(f"{path.name} item {row.get('item')}: in_scope must be yes/no/unsure, got {in_scope!r}")
            if split and split not in LABEL_VALUES["split_correct"]:
                raise ValueError(f"{path.name} item {row.get('item')}: split_correct must be yes/no/na")
            labels[row["doc_id"]] = {
                "in_scope": in_scope,
                "sections": {s for s in re.findall(r"\d{2,3}", row.get("sections_at_issue", ""))},
                "split_correct": split or "na",
            }
    return labels


def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    if len(a) != len(b) or not a:
        raise ValueError("need two equal-length, non-empty label lists")
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in set(a) | set(b)) / (n * n)
    if expected == 1.0:
        return None  # undefined: both annotators used a single identical label
    return round((observed - expected) / (1 - expected), 4)


def _prf(pairs: Iterable[tuple[bool, bool]]) -> dict[str, Any]:
    tp = fp = fn = tn = 0
    for predicted, actual in pairs:
        tp += predicted and actual
        fp += predicted and not actual
        fn += actual and not predicted
        tn += not predicted and not actual
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(tp / (tp + fn), 4) if tp + fn else None}


def detector_metrics(items: list[dict[str, Any]], gold: dict[str, dict], population: dict[str, int],
                     rule: str = "primary") -> dict[str, Any]:
    """Per-stratum and weighted pooled document-level precision/recall; section-level by group."""
    key = "primary_sections" if rule == "primary" else "loose_sections"
    scored = [i for i in items if gold[i["doc_id"]]["in_scope"] in ("yes", "no")]
    per_stratum = {}
    weighted = Counter()
    for s in STRATA:
        members = [i for i in scored if i["stratum"] == s]
        pairs = [(bool(i[key]), gold[i["doc_id"]]["in_scope"] == "yes") for i in members]
        per_stratum[s] = {"n": len(members), **_prf(pairs)}
        w = population.get(s, 0) / len(members) if members else 0.0
        for k in ("tp", "fp", "fn", "tn"):
            weighted[k] += w * per_stratum[s][k]
    pooled_weighted = {
        "precision": round(weighted["tp"] / (weighted["tp"] + weighted["fp"]), 4) if weighted["tp"] + weighted["fp"] else None,
        "recall": round(weighted["tp"] / (weighted["tp"] + weighted["fn"]), 4) if weighted["tp"] + weighted["fn"] else None,
    }
    sections = {}
    for group in ("private_defence", "299-301", "302", "303", "304"):
        pairs = []
        for i in scored:
            predicted = {s for s in i[key] if section_group(s) == group}
            actual = {s for s in gold[i["doc_id"]]["sections"] if section_group(s) == group}
            pairs += [(s in predicted, s in actual) for s in predicted | actual]
        sections[group] = _prf(pairs)
    return {"rule": rule, "scored": len(scored), "unsure_excluded": len(items) - len(scored),
            "per_stratum": per_stratum, "pooled_weighted": pooled_weighted,
            "pooled_unweighted": _prf((bool(i[key]), gold[i["doc_id"]]["in_scope"] == "yes") for i in scored),
            "section_level_unweighted": sections}


def split_accuracy(items: list[dict[str, Any]], gold: dict[str, dict]) -> dict[str, Any]:
    judged = [i for i in items if gold[i["doc_id"]]["split_correct"] in ("yes", "no")]
    per = {s: [gold[i["doc_id"]]["split_correct"] == "yes" for i in judged if i["stratum"] == s] for s in STRATA}
    overall = [gold[i["doc_id"]]["split_correct"] == "yes" for i in judged]
    return {"judged": len(judged),
            "accuracy": round(sum(overall) / len(overall), 4) if overall else None,
            "per_stratum": {s: (round(sum(v) / len(v), 4) if v else None) for s, v in per.items()}}


def score(key: dict[str, Any], a: dict, b: dict, adjudicated: dict) -> dict[str, Any]:
    items = key["sample"]
    ids = [i["doc_id"] for i in items]
    missing = [d for d in ids if d not in a or d not in b or d not in adjudicated]
    if missing:
        raise ValueError(f"labels missing for: {missing}")
    kappa = cohen_kappa([a[d]["in_scope"] for d in ids], [b[d]["in_scope"] for d in ids])
    primary = detector_metrics(items, adjudicated, key["population"], "primary")
    loose = detector_metrics(items, adjudicated, key["population"], "loose")
    split = split_accuracy(items, adjudicated)
    checks = {
        "kappa": kappa is not None and kappa >= ACCEPTANCE["kappa"],
        "weighted_precision": (primary["pooled_weighted"]["precision"] or 0) >= ACCEPTANCE["weighted_precision"],
        "split_accuracy": (split["accuracy"] or 0) >= ACCEPTANCE["split_accuracy"],
    }
    return {"kappa": kappa, "raw_agreement": round(sum(a[d]["in_scope"] == b[d]["in_scope"] for d in ids) / len(ids), 4),
            "primary": primary, "sensitivity_loose": loose, "split": split,
            "acceptance": ACCEPTANCE, "checks": checks, "accepted": all(checks.values())}


def _table(metrics: dict[str, Any]) -> str:
    lines = ["| Stratum | n | TP | FP | FN | TN | Precision | Recall |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for s, m in metrics["per_stratum"].items():
        lines.append(f"| {s} | {m['n']} | {m['tp']} | {m['fp']} | {m['fn']} | {m['tn']} | {m['precision']} | {m['recall']} |")
    return "\n".join(lines)


def render_report(result: dict[str, Any], key: dict[str, Any]) -> str:
    primary, loose = result["primary"], result["sensitivity_loose"]
    sections = "\n".join(
        f"| {g} | {m['tp']} | {m['fp']} | {m['fn']} | {m['precision']} | {m['recall']} |"
        for g, m in primary["section_level_unweighted"].items()
    )
    return Template(TEMPLATE_PATH.read_text(encoding="utf-8")).substitute(
        seed=key["seed"], population=json.dumps(key["population"]), quotas=json.dumps(key["quotas"]),
        kappa=result["kappa"], raw_agreement=result["raw_agreement"],
        primary_table=_table(primary), primary_weighted=json.dumps(primary["pooled_weighted"]),
        primary_unweighted=json.dumps({k: primary["pooled_unweighted"][k] for k in ("precision", "recall")}),
        section_table=sections,
        loose_table=_table(loose), loose_weighted=json.dumps(loose["pooled_weighted"]),
        split_accuracy=result["split"]["accuracy"], split_per_stratum=json.dumps(result["split"]["per_stratum"]),
        unsure=primary["unsure_excluded"],
        checks=json.dumps(result["checks"]), verdict="ACCEPTED" if result["accepted"] else
        "NOT ACCEPTED: change the rule and validate on a fresh 50 (these 50 become development documents)",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work-dir", type=Path, default=sc_source.DEFAULT_WORK_DIR)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("summary", help="aggregate detector counts over all candidates (no per-document output)")
    sheet = sub.add_parser("sheet", help="draw the 50 + 5 and write blind sheets")
    sheet.add_argument("--seed", type=int, default=DEFAULT_SEED)
    scoring = sub.add_parser("score", help="agreement and detector metrics from labelled sheets")
    for flag in ("--a", "--b", "--adjudicated"):
        scoring.add_argument(flag, type=Path, required=True)
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    work_dir = args.work_dir.expanduser()
    if args.command == "summary":
        print(json.dumps(pool_summary(work_dir), indent=1))
        return 0
    if args.command == "sheet":
        make_sheets(work_dir, args.seed)
        return 0
    key = json.loads((work_dir / "validation" / "validation_key.json").read_text(encoding="utf-8"))
    result = score(key, read_labels(args.a), read_labels(args.b), read_labels(args.adjudicated))
    (work_dir / "validation" / "validation_result.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    report = render_report(result, key)
    (work_dir / "validation" / "validation_report.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
