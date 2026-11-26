"""Screen sampled pre-filter non-candidates with the full-text IPC detector.

Purpose: estimate what the headnote pre-filter misses. Every sampled
non-candidate is run through corpus/ipc_detect.py; only documents with at
least one accepted in-scope mention (body or headnote) are listed, with a few
short evidence snippets, for a human to read and decide. Unflagged documents
still count in the denominator.

Run after the sample's PDFs have been downloaded and extracted with
pdf_pipeline.py --ids-file <sample>:
    python backend/corpus/screen_noncandidates.py \\
        --sample <work-dir>/noncandidate_sample_criminal_seed20261126_n100.json

Reads <work-dir>/text/ only. Writes <work-dir>/screening/<sample>_flagged.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from corpus import sc_source  # noqa: E402
from corpus.ipc_detect import detect, normalise, summarise  # noqa: E402

SNIPPETS_PER_DOC = 3
SNIPPET_CHARS = 80  # each side of the reference


def evidence(text: str, limit: int = SNIPPETS_PER_DOC) -> list[str]:
    text = normalise(text)
    snippets = []
    for mention in detect(text).accepted()[:limit]:
        start, end = max(0, mention.start - SNIPPET_CHARS), mention.end + SNIPPET_CHARS
        snippets.append(f"[{mention.section} {mention.kind}] ..." + re.sub(r"\s+", " ", text[start:end]) + "...")
    return snippets


def screen(sample_path: Path, work_dir: Path, out: Callable[[str], None] = print) -> dict[str, Any]:
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    documents = sample["documents"]
    flagged, missing = [], []
    for doc in documents:
        text_file = work_dir / "text" / f"{doc['doc_id']}.json"
        if not text_file.is_file():
            missing.append(doc["doc_id"])
            continue
        record = json.loads(text_file.read_text(encoding="utf-8"))
        if record.get("error"):
            missing.append(doc["doc_id"])
            continue
        summary = summarise(record)
        if not (summary["body_counts"] or summary["headnote_counts"]):
            continue
        flagged.append({
            "doc_id": doc["doc_id"], "era": doc.get("era"), "title": doc.get("title"),
            "case_type": doc.get("case_type"), "pdf_url": doc.get("pdf_url"),
            "split_method": record.get("split_method"),
            "body_counts": summary["body_counts"], "headnote_counts": summary["headnote_counts"],
            "in_scope_by_rule": summary["in_scope"], "included_sections": summary["included_sections"],
            "evidence_body": evidence(record.get("body", "")),
            "evidence_headnote": evidence(record.get("headnote", ""), limit=1),
            "human_decision": None,  # to fill in: in_scope | not_in_scope | unsure
        })
    screened = len(documents) - len(missing)
    result = {
        "sample": sample_path.name, "pool": sample.get("pool"), "seed": sample.get("seed"),
        "documents": len(documents), "screened": screened, "missing_text": missing,
        "flagged": len(flagged), "flagged_in_scope_by_rule": sum(f["in_scope_by_rule"] for f in flagged),
        "flagged_documents": flagged,
    }
    target_dir = work_dir / "screening"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{sample_path.stem}_flagged.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    out(f"{sample_path.name}: {screened}/{len(documents)} screened, {len(missing)} without text, "
        f"{len(flagged)} flagged ({result['flagged_in_scope_by_rule']} pass the inclusion rule)")
    for f in flagged:
        out(f"\n- {f['doc_id']} [{f['era']}] {f['case_type']} | {f['title'][:70]}")
        out(f"  body {f['body_counts']} | headnote {f['headnote_counts']} | rule: {f['in_scope_by_rule']}")
        for snippet in f["evidence_headnote"] + f["evidence_body"]:
            out(f"    {snippet}")
        out(f"  {f['pdf_url']}")
    out(f"\nWrote {target}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work-dir", type=Path, default=sc_source.DEFAULT_WORK_DIR)
    parser.add_argument("--sample", type=Path, action="append", required=True, help="sample JSON (repeatable)")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    for sample in args.sample:
        screen(sample.expanduser(), args.work_dir.expanduser())
    return 0


if __name__ == "__main__":
    sys.exit(main())
