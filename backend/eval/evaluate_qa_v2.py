"""Compare snippet and full-context QA with a resumable local response cache.

Run from the repository root with:
    python backend/eval/evaluate_qa_v2.py

The default 15-second pause respects the observed Gemini free-tier request
limit. Cached prompts are reused on every subsequent run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
EVAL_DIR = Path(__file__).resolve().parent
QUESTIONS_PATH = EVAL_DIR / "test_qa_questions.json"
CACHE_DIR = EVAL_DIR / "cache"
FINDINGS_PATH = EVAL_DIR / "qa_v2_findings.md"
QA_N_RESULTS = 5
CONTEXT_MODES = ("snippet", "full")
INSUFFICIENT_CONTEXT_PATTERNS = (
    r"no relevant judgments were found",
    r"not enough information",
    r"insufficient information",
    r"does not contain (?:enough )?information",
    r"do not contain (?:enough )?information",
    r"cannot answer.*(?:context|information|sources)",
    r"unable to answer.*(?:context|information|sources)",
)

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import qa  # noqa: E402
from search import search_judgments  # noqa: E402


def _step2_dense_cases(query: str, n_cases: int, **_kwargs: Any) -> list[dict[str, Any]]:
    """Pin this experiment to the dense 5-chunk retrieval it was started with.

    Production /ask now follows RETRIEVER (see config.py). This snippet-vs-full
    comparison keeps the original retrieval so cached prompts stay valid and
    the remaining calls are comparable with the completed ones.
    """
    return search_judgments(query, n_results=n_cases)


qa.retrieve_cases = _step2_dense_cases


def _cache_key(prompt: str) -> str:
    return hashlib.sha256(f"{qa.MODEL_NAME}{prompt}".encode("utf-8")).hexdigest()


def _cache_path(cache_key: str) -> Path:
    return CACHE_DIR / f"{cache_key}.json"


def _is_insufficient_context(answer: Any) -> bool:
    answer_text = str(answer or "").strip()
    if not answer_text:
        return True
    return any(
        re.search(pattern, answer_text, flags=re.IGNORECASE | re.DOTALL)
        for pattern in INSUFFICIENT_CONTEXT_PATTERNS
    )


def _is_quota_error(error: BaseException) -> bool:
    pending: BaseException | None = error
    seen: set[int] = set()
    while pending is not None and id(pending) not in seen:
        seen.add(id(pending))
        status = getattr(pending, "status_code", None) or getattr(pending, "code", None)
        message = f"{pending} {getattr(pending, 'detail', '')}".lower()
        if status == 429 or any(
            marker in message
            for marker in ("429", "quota", "resource_exhausted", "rate limit")
        ):
            return True
        pending = pending.__cause__ or pending.__context__
    return False


def _prepare_tasks(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build exact prompts in advance so pending cache misses can be counted."""
    tasks: list[dict[str, Any]] = []
    for question_index, entry in enumerate(questions):
        chunks = _step2_dense_cases(entry["question"], QA_N_RESULTS)
        for context_mode in CONTEXT_MODES:
            prompt = (
                qa.build_prompt(entry["question"], chunks, context_mode=context_mode)
                if chunks
                else None
            )
            tasks.append(
                {
                    "question_index": question_index,
                    "question": entry["question"],
                    "expected_answerable": bool(entry["expected_answerable"]),
                    "context_mode": context_mode,
                    "prompt_key": _cache_key(prompt) if prompt is not None else None,
                }
            )
    return tasks


def _remaining_cache_misses(tasks: list[dict[str, Any]], start_index: int) -> int:
    pending_keys = {
        task["prompt_key"]
        for task in tasks[start_index:]
        if task["prompt_key"] is not None
        and not _cache_path(task["prompt_key"]).is_file()
    }
    return len(pending_keys)


