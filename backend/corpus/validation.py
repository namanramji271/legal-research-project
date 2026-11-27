"""Hand validation of the corpus v2 IPC detector and headnote/body split.

PRE-REGISTERED LABELS (fixed before any labelling)
--------------------------------------------------
``in_scope`` is the STRICT label and the primary gold standard: yes when the
court decides or reasons about an in-scope IPC section (conviction,
acquittal, sentence, its elements, murder vs culpable homicide, private
defence, framing or quashing of the charge). ``section_as_charge`` (yes/no)
marks documents where the section is the charge, or is mentioned as the
charge, but the court does not decide it (bail, juvenility, s.319 CrPC,
witness recall, a chargesheet recital). The LOOSE label (strict yes or
section_as_charge yes) is a secondary gold standard, reported alongside;
acceptance is judged against the strict label only.

PRE-REGISTERED ANNOTATION DESIGN ("Option B", fixed before any labelling)
-------------------------------------------------------------------------
Annotator 1 is an LLM (``corpus/llm_label.py``): one fresh ``claude -p``
session per document, with no tools and no files, run in resumable
checkpoint batches of 10. It sees only the guideline (via the committed
prompt template ``corpus/llm_label_prompt.md``) and, for that document,
title, citation, extracted headnote, the first 600 characters of the body
and the full body. It never sees the key, strata, detector output, document
IDs or any other document's labels. It labels all 55 and gives a
one-sentence reason quoting the decisive sentence.

Annotator 2 is a legally trained human who labels, blind and following
corpus/annotation_guideline.md, a seeded stratified subset of 25 of the 55
(5 per stratum; seed + 2; recorded in the key as ``human_subset``), written
as validation_sheet_human_25.csv. The 5 calibration documents are labelled
and discussed jointly first and are not scored.

Agreement: Cohen's kappa on strict ``in_scope`` between the LLM and the
blind human labels on the 25-document overlap; the LLM is accepted as an
annotator if kappa >= 0.70. If it is, the LLM labels are gold for the other
30; if not, those 30 are not used until a human labels them (verdict
INCOMPLETE). On the 25, every disagreement is adjudicated by the human after
reading the LLM's reason; the human label wins, and every disagreement and
change is logged (adjudication_log.csv).

Detector and split metrics are computed on the adjudicated gold over all 55
(human on 25, LLM on 30), and also on the 25 human-labelled documents alone
as a sensitivity analysis. The report records the LLM model id, the prompt
template (path and SHA-256), the CLI version and the labelling dates. The
labels are committed later without the reason column (no document text).

PRE-REGISTERED INCLUSION RULE (fixed before any labelling)
----------------------------------------------------------
Primary rule (``ipc_detect.include_sections`` defaults): a document is in
scope if some in-scope section (IPC 96-106, 299-304) has at least 2 accepted
body mentions, or a headnote mention plus at least 1 *explicit* body mention.

The looser variant (``headnote_needs_explicit_body=False``: headnote mention
plus any accepted body mention) is reported only as a sensitivity analysis
on the same 55 documents. It is never used to choose the rule.

Acceptance thresholds: Cohen's kappa >= 0.70 between the LLM and the human
on the strict ``in_scope`` label over the 25-document overlap (kappa on
``section_as_charge`` is reported, not a criterion), weighted inclusion
precision of the primary rule against the strict label >= 0.90,
headnote/body split accuracy >= 0.90. If the primary rule misses a detector
threshold, the rule is changed and validated on a fresh 55 documents; the
first 55 then count as development documents. If only the kappa criterion
is missed, the verdict is INCOMPLETE until a human labels the other 30.

Sample design
-------------
55 documents from the extracted candidates, excluding corpus/dev_docs.json,
in five disjoint strata. Each document is assigned to the first stratum it
matches, in this priority order:
  weak_split (8)         any headnote/body split other than both markers
                         (jurisdiction+delivered) or jurisdiction+heading:
                         split_method none, delivered or jurisdiction only
  collision (10)         any IPC-range mention of 96-106 (accepted or rejected)
  rejected_flagged (10)  headnote pre-filter candidate the detector rejects
  implicit_only (12)     in scope only through implicit body mentions
  explicit (15)          in scope with an explicit body mention
The explicit stratum is about 70% of the in-scope population, so it carries
most of the weight in the pooled estimate and gets the largest quota.
Documents whose PDF failed (pdf_pipeline.excluded_ids: failed, missing,
extraction_failed) are excluded, as are the development documents.
The split rules are frozen: they are not tuned on candidate documents any
more, and any document inspected outside this protocol is added to
corpus/dev_docs.json.
The sample is therefore NOT natural prevalence. Per-stratum metrics are
primary; pooled estimates are weighted by stratum population (N_s / n_s).

Uncertainty: per-stratum proportions carry 95% Wilson intervals; the
weighted pooled precision/recall and the split accuracy carry a 95%
stratified percentile bootstrap (10,000 resamples, seeded by the sample
seed). Acceptance is judged on the point estimates; intervals are reported
beside them, because the pooled estimate rests on 8-15 labels per stratum
(5 per stratum in the 25-only sensitivity analysis).

A separate 5-document calibration set (one per stratum, disjoint from the 55
and from the dev documents) is labelled jointly first; it is not scored.

Usage (run only after the full extraction has finished):
    python backend/corpus/validation.py sheet          # draws 55 + 5, writes key and calibration sheet
    python backend/corpus/validation.py human-sheet    # adds human_subset to the key, writes the 25 sheet
    python backend/corpus/llm_label.py --dry-run       # then without --dry-run: LLM labels for all 55
    python backend/corpus/validation.py disagreements --llm <validation_sheet_LLM.csv>
        --human <validation_sheet_human_25.csv> --out-dir <dir outside the repo>
        (writes adjudication_review.csv, adjudicated_25.csv, adjudication_log.csv; then the human fills in
        final + note in a copy of the review, adjudication_review_final.csv)
    python backend/corpus/validation.py apply-adjudication --review-final <adjudication_review_final.csv>
        --log <adjudication_log.csv> --adjudicated <adjudicated_25.csv> --human <...human_25.csv> --llm <...LLM.csv>
        (backs both targets up to .bak, fills the log and adjudicated sheet, runs check_adjudication)
    python backend/corpus/validation.py score --llm <validation_sheet_LLM.csv>
        --human <validation_sheet_human_25.csv> --adjudicated <adjudicated_25.csv>
        --log <adjudication_log.csv>       (one command; wrapped here)

Files go to <work-dir>/validation/ (titles and IDs; no judgment text, except the
LLM sheet's reason column, which quotes the decisive sentence and stays there).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import random
import re
import shutil
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
QUOTAS = {"weak_split": 8, "collision": 10, "rejected_flagged": 10, "implicit_only": 12, "explicit": 15}
SAMPLE_SIZE = sum(QUOTAS.values())  # 55
HUMAN_PER_STRATUM = 5  # human subset: 5 per stratum = 25
HUMAN_SUBSET_SEED_OFFSET = 2  # sample uses seed, calibration sheet seed + 1, human subset seed + 2
HUMAN_SHEET = "validation_sheet_human_25.csv"
FULL_SPLITS = ("jurisdiction+delivered", "jurisdiction+heading")
DEFAULT_SEED = 20261127
ACCEPTANCE = {"kappa": 0.70, "weighted_precision": 0.90, "split_accuracy": 0.90}
Z95 = 1.959963984540054  # two-sided 95%
BOOTSTRAP_RESAMPLES = 10_000
TEMPLATE_PATH = Path(__file__).with_name("validation_report_template.md")

SHEET_COLUMNS = (
    "item", "doc_id", "title", "citation", "pdf_url", "body_starts_with",
    # Annotator fields:
    "in_scope", "section_as_charge", "sections_at_issue", "passing_sections", "split_correct", "notes",
)
LABEL_VALUES = {"in_scope": ("yes", "no", "unsure"), "section_as_charge": ("yes", "no"),
                "split_correct": ("yes", "no", "na")}
GOLD_LABELS = ("strict", "loose")


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
    """(sample of SAMPLE_SIZE, calibration of 5, stratum population sizes). Seeded, order-independent."""
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
                "in_scope": "", "section_as_charge": "", "sections_at_issue": "", "passing_sections": "", "split_correct": "", "notes": "",
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
    write_sheet(target / "calibration_sheet.csv", calibration, candidates, texts, seed + 1)
    key = {
        "seed": seed, "rule": "primary: >=2 body mentions, or headnote + >=1 explicit body mention",
        "population": population, "quotas": QUOTAS, "short_strata": short,
        "excluded_dev_documents": len(exclude), "excluded_failed_pdfs": sorted(failed),
        "sample": sample, "calibration": calibration,
        "human_subset_seed": seed + HUMAN_SUBSET_SEED_OFFSET, "human_subset": draw_human_subset(sample, seed),
    }
    (target / "validation_key.json").write_text(json.dumps(key, indent=1) + "\n", encoding="utf-8")
    out(f"Pool: {len(pool)} extracted candidates; excluded {len(exclude)} dev documents")
    out(f"Stratum populations: {population}")
    out(f"Sample: {len(sample)} ({dict(Counter(f['stratum'] for f in sample))}); calibration: {len(calibration)}")
    if short:
        out(f"WARNING: strata below quota: {short}")
    out(f"Wrote {target}/calibration_sheet.csv, validation_key.json (keep the key away from the annotators); "
        "run `human-sheet` for the human sheet")
    return key


def draw_human_subset(sample: list[dict[str, Any]], seed: int) -> list[str]:
    """HUMAN_PER_STRATUM doc_ids per stratum from the sample, seeded (seed + 2), order-independent."""
    rng = random.Random(seed + HUMAN_SUBSET_SEED_OFFSET)
    chosen = []
    for s in STRATA:
        members = sorted(i["doc_id"] for i in sample if i["stratum"] == s)
        rng.shuffle(members)
        chosen += sorted(members[:HUMAN_PER_STRATUM])
    return chosen


def make_human_sheet(work_dir: Path, out: Callable[[str], None] = print) -> dict[str, Any]:
    """Record the human subset in the existing key (sample untouched) and write the blind 25-document sheet."""
    target = work_dir / "validation"
    key_path = target / "validation_key.json"
    key = json.loads(key_path.read_text(encoding="utf-8"))
    subset = draw_human_subset(key["sample"], key["seed"])
    if "human_subset" in key and key["human_subset"] != subset:
        raise ValueError("validation_key.json has a different human_subset than the seeded draw; refusing to overwrite")
    short = [s for s in STRATA if sum(i["stratum"] == s and i["doc_id"] in subset for i in key["sample"])
             < HUMAN_PER_STRATUM]
    if "human_subset" not in key:
        key["human_subset_seed"] = key["seed"] + HUMAN_SUBSET_SEED_OFFSET
        key["human_subset"] = subset
        key_path.write_text(json.dumps(key, indent=1) + "\n", encoding="utf-8")
    candidates = {r["doc_id"]: r for r in load_records(work_dir / "candidates.jsonl")}
    texts = {d: json.loads((work_dir / "text" / f"{d}.json").read_text(encoding="utf-8")) for d in subset}
    items = [i for i in key["sample"] if i["doc_id"] in set(subset)]
    path = target / HUMAN_SHEET
    write_sheet(path, items, candidates, texts, key["human_subset_seed"])
    out(f"Wrote {path}: {len(items)} documents" + (f"; WARNING: strata below {HUMAN_PER_STRATUM}: {short}" if short else ""))
    return key


# --- labels and metrics ---------------------------------------------------------

def parse_label_row(row: dict[str, str], where: str) -> dict[str, Any]:
    """Validate one sheet row (the rules read_labels applies) and return its parsed labels."""
    in_scope = (row.get("in_scope") or "").strip().lower()
    charge = (row.get("section_as_charge") or "").strip().lower()
    split = (row.get("split_correct") or "").strip().lower()
    if in_scope not in LABEL_VALUES["in_scope"]:
        raise ValueError(f"{where}: in_scope must be yes/no/unsure, got {in_scope!r}")
    if charge not in LABEL_VALUES["section_as_charge"]:
        raise ValueError(f"{where}: section_as_charge must be yes/no, got {charge!r}")
    if in_scope == "yes" and charge == "yes":
        raise ValueError(f"{where}: section_as_charge must be no when in_scope is yes (the court decides it)")
    if split and split not in LABEL_VALUES["split_correct"]:
        raise ValueError(f"{where}: split_correct must be yes/no/na")
    return {
        "in_scope": in_scope,
        "section_as_charge": charge,
        "sections": {s for s in re.findall(r"\d{2,3}", row.get("sections_at_issue") or "")},
        "split_correct": split or "na",
    }


def read_labels(path: Path) -> dict[str, dict[str, Any]]:
    labels = {}
    with path.open(newline="", encoding="utf-8-sig") as f:  # -sig: a BOM must not hide the first column
        for row in csv.DictReader(f):
            labels[row["doc_id"]] = parse_label_row(row, f"{path.name} item {row.get('item')}")
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


# --- uncertainty --------------------------------------------------------------

def wilson(k: int, n: int, z: float = Z95) -> list[float] | None:
    """Wilson score interval for a proportion k/n; None when n == 0."""
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def _percentile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolation percentile of an already sorted list."""
    pos = (len(sorted_values) - 1) * q
    lo = math.floor(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def stratified_bootstrap(groups: dict[str, list], statistic: Callable[[dict[str, list]], dict[str, float | None]],
                         seed: int, resamples: int = BOOTSTRAP_RESAMPLES) -> dict[str, dict[str, Any]]:
    """Percentile 95% intervals for each named output of ``statistic``.

    Each replicate resamples every stratum with replacement at its own size, so
    the stratum sizes (and hence the N_s / n_s weights) stay fixed. Replicates
    where an output is undefined (None) are dropped for that output and counted.
    """
    rng = random.Random(seed)
    names = list(statistic(groups))
    draws: dict[str, list[float]] = {name: [] for name in names}
    for _ in range(resamples):
        replicate = {s: rng.choices(m, k=len(m)) if m else [] for s, m in groups.items()}
        for name, value in statistic(replicate).items():
            if value is not None:
                draws[name].append(value)
    out = {}
    for name in names:
        values = sorted(draws[name])
        ci = [round(_percentile(values, 0.025), 4), round(_percentile(values, 0.975), 4)] if values else None
        out[name] = {"ci": ci, "undefined_replicates": resamples - len(values)}
    return out


def _prf(pairs: Iterable[tuple[bool, bool]]) -> dict[str, Any]:
    tp = fp = fn = tn = 0
    for predicted, actual in pairs:
        tp += predicted and actual
        fp += predicted and not actual
        fn += actual and not predicted
        tn += not predicted and not actual
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "precision_ci": wilson(tp, tp + fp),
            "recall": round(tp / (tp + fn), 4) if tp + fn else None,
            "recall_ci": wilson(tp, tp + fn)}


