"""Retriever selection, BM25 filtering, /search and /ask wiring.

Everything is monkeypatched: no Gemini calls, no ChromaDB queries and no
embedding-model downloads.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from rank_bm25 import BM25Okapi

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# qa.py refuses to import without a key; a fake one never reaches the network
# because every test stubs the Gemini call.
os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")

import bm25_search  # noqa: E402
import config  # noqa: E402
import qa  # noqa: E402
import search  # noqa: E402
from explainability import STOPWORDS  # noqa: E402


def _chunk(case_name: str, text: str = "", **extra: Any) -> dict[str, Any]:
    return {
        "case_name": case_name,
        "court": "Supreme Court of India",
        "year": 1970,
        "ipc_sections": ["302"],
        "snippet": text[:200],
        "chunk_text": text,
        **extra,
    }


@pytest.fixture
def tiny_bm25_index(monkeypatch: pytest.MonkeyPatch) -> None:
    documents = [
        "private defence of body exceeded the right",
        "culpable homicide not amounting to murder sudden provocation",
        "murder conviction upheld life imprisonment",
        "appeal dismissed costs awarded",
    ]
    metadatas = [
        {"case_name": f"ILDC case 2000_{i}", "court": "SC", "year": 2000, "ipc_sections": '["302"]'}
        for i in range(len(documents))
    ]
    index = bm25_search.BM25JudgmentIndex(
        index=BM25Okapi([bm25_search._tokenize(d) for d in documents]),
        documents=documents,
        metadatas=metadatas,
    )
    monkeypatch.setattr(bm25_search, "get_bm25_index", lambda *args, **kwargs: index)


def _set_settings(monkeypatch: pytest.MonkeyPatch, retriever: str, min_score: float = 0.0) -> None:
    monkeypatch.setattr(
        config, "SETTINGS", config.Settings(retriever=retriever, bm25_min_score=min_score)
    )


# --- settings --------------------------------------------------------------


def test_settings_default_to_bm25_and_zero_min_score() -> None:
    assert config.load_settings({}) == config.Settings("bm25", 0.0)


def test_settings_parse_values_case_insensitively() -> None:
    settings = config.load_settings({"RETRIEVER": " Hybrid ", "BM25_MIN_SCORE": "2.5"})
    assert settings == config.Settings("hybrid", 2.5)


@pytest.mark.parametrize(
    "environ",
    [{"RETRIEVER": "faiss"}, {"BM25_MIN_SCORE": "high"}],
)
def test_settings_reject_invalid_values(environ: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        config.load_settings(environ)


# --- BM25 chunk filtering --------------------------------------------------


def test_bm25_stopword_only_query_returns_nothing(tiny_bm25_index: None) -> None:
    assert bm25_search.bm25_search_chunks("the of and is", stopwords=STOPWORDS) == []


def test_bm25_stopwords_filter_query_tokens(
    tiny_bm25_index: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = bm25_search.get_bm25_index()
    seen_tokens: list[list[str]] = []
    original = index.index.get_scores

    def recording_get_scores(tokens: list[str]):
        seen_tokens.append(list(tokens))
        return original(tokens)

    monkeypatch.setattr(index.index, "get_scores", recording_get_scores)
    bm25_search.bm25_search_chunks("what is the right of private defence", stopwords=STOPWORDS)
    assert seen_tokens == [["right", "private", "defence"]]


def test_bm25_gibberish_query_returns_nothing(tiny_bm25_index: None) -> None:
    assert bm25_search.bm25_search_chunks("xqzv blorf", stopwords=STOPWORDS) == []


def test_bm25_min_score_drops_low_scoring_chunks(tiny_bm25_index: None) -> None:
    all_chunks = bm25_search.bm25_search_chunks("conviction provocation", n_chunks=10)
    assert len(all_chunks) >= 2
    assert all(chunk["score"] > 0 for chunk in all_chunks)
    cutoff = all_chunks[0]["score"] - 1e-9
    kept = bm25_search.bm25_search_chunks("conviction provocation", n_chunks=10, min_score=cutoff)
    assert [chunk["case_name"] for chunk in kept] == [all_chunks[0]["case_name"]]
    assert all(chunk["score"] > cutoff for chunk in kept)


def test_bm25_chunks_include_full_chunk_text(tiny_bm25_index: None) -> None:
    [top] = bm25_search.bm25_search_chunks("private defence", n_chunks=1)
    assert top["chunk_text"] == "private defence of body exceeded the right"


# --- retriever dispatch ----------------------------------------------------


@pytest.fixture
def recorded_retrievers(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict[str, Any]]]:
    calls: dict[str, list[dict[str, Any]]] = {"bm25": [], "dense": []}

    def fake_bm25(query: str, n_chunks: int, min_score: float, stopwords):
        calls["bm25"].append(
            {"query": query, "n_chunks": n_chunks, "min_score": min_score, "stopwords": stopwords}
        )
        return [_chunk("A", "bm25 A"), _chunk("B", "bm25 B")]

    def fake_dense(query: str, n_results: int, distance_threshold):
        calls["dense"].append(
            {"query": query, "n_results": n_results, "distance_threshold": distance_threshold}
        )
        return [_chunk("C", "dense C"), _chunk("A", "dense A")]

    monkeypatch.setattr(search, "bm25_search_chunks", fake_bm25)
    monkeypatch.setattr(search, "search_judgments", fake_dense)
    return calls


def test_bm25_retriever_uses_stopwords_min_score_and_no_dense(
    monkeypatch: pytest.MonkeyPatch, recorded_retrievers: dict[str, list[dict[str, Any]]]
) -> None:
    _set_settings(monkeypatch, "bm25", min_score=1.5)
    results = search.retrieve_chunks("private defence", n_chunks=7)
    assert [r["case_name"] for r in results] == ["A", "B"]
    assert recorded_retrievers["dense"] == []
    [call] = recorded_retrievers["bm25"]
    assert call["n_chunks"] == 7
    assert call["min_score"] == 1.5
    assert call["stopwords"] is STOPWORDS


def test_dense_retriever_keeps_production_threshold(
    monkeypatch: pytest.MonkeyPatch, recorded_retrievers: dict[str, list[dict[str, Any]]]
) -> None:
    _set_settings(monkeypatch, "dense")
    results = search.retrieve_chunks("private defence", n_chunks=7)
    assert [r["case_name"] for r in results] == ["C", "A"]
    assert recorded_retrievers["bm25"] == []
    assert recorded_retrievers["dense"][0]["distance_threshold"] == search.SEARCH_DISTANCE_THRESHOLD == 0.65


def test_dense_threshold_can_be_disabled_for_evaluation(
    monkeypatch: pytest.MonkeyPatch, recorded_retrievers: dict[str, list[dict[str, Any]]]
) -> None:
    _set_settings(monkeypatch, "dense")
    search.retrieve_chunks("q", n_chunks=100, distance_threshold=None)
    assert recorded_retrievers["dense"][0]["distance_threshold"] is None


def test_hybrid_retriever_fuses_both_lists(
    monkeypatch: pytest.MonkeyPatch, recorded_retrievers: dict[str, list[dict[str, Any]]]
) -> None:
    _set_settings(monkeypatch, "hybrid")
    results = search.retrieve_chunks("private defence", n_chunks=10)
    # A is rank 1 in BM25 and rank 2 in dense, so it wins 1:1 RRF.
    assert [r["case_name"] for r in results] == ["A", "C", "B"]
    assert len(recorded_retrievers["bm25"]) == len(recorded_retrievers["dense"]) == 1


def test_explicit_retriever_overrides_setting(
    monkeypatch: pytest.MonkeyPatch, recorded_retrievers: dict[str, list[dict[str, Any]]]
) -> None:
    _set_settings(monkeypatch, "bm25")
    search.retrieve_chunks("q", n_chunks=5, retriever="dense")
    assert recorded_retrievers["bm25"] == []
    assert len(recorded_retrievers["dense"]) == 1


def test_retrieve_cases_overfetches_and_keeps_best_chunk_per_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[int] = []

    def fake_chunks(query, n_chunks, retriever=None, distance_threshold=0.65):
        requested.append(n_chunks)
        return [
            _chunk("A", "A best"),
            _chunk("A", "A second"),
            _chunk("B", "B best"),
            _chunk("C", "C best"),
            _chunk("B", "B second"),
        ]

    monkeypatch.setattr(search, "retrieve_chunks", fake_chunks)
    cases = search.retrieve_cases("q", n_cases=2)
    assert requested == [search.CASE_OVERFETCH_CHUNKS] == [50]
    assert [(c["case_name"], c["chunk_text"]) for c in cases] == [("A", "A best"), ("B", "B best")]


# --- /search route ---------------------------------------------------------


def test_search_route_returns_cases_with_badge_and_no_chunk_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_settings(monkeypatch, "bm25")
    monkeypatch.setattr(
        search,
        "retrieve_cases",
        lambda q, n: [_chunk("A", "private defence exceeded", score=9.1), _chunk("B", "murder", score=3.0)],
    )
    monkeypatch.setattr(search, "bm25_search", lambda q, n_results: [_chunk("A")])
    monkeypatch.setattr(search, "search_judgments", lambda q, n_results: [_chunk("A"), _chunk("C")])

    results = search.search(q="private defence", n_results=2, user=None)

    assert [r["case_name"] for r in results] == ["A", "B"]
    for result in results:
        assert "chunk_text" not in result
        assert "score" not in result
        assert {"matched_methods", "matched_terms", "relevance_label"} <= result.keys()
    assert results[0]["matched_methods"] == ["dense", "bm25"]
    assert results[0]["relevance_label"] == "Strong match"
    assert results[0]["matched_terms"] == ["private", "defence"]
    assert results[1]["relevance_label"] == "Weak match"


def test_search_route_empty_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(search, "retrieve_cases", lambda q, n: [])
    assert search.search(q="xqzv blorf", n_results=5, user=None) == []


def test_search_route_badge_fallback_names_active_retriever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_settings(monkeypatch, "bm25")
    monkeypatch.setattr(search, "retrieve_cases", lambda q, n: [_chunk("A", "text")])

    def broken(*args, **kwargs):
        raise RuntimeError("chroma unavailable")

    monkeypatch.setattr(search, "bm25_search", broken)
    [result] = search.search(q="q", n_results=1, user=None)
    assert result["matched_methods"] == ["bm25"]
    assert "chunk_text" not in result


# --- /ask ------------------------------------------------------------------


def test_ask_uses_selected_retriever_and_sends_full_chunk_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retrieval_calls: list[tuple[str, int]] = []
    prompts: list[str] = []

    def fake_retrieve_cases(query: str, n_cases: int):
        retrieval_calls.append((query, n_cases))
        return [
            _chunk("ILDC case 1967_328", "FULL TEXT about private defence " * 20),
            _chunk("ILDC case 1970_1", "FULL TEXT about exceeding the right"),
        ]

    def fake_gemini(prompt: str):
        prompts.append(prompt)
        return SimpleNamespace(text="Per ILDC case 1967_328, the right was exceeded.")

    monkeypatch.setattr(qa, "retrieve_cases", fake_retrieve_cases)
    monkeypatch.setattr(qa, "_call_gemini_with_retry", fake_gemini)

    response = qa.ask_question("When is private defence exceeded?")

    assert retrieval_calls == [("When is private defence exceeded?", 5)]
    assert qa.AskRequest(question="x").n_results == 5
    [prompt] = prompts
    assert ("FULL TEXT about private defence " * 20).strip() in prompt
    assert response["verified"] is True
    assert response["sources_used"] == ["ILDC case 1967_328"]
    assert response["retrieved_sources"] == ["ILDC case 1967_328", "ILDC case 1970_1"]


def test_ask_flags_citation_outside_retrieved_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qa, "retrieve_cases", lambda query, n_cases: [_chunk("ILDC case 1967_328", "text")])
    monkeypatch.setattr(
        qa,
        "_call_gemini_with_retry",
        lambda prompt: SimpleNamespace(text="See ILDC case 1999_12."),
    )
    response = qa.ask_question("q")
    assert response["verified"] is False
    assert response["unverified_citations"] == ["ILDC case 1999_12"]


def test_ask_with_no_retrieved_cases_skips_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qa, "retrieve_cases", lambda query, n_cases: [])

    def must_not_call(prompt: str):
        raise AssertionError("Gemini must not be called without context")

    monkeypatch.setattr(qa, "_call_gemini_with_retry", must_not_call)
    response = qa.ask_question("xqzv blorf")
    assert response["verified"] is False
    assert response["sources_used"] == []


# --- badge matched_terms ---------------------------------------------------


def test_search_badge_terms_come_from_full_chunk_text(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_settings(monkeypatch, "bm25")
    long_text = ("procedural history of the appeal " * 10) + "the dying declaration was recorded"
    assert len(long_text.split("dying")[0]) > 200
    result = _chunk("A", long_text)
    assert "dying" not in result["snippet"]
    monkeypatch.setattr(search, "retrieve_cases", lambda q, n: [result])
    monkeypatch.setattr(search, "bm25_search", lambda q, n_results: [_chunk("A")])
    monkeypatch.setattr(search, "search_judgments", lambda q, n_results: [_chunk("A")])

    [response] = search.search(q="dying declaration", n_results=1, user=None)

    assert response["matched_terms"] == ["dying", "declaration"]
    assert "chunk_text" not in response
    assert response["snippet"] == long_text[:200]


def test_badge_terms_match_whole_words_only() -> None:
    from explainability import compute_match_explanation

    explanation = compute_match_explanation(
        query="NDPS Act bail",
        case_name="A",
        snippet="In fact the exact facts show bail was refused.",
        dense_case_names=[],
        bm25_case_names=["A"],
    )
    assert explanation["matched_terms"] == ["bail"]


def test_badge_terms_use_bm25_tokenizer() -> None:
    from explainability import compute_match_explanation

    explanation = compute_match_explanation(
        query="Section 302, IPC; murder!",
        case_name="A",
        snippet="convicted under s.302 of the IPC for MURDER",
        dense_case_names=["A"],
        bm25_case_names=["A"],
    )
    expected = [
        t for t in bm25_search._tokenize("Section 302, IPC; murder!")
        if t in set(bm25_search._tokenize("convicted under s.302 of the IPC for MURDER"))
        and t not in STOPWORDS
    ]
    assert explanation["matched_terms"] == expected == ["302", "ipc", "murder"]
    assert explanation["relevance_label"] == "Strong match"
