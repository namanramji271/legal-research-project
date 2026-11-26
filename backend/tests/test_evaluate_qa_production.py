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
    state = SimpleNamespace(fail_on_call=None, error=None)

    def fake_generate(prompt: str):
        calls.append(prompt)
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
        "question_number": 4,
    }
    assert "Stopped at Q4: `FakeQuotaError` (status 429): 429 RESOURCE_EXHAUSTED" in (
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