def _weighted_pr(groups: dict[str, list[tuple[bool, bool]]], population: dict[str, int]) -> dict[str, float | None]:
    """Population-weighted (N_s / n_s) pooled precision and recall over per-stratum (predicted, actual) pairs."""
    tp = fp = fn = 0.0
    for s, pairs in groups.items():
        if not pairs:
            continue
        w = population.get(s, 0) / len(pairs)
        tp += w * sum(p and a for p, a in pairs)
        fp += w * sum(p and not a for p, a in pairs)
        fn += w * sum(a and not p for p, a in pairs)
    return {"precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None}


def gold_in_scope(label: dict[str, Any], view: str = "strict") -> bool | None:
    """Document-level gold value: strict = in_scope; loose = in_scope or section_as_charge. None = unsure."""
    if view not in GOLD_LABELS:
        raise ValueError(f"gold label view must be one of {GOLD_LABELS}")
    if view == "loose" and label.get("section_as_charge") == "yes":
        return True
    return {"yes": True, "no": False}.get(label["in_scope"])


def detector_metrics(items: list[dict[str, Any]], gold: dict[str, dict], population: dict[str, int],
                     rule: str = "primary", label: str = "strict", seed: int = DEFAULT_SEED,
                     resamples: int = BOOTSTRAP_RESAMPLES) -> dict[str, Any]:
    """Per-stratum and weighted pooled document-level precision/recall; section-level by group.

    ``rule`` picks the detector rule (primary / loose sensitivity variant);
    ``label`` picks the gold standard (strict in_scope / loose with section_as_charge).
    Per-stratum and unweighted figures carry Wilson intervals; the weighted
    pooled figures carry a seeded stratified-bootstrap interval.
    """
    key = "primary_sections" if rule == "primary" else "loose_sections"
    truth = {i["doc_id"]: gold_in_scope(gold[i["doc_id"]], label) for i in items}
    scored = [i for i in items if truth[i["doc_id"]] is not None]
    per_stratum, groups = {}, {}
    for s in STRATA:
        members = [i for i in scored if i["stratum"] == s]
        groups[s] = [(bool(i[key]), truth[i["doc_id"]]) for i in members]
        per_stratum[s] = {"n": len(members), **_prf(groups[s])}
    point = _weighted_pr(groups, population)
    intervals = stratified_bootstrap(groups, lambda g: _weighted_pr(g, population), seed, resamples)
    pooled_weighted = {}
    for name in ("precision", "recall"):
        pooled_weighted[name] = round(point[name], 4) if point[name] is not None else None
        pooled_weighted[f"{name}_ci"] = intervals[name]["ci"]
        pooled_weighted[f"{name}_undefined_replicates"] = intervals[name]["undefined_replicates"]
    sections = {}
    for group in ("private_defence", "299-301", "302", "303", "304"):
        pairs = []
        for i in scored:
            predicted = {s for s in i[key] if section_group(s) == group}
            actual = {s for s in gold[i["doc_id"]]["sections"] if section_group(s) == group}
            pairs += [(s in predicted, s in actual) for s in predicted | actual]
        sections[group] = _prf(pairs)
    return {"rule": rule, "label": label, "scored": len(scored), "unsure_excluded": len(items) - len(scored),
            "per_stratum": per_stratum, "pooled_weighted": pooled_weighted,
            "pooled_unweighted": _prf((bool(i[key]), truth[i["doc_id"]]) for i in scored),
            "section_level_unweighted": sections}


def _share(groups: dict[str, list[bool]]) -> dict[str, float | None]:
    values = [x for v in groups.values() for x in v]
    return {"accuracy": sum(values) / len(values) if values else None}


def split_accuracy(items: list[dict[str, Any]], gold: dict[str, dict], seed: int = DEFAULT_SEED,
                   resamples: int = BOOTSTRAP_RESAMPLES) -> dict[str, Any]:
    """Unweighted share of judged splits that are correct (pre-registered statistic).

    Interval: stratified bootstrap of that same unweighted share; per stratum: Wilson.
    """
    judged = [i for i in items if gold[i["doc_id"]]["split_correct"] in ("yes", "no")]
    per = {s: [gold[i["doc_id"]]["split_correct"] == "yes" for i in judged if i["stratum"] == s] for s in STRATA}
    point = _share(per)["accuracy"]
    boot = stratified_bootstrap(per, _share, seed, resamples)["accuracy"]
    return {"judged": len(judged),
            "accuracy": round(point, 4) if point is not None else None,
            "accuracy_ci": boot["ci"],
            "per_stratum": {s: (round(sum(v) / len(v), 4) if v else None) for s, v in per.items()},
            "per_stratum_ci": {s: wilson(sum(v), len(v)) for s, v in per.items()}}


ADJUDICATED_FIELDS = ("in_scope", "section_as_charge", "split_correct")
LOG_COLUMNS = ("doc_id", "field", "human_blind", "llm", "final", "note")


def read_log(path: Path) -> list[dict[str, str]]:
    """adjudication_log.csv: one row per LLM/human disagreement on the 25."""
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = [c for c in LOG_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path.name}: missing columns {missing}")
        return [{c: (row[c] or "").strip().lower() if c != "note" else (row[c] or "").strip() for c in LOG_COLUMNS}
                for row in reader]


def check_adjudication(subset: list[str], llm: dict, human: dict, adjudicated: dict,
                       log: list[dict[str, str]]) -> dict[str, Any]:
    """Enforce the pre-registered adjudication: every disagreement logged, the human decides, nothing silent.

    Raises ValueError if a disagreement has no log row, a log row does not match
    the sheets, or an adjudicated label differs from the blind human label
    without a log row.
    """
    logged = {}
    for row in log:
        if row["field"] not in ADJUDICATED_FIELDS:
            raise ValueError(f"adjudication log: unknown field {row['field']!r} for {row['doc_id']}")
        if row["doc_id"] not in subset:
            raise ValueError(f"adjudication log: {row['doc_id']} is not in the human subset")
        k = (row["doc_id"], row["field"])
        if k in logged:
            raise ValueError(f"adjudication log: duplicate row for {k}")
        logged[k] = row
    errors, disagreements, changed = [], Counter(), Counter()
    for d in subset:
        for field in ADJUDICATED_FIELDS:
            h, m, final = human[d][field], llm[d][field], adjudicated[d][field]
            row = logged.get((d, field))
            if h != m:
                disagreements[field] += 1
            if row is None:
                if h != m:
                    errors.append(f"{d} {field}: human {h!r} vs LLM {m!r} has no log row")
                elif final != h:
                    errors.append(f"{d} {field}: adjudicated {final!r} differs from blind human {h!r} without a log row")
                continue
            if (row["human_blind"], row["llm"], row["final"]) != (h, m, final):
                errors.append(f"{d} {field}: log row {row['human_blind']}/{row['llm']}/{row['final']} "
                              f"does not match sheets {h}/{m}/{final}")
            changed[field] += final != h
    if errors:
        raise ValueError("adjudication check failed:\n  " + "\n  ".join(errors))
    return {"disagreements": {f: disagreements[f] for f in ADJUDICATED_FIELDS},
            "changed_from_blind_human": {f: changed[f] for f in ADJUDICATED_FIELDS},
            "logged_rows": len(log)}


REPO_DIR = BACKEND_DIR.parent
REVIEW_FILE, ADJUDICATED_FILE, LOG_FILE = "adjudication_review.csv", "adjudicated_25.csv", "adjudication_log.csv"
REVIEW_COLUMNS = (
    "item", "field", "title", "citation", "pdf_url",
    "human_in_scope", "human_section_as_charge", "human_split_correct", "human_sections_at_issue", "human_notes",
    "llm_in_scope", "llm_section_as_charge", "llm_split_correct", "llm_sections_at_issue", "llm_reason",
)  # no doc_id, strata, judgment text (body_starts_with) or key contents


def _raw_rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return {row["doc_id"]: row for row in csv.DictReader(f)}


def write_disagreements(llm_path: Path, human_path: Path, out_dir: Path,
                        out: Callable[[str], None] = print) -> dict[str, int]:
    """Prepare adjudication of the 25: review sheet, editable adjudicated copy, prefilled log.

    A disagreement is a (document, field) pair in ADJUDICATED_FIELDS where the
    validated human and LLM values differ ('unsure' is a value). The log rows
    carry the blind human and LLM values and leave ``final`` and ``note`` empty,
    so check_adjudication fails until the human fills them in.
    """
    out_dir = out_dir.expanduser().resolve()
    if out_dir.is_relative_to(REPO_DIR.resolve()):
        raise ValueError(f"--out-dir must be outside the repository ({REPO_DIR}); got {out_dir}")
    paths = {name: out_dir / name for name in (REVIEW_FILE, ADJUDICATED_FILE, LOG_FILE)}
    existing = [str(p) for p in paths.values() if p.exists()]
    if existing:
        raise ValueError(f"refusing to overwrite existing files: {existing}")
    llm, human = read_labels(llm_path), read_labels(human_path)
    missing = [d for d in human if d not in llm]
    if missing:
        raise ValueError(f"{llm_path.name}: missing {len(missing)} of the human-labelled documents")
    llm_raw, human_raw = _raw_rows(llm_path), _raw_rows(human_path)

    review, log, counts = [], [], Counter()
    for d in human:  # human sheet order
        h_row, m_row = human_raw[d], llm_raw[d]
        for field in ADJUDICATED_FIELDS:
            if human[d][field] == llm[d][field]:
                continue
            counts[field] += 1
            review.append({
                "item": h_row.get("item", ""), "field": field, "title": h_row.get("title", ""),
                "citation": h_row.get("citation", ""), "pdf_url": h_row.get("pdf_url", ""),
                **{f"human_{f}": human[d][f] for f in ADJUDICATED_FIELDS},
                "human_sections_at_issue": h_row.get("sections_at_issue", ""), "human_notes": h_row.get("notes", ""),
                **{f"llm_{f}": llm[d][f] for f in ADJUDICATED_FIELDS},
                "llm_sections_at_issue": m_row.get("sections_at_issue", ""), "llm_reason": m_row.get("reason", ""),
            })
            log.append({"doc_id": d, "field": field, "human_blind": human[d][field], "llm": llm[d][field],
                        "final": "", "note": ""})

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, columns, rows in ((REVIEW_FILE, REVIEW_COLUMNS, review), (LOG_FILE, LOG_COLUMNS, log)):
        with paths[name].open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    paths[ADJUDICATED_FILE].write_bytes(human_path.read_bytes())  # final labels: start from the blind human sheet

    summary = {f: counts[f] for f in ADJUDICATED_FIELDS}
    out(f"Disagreements: {len(log)} ({', '.join(f'{f} {n}' for f, n in summary.items())})")
    for p in paths.values():
        out(f"Wrote {p}")
    return summary


FINAL_VALUES = {"in_scope": LABEL_VALUES["in_scope"], "section_as_charge": LABEL_VALUES["section_as_charge"],
                "split_correct": LABEL_VALUES["split_correct"]}
BOM = b"\xef\xbb\xbf"


def _read_table(path: Path) -> dict[str, Any]:
    """Raw CSV table plus its byte format (BOM, line ending), so it can be rewritten unchanged elsewhere."""
    data = path.read_bytes()
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"), newline="")))
    if not rows:
        raise ValueError(f"{path.name}: empty file")
    return {"bom": data.startswith(BOM), "newline": "\r\n" if b"\r\n" in data else "\n",
            "header": rows[0], "rows": rows[1:]}


def _write_table(path: Path, table: dict[str, Any]) -> None:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator=table["newline"])
    writer.writerow(table["header"])
    writer.writerows(table["rows"])
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes((BOM if table["bom"] else b"") + buf.getvalue().encode("utf-8"))
    os.replace(tmp, path)


