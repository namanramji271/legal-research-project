"""Download and extract corpus v2 judgment PDFs (standalone, resumable CLI).

Run from the repository root, e.g. in its own terminal:
    python backend/corpus/pdf_pipeline.py                     # all census candidates
    python backend/corpus/pdf_pipeline.py --trial 20          # seeded trial: half pre-1980
    python backend/corpus/pdf_pipeline.py --ids-file <work-dir>/noncandidate_sample_criminal_seed20261126_n100.json
    python backend/corpus/pdf_pipeline.py --download-only     # or --extract-only

Everything goes to the work dir (default ~/.cache/legal-research/sc_v2):
- pdf/<doc_id>_EN.pdf       downloaded over anonymous HTTPS
- pdf_manifest.jsonl        one line per download: url, bytes, ETag, SHA-256, status
- text/<doc_id>.json        extracted text split into headnote / proceedings / body

Safe to stop with Ctrl+C and rerun: files are written to a temporary name
and renamed when complete, finished downloads and extractions are skipped.
Downloads use a few threads with retries and back-off on 429/5xx/timeouts.

Headnote/body split for Supreme Court Reports PDFs, in this order:
headnote, then the procedural block starting "CRIMINAL/CIVIL APPELLATE (or
ORIGINAL) JURISDICTION: ..." (appeal number, counsel), then "The Judgment of
the Court was delivered by ...", then the judgment. split_method records
which markers were found: jurisdiction+delivered, jurisdiction+heading,
jurisdiction+digital_heading (Digital SCR, 2024-: "Judgment / Order of the
Supreme Court" / "Judgment"), jurisdiction, delivered, or none (then body =
full text, headnote empty).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from corpus import sc_source  # noqa: E402
from corpus.prefilter import ERAS, era  # noqa: E402

DEFAULT_WORKERS = 4
DEFAULT_EXTRACT_WORKERS = max(1, min(4, (os.cpu_count() or 2) - 1))
RETRIES = 4
BACKOFF_SECONDS = 5.0
TIMEOUT_SECONDS = 60.0
FULL_PAGE_IMAGE_SHARE = 0.8
DATA_LOSS = "Data-loss while decompressing corrupted data"
EXCLUDED_STATUSES = ("failed", "missing", "extraction_failed")
DEV_DOCS_PATH = BACKEND_DIR / "corpus" / "dev_docs.json"
ERA_LABELS = [f"{a}-{b}" for a, b in ERAS]

Opener = Callable[[str], tuple[bytes, dict[str, str]]]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- selection ----------------------------------------------------------------

def load_records(path: Path) -> list[dict[str, Any]]:
    """Records with doc_id, year and pdf_url from a .jsonl file or a sample .json."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        data = json.loads(text)
        records = data["documents"] if isinstance(data, dict) else data
    for r in records:
        r.setdefault("pdf_url", sc_source.pdf_url(int(r["year"]), r["doc_id"]))
        r.setdefault("era", era(int(r["year"])))
    return records


def load_dev_ids(path: Path = DEV_DOCS_PATH) -> set[str]:
    if not path.is_file():
        return set()
    return {d["doc_id"] for d in json.loads(path.read_text(encoding="utf-8"))["documents"]}


def select_trial(records: list[dict[str, Any]], n: int, pre1980: int, seed: int,
                 exclude: set[str]) -> list[dict[str, Any]]:
    """n documents: ``pre1980`` from before 1980, the rest spread over the later eras."""
    rng = random.Random(seed)
    pool = sorted((r for r in records if r["doc_id"] not in exclude), key=lambda r: r["doc_id"])
    early = [r for r in pool if int(r["year"]) < 1980]
    chosen = rng.sample(early, min(pre1980, len(early)))
    later_eras = [e for e in ERA_LABELS if int(e[:4]) >= 1980]
    rest = n - len(chosen)
    for i, e in enumerate(later_eras):
        quota = rest // len(later_eras) + (1 if i < rest % len(later_eras) else 0)
        in_era = [r for r in pool if r["era"] == e]
        chosen += rng.sample(in_era, min(quota, len(in_era)))
    return chosen


# --- download -----------------------------------------------------------------

def pdf_path(work_dir: Path, doc_id: str) -> Path:
    return work_dir / "pdf" / f"{doc_id}_EN.pdf"


def text_path(work_dir: Path, doc_id: str) -> Path:
    return work_dir / "text" / f"{doc_id}.json"


