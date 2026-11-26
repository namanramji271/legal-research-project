"""Retrieval and corpus settings read from the environment.

This is the only module that reads RETRIEVER, BM25_MIN_SCORE, CORPUS_VERSION
and CORPUS_HEADNOTE. Other modules import ``SETTINGS`` (or call
``corpus_paths()``) from here instead of calling ``os.environ``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

VALID_RETRIEVERS = ("bm25", "dense", "hybrid")
DEFAULT_RETRIEVER = "bm25"
DEFAULT_BM25_MIN_SCORE = 0.0
# v1 = frozen ILDC baseline (48 judgments); v2 = Supreme Court PDFs from
# s3://indian-supreme-court-judgments (Dattam Labs, CC-BY-4.0).
VALID_CORPUS_VERSIONS = ("v1", "v2")
DEFAULT_CORPUS_VERSION = "v1"
# Whether chunks include the SCR headnote (v2 only; v1 has no headnote).
VALID_CORPUS_HEADNOTE = ("exclude", "include")
DEFAULT_CORPUS_HEADNOTE = "exclude"

DATA_DIR = Path(__file__).resolve().parent / "data"


@dataclass(frozen=True)
class Settings:
    """Validated retrieval and corpus settings."""

    retriever: str
    bm25_min_score: float
    corpus_version: str = DEFAULT_CORPUS_VERSION
    corpus_headnote: str = DEFAULT_CORPUS_HEADNOTE


def _choice(env: Mapping[str, str], name: str, valid: tuple[str, ...], default: str) -> str:
    value = (env.get(name) or default).strip().lower()
    if value not in valid:
        raise ValueError(f"{name} must be one of {', '.join(valid)}; got {value!r}")
    return value


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Read and validate settings from ``environ`` (default os.environ)."""
    env = os.environ if environ is None else environ

    retriever = _choice(env, "RETRIEVER", VALID_RETRIEVERS, DEFAULT_RETRIEVER)

    raw_min_score = (env.get("BM25_MIN_SCORE") or "").strip()
    try:
        bm25_min_score = float(raw_min_score) if raw_min_score else DEFAULT_BM25_MIN_SCORE
    except ValueError as error:
        raise ValueError(
            f"BM25_MIN_SCORE must be a number; got {raw_min_score!r}"
        ) from error

    corpus_version = _choice(env, "CORPUS_VERSION", VALID_CORPUS_VERSIONS, DEFAULT_CORPUS_VERSION)
    corpus_headnote = _choice(env, "CORPUS_HEADNOTE", VALID_CORPUS_HEADNOTE, DEFAULT_CORPUS_HEADNOTE)
    if corpus_version == "v1" and corpus_headnote != "exclude":
        raise ValueError("CORPUS_HEADNOTE=include needs CORPUS_VERSION=v2; v1 has no headnotes")

    return Settings(
        retriever=retriever,
        bm25_min_score=bm25_min_score,
        corpus_version=corpus_version,
        corpus_headnote=corpus_headnote,
    )


SETTINGS = load_settings()


@dataclass(frozen=True)
class CorpusPaths:
    """Where one corpus version's judgments and indexes live."""

    version: str
    headnote: str
    judgments: Path
    minilm_db: Path
    minilm_collection: str
    bge_db: Path
    bge_collection: str


def corpus_paths(version: str | None = None, headnote: str | None = None) -> CorpusPaths:
    """Paths for a corpus version; defaults come from ``SETTINGS``.

    v1 keeps the original locations so existing data and indexes need no move.
    v2 lives under data/corpora/v2/, with separate collections per headnote
    variant so both can be built and compared side by side.
    """
    version = (version or SETTINGS.corpus_version).lower()
    headnote = (headnote or SETTINGS.corpus_headnote).lower()
    if version not in VALID_CORPUS_VERSIONS:
        raise ValueError(f"unknown corpus version {version!r}")
    if headnote not in VALID_CORPUS_HEADNOTE:
        raise ValueError(f"unknown headnote setting {headnote!r}")

    if version == "v1":
        if headnote != "exclude":
            raise ValueError("v1 has no headnotes; use headnote='exclude'")
        return CorpusPaths(
            version="v1",
            headnote="exclude",
            judgments=DATA_DIR / "judgments.jsonl",
            minilm_db=DATA_DIR / "chroma_db",
            minilm_collection="judgment_chunks",
            bge_db=DATA_DIR / "chroma_db_bge",
            bge_collection="judgments_bge_m3",
        )

    root = DATA_DIR / "corpora" / version
    suffix = "_headnote" if headnote == "include" else ""
    return CorpusPaths(
        version=version,
        headnote=headnote,
        judgments=root / "judgments.jsonl",
        minilm_db=root / f"chroma_minilm{suffix}",
        minilm_collection=f"judgment_chunks_{version}{suffix}",
        bge_db=root / f"chroma_bge{suffix}",
        bge_collection=f"judgments_bge_m3_{version}{suffix}",
    )