def _column(table: dict[str, Any], name: str, path: Path) -> int:
    if name not in table["header"]:
        raise ValueError(f"{path.name}: missing column {name!r}")
    return table["header"].index(name)


def apply_adjudication(review_final: Path, log_path: Path, adjudicated_path: Path, human_path: Path,
                       llm_path: Path, out: Callable[[str], None] = print) -> dict[str, Any]:
    """Apply the human's final labels from the review-final file to the log and adjudicated_25.csv.

    Review row i pairs with log row i. Every check runs before any write, and any
    failure aborts with nothing changed. Errors name row numbers or doc_ids, never
    labels. Both targets are backed up to <name>.bak first; afterwards
    check_adjudication runs on the written files (subset = doc_ids in --human).
    """
    with review_final.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        needed = ["field", "final", "note"] + [f"{who}_{fld}" for who in ("human", "llm") for fld in ADJUDICATED_FIELDS]
        missing_cols = [c for c in needed if c not in (reader.fieldnames or [])]
        if missing_cols:
            raise ValueError(f"{review_final.name}: missing columns {missing_cols}")
        review = [{k: (v or "").strip() for k, v in row.items() if k is not None} for row in reader]
    log = read_log(log_path)
    human, llm = read_labels(human_path), read_labels(llm_path)
    subset = list(human)

    if len(review) != len(log):
        raise ValueError(f"{review_final.name} has {len(review)} rows but {log_path.name} has {len(log)}; nothing changed")
    errors = []
    for i, (r, row) in enumerate(zip(review, log), start=1):
        field = r["field"].lower()
        if field not in ADJUDICATED_FIELDS:
            errors.append(f"row {i}: unknown field")
            continue
        if (row["field"], row["human_blind"], row["llm"]) != (field, r[f"human_{field}"].lower(), r[f"llm_{field}"].lower()):
            errors.append(f"row {i}: log field/human_blind/llm do not match the review row")
        elif row["doc_id"] not in human:
            errors.append(f"row {i}: log doc_id is not in the human sheet")
        elif row["human_blind"] != human[row["doc_id"]][field]:
            errors.append(f"row {i}: log human_blind does not match the blind human sheet")
        elif row["doc_id"] not in llm or row["llm"] != llm[row["doc_id"]][field]:
            errors.append(f"row {i}: log llm does not match the LLM sheet")
    if errors:
        raise ValueError("review and log do not pair up; nothing changed:\n  " + "\n  ".join(errors))

    incomplete = [i for i, r in enumerate(review, start=1)
                  if r["final"].lower() not in FINAL_VALUES[r["field"].lower()] or not r["note"]]
    if incomplete:
        raise ValueError(f"rows with an empty or invalid final, or an empty note: {incomplete}; nothing changed")

    table = _read_table(adjudicated_path)
    id_col = _column(table, "doc_id", adjudicated_path)
    ids = [row[id_col] if id_col < len(row) else "" for row in table["rows"]]
    current = read_labels(adjudicated_path)
    bad_ids = sorted({row["doc_id"] for row in log if ids.count(row["doc_id"]) != 1})
    if bad_ids:
        raise ValueError(f"{adjudicated_path.name}: doc_ids not present exactly once: {bad_ids}; nothing changed")
    edited = sorted(d for d in subset if d not in current
                    or any(current[d][fld] != human[d][fld] for fld in ADJUDICATED_FIELDS))
    if edited:
        raise ValueError(f"{adjudicated_path.name} already differs from the blind human sheet for: {edited}; "
                         "start from a fresh copy; nothing changed")

    log_table = _read_table(log_path)
    final_col, note_col = _column(log_table, "final", log_path), _column(log_table, "note", log_path)
    changed = 0
    for r, row, raw in zip(review, log, log_table["rows"]):
        final = r["final"].lower()
        raw += [""] * (max(final_col, note_col) + 1 - len(raw))
        raw[final_col], raw[note_col] = final, r["note"]
        if final != row["human_blind"]:
            target = table["rows"][ids.index(row["doc_id"])]
            col = _column(table, row["field"], adjudicated_path)
            target += [""] * (col + 1 - len(target))
            target[col] = final
            changed += 1
    inconsistent = []
    for d, raw in zip(ids, table["rows"]):
        try:
            parse_label_row(dict(zip(table["header"], raw)), d)
        except ValueError:
            inconsistent.append(d)
    if inconsistent:
        raise ValueError(f"result would break the label rules for: {sorted(inconsistent)}; nothing changed")

    baks = [p.with_name(p.name + ".bak") for p in (log_path, adjudicated_path)]
    existing = [str(b) for b in baks if b.exists()]
    if existing:
        raise ValueError(f"refusing to overwrite existing backups: {existing}; nothing changed")
    for src, bak in zip((log_path, adjudicated_path), baks):
        shutil.copyfile(src, bak)
    _write_table(log_path, log_table)
    _write_table(adjudicated_path, table)

    try:
        check_adjudication(subset, llm, human, read_labels(adjudicated_path), read_log(log_path))
        passed, problems = True, 0
    except ValueError as e:  # its message lists labels per item: report only the count
        passed, problems = False, max(1, str(e).count("\n  "))
    out(f"Applied {len(log)} rows; {changed} labels changed; check_adjudication: "
        + ("passed" if passed else f"FAILED ({problems} problems)"))
    return {"applied": len(log), "changed": changed, "check_passed": passed}


