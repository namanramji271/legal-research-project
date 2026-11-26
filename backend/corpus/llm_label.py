"""LLM annotator for the corpus v2 validation (Option B; see validation.py).

One fresh ``claude -p`` session per document, run in resumable checkpoint
batches (default 10 documents per batch). Each session:
  - has no tools (``--tools ""``), no MCP servers, no settings sources and no
    saved session, and runs in a new empty temporary directory, so it cannot
    read validation_key.json, validation.py, the detector or any other file;
  - receives on stdin only the committed prompt template
    (corpus/llm_label_prompt.md) filled with the annotation guideline and this
    one document's title, citation, extracted headnote, first 600 characters
    of the body and full body. No doc_id, stratum, detector output or other
    document's labels are ever put in the prompt.
Only this parent process reads the key (to know which 55 documents to label).

Outputs in <work-dir>/validation/:
  llm_labels.jsonl          checkpoint, one line per labelled document (resume state)
  validation_sheet_LLM.csv  sheet columns + reason (work-dir only: reasons quote the judgment)
  validation_labels_LLM_no_text.csv  same without the reason column (the copy to commit later)
  llm_run.json              disclosure: model ids, prompt/guideline SHA-256, CLI version, dates

Usage:
    python backend/corpus/llm_label.py --dry-run          # token estimate, no calls
    python backend/corpus/llm_label.py --max-batches 1    # label the next 10 documents
    python backend/corpus/llm_label.py                    # label everything still pending
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from string import Template
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from corpus import sc_source  # noqa: E402
from corpus.pdf_pipeline import load_records  # noqa: E402
from corpus.validation import LABEL_VALUES, SHEET_COLUMNS  # noqa: E402

PROMPT_PATH = Path(__file__).with_name("llm_label_prompt.md")
GUIDELINE_PATH = Path(__file__).with_name("annotation_guideline.md")
DEFAULT_MODEL = "claude-sonnet-5-5"
BATCH_SIZE = 10
BODY_OPENING_CHARS = 600
ORDER_SEED_OFFSET = 3  # labelling order: seed + 3 (sample seed, calibration + 1, human subset + 2)
# Estimates only (--dry-run), calibrated on a probe: an 11.4k-char prompt used 5,560 input tokens and
# ~400 output tokens. Deliberately conservative.
CHARS_PER_TOKEN = 3.0
CALL_OVERHEAD_TOKENS = 1_500  # Claude Code's own context + output schema per call
OUTPUT_TOKENS_PER_DOC = (500, 2_000)  # labels + reason + thinking

STATE_FILE = "llm_labels.jsonl"
LLM_SHEET = "validation_sheet_LLM.csv"
PUBLIC_SHEET = "validation_labels_LLM_no_text.csv"
RUN_FILE = "llm_run.json"
LLM_COLUMNS = SHEET_COLUMNS + ("reason",)
LABEL_FIELDS = ("in_scope", "section_as_charge", "sections_at_issue", "passing_sections", "split_correct",
                "notes", "reason")
PAYLOAD_FIELDS = ("title", "citation", "headnote", "body_opening", "body")

SYSTEM_PROMPT = ("You are a careful legal annotator. Label the single judgment you are given strictly by the "
                 "annotation guideline in the message. Use only the text provided. Reply with the JSON object only.")
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "in_scope": {"type": "string", "enum": list(LABEL_VALUES["in_scope"])},
        "section_as_charge": {"type": "string", "enum": list(LABEL_VALUES["section_as_charge"])},
        "sections_at_issue": {"type": "string"},
        "passing_sections": {"type": "string"},
        "split_correct": {"type": "string", "enum": list(LABEL_VALUES["split_correct"])},
        "notes": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": list(LABEL_FIELDS),
    "additionalProperties": False,
}

Runner = Callable[..., subprocess.CompletedProcess]


class LabelError(RuntimeError):
    """The labeller returned unusable output or the CLI call failed."""


# --- prompt -------------------------------------------------------------------

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def document_payload(record: dict[str, Any], meta: dict[str, Any]) -> dict[str, str]:
    """The only document fields the labeller sees. Deliberately no doc_id, stratum or detector output."""
    body = record.get("body", "")
    return {"title": meta.get("title", "") or "(none)", "citation": meta.get("citation", "") or "(none)",
            "headnote": record.get("headnote", "") or "(none extracted)",
            "body_opening": body[:BODY_OPENING_CHARS], "body": body}


def build_prompt(payload: dict[str, str], template: str, guideline: str) -> str:
    if set(payload) != set(PAYLOAD_FIELDS):
        raise ValueError(f"payload fields must be exactly {PAYLOAD_FIELDS}")
    template = re.sub(r"<!--.*?-->\s*", "", template, flags=re.S)  # maintainer comments are not sent
    return Template(template).substitute(guideline=guideline.strip(), **payload)


def labelling_order(key: dict[str, Any]) -> list[str]:
    """All 55 sample doc_ids in a seeded order that does not group strata."""
    ids = sorted(i["doc_id"] for i in key["sample"])
    random.Random(key["seed"] + ORDER_SEED_OFFSET).shuffle(ids)
    return ids


# --- the call -------------------------------------------------------------------

def claude_command(executable: str, model: str) -> list[str]:
    return [executable, "-p", "--model", model, "--tools", "", "--strict-mcp-config", "--setting-sources", "",
            "--no-session-persistence", "--output-format", "json", "--json-schema", json.dumps(OUTPUT_SCHEMA),
            "--system-prompt", SYSTEM_PROMPT]


def _parse_labels(result: dict[str, Any]) -> dict[str, Any]:
    labels = result.get("structured_output")
    if labels is None:
        text = (result.get("result") or "").strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        try:
            labels = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LabelError(f"labeller output is not JSON: {exc}") from None
    if not isinstance(labels, dict):
        raise LabelError("labeller output is not a JSON object")
    return labels


def validate_labels(labels: dict[str, Any]) -> dict[str, str]:
    """Same rules as validation.read_labels, plus a non-empty reason."""
    missing = [f for f in LABEL_FIELDS if f not in labels]
    if missing:
        raise LabelError(f"labeller output misses {missing}")
    out = {f: str(labels[f]).strip() for f in LABEL_FIELDS}
    for f in ("in_scope", "section_as_charge", "split_correct"):
        out[f] = out[f].lower()
        if out[f] not in LABEL_VALUES[f]:
            raise LabelError(f"{f} must be one of {LABEL_VALUES[f]}, got {out[f]!r}")
    if out["in_scope"] == "yes" and out["section_as_charge"] == "yes":
        raise LabelError("section_as_charge must be no when in_scope is yes")
    for f in ("sections_at_issue", "passing_sections"):
        out[f] = ";".join(re.findall(r"\d{2,3}[A-Z]?", out[f]))
    if not out["reason"]:
        raise LabelError("reason is empty")
    return out


def label_document(prompt: str, model: str, runner: Runner = subprocess.run,
                   executable: str | None = None) -> tuple[dict[str, str], dict[str, Any]]:
    """One fresh tool-less session in an empty temporary directory. Returns (labels, call metadata)."""
    executable = executable or shutil.which("claude")
    if not executable:
        raise LabelError("the `claude` CLI is not on PATH")
    with tempfile.TemporaryDirectory(prefix="llm_label_") as empty:
        proc = runner(claude_command(executable, model), input=prompt, capture_output=True, text=True,
                      encoding="utf-8", cwd=empty, timeout=900)
    if proc.returncode != 0:
        raise LabelError(f"claude exited {proc.returncode}: {(proc.stderr or proc.stdout or '')[:500]}")
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise LabelError(f"claude printed non-JSON output: {proc.stdout[:300]!r}") from None
    if result.get("is_error"):
        raise LabelError(f"claude reported an error: {str(result.get('result'))[:500]}")
    labels = validate_labels(_parse_labels(result))
    usage = result.get("usage", {})
    meta = {"models": sorted(result.get("modelUsage", {})) or [model],
            "input_tokens": sum(usage.get(k, 0) for k in
                                ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
            "output_tokens": usage.get("output_tokens", 0),
            "cost_usd_equivalent": result.get("total_cost_usd")}
    return labels, meta


# --- resumable run --------------------------------------------------------------

def load_state(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def estimate_tokens(prompts: list[str]) -> dict[str, int]:
    inputs = sum(len(p) for p in prompts) / CHARS_PER_TOKEN + CALL_OVERHEAD_TOKENS * len(prompts)
    return {"documents": len(prompts), "input_tokens": round(inputs),
            "output_tokens_low": OUTPUT_TOKENS_PER_DOC[0] * len(prompts),
            "output_tokens_high": OUTPUT_TOKENS_PER_DOC[1] * len(prompts),
            "largest_prompt_tokens": round(max((len(p) for p in prompts), default=0) / CHARS_PER_TOKEN)
                                     + CALL_OVERHEAD_TOKENS}


def write_outputs(target: Path, order: list[str], state: dict[str, dict], key: dict[str, Any],
                  model: str, cli_version: str, candidates: dict[str, dict]) -> None:
    # Metadata only; body_starts_with stays empty (judgment text).
    candidates_meta = {d: {c: candidates.get(d, {}).get(c, "") for c in ("title", "citation", "pdf_url")}
                       for d in order}
    for columns, path in ((LLM_COLUMNS, target / LLM_SHEET), (SHEET_COLUMNS, target / PUBLIC_SHEET)):
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for i, doc_id in enumerate(order, start=1):
                row = state[doc_id]
                writer.writerow({"item": i, "doc_id": doc_id, **candidates_meta.get(doc_id, {}),
                                 **{f: row["labels"][f] for f in LABEL_FIELDS}})
    run = {"requested_model": model, "models": sorted({m for r in state.values() for m in r["models"]}),
           "prompt_template": "backend/corpus/llm_label_prompt.md", "prompt_sha256": next(iter(state.values()))["prompt_sha256"],
           "guideline_sha256": next(iter(state.values()))["guideline_sha256"], "cli_version": cli_version,
           "dates": sorted({r["date"] for r in state.values()}), "documents": len(state),
           "seed": key["seed"], "order_seed": key["seed"] + ORDER_SEED_OFFSET,
           "input_tokens": sum(r["input_tokens"] for r in state.values()),
           "output_tokens": sum(r["output_tokens"] for r in state.values())}
    (target / RUN_FILE).write_text(json.dumps(run, indent=1) + "\n", encoding="utf-8")


def run(work_dir: Path, model: str = DEFAULT_MODEL, batch_size: int = BATCH_SIZE, max_batches: int | None = None,
        dry_run: bool = False, runner: Runner = subprocess.run, executable: str | None = None,
        out: Callable[[str], None] = print) -> dict[str, Any]:
    target = work_dir / "validation"
    key = json.loads((target / "validation_key.json").read_text(encoding="utf-8"))
    order = labelling_order(key)
    state_path = target / STATE_FILE
    state = {r["doc_id"]: r for r in load_state(state_path)}
    prompt_sha, guideline_sha = sha256(PROMPT_PATH), sha256(GUIDELINE_PATH)
    stale = {r["prompt_sha256"] for r in state.values()} | {r["guideline_sha256"] for r in state.values()}
    if stale - {prompt_sha, guideline_sha}:
        raise LabelError("the prompt template or guideline changed since labelling started; refusing to mix "
                         f"versions (move {state_path.name} aside to start over)")
    pending = [d for d in order if d not in state]
    batches = [pending[i:i + batch_size] for i in range(0, len(pending), batch_size)]
    template, guideline = PROMPT_PATH.read_text(encoding="utf-8"), GUIDELINE_PATH.read_text(encoding="utf-8")
    candidates = {r["doc_id"]: r for r in load_records(work_dir / "candidates.jsonl")}

    def prompt_for(doc_id: str) -> str:
        record = json.loads((work_dir / "text" / f"{doc_id}.json").read_text(encoding="utf-8"))
        return build_prompt(document_payload(record, candidates.get(doc_id, {})), template, guideline)

    if dry_run:
        todo = batches[:max_batches] if max_batches else batches
        estimate = estimate_tokens([prompt_for(d) for b in todo for d in b])
        out(f"Documents: {len(order)} in sample, {len(state)} done, {len(pending)} pending "
            f"({len(batches)} batches of up to {batch_size}); this run would label {estimate['documents']}")
        out(f"Estimated input tokens: ~{estimate['input_tokens']:,} (largest single prompt "
            f"~{estimate['largest_prompt_tokens']:,}); output ~{estimate['output_tokens_low']:,}-"
            f"{estimate['output_tokens_high']:,} incl. thinking. Model: {model}. No calls made.")
        return estimate

    executable = executable or shutil.which("claude")
    if not executable:
        raise LabelError("the `claude` CLI is not on PATH")
    version = runner([executable, "--version"], capture_output=True, text=True, encoding="utf-8")
    cli_version = (version.stdout or "").strip() or "unknown"
    for b, batch in enumerate(batches[:max_batches] if max_batches else batches, start=1):
        for doc_id in batch:
            prompt = prompt_for(doc_id)
            for attempt in (1, 2):
                try:
                    labels, meta = label_document(prompt, model, runner, executable)
                    break
                except LabelError as exc:
                    if attempt == 2:
                        raise LabelError(f"stopped after 2 failed attempts on item {len(state) + 1} of "
                                         f"{len(order)} ({exc}); finished items are saved, rerun to resume") from None
            row = {"doc_id": doc_id, "labels": labels, **meta, "requested_model": model,
                   "prompt_sha256": prompt_sha, "guideline_sha256": guideline_sha, "cli_version": cli_version,
                   "date": datetime.now(timezone.utc).date().isoformat()}
            with state_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            state[doc_id] = row
        out(f"Batch {b}: labelled {len(batch)} documents ({len(state)}/{len(order)} done)")
    if len(state) == len(order):
        write_outputs(target, order, state, key, model, cli_version, candidates)
        out(f"All {len(order)} labelled. Wrote {target / LLM_SHEET}, {target / PUBLIC_SHEET}, {target / RUN_FILE}")
    else:
        out(f"{len(order) - len(state)} documents still pending; rerun to continue")
    return {"done": len(state), "total": len(order)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work-dir", type=Path, default=sc_source.DEFAULT_WORK_DIR)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--max-batches", type=int, default=None, help="stop after this many batches")
    parser.add_argument("--dry-run", action="store_true", help="estimate tokens only; make no calls")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        run(args.work_dir.expanduser(), args.model, args.batch_size, args.max_batches, args.dry_run)
    except LabelError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
