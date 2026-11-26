"""Production QA eval: ordering, dry run, cache resume, quota stop, error reporting.

Gemini and retrieval are monkeypatched; nothing reaches the network and no
index is loaded. All files go to tmp_path.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")

import config  # noqa: E402
import qa  # noqa: E402
from eval import evaluate_qa_production as prod  # noqa: E402
from eval import qa_cache  # noqa: E402

QUESTIONS = [
    {"question": "When is private defence exceeded?", "expected_answerable": True},
    {"question": "How is GST calculated?", "expected_answerable": False},
    {"question": "What is culpable homicide?", "expected_answerable": True},
    {"question": "What are NDPS bail rules?", "expected_answerable": False},
]

ANSWERS = {
    "When is private defence exceeded?": "Per ILDC case 1967_328, force must be proportionate.",
    "How is GST calculated?": "Based on the provided context, there is no information about GST.",
    "What is culpable homicide?": "Based on the provided context, there is not enough information to answer.",
    "What are NDPS bail rules?": "Under ILDC case 1970_1, bail is granted freely.",  # wrong: answered
}


class FakeServerError(Exception):
    """Shaped like google.genai's ServerError: .code, .status and its message format."""

    def __init__(self, code: int, status: str) -> None:
        super().__init__(f"{code} {status}. {{'error': {{'code': {code}, 'status': '{status}'}}}}")
        self.code = code
        self.status = status


class FakeQuotaError(Exception):
    """Shaped like google.genai's ClientError for a 429."""

    def __init__(self) -> None:
        super().__init__("429 RESOURCE_EXHAUSTED. Quota exceeded for generate_content.")
        self.code = 429


def _question_in(prompt: str) -> str:
    return next(q for q in ANSWERS if q in prompt)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    monkeypatch.setattr(config, "SETTINGS", config.load_settings({"RETRIEVER": "bm25"}))
    retrieved: list[str] = []

    def fake_retrieve_cases(query: str, n_cases: int, **_kwargs: Any):
        retrieved.append(query)
        base = {"court": "Supreme Court of India", "year": 1970, "ipc_sections": ["302"], "snippet": ""}
        return [
            {**base, "case_name": "ILDC case 1967_328", "chunk_text": f"text about {query}", "score": 15.31234},
            {**base, "case_name": "ILDC case 1970_1", "chunk_text": "more text", "score": 9.5},
        ]

    calls: list[str] = []
    # queue: per-attempt outcomes (an exception to raise, or None for success), used first.
    state = SimpleNamespace(fail_on_call=None, error=None, queue=[])

    def fake_generate(prompt: str):
        calls.append(prompt)
        if state.queue:
            outcome = state.queue.pop(0)
            if outcome is not None:
                raise outcome
            return SimpleNamespace(text=ANSWERS[_question_in(prompt)])
        if state.fail_on_call is not None and len(calls) >= state.fail_on_call:
            raise state.error
        return SimpleNamespace(text=ANSWERS[_question_in(prompt)])

    def production_gemini_must_not_run(prompt: str):
        raise AssertionError("the eval must replace qa._call_gemini_with_retry")

    monkeypatch.setattr(qa, "retrieve_cases", fake_retrieve_cases)
    monkeypatch.setattr(qa, "_call_gemini_with_retry", production_gemini_must_not_run)
    monkeypatch.setattr(prod, "gemini_generate", fake_generate)

    paths = dict(
        cache_dir=tmp_path / "cache",
        results_path=tmp_path / "results" / "qa_production.json",
        findings_path=tmp_path / "qa_production_findings.md",
    )
    sleeps: list[float] = []
    lines: list[str] = []

    def run(**kwargs: Any) -> dict[str, Any]:
        return prod.run(QUESTIONS, delay_seconds=0, sleep=sleeps.append, out=lines.append, **paths, **kwargs)

    return SimpleNamespace(
        run=run, calls=calls, state=state, sleeps=sleeps, lines=lines,
        retrieved=retrieved, originals=(fake_retrieve_cases, production_gemini_must_not_run), **paths,
    )