def _evaluate(items: list[dict[str, Any]], gold: dict[str, dict], key: dict[str, Any],
              resamples: int) -> dict[str, Any]:
    pop, seed = key["population"], key["seed"]
    return {"documents": len(items),
            "per_stratum_n": {s: sum(i["stratum"] == s for i in items) for s in STRATA},
            "primary": detector_metrics(items, gold, pop, "primary", "strict", seed, resamples),
            "secondary_loose_label": detector_metrics(items, gold, pop, "primary", "loose", seed, resamples),
            "sensitivity_loose_rule": detector_metrics(items, gold, pop, "loose", "strict", seed, resamples),
            "split": split_accuracy(items, gold, seed, resamples)}


def score(key: dict[str, Any], llm: dict, human: dict, adjudicated: dict, log: list[dict[str, str]],
          llm_run: dict[str, Any] | None = None, resamples: int = BOOTSTRAP_RESAMPLES) -> dict[str, Any]:
    """Option B scoring. Acceptance uses point estimates; intervals are reported beside them.

    ``llm`` covers all 55, ``human`` (blind) and ``adjudicated`` cover the 25 in
    key["human_subset"]. Kappa is LLM vs blind human on the 25. Gold is the
    adjudicated label on the 25 plus, only if kappa >= 0.70, the LLM label on
    the other 30.
    """
    items = key["sample"]
    subset = key.get("human_subset")
    if not subset:
        raise ValueError("validation_key.json has no human_subset; run `validation.py human-sheet` first")
    ids = [i["doc_id"] for i in items]
    missing = ([f"llm:{d}" for d in ids if d not in llm] + [f"human:{d}" for d in subset if d not in human]
               + [f"adjudicated:{d}" for d in subset if d not in adjudicated])
    if missing:
        raise ValueError(f"labels missing for: {missing}")
    agreement = {}
    for field in ADJUDICATED_FIELDS:
        xl, xh = [llm[d][field] for d in subset], [human[d][field] for d in subset]
        agreement[field] = {"kappa": cohen_kappa(xl, xh),
                            "raw_agreement": round(sum(x == y for x, y in zip(xl, xh)) / len(subset), 4)}
    adjudication = check_adjudication(subset, llm, human, adjudicated, log)
    kappa = agreement["in_scope"]["kappa"]
    llm_accepted = kappa is not None and kappa >= ACCEPTANCE["kappa"]

    in_subset = set(subset)
    gold = {d: adjudicated[d] for d in subset}
    if llm_accepted:
        gold |= {d: llm[d] for d in ids if d not in in_subset}
    main_items = [i for i in items if i["doc_id"] in gold]
    main = _evaluate(main_items, gold, key, resamples)
    human_only = _evaluate([i for i in items if i["doc_id"] in in_subset], gold, key, resamples)

    checks = {
        "kappa": llm_accepted,
        "weighted_precision": (main["primary"]["pooled_weighted"]["precision"] or 0) >= ACCEPTANCE["weighted_precision"],
        "split_accuracy": (main["split"]["accuracy"] or 0) >= ACCEPTANCE["split_accuracy"],
    }
    if all(checks.values()):
        verdict = "ACCEPTED"
    elif not llm_accepted:
        verdict = (f"INCOMPLETE: LLM-human kappa below {ACCEPTANCE['kappa']}; the other "
                   f"{len(ids) - len(subset)} documents await human labels (the main analysis is provisional, "
                   f"{len(subset)} documents only)")
    else:
        verdict = (f"NOT ACCEPTED: change the rule and validate on a fresh {SAMPLE_SIZE} "
                   f"(these {SAMPLE_SIZE} become development documents)")
    return {"design": "option_b", "agreement_llm_vs_human": agreement, "overlap": len(subset),
            "adjudication": adjudication, "llm_accepted_as_annotator": llm_accepted,
            "gold_sources": {"adjudicated_human": len(subset),
                             "llm": len(gold) - len(subset), "unused_pending_human": len(ids) - len(gold)},
            "main": main, "sensitivity_human_25": human_only, "llm_run": llm_run or {},
            "intervals": {"confidence": 0.95, "per_stratum": "wilson", "pooled_and_split": "stratified percentile bootstrap",
                          "bootstrap_resamples": resamples, "bootstrap_seed": key["seed"]},
            "acceptance": ACCEPTANCE, "acceptance_on": "point estimates", "checks": checks,
            "accepted": all(checks.values()), "verdict": verdict}


