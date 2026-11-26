"""Seeded, era-stratified sample of headnote pre-filter non-candidates.

Purpose: estimate what the pre-filter misses. Annotators read the sampled
PDFs and mark any that are in scope (IPC 96-106 / 299-304 at issue).

Run after census.py (reads <work-dir>/non_candidates.jsonl):
    python backend/corpus/sample_noncandidates.py                  # 20 docs, all non-candidates
    python backend/corpus/sample_noncandidates.py --pool criminal  # only criminal case types
    python backend/corpus/sample_noncandidates.py --pool criminal --n 100         --include <work-dir>/noncandidate_sample_criminal_seed20261126.json   # grow to 100

Writes <work-dir>/noncandidate_sample_<pool>_seed<seed>.json (ids, metadata,
PDF URLs; no text). PDFs are not downloaded here.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from corpus import sc_source  # noqa: E402
from corpus.prefilter import ERAS  # noqa: E402

ERA_LABELS = [f"{a}-{b}" for a, b in ERAS]
DEFAULT_N = 20
DEFAULT_SEED = 20261126
FIELDS = ("doc_id", "year", "era", "title", "citation", "case_id", "case_type", "criminal", "pdf_url")


def stratified_sample(
    records: list[dict[str, Any]], n: int, seed: int, include: list[str] | None = None
) -> list[dict[str, Any]]:
    """Equal allocation across eras (remainder to the earliest eras); seeded and order-independent.

    ``include``: doc_ids that must be in the sample (e.g. a smaller sample drawn
    earlier). They count towards their era's quota; the rest of each quota is
    drawn from the remaining pool.
    """
    rng = random.Random(seed)
    by_id = {r["doc_id"]: r for r in records}
    missing = [d for d in (include or []) if d not in by_id]
    if missing:
        raise ValueError(f"included doc_ids are not in the pool: {missing}")
    kept = [by_id[d] for d in (include or [])]
    kept_ids = {r["doc_id"] for r in kept}
    by_era = {
        e: sorted((r for r in records if r["era"] == e and r["doc_id"] not in kept_ids), key=lambda r: r["doc_id"])
        for e in ERA_LABELS
    }
    base, extra = divmod(n, len(ERA_LABELS))
    sample = []
    for i, e in enumerate(ERA_LABELS):
        quota = base + (1 if i < extra else 0)
        already = [r for r in kept if r["era"] == e]
        pool = by_era[e]
        sample += already + rng.sample(pool, max(0, min(quota - len(already), len(pool))))
    return [{k: r[k] for k in FIELDS} for r in sample]


def run(work_dir: Path, n: int = DEFAULT_N, seed: int = DEFAULT_SEED, pool: str = "all",
        out: Callable[[str], None] = print, include_file: Path | None = None) -> list[dict[str, Any]]:
    source = work_dir / "non_candidates.jsonl"
    if not source.is_file():
        raise FileNotFoundError(f"{source} not found; run census.py first")
    records = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    if pool == "criminal":
        records = [r for r in records if r["criminal"]]
    include = None
    if include_file is not None:
        include = [d["doc_id"] for d in json.loads(include_file.read_text(encoding="utf-8"))["documents"]]
    sample = stratified_sample(records, n, seed, include)
    target = work_dir / (
        f"noncandidate_sample_{pool}_seed{seed}_n{n}.json" if include is not None
        else f"noncandidate_sample_{pool}_seed{seed}.json"
    )
    target.write_text(json.dumps({"pool": pool, "seed": seed, "n": n, "pool_size": len(records),
                                  "included_from": include_file.name if include_file else None,
                                  "documents": sample}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    out(f"Pool: {pool} non-candidates ({len(records)}); sampled {len(sample)} with seed {seed}")
    for r in sample:
        out(f"  {r['era']}  {r['doc_id']:22s} {r['case_type'][:28]:28s} {r['title'][:60]}")
    out(f"Wrote {target}")
    return sample


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work-dir", type=Path, default=sc_source.DEFAULT_WORK_DIR)
    parser.add_argument("--n", type=int, default=DEFAULT_N)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--pool", choices=("all", "criminal"), default="all")
    parser.add_argument("--include", type=Path, default=None,
                        help="earlier sample JSON whose documents must be kept (sample grows, never changes)")
    args = parser.parse_args(argv)
    if args.n <= 0:
        parser.error("--n must be positive")
    sys.stdout.reconfigure(encoding="utf-8")
    run(args.work_dir.expanduser(), args.n, args.seed, args.pool, include_file=args.include)
    return 0


if __name__ == "__main__":
    sys.exit(main())
