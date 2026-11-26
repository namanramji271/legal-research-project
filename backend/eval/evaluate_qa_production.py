"""Evaluate the 13 QA questions through the production /ask path.

Run from the repository root with:
    python backend/eval/evaluate_qa_production.py --dry-run
    python backend/eval/evaluate_qa_production.py [--only unanswerable|answerable]

Uses qa.ask_question() unchanged (RETRIEVER=bm25, full chunk text, 5 cases).
The script swaps two qa.py hooks for the duration of the run only:
- qa._call_gemini_with_retry -> disk cache (backend/eval/cache, shared with
  evaluate_qa_v2.py via qa_cache.py) plus one Gemini attempt. A quota/429
  error stops the run at once; any other error is retried once, like
  production, then stops the run. The root exception is reported instead of
  qa.py's generic 503.
- qa.retrieve_cases -> a pass-through recorder that keeps the BM25 score of
  each retrieved case, which ask_question() does not return.

Before any Gemini call it prints how many calls are uncached; --dry-run
stops there and writes nothing. Otherwise results go to
qa_production_findings.md and results/qa_production.json, also when the run
stops early. Re-running resumes from the cache.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

BACKEND_DIR = Path(__file__).resolve().parents[1]
EVAL_DIR = Path(__file__).resolve().parent
QUESTIONS_PATH = EVAL_DIR / "test_qa_questions.json"
FINDINGS_PATH = EVAL_DIR / "qa_production_findings.md"
RESULTS_PATH = EVAL_DIR / "results" / "qa_production.json"
N_RESULTS = 5
CONTEXT_MODE = "full"
REQUIRED_RETRIEVER = "bm25"
DEFAULT_DELAY_SECONDS = 15.0
NON_QUOTA_RETRY_DELAY_SECONDS = 2.0  # same as qa._call_gemini_with_retry

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import config  # noqa: E402
import qa  # noqa: E402
from eval import qa_cache  # noqa: E402
from eval.refusal_patterns import is_insufficient_context  # noqa: E402


def gemini_generate(prompt: str):
    """One Gemini request, identical to the one in qa._call_gemini_with_retry."""
    from google.genai import types

    return qa.client.models.generate_content(
        model=qa.MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0),
    )


def call_gemini(prompt: str, sleep: Callable[[float], None] = time.sleep):
    """Stop on the first quota error; retry any other error once, like production."""
    try:
        return gemini_generate(prompt)
    except Exception as error:
        if qa_cache.is_quota_error(error):
            raise
        sleep(NON_QUOTA_RETRY_DELAY_SECONDS)
        return gemini_generate(prompt)


def ordered_questions(
    questions: list[dict[str, Any]], only: str | None = None
) -> list[tuple[int, dict[str, Any]]]:
    """Unanswerable questions first, then answerable; original order within each."""
    indexed = list(enumerate(questions, start=1))
    unanswerable = [(n, q) for n, q in indexed if not q["expected_answerable"]]
    answerable = [(n, q) for n, q in indexed if q["expected_answerable"]]
    if only == "unanswerable":
        return unanswerable
    if only == "answerable":
        return answerable
    return unanswerable + answerable


class _Hooks:
    """Temporarily replaces qa.retrieve_cases and qa._call_gemini_with_retry."""

    def __init__(self, gemini_hook: Callable[[str], Any]) -> None:
        self.gemini_hook = gemini_hook
        self.last_chunks: list[dict[str, Any]] = []
        self.last_key: str | None = None

    def __enter__(self) -> "_Hooks":
        self._original_retrieve = qa.retrieve_cases
        self._original_call = qa._call_gemini_with_retry

        def recording_retrieve(query: str, n_cases: int, **kwargs: Any):
            chunks = self._original_retrieve(query, n_cases=n_cases, **kwargs)
            self.last_chunks = list(chunks)
            return chunks

        def keyed_call(prompt: str):
            self.last_key = qa_cache.cache_key(qa.MODEL_NAME, prompt)
            return self.gemini_hook(prompt)

        qa.retrieve_cases = recording_retrieve
        qa._call_gemini_with_retry = keyed_call
        return self

    def __exit__(self, *_exc: Any) -> None:
        qa.retrieve_cases = self._original_retrieve
        qa._call_gemini_with_retry = self._original_call

    def reset(self) -> None:
        self.last_chunks = []
        self.last_key = None


def _ask(hooks: _Hooks, question: str) -> dict[str, Any]:
    hooks.reset()
    return qa.ask_question(question, n_results=N_RESULTS, context_mode=CONTEXT_MODE)


def _retrieved(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "case_name": chunk.get("case_name"),
            "score": round(float(chunk["score"]), 4) if chunk.get("score") is not None else None,
        }
        for chunk in chunks
    ]


def run(
    questions: list[dict[str, Any]],
    *,
    only: str | None = None,
    dry_run: bool = False,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    cache_dir: Path = qa_cache.CACHE_DIR,
    results_path: Path = RESULTS_PATH,
    findings_path: Path = FINDINGS_PATH,
    sleep: Callable[[float], None] = time.sleep,
    out: Callable[[str], None] = print,
) -> dict[str, Any]:
    retriever = config.SETTINGS.retriever
    if retriever != REQUIRED_RETRIEVER:
        raise RuntimeError(
            f"RETRIEVER is {retriever!r}; this eval measures production "
            f"({REQUIRED_RETRIEVER!r}). Unset RETRIEVER or set it to bm25."
        )
    selected = ordered_questions(questions, only)

    # Pass 1: build the exact production prompts and count cache misses.
    # The probe never calls Gemini.
    misses: dict[int, str] = {}

    def probe(prompt: str):
        key = qa_cache.cache_key(qa.MODEL_NAME, prompt)
        cached = qa_cache.read_cached_answer(key, cache_dir)
        if cached is None:
            misses[current] = key
            return SimpleNamespace(text="")
        return SimpleNamespace(text=cached)

    no_context = 0
    with _Hooks(probe) as hooks:
        for current, entry in selected:
            _ask(hooks, entry["question"])
            state = (
                "no retrieved cases (no Gemini call)" if hooks.last_key is None
                else "uncached" if current in misses
                else "cached"
            )
            no_context += hooks.last_key is None
            out(f"Q{current:02d} expected_answerable={entry['expected_answerable']}: {state}")
    uncached_before = len(misses)
    out(
        f"Uncached Gemini calls needed: {uncached_before} of {len(selected)} questions "
        f"(cached: {len(selected) - uncached_before - no_context}, "
        f"no retrieved cases: {no_context})"
    )
    if dry_run:
        out("Dry run: no Gemini calls made, no files written.")
        return {"status": "dry_run", "uncached_calls_before_run": uncached_before}

    # Pass 2: the real run.
    stats = {"gemini_calls": 0, "cache_hits": 0}
    last_call_at: list[float] = []

    def cached_gemini(prompt: str):
        key = qa_cache.cache_key(qa.MODEL_NAME, prompt)
        cached = qa_cache.read_cached_answer(key, cache_dir)
        if cached is not None:
            stats["cache_hits"] += 1
            return SimpleNamespace(text=cached, from_cache=True)
        if last_call_at and delay_seconds:
            wait = delay_seconds - (time.monotonic() - last_call_at[-1])
            if wait > 0:
                sleep(wait)
        last_call_at.append(time.monotonic())
        response = call_gemini(prompt, sleep=sleep)
        answer = str(getattr(response, "text", "") or "")
        qa_cache.write_cached_answer(key, qa.MODEL_NAME, answer, cache_dir)
        stats["gemini_calls"] += 1
        return SimpleNamespace(text=answer, from_cache=False)

    results: list[dict[str, Any]] = []
    status = "complete"
    error_info: dict[str, Any] | None = None
    with _Hooks(cached_gemini) as hooks:
        for number, entry in selected:
            calls_before = stats["gemini_calls"]
            try:
                response = _ask(hooks, entry["question"])
            except Exception as error:
                error_info = qa_cache.describe_error(error)
                error_info["question_number"] = number
                status = "quota_exhausted" if error_info["quota"] else "stopped_on_error"
                out(
                    f"Q{number:02d}: stopped ({status}): {error_info['type']}"
                    f"{' ' + str(error_info['status']) if error_info['status'] is not None else ''}"
                    f": {error_info['message']}"
                )
                break
            answer = str(response.get("answer") or "")
            declined = is_insufficient_context(answer)
            expected = bool(entry["expected_answerable"])
            results.append(
                {
                    "number": number,
                    "question": entry["question"],
                    "expected_answerable": expected,
                    "retrieved_cases": _retrieved(hooks.last_chunks),
                    "answer": answer,
                    "verified": bool(response.get("verified", False)),
                    "sources_used": response.get("sources_used") or [],
                    "unverified_citations": response.get("unverified_citations") or [],
                    "declined": declined,
                    "decline_match": declined != expected,
                    "cache_key": hooks.last_key,
                    "gemini_called_this_run": stats["gemini_calls"] > calls_before,
                }
            )
            out(
                f"Q{number:02d}: verified={results[-1]['verified']} declined={declined} "
                f"expected_answerable={expected} match={declined != expected}"
            )

    report = {
        "status": status,
        "error": error_info,
        "model": qa.MODEL_NAME,
        "retriever": retriever,
        "bm25_min_score": config.SETTINGS.bm25_min_score,
        "n_results": N_RESULTS,
        "context_mode": CONTEXT_MODE,
        "only": only,
        "question_order": [number for number, _ in selected],
        "questions_selected": len(selected),
        "questions_completed": len(results),
        "uncached_calls_before_run": uncached_before,
        "gemini_calls_this_run": stats["gemini_calls"],
        "cache_hits": stats["cache_hits"],
        "uncached_calls_remaining": uncached_before - stats["gemini_calls"],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "results": results,
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    findings_path.write_text(_findings_markdown(report), encoding="utf-8")
    out(f"Status: {status}; Gemini calls this run: {stats['gemini_calls']}; "
        f"uncached remaining: {report['uncached_calls_remaining']}")
    out(f"Results: {results_path}")
    out(f"Findings: {findings_path}")
    return report


def _count(results: list[dict[str, Any]], field: str) -> str:
    return f"{sum(bool(r[field]) for r in results)}/{len(results)}"


def _findings_markdown(report: dict[str, Any]) -> str:
    results = report["results"]
    answerable = [r for r in results if r["expected_answerable"]]
    unanswerable = [r for r in results if not r["expected_answerable"]]
    lines = [
        "# QA Evaluation: production path",
        "",
        f"- Run status: **{report['status']}**",
        f"- Path: `qa.ask_question()` with `RETRIEVER={report['retriever']}` "
        f"(BM25_MIN_SCORE={report['bm25_min_score']}), `context_mode={report['context_mode']}`, "
        f"{report['n_results']} cases",
        f"- Model: `{report['model']}`; generated {report['generated_at']}",
        f"- Questions completed: {report['questions_completed']}/{report['questions_selected']}"
        + (f" (`--only {report['only']}`)" if report["only"] else ""),
        f"- Gemini calls this run: {report['gemini_calls_this_run']}; cache hits: {report['cache_hits']}; "
        f"uncached calls remaining: {report['uncached_calls_remaining']}",
    ]
    if report["error"]:
        error = report["error"]
        lines.append(
            f"- Stopped at Q{error['question_number']}: `{error['type']}` "
            f"(status {error['status']}): {error['message']}"
        )
    lines += [
        "",
        "Decline detection uses `backend/eval/refusal_patterns.py`. A match means an answerable "
        "question was answered or an unanswerable one was declined. Full answers and BM25 scores "
        "are in `results/qa_production.json`.",
        "",
        "| Group | Completed | Verified | Answer/decline matches |",
        "| --- | ---: | ---: | ---: |",
        f"| answerable | {len(answerable)} | {_count(answerable, 'verified')} | {_count(answerable, 'decline_match')} |",
        f"| unanswerable | {len(unanswerable)} | {_count(unanswerable, 'verified')} | {_count(unanswerable, 'decline_match')} |",
        f"| all | {len(results)} | {_count(results, 'verified')} | {_count(results, 'decline_match')} |",
        "",
        "## Per-question outcomes",
        "",
        "| # | Expected | Declined | Match | Verified | Retrieved cases (BM25 score) |",
        "| ---: | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        cases = ", ".join(
            f"{c['case_name']} ({c['score']})" if c["score"] is not None else str(c["case_name"])
            for c in r["retrieved_cases"]
        ) or "none"
        expected = "answerable" if r["expected_answerable"] else "unanswerable"
        lines.append(
            f"| {r['number']} | {expected} | {r['declined']} | {r['decline_match']} | {r['verified']} | {cases} |"
        )
    lines += ["", "## Answers", ""]
    for r in results:
        lines += [f"### Q{r['number']}: {r['question']}", ""]
        lines += [f"> {line}" if line else ">" for line in r["answer"].splitlines()] or ["> (empty)"]
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="count uncached calls, then stop")
    parser.add_argument("--only", choices=("unanswerable", "answerable"), help="run one group only")
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help=f"pause between uncached Gemini calls (default: {DEFAULT_DELAY_SECONDS:g})",
    )
    args = parser.parse_args(argv)
    if args.delay_seconds < 0:
        parser.error("--delay-seconds must be non-negative")
    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    try:
        report = run(questions, only=args.only, dry_run=args.dry_run, delay_seconds=args.delay_seconds)
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    return {"dry_run": 0, "complete": 0, "quota_exhausted": 3}.get(report["status"], 1)


if __name__ == "__main__":
    sys.exit(main())
