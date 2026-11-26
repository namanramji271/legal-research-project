"""Corpus v2 census: metadata-only counts for the headnote pre-filter.

Run from the repository root (downloads ~50 MB of metadata, no PDFs):
    python backend/corpus/census.py
    python backend/corpus/census.py --work-dir D:/sc_v2 --skip-download

Writes to the work dir (default ~/.cache/legal-research/sc_v2), never to
backend/data/:
- census.json        counts only
- candidates.jsonl   one line per candidate: ids, metadata and pre-filter
                     result, no judgment text

Reports: rows and duplicates, headnote-present rate by decade, case types,
candidates by reason, by era x section group (all groups and primary
group), and the criminal share of candidates and non-candidates.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from corpus import sc_source  # noqa: E402
from corpus.prefilter import ERAS, GROUP_ORDER, decade, era, prefilter  # noqa: E402

ERA_LABELS = [f"{a}-{b}" for a, b in ERAS]


def annotate(frame: Any) -> list[dict[str, Any]]:
    """One record per metadata row: parsed listing + pre-filter result."""
    records = []
    for row in frame.itertuples(index=False):
        listing = sc_source.parse_listing(row.raw_html)
        result = prefilter(listing.headnote_excerpt)
        year = int(row.year)
        records.append(
            {
                "doc_id": row.path,
                "year": year,
                "era": era(year),
                "decade": decade(year),
                "title": row.title,
                "citation": row.citation,
                "case_id": row.case_id,
                "decision_date": row.decision_date,
                "case_type": listing.case_type,
                "criminal": sc_source.is_criminal_case_type(listing.case_type),
                "coram": listing.coram,
                "author_judge": listing.author_judge,
                "bench_size": listing.bench_size,
                "has_headnote": listing.has_headnote,
                "candidate": result.candidate,
                "reasons": list(result.reasons),
                "headnote_sections": list(result.sections),
                "groups": list(result.groups),
                "primary_group": result.primary_group,
                "pdf_url": sc_source.pdf_url(year, row.path),
            }
        )
    return records


def _share(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def summarize(records: list[dict[str, Any]], duplicates_dropped: int) -> dict[str, Any]:
    total = len(records)
    candidates = [r for r in records if r["candidate"]]
    non_candidates = [r for r in records if not r["candidate"]]

    by_decade: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_decade[r["decade"]].append(r)
    headnote_by_decade = {
        d: {"documents": len(rs), "with_headnote": sum(r["has_headnote"] for r in rs),
            "rate": _share(sum(r["has_headnote"] for r in rs), len(rs))}
        for d, rs in sorted(by_decade.items())
    }

    def era_table(key: Callable[[dict[str, Any]], list[str]]) -> dict[str, dict[str, int]]:
        table = {g: {e: 0 for e in ERA_LABELS} for g in GROUP_ORDER}
        for r in candidates:
            for g in key(r):
                table[g][r["era"]] += 1
        for g in table:
            table[g]["total"] = sum(table[g][e] for e in ERA_LABELS)
        return table

    reasons = Counter(reason for r in candidates for reason in r["reasons"])
    return {
        "source": sc_source.SOURCE,
        "metadata_rows_unique": total,
        "duplicate_rows_dropped": duplicates_dropped,
        "years": [min(r["year"] for r in records), max(r["year"] for r in records)] if records else [],
        "headnote_present_by_decade": headnote_by_decade,
        "case_types_top": Counter(r["case_type"] or "(none)" for r in records).most_common(10),
        "criminal_case_type": {"all": sum(r["criminal"] for r in records), "share": _share(sum(r["criminal"] for r in records), total)},
        "candidates": len(candidates),
        "candidate_reasons": dict(reasons),
        "candidates_by_era": {e: sum(r["era"] == e for r in candidates) for e in ERA_LABELS},
        "candidates_by_era_and_group_all": era_table(lambda r: r["groups"]),
        "candidates_by_era_and_primary_group": era_table(lambda r: [r["primary_group"]]),
        "candidates_criminal": {"count": sum(r["criminal"] for r in candidates), "share": _share(sum(r["criminal"] for r in candidates), len(candidates))},
        "non_candidates": len(non_candidates),
        "non_candidates_criminal": sum(r["criminal"] for r in non_candidates),
        "non_candidates_by_era": {e: sum(r["era"] == e for r in non_candidates) for e in ERA_LABELS},
    }


def render(summary: dict[str, Any]) -> str:
    lines = [
        f"Source: {summary['source']}",
        f"Unique documents: {summary['metadata_rows_unique']} (duplicate rows dropped: {summary['duplicate_rows_dropped']}), years {summary['years']}",
        "",
        "Headnote present by decade (listing excerpt):",
    ]
    for d, v in summary["headnote_present_by_decade"].items():
        lines.append(f"  {d}: {v['with_headnote']}/{v['documents']} = {v['rate']:.2%}")
    lines += [
        "",
        f"Criminal case types: {summary['criminal_case_type']['all']} ({summary['criminal_case_type']['share']:.1%})",
        f"Candidates: {summary['candidates']}  reasons: {summary['candidate_reasons']}",
        f"Candidates criminal: {summary['candidates_criminal']['count']} ({summary['candidates_criminal']['share']:.1%})",
        f"Non-candidates: {summary['non_candidates']} (criminal: {summary['non_candidates_criminal']})",
    ]
    for title, key in (("all groups (multi-label)", "candidates_by_era_and_group_all"),
                       ("primary group (rarest first)", "candidates_by_era_and_primary_group")):
        lines += ["", f"Candidates by era x section group, {title}:",
                  "  " + f"{'group':16s}" + "".join(f"{e:>11s}" for e in ERA_LABELS) + f"{'total':>8s}"]
        for group, row in summary[key].items():
            lines.append("  " + f"{group:16s}" + "".join(f"{row[e]:>11d}" for e in ERA_LABELS) + f"{row['total']:>8d}")
    return "\n".join(lines)


def run(work_dir: Path, skip_download: bool = False, fetch: sc_source.Fetch = sc_source.http_get,
        out: Callable[[str], None] = print) -> dict[str, Any]:
    if not skip_download:
        sc_source.download_metadata(work_dir, fetch=fetch, out=out)
    frame, duplicates = sc_source.load_metadata(work_dir)
    records = annotate(frame)
    summary = summarize(records, duplicates)
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "census.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with (work_dir / "candidates.jsonl").open("w", encoding="utf-8") as f:
        for r in records:
            if r["candidate"]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (work_dir / "non_candidates.jsonl").open("w", encoding="utf-8") as f:
        for r in records:
            if not r["candidate"]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    out(render(summary))
    out(f"\nWrote {work_dir / 'census.json'}, candidates.jsonl, non_candidates.jsonl")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work-dir", type=Path, default=sc_source.DEFAULT_WORK_DIR)
    parser.add_argument("--skip-download", action="store_true", help="use metadata already in the work dir")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    run(args.work_dir.expanduser(), skip_download=args.skip_download)
    return 0


if __name__ == "__main__":
    sys.exit(main())