def test_unanswerable_first_and_only_filter() -> None:
    assert [n for n, _ in prod.ordered_questions(QUESTIONS)] == [2, 4, 1, 3]
    assert [n for n, _ in prod.ordered_questions(QUESTIONS, "unanswerable")] == [2, 4]
    assert [n for n, _ in prod.ordered_questions(QUESTIONS, "answerable")] == [1, 3]


def test_dry_run_counts_uncached_and_calls_nothing(env: SimpleNamespace) -> None:
    # Pre-cache one question's exact prompt so the count is not trivially "all".
    env.run(only="unanswerable")
    env.calls.clear()
    env.lines.clear()

    report = env.run(dry_run=True)

    assert report == {"status": "dry_run", "uncached_calls_before_run": 2}
    assert env.calls == []
    assert "Uncached Gemini calls needed: 2 of 4 questions (cached: 2, no retrieved cases: 0)" in env.lines
    assert env.lines[-1] == "Dry run: no Gemini calls made, no files written."


def test_dry_run_writes_no_files(env: SimpleNamespace) -> None:
    env.run(dry_run=True)
    assert env.calls == []
    assert not env.results_path.exists()
    assert not env.findings_path.exists()
    assert not env.cache_dir.exists()


def test_full_run_records_answers_scores_and_scoring(env: SimpleNamespace) -> None:
    report = env.run()

    assert report["status"] == "complete"
    assert report["gemini_calls_this_run"] == 4
    assert report["question_order"] == [2, 4, 1, 3]
    saved = json.loads(env.results_path.read_text(encoding="utf-8"))
    assert saved["retriever"] == "bm25" and saved["n_results"] == 5 and saved["context_mode"] == "full"
    by_number = {r["number"]: r for r in saved["results"]}
    assert by_number[2]["answer"] == ANSWERS["How is GST calculated?"]
    assert by_number[2]["retrieved_cases"] == [
        {"case_name": "ILDC case 1967_328", "score": 15.3123},
        {"case_name": "ILDC case 1970_1", "score": 9.5},
    ]
    # GST declined (correct); NDPS answered (wrong); Q1 answered (correct); Q3 declined (wrong).
    assert {n: r["decline_match"] for n, r in by_number.items()} == {2: True, 4: False, 1: True, 3: False}
    assert by_number[1]["verified"] is True and by_number[1]["sources_used"] == ["ILDC case 1967_328"]
    findings = env.findings_path.read_text(encoding="utf-8")
    assert "| all | 4 | 4/4 | 2/4 |" in findings
    assert ANSWERS["What are NDPS bail rules?"] in findings
    # The eval's hooks are removed afterwards.
    assert (qa.retrieve_cases, qa._call_gemini_with_retry) == env.originals


def test_second_run_is_served_from_cache(env: SimpleNamespace) -> None:
    env.run()
    env.calls.clear()

    report = env.run()

    assert env.calls == []
    assert report["uncached_calls_before_run"] == 0
    assert report["cache_hits"] == 4 and report["gemini_calls_this_run"] == 0


def test_quota_error_stops_at_once_without_retry_and_resumes(env: SimpleNamespace) -> None:
    env.state.fail_on_call, env.state.error = 2, FakeQuotaError()

    report = env.run()

    assert len(env.calls) == 2  # Q2 ok, Q4 hit quota once: no retry
    assert env.sleeps == []  # no retry back-off either
    assert report["status"] == "quota_exhausted"
    assert report["questions_completed"] == 1
    assert report["uncached_calls_remaining"] == 3
    assert report["error"] == {
        "type": "FakeQuotaError",
        "status": 429,
        "message": "429 RESOURCE_EXHAUSTED. Quota exceeded for generate_content.",
        "quota": True,
        "kind": "quota",
        "question_number": 4,
        "transient_retries": 0,
    }
    assert "Stopped at Q4 (quota error, after 0 transient retries): `FakeQuotaError` (status 429): 429 RESOURCE_EXHAUSTED" in (
        env.findings_path.read_text(encoding="utf-8")
    )
    assert "Q04: stopped (quota_exhausted): FakeQuotaError 429: 429 RESOURCE_EXHAUSTED" in " ".join(env.lines)

    env.state.fail_on_call = None
    env.calls.clear()
    resumed = env.run()
    assert resumed["status"] == "complete"
    assert len(env.calls) == 3 and resumed["cache_hits"] == 1


