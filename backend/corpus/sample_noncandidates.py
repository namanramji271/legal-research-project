"""Seeded, era-stratified sample of headnote pre-filter non-candidates.

Purpose: estimate what the pre-filter misses. Annotators read the sampled
PDFs and mark any that are in scope (IPC 96-106 / 299-304 at issue).

Run after census.py (reads <work-dir>/non_candidates.jsonl):
    python backend/corpus/sample_noncandidates.py                  # 20 docs, all non-candidates
    python backend/corpus/sample_noncandidates.py --pool criminal  # only criminal case types

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


def stratified_sample(records: list[dict[str, Any]], n: int, seed: int) -> list[dict[str, Any]]:
    """Equal allocation across eras (remainder to the earliest eras); seeded and order-independent."""
    rng = random.Random(seed)
    by_era = {e: sorted((r for r in records if r["era"] == e), key=lambda r: r["doc_id"]) for e in ERA_LABELS}
    base, extra = divmod(n, len(ERA_LABELS))
    sample = []
    for i, e in enumerate(ERA_LABELS):
        quota = base + (1 if i < extra else 0)
        pool = by_era[e]
        sample += rng.sample(pool, min(quota, len(pool)))
    return [{k: r[k] for k in FIELDS} for r in sample]


def run(work_dir: Path, n: int = DEFAULT_N, seed: int = DEFAULT_SEED, pool: str = "all",
        out: Callable[[str], None] = print) -> list[dict[str, Any]]:
    source = work_dir / "non_candidates.jsonl"
    if not source.is_file():
        raise FileNotFoundError(f"{source} not found; run census.py first")
    records = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    if pool == "criminal":
        records = [r for r in records if r["criminal"]]
    sample = stratified_sample(records, n, seed)
    target = work_dir / f"noncandidate_sample_{pool}_seed{seed}.json"
    target.write_text(json.dumps({"pool": pool, "seed": seed, "n": n, "pool_size": len(records),
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
    args = parser.parse_args(argv)
    if args.n <= 0:
        parser.error("--n must be positive")
    sys.stdout.reconfigure(encoding="utf-8")
    run(args.work_dir.expanduser(), args.n, args.seed, args.pool)
    return 0


if __name__ == "__main__":
    sys.exit(main())
