"""CORPUS_VERSION / CORPUS_HEADNOTE settings and corpus_paths()."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import config  # noqa: E402

DATA = BACKEND_DIR / "data"


def test_corpus_settings_default_to_v1_without_headnote() -> None:
    settings = config.load_settings({})
    assert settings.corpus_version == "v1"
    assert settings.corpus_headnote == "exclude"
    # Positional construction used elsewhere still compares equal.
    assert settings == config.Settings("bm25", 0.0)


def test_corpus_settings_parse_case_insensitively() -> None:
    settings = config.load_settings({"CORPUS_VERSION": " V2 ", "CORPUS_HEADNOTE": "Include"})
    assert (settings.corpus_version, settings.corpus_headnote) == ("v2", "include")


@pytest.mark.parametrize(
    "environ, message",
    [
        ({"CORPUS_VERSION": "v3"}, "CORPUS_VERSION must be one of v1, v2"),
        ({"CORPUS_HEADNOTE": "maybe"}, "CORPUS_HEADNOTE must be one of exclude, include"),
        ({"CORPUS_HEADNOTE": "include"}, "needs CORPUS_VERSION=v2"),
    ],
)
def test_corpus_settings_reject_invalid_values(environ: dict[str, str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        config.load_settings(environ)


def test_v1_paths_are_the_original_locations() -> None:
    paths = config.corpus_paths("v1")
    assert paths.judgments == DATA / "judgments.jsonl"
    assert (paths.minilm_db, paths.minilm_collection) == (DATA / "chroma_db", "judgment_chunks")
    assert (paths.bge_db, paths.bge_collection) == (DATA / "chroma_db_bge", "judgments_bge_m3")


def test_v1_paths_match_the_existing_constants() -> None:
    import embeddings

    paths = config.corpus_paths("v1")
    assert paths.minilm_db == embeddings.CHROMA_DB_PATH
    assert paths.minilm_collection == embeddings.COLLECTION_NAME
    assert paths.bge_db == embeddings.BGE_CHROMA_DB_PATH
    assert paths.bge_collection == embeddings.BGE_COLLECTION_NAME


def test_v2_paths_are_separate_per_headnote_variant() -> None:
    body = config.corpus_paths("v2", "exclude")
    with_headnote = config.corpus_paths("v2", "include")
    root = DATA / "corpora" / "v2"
    assert body.judgments == with_headnote.judgments == root / "judgments.jsonl"
    assert (body.minilm_db, body.minilm_collection) == (root / "chroma_minilm", "judgment_chunks_v2")
    assert (body.bge_db, body.bge_collection) == (root / "chroma_bge", "judgments_bge_m3_v2")
    assert (with_headnote.minilm_db, with_headnote.minilm_collection) == (
        root / "chroma_minilm_headnote",
        "judgment_chunks_v2_headnote",
    )
    assert with_headnote.bge_collection == "judgments_bge_m3_v2_headnote"
    v1 = config.corpus_paths("v1")
    assert not {body.minilm_db, with_headnote.minilm_db, body.bge_db} & {v1.minilm_db, v1.bge_db}


def test_corpus_paths_defaults_follow_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "SETTINGS", config.load_settings({"CORPUS_VERSION": "v2"}))
    assert config.corpus_paths().version == "v2"
    assert config.corpus_paths().headnote == "exclude"


def test_corpus_paths_reject_bad_arguments() -> None:
    with pytest.raises(ValueError, match="v1 has no headnotes"):
        config.corpus_paths("v1", "include")
    with pytest.raises(ValueError, match="unknown corpus version"):
        config.corpus_paths("v9")
