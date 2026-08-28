"""Cached BM25 keyword retrieval over the judgment chunks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

from scripts.build_embeddings import DEFAULT_INPUT_PATH, build_chunk_records


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class BM25JudgmentIndex:
    """In-memory BM25 index and the chunk records it ranks."""

    index: BM25Okapi
    documents: list[str]
    metadatas: list[dict[str, str | int]]


def _tokenize(text: str) -> list[str]:
    """Normalize text into lowercase alphanumeric terms for BM25 scoring."""
    return TOKEN_PATTERN.findall(text.lower())


@lru_cache(maxsize=1)
def get_bm25_index(
    input_path: Path = DEFAULT_INPUT_PATH,
) -> BM25JudgmentIndex:
    """Build the chunk-level BM25 index once per corpus path and process."""
    _ids, documents, metadatas = build_chunk_records(input_path)
    tokenized_documents = [_tokenize(document) for document in documents]
    return BM25JudgmentIndex(
        index=BM25Okapi(tokenized_documents),
        documents=documents,
        metadatas=metadatas,
    )


def _ipc_sections(value: Any) -> list[str]:
    """Decode the scalar JSON metadata representation used by ChromaDB."""
    if isinstance(value, list):
        return [str(section) for section in value]
    if not isinstance(value, str):
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        decoded = [section.strip() for section in value.split(",") if section.strip()]
    return [str(section) for section in decoded] if isinstance(decoded, list) else []


def _snippet(document: str, length: int = 200) -> str:
    """Return a readable, compact preview of a matching document chunk."""
    compact_document = " ".join(document.split())
    if len(compact_document) <= length:
        return compact_document
    return f"{compact_document[: length - 3]}..."


def bm25_search(query: str, n_results: int = 10) -> list[dict[str, Any]]:
    """Return unique cases in first-occurrence order by positive BM25 score."""
    if not query.strip():
        raise ValueError("query must not be empty")
    if n_results <= 0:
        raise ValueError("n_results must be positive")

    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    judgment_index = get_bm25_index()
    scores = judgment_index.index.get_scores(query_tokens)
    ranked_indices = sorted(
        range(len(scores)), key=lambda index: scores[index], reverse=True
    )

    results: list[dict[str, Any]] = []
    seen_case_names: set[str] = set()
    for index in ranked_indices:
        if scores[index] <= 0:
            break
        metadata = judgment_index.metadatas[index]
        case_name = str(metadata.get("case_name", ""))
        if case_name in seen_case_names:
            continue
        seen_case_names.add(case_name)
        results.append(
            {
                "case_name": case_name,
                "court": metadata.get("court", ""),
                "year": metadata.get("year"),
                "ipc_sections": _ipc_sections(metadata.get("ipc_sections")),
                "snippet": _snippet(judgment_index.documents[index]),
            }
        )
        if len(results) == n_results:
            break
    return results