def test_quota_error_wrapped_in_503_is_still_reported_as_root_cause() -> None:
    try:
        try:
            raise FakeQuotaError()
        except FakeQuotaError as inner:
            raise HTTPException(status_code=503, detail="temporarily unavailable") from inner
    except HTTPException as outer:
        info = qa_cache.describe_error(outer)
    assert info["type"] == "FakeQuotaError" and info["status"] == 429 and info["quota"] is True


def test_other_error_retries_once_then_stops_with_real_type(env: SimpleNamespace) -> None:
    env.state.fail_on_call, env.state.error = 1, ValueError("model returned malformed response")

    report = env.run(only="unanswerable")

    assert len(env.calls) == 2  # one retry, like production
    assert env.sleeps == [prod.NON_QUOTA_RETRY_DELAY_SECONDS]
    assert report["status"] == "stopped_on_error"
    assert report["error"]["type"] == "ValueError"
    assert report["error"]["message"] == "model returned malformed response"
    assert report["questions_completed"] == 0


def test_no_retrieved_cases_is_a_decline_without_gemini(env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qa, "retrieve_cases", lambda query, n_cases, **_: [])

    report = env.run(only="unanswerable")

    assert env.calls == []
    assert all(r["declined"] and r["decline_match"] and r["cache_key"] is None for r in report["results"])
    assert "no retrieved cases: 2" in " ".join(env.lines)


def test_refuses_to_run_without_bm25(env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "SETTINGS", config.load_settings({"RETRIEVER": "dense"}))
    with pytest.raises(RuntimeError, match="RETRIEVER is 'dense'"):
        env.run(dry_run=True)
    assert env.calls == []


def test_pacing_waits_between_uncached_calls(env: SimpleNamespace) -> None:
    prod.run(QUESTIONS[:2], delay_seconds=15, sleep=env.sleeps.append, out=env.lines.append,
             cache_dir=env.cache_dir, results_path=env.results_path, findings_path=env.findings_path)
    assert len(env.calls) == 2
    assert len(env.sleeps) == 1 and 14 < env.sleeps[0] <= 15


# --- Timeout, transient retries and progress lines ---------------------------


def test_classify_error() -> None:
    import httpx

    assert prod.classify_error(FakeQuotaError()) == "quota"
    assert prod.classify_error(FakeServerError(503, "UNAVAILABLE")) == "transient"
    assert prod.classify_error(FakeServerError(504, "DEADLINE_EXCEEDED")) == "transient"
    assert prod.classify_error(httpx.ReadTimeout("timed out")) == "transient"
    assert prod.classify_error(FakeServerError(500, "INTERNAL")) == "other"
    assert prod.classify_error(ValueError("bad")) == "other"