def _write_findings(
    status: str,
    questions: list[dict[str, Any]],
    task_results: list[dict[str, Any]],
    api_calls: int,
    cache_hits: int,
    calls_remaining: int,
    stopped_reason: str | None,
) -> None:
    summary: dict[str, dict[str, int]] = {}
    for mode in CONTEXT_MODES:
        mode_results = [result for result in task_results if result["context_mode"] == mode]
        summary[mode] = {
            "completed": len(mode_results),
            "verified": sum(bool(result["verified"]) for result in mode_results),
            "answer_decline_match": sum(
                bool(result["answer_decline_match"]) for result in mode_results
            ),
        }

    lines = [
        "# QA Context Evaluation v2",
        "",
        f"- Run status: **{status}**",
        f"- Model: `{qa.MODEL_NAME}`",
        f"- Questions: {len(questions)}; expected requests: {len(questions) * len(CONTEXT_MODES)} context/question pairs",
        f"- Uncached Gemini prompt calls this run: {api_calls}; disk-cache hits: {cache_hits}",
        f"- Uncached evaluation calls remaining: {calls_remaining}",
    ]
    if stopped_reason:
        lines.append(f"- Stop reason: {stopped_reason}")
    lines.extend(
        [
            "",
            "`answer/decline match` means answerable questions did not decline and unanswerable questions did decline, using the established refusal-pattern check.",
            "",
            "| Context mode | Completed | Verified | Answer/decline matches |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for mode in CONTEXT_MODES:
        values = summary[mode]
        lines.append(
            f"| {mode} | {values['completed']}/{len(questions)} | "
            f"{values['verified']}/{values['completed']} | "
            f"{values['answer_decline_match']}/{values['completed']} |"
        )
    lines.extend(["", "## Per-question outcomes", "", "| # | Context | Verified | Answer/decline match |", "| ---: | --- | --- | --- |"])
    for result in task_results:
        lines.append(
            f"| {result['question_index'] + 1} | {result['context_mode']} | "
            f"{result['verified']} | {result['answer_decline_match']} |"
        )
    lines.append("")
    FINDINGS_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=15.0,
        help="pause between uncached Gemini generations (default: 15)",
    )
    args = parser.parse_args()
    if args.delay_seconds < 0:
        parser.error("--delay-seconds must be non-negative")

    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tasks = _prepare_tasks(questions)
    task_results: list[dict[str, Any]] = []
    api_calls = 0
    cache_hits = 0
    calls_remaining = _remaining_cache_misses(tasks, 0)
    stopped_reason: str | None = None
    status = "complete"
    last_api_call_at: float | None = None
    original_call = qa._call_gemini_with_retry

    def cached_call(prompt: str):
        nonlocal api_calls, cache_hits, last_api_call_at
        key = _cache_key(prompt)
        path = _cache_path(key)
        if path.is_file():
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
                cache_hits += 1
                return SimpleNamespace(text=cached["answer"])
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                pass

        if last_api_call_at is not None and args.delay_seconds:
            elapsed = time.monotonic() - last_api_call_at
            if elapsed < args.delay_seconds:
                time.sleep(args.delay_seconds - elapsed)
        api_calls += 1
        last_api_call_at = time.monotonic()
        response = original_call(prompt)
        answer = str(response.text or "")
        temporary_path = path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(
                {"model": qa.MODEL_NAME, "prompt_sha256": key, "answer": answer},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
        return response

    qa._call_gemini_with_retry = cached_call
    try:
        for task_index, task in enumerate(tasks):
            try:
                response = qa.ask_question(
                    task["question"],
                    n_results=QA_N_RESULTS,
                    context_mode=task["context_mode"],
                )
            except Exception as error:
                calls_remaining = _remaining_cache_misses(tasks, task_index)
                status = "quota_exhausted" if _is_quota_error(error) else "stopped_on_error"
                stopped_reason = f"{type(error).__name__}: {error}"
                print(f"Stopped cleanly: {stopped_reason}")
                print(f"Uncached evaluation calls remaining: {calls_remaining}")
                break

            insufficient = _is_insufficient_context(response.get("answer"))
            expected_answerable = task["expected_answerable"]
            task_results.append(
                {
                    "question_index": task["question_index"],
                    "context_mode": task["context_mode"],
                    "verified": bool(response.get("verified", False)),
                    "answer_decline_match": insufficient != expected_answerable,
                }
            )
            calls_remaining = _remaining_cache_misses(tasks, task_index + 1)
            print(
                f"{task['question_index'] + 1:02d}/{len(questions)} {task['context_mode']}: "
                f"verified={bool(response.get('verified', False))} "
                f"answer_decline_match={insufficient != expected_answerable} "
                f"uncached_calls_remaining={calls_remaining}"
            )
    finally:
        qa._call_gemini_with_retry = original_call

    _write_findings(
        status,
        questions,
        task_results,
        api_calls,
        cache_hits,
        calls_remaining,
        stopped_reason,
    )
    print(f"QA v2 status: {status}")
    print(f"Findings: {FINDINGS_PATH}")
    print(f"Uncached evaluation calls remaining: {calls_remaining}")


if __name__ == "__main__":
    main()