class Manifest:
    """Append-only JSONL of download results; the last line per doc_id wins."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.state: dict[str, dict[str, Any]] = {}
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    record = json.loads(line)
                    self.state[record["doc_id"]] = record

    def append(self, record: dict[str, Any]) -> None:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
                f.flush()
            self.state[record["doc_id"]] = record


def http_open(url: str) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": sc_source.USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read(), dict(response.headers.items())


def _is_complete(manifest: Manifest, record: dict[str, Any], dest: Path) -> bool:
    previous = manifest.state.get(record["doc_id"])
    return bool(previous and previous.get("status") in ("ok", "extraction_failed") and dest.is_file()
                and dest.stat().st_size == previous.get("bytes"))


def download_one(record: dict[str, Any], work_dir: Path, manifest: Manifest,
                 opener: Opener = http_open, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    doc_id, url = record["doc_id"], record["pdf_url"]
    dest = pdf_path(work_dir, doc_id)
    if _is_complete(manifest, record, dest):
        return {**manifest.state[doc_id], "skipped": True}
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_error = ""
    for attempt in range(1, RETRIES + 1):
        try:
            data, headers = opener(url)
        except urllib.error.HTTPError as error:
            if error.code in (403, 404):
                result = {"doc_id": doc_id, "url": url, "status": "missing", "http_status": error.code,
                          "attempts": attempt, "fetched_at": now()}
                manifest.append(result)
                return result
            last_error = f"HTTP {error.code}"
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            last_error = f"{type(error).__name__}: {error}"
        else:
            partial = dest.with_suffix(".part")
            partial.write_bytes(data)
            partial.replace(dest)
            headers = {k.lower(): v for k, v in headers.items()}
            result = {
                "doc_id": doc_id, "year": int(record["year"]), "url": url, "status": "ok",
                "bytes": len(data), "etag": headers.get("etag", "").strip('"'),
                "sha256": hashlib.sha256(data).hexdigest(), "attempts": attempt, "fetched_at": now(),
            }
            manifest.append(result)
            return result
        if attempt < RETRIES:
            sleep(BACKOFF_SECONDS * attempt)
    result = {"doc_id": doc_id, "url": url, "status": "failed", "error": last_error,
              "attempts": RETRIES, "fetched_at": now()}
    manifest.append(result)
    return result


def download_all(records: list[dict[str, Any]], work_dir: Path, workers: int = DEFAULT_WORKERS,
                 opener: Opener = http_open, sleep: Callable[[float], None] = time.sleep,
                 out: Callable[[str], None] = print) -> dict[str, Any]:
    manifest = Manifest(work_dir / "pdf_manifest.jsonl")
    started = time.monotonic()
    counts: Counter[str] = Counter()
    fetched_bytes = 0
    executor = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = [executor.submit(download_one, r, work_dir, manifest, opener, sleep) for r in records]
        for i, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            key = "skipped" if result.get("skipped") else result["status"]
            counts[key] += 1
            if key == "ok":
                fetched_bytes += result["bytes"]
            if key in ("failed", "missing"):
                out(f"  {result['doc_id']}: {key} {result.get('error') or result.get('http_status')}")
            if i % 100 == 0 or i == len(futures):
                out(f"download {i}/{len(futures)}: {dict(counts)} {fetched_bytes / 1e6:.0f} MB")
    except KeyboardInterrupt:
        out("Interrupted: cancelling queued downloads, letting in-flight ones finish...")
        # Wait for in-flight downloads (at most `workers`, each bounded by the timeout)
        # so the manifest and pdf/ are consistent when this returns.
        executor.shutdown(wait=True, cancel_futures=True)
        out("Finished downloads are kept; rerun to resume.")
        raise
    executor.shutdown(wait=True)
    seconds = time.monotonic() - started
    return {"counts": dict(counts), "mb": round(fetched_bytes / 1e6, 1), "seconds": round(seconds, 1),
            "mb_per_s": round(fetched_bytes / 1e6 / seconds, 2) if seconds else None}


# --- headnote / body split ----------------------------------------------------

# The procedural block's first line, near a line start, tolerant of OCR. Either an
# uppercase JURISDICTION (I/1/l, 0/O, U/V swaps; "CalMINArt~PBLLATB JURISDICTION:"),
# or an uppercase APPELLATE/ORIGINAL followed by one garbled word and a colon
# ("APPELLATE JURISnICTION :", "APPELLATE JURISDI~ION :", "CRIMINALAPPELLATE jLJRISDICTION :").
# Case-sensitive, so a headnote's "appellate court" or "jurisdiction" does not match.
JURISDICTION = re.compile(
    r"(?m)^[^\n]{0,60}?(?:(?<![A-Za-z])[JI][UV]R[I1lL]SD[I1lL]CT[I1lL][O0]N\b|(?:APPELLATE|ORIGINAL)[ \t]?[JjIL]\S{3,15}[ \t]?:)"
)
# "The Judgment of the Court was delivered by", "The Judgment of P. N. Bhagwati and
# R. S. Sarkaria was delivered", possibly wrapped over one line break; OCR may
# garble "was" ("wai delivered, by").
DELIVERED = re.compile(
    r"(?i)\b(?:judgment|judgement|order|opinion)s?\b(?:[^\n]|\n(?!\s*\n)){0,160}?"
    r"\b(?:was|were|w[a-z0-9]{1,2})\s+deliv[a-z0-9~]*\b[^\n]*"
)
# A standalone heading line: JUDGMENT / J U D G M E N T / ORDER / O R D E R.
HEADING = re.compile(r"(?m)^[ \t]*(?:J\s?U\s?D\s?G\s?E?\s?M\s?E\s?N\s?T|O\s?R\s?D\s?E\s?R)[ \t]*:?[ \t]*$")
# Digital SCR layout (2024-): a title-case "Judgment / Order of the Supreme Court" line,
# usually followed by a "Judgment" or "Order" line, then the authoring judge. Case-sensitive;
# only tried after the jurisdiction line when neither DELIVERED nor HEADING matched.
DIGITAL_HEADING = re.compile(
    r"(?m)^[ \t]*Judgment\s*/\s*Order\s+of\s+the\s+Supreme\s+Court[ \t]*$(?:\n[ \t]*(?:Judgment|Order)[ \t]*$)?"
)
PROCEEDINGS_WINDOW = 8000  # max distance from the jurisdiction line to the body marker


def split_headnote_body(text: str) -> dict[str, Any]:
    j = JURISDICTION.search(text)
    start = j.start() if j else 0
    window_end = start + PROCEEDINGS_WINDOW if j else int(len(text) * 0.6)
    d = DELIVERED.search(text, start, window_end)
    h = HEADING.search(text, start, window_end) if j and not d else None
    g = DIGITAL_HEADING.search(text, start, window_end) if j and not d and not h else None

    if j and d:
        method, head, proceedings, body = "jurisdiction+delivered", text[:j.start()], text[j.start():d.end()], text[d.end():]
    elif j and h:
        method, head, proceedings, body = "jurisdiction+heading", text[:j.start()], text[j.start():h.end()], text[h.end():]
    elif j and g:
        method, head, proceedings, body = ("jurisdiction+digital_heading", text[:j.start()], text[j.start():g.end()],
                                           text[g.end():])
    elif j:
        method, head, proceedings, body = "jurisdiction", text[:j.start()], "", text[j.start():]
    elif d:
        method, head, proceedings, body = "delivered", text[:d.start()], text[d.start():d.end()], text[d.end():]
    else:
        method, head, proceedings, body = "none", "", "", text

    total = max(len(text), 1)
    suspect = method != "none" and (len(head) > 0.6 * total or len(body.strip()) < 1000)
    return {"split_method": method, "split_suspect": suspect,
            "headnote": head.strip(), "proceedings": proceedings.strip(), "body": body.strip()}


# --- extraction ---------------------------------------------------------------

def read_pages(path: Path) -> list[tuple[str, bool]]:
    """(text, is_full_page_image) per page."""
    import pdfplumber

    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            area = float(page.width * page.height) or 1.0
            full_image = any((i["width"] * i["height"]) / area > FULL_PAGE_IMAGE_SHARE for i in page.images)
            pages.append((page.extract_text() or "", full_image))
    return pages


def expected_pages(doc_id: str) -> int | None:
    """Page count implied by the SCR page range in the id ('1975_1_906_913' -> 8)."""
    match = re.fullmatch(r"(?:S_)?\d{4}_\d+_(\d+)_(\d+)", doc_id)
    if not match:
        return None
    first, last = int(match.group(1)), int(match.group(2))
    return last - first + 1 if last >= first else None


class _WarningCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def extract_one(doc_id: str, source: str, target: str) -> dict[str, Any]:
    """Top-level so it can run in a process pool.

    A pdfminer "Data-loss while decompressing corrupted data" warning means
    part of the PDF could not be read: it is recorded as an extraction error.
    """
    started = time.monotonic()
    capture = _WarningCapture()
    pdfminer_log = logging.getLogger("pdfminer")
    pdfminer_log.addHandler(capture)
    try:
        pages = read_pages(Path(source))
        text = "\n".join(t for t, _ in pages)
        image_pages = sum(img for _, img in pages)
        data_loss = [m for m in capture.messages if DATA_LOSS in m]
        result = {
            "doc_id": doc_id, "error": f"data loss: {data_loss[0]}" if data_loss else None,
            "pages": len(pages), "expected_pages": expected_pages(doc_id), "chars": len(text),
            "empty_pages": sum(len(t.strip()) < 50 for t, _ in pages), "image_pages": image_pages,
            "scanned": bool(pages) and image_pages >= 0.8 * len(pages),
            "warnings": sorted(set(capture.messages))[:5],
            **split_headnote_body(text),
        }
    except Exception as error:  # a broken PDF must not stop the batch
        result = {"doc_id": doc_id, "error": f"{type(error).__name__}: {error}", "pages": 0, "chars": 0,
                  "split_method": None, "headnote": "", "proceedings": "", "body": ""}
    finally:
        pdfminer_log.removeHandler(capture)
    result["seconds"] = round(time.monotonic() - started, 2)
    result["extracted_at"] = now()
    partial = Path(target).with_suffix(".part")
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    partial.replace(target)
    return {k: v for k, v in result.items() if k not in ("headnote", "proceedings", "body")}


def extract_all(doc_ids: Iterable[str], work_dir: Path, workers: int = DEFAULT_EXTRACT_WORKERS,
                force: bool = False, out: Callable[[str], None] = print) -> dict[str, Any]:
    jobs = [(d, str(pdf_path(work_dir, d)), str(text_path(work_dir, d))) for d in doc_ids
            if pdf_path(work_dir, d).is_file() and (force or not text_path(work_dir, d).is_file())]
    started = time.monotonic()
    done = 0
    if not jobs:
        return {"extracted": 0, "seconds": 0.0}
    if workers <= 1:  # inline: easier to debug, and test monkeypatches apply
        for done, job in enumerate(jobs, start=1):
            result = extract_one(*job)
            if result["error"]:
                out(f"  {result['doc_id']}: extraction failed: {result['error']}")
        return {"extracted": done, "seconds": round(time.monotonic() - started, 1)}
    executor = ProcessPoolExecutor(max_workers=workers)
    try:
        futures = [executor.submit(extract_one, *job) for job in jobs]
        for done, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            if result["error"]:
                out(f"  {result['doc_id']}: extraction failed: {result['error']}")
            if done % 50 == 0 or done == len(futures):
                out(f"extract {done}/{len(futures)} ({time.monotonic() - started:.0f}s)")
    except KeyboardInterrupt:
        executor.shutdown(wait=False, cancel_futures=True)
        out("Interrupted: finished extractions are kept; rerun to resume.")
        raise
    executor.shutdown(wait=True)
    return {"extracted": done, "seconds": round(time.monotonic() - started, 1)}


# --- report -------------------------------------------------------------------

def report(records: list[dict[str, Any]], work_dir: Path) -> dict[str, Any]:
    rows = []
    for r in records:
        path = text_path(work_dir, r["doc_id"])
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            rows.append({**{k: v for k, v in data.items() if k not in ("headnote", "proceedings", "body")},
                         "era": r["era"], "headnote_chars": len(data.get("headnote", "")),
                         "body_chars": len(data.get("body", ""))})
    by_era: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        by_era[row["era"]][row["split_method"] or "error"] += 1
    ok = [row for row in rows if not row["error"]]
    pages = sum(row["pages"] for row in ok)
    return {
        "documents": len(records), "extracted": len(rows), "failures": [r["doc_id"] for r in rows if r["error"]],
        "split_by_era": {e: dict(by_era[e]) for e in ERA_LABELS if e in by_era},
        "split_suspect": [row["doc_id"] for row in ok if row.get("split_suspect")],
        "scanned": sum(bool(row.get("scanned")) for row in ok), "pages": pages,
        "extract_seconds_total": round(sum(row["seconds"] for row in ok), 1),
        "seconds_per_page": round(sum(row["seconds"] for row in ok) / pages, 3) if pages else None,
    }


def excluded_ids(work_dir: Path) -> set[str]:
    """Documents whose last manifest status is failed, missing or extraction_failed."""
    manifest = Manifest(work_dir / "pdf_manifest.jsonl")
    return {d for d, r in manifest.state.items() if r.get("status") in EXCLUDED_STATUSES}


def redo(records: list[dict[str, Any]], work_dir: Path, opener: Opener = http_open,
         sleep: Callable[[float], None] = time.sleep, out: Callable[[str], None] = print) -> list[dict[str, Any]]:
    """Re-download once (ignoring the skip check) and re-extract each record.

    Reports whether ETag/size/SHA-256 changed. If extraction still fails, an
    ``extraction_failed`` line is appended to the manifest: the document is
    then excluded from the corpus and not re-fetched by normal runs.
    """
    manifest = Manifest(work_dir / "pdf_manifest.jsonl")
    outcomes = []
    for record in records:
        doc_id = record["doc_id"]
        before = dict(manifest.state.get(doc_id) or {})
        manifest.state.pop(doc_id, None)  # force a fresh download
        fetched = download_one(record, work_dir, manifest, opener, sleep)
        same = {k: before.get(k) == fetched.get(k) for k in ("etag", "bytes", "sha256")}
        extracted = (extract_one(doc_id, str(pdf_path(work_dir, doc_id)), str(text_path(work_dir, doc_id)))
                     if fetched["status"] == "ok" else {"error": f"download {fetched['status']}"})
        outcome = {"doc_id": doc_id, "download": fetched["status"], "unchanged": same,
                   "error": extracted.get("error"), "pages": extracted.get("pages"),
                   "expected_pages": extracted.get("expected_pages")}
        if extracted.get("error") and fetched["status"] == "ok":
            manifest.append({**fetched, "status": "extraction_failed", "error": extracted["error"],
                             "fetched_at": now()})
            outcome["recorded"] = "extraction_failed"
        out(f"{doc_id}: download {fetched['status']}, unchanged {same}, "
            f"extraction {'failed: ' + str(extracted.get('error')) if extracted.get('error') else 'ok'}")
        outcomes.append(outcome)
    return outcomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--redo", nargs="+", metavar="DOC_ID", default=None,
                        help="re-download and re-extract these documents; record extraction_failed if still failing")
    parser.add_argument("--work-dir", type=Path, default=sc_source.DEFAULT_WORK_DIR)
    parser.add_argument("--ids-file", type=Path, default=None,
                        help="records to process (.jsonl or sample .json); default <work-dir>/candidates.jsonl")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--trial", type=int, default=None, help="process a seeded trial of N candidates")
    parser.add_argument("--trial-pre1980", type=int, default=None, help="pre-1980 documents in the trial (default N/2)")
    parser.add_argument("--seed", type=int, default=20261126)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="download threads")
    parser.add_argument("--extract-workers", type=int, default=DEFAULT_EXTRACT_WORKERS)
    stage = parser.add_mutually_exclusive_group()
    stage.add_argument("--download-only", action="store_true")
    stage.add_argument("--extract-only", action="store_true")
    parser.add_argument("--force-extract", action="store_true", help="re-extract even if text exists")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    work_dir = args.work_dir.expanduser()

    records = load_records(args.ids_file or work_dir / "candidates.jsonl")
    if args.redo:
        by_id = {r["doc_id"]: r for r in records}
        unknown = [d for d in args.redo if d not in by_id]
        if unknown:
            parser.error(f"not in {args.ids_file or 'candidates.jsonl'}: {unknown}")
        redo([by_id[d] for d in args.redo], work_dir)
        return 0
    if args.trial:
        pre = args.trial // 2 if args.trial_pre1980 is None else args.trial_pre1980
        records = select_trial(records, args.trial, pre, args.seed, exclude=load_dev_ids())
        (work_dir / "trial_ids.json").write_text(
            json.dumps({"seed": args.seed, "documents": records}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Trial: {len(records)} documents ({sum(int(r['year']) < 1980 for r in records)} pre-1980), "
              f"ids in {work_dir / 'trial_ids.json'}")
    if args.limit:
        records = records[: args.limit]

    try:
        if not args.extract_only:
            summary = download_all(records, work_dir, args.workers)
            print(f"Downloads: {summary}")
        if not args.download_only:
            summary = extract_all([r["doc_id"] for r in records], work_dir, args.extract_workers, args.force_extract)
            print(f"Extraction: {summary}")
            print(json.dumps(report(records, work_dir), indent=1))
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