def test_gemini_request_has_60s_timeout_and_production_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def generate_content(**kwargs: Any):
        seen.update(kwargs)
        return SimpleNamespace(text="ok")

    monkeypatch.setattr(qa, "client", SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    prod.gemini_generate("prompt")
    assert seen["model"] == qa.MODEL_NAME and seen["contents"] == "prompt"
    assert seen["config"].temperature == 0
    assert seen["config"].http_options.timeout == 60_000
    assert seen["config"].http_options.retry_options is None  # no hidden SDK retries


def test_503_is_retried_after_backoff_and_counted(env: SimpleNamespace) -> None:
    env.state.queue = [FakeServerError(503, "UNAVAILABLE"), None]

    report = env.run(only="unanswerable")

    assert report["status"] == "complete"
    assert len(env.calls) == 3  # Q2: fail + success; Q4: success
    assert env.sleeps == [30.0]
    assert report["transient_retries_total"] == 1
    saved = json.loads(env.results_path.read_text(encoding="utf-8"))
    assert [r["transient_retries"] for r in saved["results"]] == [1, 0]
    findings = env.findings_path.read_text(encoding="utf-8")
    assert "- Transient retries (503/504/timeout): 1 (request timeout 60s, backoff 30s, max 3 per call)" in findings
    assert "| 2 | unanswerable | True | True | True | 1 |" in findings


def test_504_exhausts_retries_then_stops_with_real_error(env: SimpleNamespace) -> None:
    env.state.queue = [FakeServerError(504, "DEADLINE_EXCEEDED")] * 4

    report = env.run()

    assert len(env.calls) == 4  # 1 attempt + 3 retries, then stop
    assert env.sleeps == [30.0, 30.0, 30.0]
    assert report["status"] == "stopped_on_error"
    assert report["questions_completed"] == 0
    assert report["transient_retries_total"] == 3
    assert report["error"]["kind"] == "transient"
    assert report["error"]["type"] == "FakeServerError"
    assert report["error"]["status"] == 504
    assert report["error"]["message"].startswith("504 DEADLINE_EXCEEDED.")
    assert report["error"]["transient_retries"] == 3
    assert "Stopped at Q2 (transient error, after 3 transient retries): `FakeServerError` (status 504)" in (
        env.findings_path.read_text(encoding="utf-8")
    )
    assert any("transient retries exhausted (3), stopping" in line for line in env.lines)


def test_our_own_timeout_is_transient(env: SimpleNamespace) -> None:
    import httpx

    env.state.queue = [httpx.ReadTimeout("The read operation timed out"), None]

    report = env.run(only="unanswerable")

    assert report["status"] == "complete"
    assert report["transient_retries_total"] == 1
    assert env.sleeps == [30.0]


def test_backoff_and_max_retries_are_configurable(env: SimpleNamespace) -> None:
    env.state.queue = [FakeServerError(503, "UNAVAILABLE")] * 2

    report = env.run(backoff_seconds=5, max_transient_retries=1)

    assert len(env.calls) == 2
    assert env.sleeps == [5]
    assert report["status"] == "stopped_on_error"
    assert report["backoff_seconds"] == 5 and report["max_transient_retries"] == 1


def test_quota_after_transient_still_stops_without_retry(env: SimpleNamespace) -> None:
    env.state.queue = [FakeServerError(503, "UNAVAILABLE"), FakeQuotaError()]

    report = env.run()

    assert len(env.calls) == 2
    assert env.sleeps == [30.0]  # only the transient backoff
    assert report["status"] == "quota_exhausted"
    assert report["error"]["kind"] == "quota" and report["error"]["transient_retries"] == 1


def test_progress_lines_show_attempts_and_elapsed_seconds(env: SimpleNamespace) -> None:
    ticks = iter(float(i) * 1.5 for i in range(1000))
    env.state.queue = [FakeServerError(503, "UNAVAILABLE"), None]

    env.run(only="unanswerable", clock=lambda: next(ticks))
    q2 = [line for line in env.lines if line.startswith("Q02: ")]

    assert q2[0] == "Q02: Gemini call start (attempt 1)"
    assert q2[1].startswith("Q02: FakeServerError 503: 503 UNAVAILABLE.")
    assert q2[1].endswith("after 1.5s; transient, retrying in 30s (retry 1/3)")
    assert q2[2] == "Q02: Gemini call start (attempt 2)"
    assert q2[3] == "Q02: Gemini returned in 1.5s"

    env.lines.clear()
    env.run(only="unanswerable")
    assert "Q02: cached answer" in env.lines


def test_cli_options_reach_run(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(prod, "run", lambda questions, **kwargs: seen.update(kwargs) or {"status": "dry_run"})

    assert prod.main(["--dry-run", "--backoff-seconds", "5", "--max-transient-retries", "1"]) == 0
    assert seen["backoff_seconds"] == 5 and seen["max_transient_retries"] == 1 and seen["dry_run"] is True
    assert prod.main([]) == 0
    assert seen["backoff_seconds"] == 30 and seen["max_transient_retries"] == 3
