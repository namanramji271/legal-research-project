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
    python backend/corpus/validation.py score --llm <validation_sheet_LLM.csv>
        --human <validation_sheet_human_25.csv> --adjudicated <adjudicated_25.csv>
        --log <adjudication_log.csv>       (one command; wrapped here)

Files go to <work-dir>/validation/ (titles and IDs; no judgment text).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
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

def read_labels(path: Path) -> dict[str, dict[str, Any]]:
    labels = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            where = f"{path.name} item {row.get('item')}"
            in_scope = row["in_scope"].strip().lower()
            charge = row.get("section_as_charge", "").strip().lower()
            split = row.get("split_correct", "").strip().lower()
            if in_scope not in LABEL_VALUES["in_scope"]:
                raise ValueError(f"{where}: in_scope must be yes/no/unsure, got {in_scope!r}")
            if charge not in LABEL_VALUES["section_as_charge"]:
                raise ValueError(f"{where}: section_as_charge must be yes/no, got {charge!r}")
            if in_scope == "yes" and charge == "yes":
                raise ValueError(f"{where}: section_as_charge must be no when in_scope is yes (the court decides it)")
            if split and split not in LABEL_VALUES["split_correct"]:
                raise ValueError(f"{where}: split_correct must be yes/no/na")
            labels[row["doc_id"]] = {
                "in_scope": in_scope,
                "section_as_charge": charge,
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


def score(key: dict[str, Any], a: dict, b: dict, adjudicated: dict,
          resamples: int = BOOTSTRAP_RESAMPLES) -> dict[str, Any]:
    """Agreement, detector and split metrics. Acceptance uses point estimates; intervals are reported beside them."""
    items = key["sample"]
    ids = [i["doc_id"] for i in items]
    missing = [d for d in ids if d not in a or d not in b or d not in adjudicated]
    if missing:
        raise ValueError(f"labels missing for: {missing}")
    agreement = {}
    for field in ("in_scope", "section_as_charge"):
        xa, xb = [a[d][field] for d in ids], [b[d][field] for d in ids]
        agreement[field] = {"kappa": cohen_kappa(xa, xb),
                            "raw_agreement": round(sum(x == y for x, y in zip(xa, xb)) / len(ids), 4)}
    pop, seed = key["population"], key["seed"]
    primary = detector_metrics(items, adjudicated, pop, "primary", "strict", seed, resamples)
    secondary = detector_metrics(items, adjudicated, pop, "primary", "loose", seed, resamples)
    sensitivity = detector_metrics(items, adjudicated, pop, "loose", "strict", seed, resamples)
    split = split_accuracy(items, adjudicated, seed, resamples)
    kappa = agreement["in_scope"]["kappa"]
    checks = {
        "kappa": kappa is not None and kappa >= ACCEPTANCE["kappa"],
        "weighted_precision": (primary["pooled_weighted"]["precision"] or 0) >= ACCEPTANCE["weighted_precision"],
        "split_accuracy": (split["accuracy"] or 0) >= ACCEPTANCE["split_accuracy"],
    }
    return {"agreement": agreement, "primary": primary, "secondary_loose_label": secondary,
            "sensitivity_loose_rule": sensitivity, "split": split,
            "intervals": {"confidence": 0.95, "per_stratum": "wilson", "pooled_and_split": "stratified percentile bootstrap",
                          "bootstrap_resamples": resamples, "bootstrap_seed": seed},
            "acceptance": ACCEPTANCE, "acceptance_on": "point estimates", "checks": checks,
            "accepted": all(checks.values())}


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


def render_report(result: dict[str, Any], key: dict[str, Any]) -> str:
    primary, secondary = result["primary"], result["secondary_loose_label"]
    loose = result["sensitivity_loose_rule"]
    agreement, split = result["agreement"], result["split"]
    sections = "\n".join(
        f"| {g} | {m['tp']} | {m['fp']} | {m['fn']} | {_fmt(m['precision'], m['precision_ci'])} | "
        f"{_fmt(m['recall'], m['recall_ci'])} |"
        for g, m in primary["section_level_unweighted"].items()
    )
    split_per_stratum = "; ".join(f"{s} {_fmt(split['per_stratum'][s], split['per_stratum_ci'][s])}"
                                  for s in split["per_stratum"])
    quotas = key["quotas"].values()
    return Template(TEMPLATE_PATH.read_text(encoding="utf-8")).substitute(
        seed=key["seed"], population=json.dumps(key["population"]), quotas=json.dumps(key["quotas"]),
        min_quota=min(quotas), max_quota=max(quotas), resamples=result["intervals"]["bootstrap_resamples"],
        kappa=agreement["in_scope"]["kappa"], raw_agreement=agreement["in_scope"]["raw_agreement"],
        kappa_charge=agreement["section_as_charge"]["kappa"],
        raw_agreement_charge=agreement["section_as_charge"]["raw_agreement"],
        primary_table=_table(primary), primary_weighted=_weighted_line(primary),
        primary_unweighted=_unweighted_line(primary),
        section_table=sections,
        secondary_table=_table(secondary), secondary_weighted=_weighted_line(secondary),
        secondary_unsure=secondary["unsure_excluded"],
        loose_table=_table(loose), loose_weighted=_weighted_line(loose),
        split_accuracy=_fmt(split["accuracy"], split["accuracy_ci"]), split_per_stratum=split_per_stratum,
        unsure=primary["unsure_excluded"],
        checks=json.dumps(result["checks"]), verdict="ACCEPTED" if result["accepted"] else
        f"NOT ACCEPTED: change the rule and validate on a fresh {SAMPLE_SIZE} (these {SAMPLE_SIZE} become development documents)",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work-dir", type=Path, default=sc_source.DEFAULT_WORK_DIR)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("summary", help="aggregate detector counts over all candidates (no per-document output)")
    sheet = sub.add_parser("sheet", help=f"draw the {SAMPLE_SIZE} + 5, write the key and the calibration sheet")
    sheet.add_argument("--seed", type=int, default=DEFAULT_SEED)
    sub.add_parser("human-sheet", help=f"record the human subset in the key and write {HUMAN_SHEET}")
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
    if args.command == "human-sheet":
        make_human_sheet(work_dir)
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
