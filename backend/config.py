"""Retrieval settings read from the environment.

This is the only module that reads RETRIEVER and BM25_MIN_SCORE. Other
modules import ``SETTINGS`` from here instead of calling ``os.environ``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

VALID_RETRIEVERS = ("bm25", "dense", "hybrid")
DEFAULT_RETRIEVER = "bm25"
DEFAULT_BM25_MIN_SCORE = 0.0


@dataclass(frozen=True)
class Settings:
    """Validated retrieval settings."""

    retriever: str
    bm25_min_score: float


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Read and validate retrieval settings from ``environ`` (default os.environ)."""
    env = os.environ if environ is None else environ

    retriever = (env.get("RETRIEVER") or DEFAULT_RETRIEVER).strip().lower()
    if retriever not in VALID_RETRIEVERS:
        raise ValueError(
            f"RETRIEVER must be one of {', '.join(VALID_RETRIEVERS)}; got {retriever!r}"
        )

    raw_min_score = (env.get("BM25_MIN_SCORE") or "").strip()
    try:
        bm25_min_score = float(raw_min_score) if raw_min_score else DEFAULT_BM25_MIN_SCORE
    except ValueError as error:
        raise ValueError(
            f"BM25_MIN_SCORE must be a number; got {raw_min_score!r}"
        ) from error

    return Settings(retriever=retriever, bm25_min_score=bm25_min_score)


SETTINGS = load_settings()