def _fmt(value: float | None, ci: list[float] | None) -> str:
    """'0.93 [0.81, 0.98]'; 'n/a' when the figure is undefined."""
    if value is None:
        return "n/a"
    return f"{value} [{ci[0]}, {ci[1]}]" if ci else str(value)


def _table(metrics: dict[str, Any]) -> str:
    lines = ["| Stratum | n | TP | FP | FN | TN | Precision [95% Wilson] | Recall [95% Wilson] |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for s, m in metrics["per_stratum"].items():
        lines.append(f"| {s} | {m['n']} | {m['tp']} | {m['fp']} | {m['fn']} | {m['tn']} | "
                     f"{_fmt(m['precision'], m['precision_ci'])} | {_fmt(m['recall'], m['recall_ci'])} |")
    return "\n".join(lines)


def _weighted_line(metrics: dict[str, Any]) -> str:
    w = metrics["pooled_weighted"]
    parts = []
    for name in ("precision", "recall"):
        text = f"{name} {_fmt(w[name], w[f'{name}_ci'])}"
        if w[f"{name}_undefined_replicates"]:
            text += f" ({w[f'{name}_undefined_replicates']} undefined bootstrap replicates dropped)"
        parts.append(text)
    return "; ".join(parts) + " (95% stratified bootstrap)"


def _unweighted_line(metrics: dict[str, Any]) -> str:
    u = metrics["pooled_unweighted"]
    return (f"precision {_fmt(u['precision'], u['precision_ci'])}; "
            f"recall {_fmt(u['recall'], u['recall_ci'])} (95% Wilson)")


def _analysis_block(bundle: dict[str, Any], heading: str) -> str:
    """Markdown for one analysis (main or 25-only): detector tables, sensitivity, split."""
    primary, secondary = bundle["primary"], bundle["secondary_loose_label"]
    loose, split = bundle["sensitivity_loose_rule"], bundle["split"]
    sections = "\n".join(
        f"| {g} | {m['tp']} | {m['fp']} | {m['fn']} | {_fmt(m['precision'], m['precision_ci'])} | "
        f"{_fmt(m['recall'], m['recall_ci'])} |"
        for g, m in primary["section_level_unweighted"].items()
    )
    split_per_stratum = "; ".join(f"{s} {_fmt(split['per_stratum'][s], split['per_stratum_ci'][s])}"
                                  for s in split["per_stratum"])
    return "\n".join([
        f"### {heading}: primary rule against the strict label (acceptance)",
        "",
        f"Documents: {bundle['documents']} (per stratum: {json.dumps(bundle['per_stratum_n'])}); "
        f"unsure excluded: {primary['unsure_excluded']} strict, {secondary['unsure_excluded']} loose.",
        "",
        _table(primary),
        "",
        f"- Weighted pooled: {_weighted_line(primary)}",
        f"- Unweighted pooled (reference only): {_unweighted_line(primary)}",
        "",
        "Section level (unweighted; pairs of document × section; 95% Wilson):",
        "",
        "| Group | TP | FP | FN | Precision | Recall |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        sections,
        "",
        f"### {heading}: primary rule against the loose label (secondary, not used for acceptance)",
        "",
        _table(secondary),
        "",
        f"- Weighted pooled: {_weighted_line(secondary)}",
        "",
        f"### {heading}: looser rule against the strict label (sensitivity, not used to choose the rule)",
        "",
        _table(loose),
        "",
        f"- Weighted pooled: {_weighted_line(loose)}",
        "",
        f"### {heading}: headnote / body split",
        "",
        f"- Accuracy over {split['judged']} judged documents (unweighted share; 95% stratified bootstrap): "
        f"**{_fmt(split['accuracy'], split['accuracy_ci'])}**",
        f"- Per stratum (95% Wilson): {split_per_stratum}",
    ])


def _kappa(value: float | None) -> str:
    return "undefined (both used one identical label)" if value is None else str(value)


def render_report(result: dict[str, Any], key: dict[str, Any]) -> str:
    agreement, run = result["agreement_llm_vs_human"], result["llm_run"]
    adj, sources = result["adjudication"], result["gold_sources"]
    quotas = key["quotas"].values()
    not_recorded = "NOT RECORDED"
    main_heading = "All adjudicated documents" if result["llm_accepted_as_annotator"] else "Provisional (25 only)"
    return Template(TEMPLATE_PATH.read_text(encoding="utf-8")).substitute(
        seed=key["seed"], population=json.dumps(key["population"]), quotas=json.dumps(key["quotas"]),
        min_quota=min(quotas), max_quota=max(quotas), human_per_stratum=HUMAN_PER_STRATUM,
        human_subset_seed=key.get("human_subset_seed", not_recorded), overlap=result["overlap"],
        resamples=result["intervals"]["bootstrap_resamples"],
        llm_model=", ".join(run.get("models", [])) or not_recorded,
        llm_requested_model=run.get("requested_model", not_recorded),
        prompt_template=run.get("prompt_template", not_recorded),
        prompt_sha256=run.get("prompt_sha256", not_recorded),
        cli_version=run.get("cli_version", not_recorded),
        llm_dates=", ".join(run.get("dates", [])) or not_recorded,
        kappa=_kappa(agreement["in_scope"]["kappa"]), raw_agreement=agreement["in_scope"]["raw_agreement"],
        kappa_charge=_kappa(agreement["section_as_charge"]["kappa"]),
        raw_agreement_charge=agreement["section_as_charge"]["raw_agreement"],
        kappa_split=_kappa(agreement["split_correct"]["kappa"]),
        raw_agreement_split=agreement["split_correct"]["raw_agreement"],
        llm_accepted="yes" if result["llm_accepted_as_annotator"] else "no",
        disagreements=json.dumps(adj["disagreements"]), changed=json.dumps(adj["changed_from_blind_human"]),
        gold_human=sources["adjudicated_human"], gold_llm=sources["llm"], gold_pending=sources["unused_pending_human"],
        main_block=_analysis_block(result["main"], main_heading),
        human_block=_analysis_block(result["sensitivity_human_25"], "Human-labelled 25 only"),
        checks=json.dumps(result["checks"]), verdict=result["verdict"],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work-dir", type=Path, default=sc_source.DEFAULT_WORK_DIR)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("summary", help="aggregate detector counts over all candidates (no per-document output)")
    sheet = sub.add_parser("sheet", help=f"draw the {SAMPLE_SIZE} + 5, write the key and the calibration sheet")
    sheet.add_argument("--seed", type=int, default=DEFAULT_SEED)
    sub.add_parser("human-sheet", help=f"record the human subset in the key and write {HUMAN_SHEET}")
    scoring = sub.add_parser("score", help="Option B: LLM-human agreement, adjudication check and metrics")
    scoring.add_argument("--llm", type=Path, required=True, help="validation_sheet_LLM.csv (all 55)")
    scoring.add_argument("--human", type=Path, required=True, help=f"blind {HUMAN_SHEET}, filled in")
    scoring.add_argument("--adjudicated", type=Path, required=True, help="adjudicated_25.csv (final labels)")
    scoring.add_argument("--log", type=Path, required=True, help="adjudication_log.csv")
    scoring.add_argument("--llm-run", type=Path, default=None, help="llm_run.json (default: <work-dir>/validation/)")
    dis = sub.add_parser("disagreements", help="write the adjudication review sheet, adjudicated copy and prefilled log")
    dis.add_argument("--llm", type=Path, required=True, help="validation_sheet_LLM.csv (all 55)")
    dis.add_argument("--human", type=Path, required=True, help=f"blind {HUMAN_SHEET}, filled in")
    dis.add_argument("--out-dir", type=Path, required=True, help="directory outside the repository")
    app = sub.add_parser("apply-adjudication", help="apply final labels to the log and adjudicated_25.csv, then check")
    app.add_argument("--review-final", type=Path, required=True, help="adjudication_review_final.csv (+ final, note)")
    app.add_argument("--log", type=Path, required=True, help="adjudication_log.csv")
    app.add_argument("--adjudicated", type=Path, required=True, help="adjudicated_25.csv")
    app.add_argument("--human", type=Path, required=True, help=f"blind {HUMAN_SHEET}; its doc_ids are the subset")
    app.add_argument("--llm", type=Path, required=True, help="validation_sheet_LLM.csv (all 55)")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    work_dir = args.work_dir.expanduser()
    if args.command == "summary":
        print(json.dumps(pool_summary(work_dir), indent=1))
        return 0
    if args.command == "sheet":
        make_sheets(work_dir, args.seed)
        return 0
    if args.command == "human-sheet":
        make_human_sheet(work_dir)
        return 0
    if args.command == "disagreements":
        write_disagreements(args.llm, args.human, args.out_dir)
        return 0
    if args.command == "apply-adjudication":
        result = apply_adjudication(args.review_final, args.log, args.adjudicated, args.human, args.llm)
        return 0 if result["check_passed"] else 1
    target = work_dir / "validation"
    key = json.loads((target / "validation_key.json").read_text(encoding="utf-8"))
    run_path = args.llm_run or target / "llm_run.json"
    llm_run = json.loads(run_path.read_text(encoding="utf-8")) if run_path.is_file() else None
    result = score(key, read_labels(args.llm), read_labels(args.human), read_labels(args.adjudicated),
                   read_log(args.log), llm_run)
    (target / "validation_result.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    report = render_report(result, key)
    (target / "validation_report.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
