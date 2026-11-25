"""Shared ChromaDB retrieval helpers for future API routes."""

from __future__ import annotations

import json
from typing import Any

import chromadb
from fastapi import APIRouter, Depends, Query

from auth import require_role

import config
from bm25_search import bm25_search, bm25_search_chunks
from embeddings import (
    BGE_CHROMA_DB_PATH,
    BGE_COLLECTION_NAME,
    CHROMA_DB_PATH,
    COLLECTION_NAME,
    get_bge_embedding_function,
    get_embedding_function,
)
from eval.metrics import collapse_cases, weighted_rrf
from explainability import STOPWORDS, compute_match_explanation

SEARCH_DISTANCE_THRESHOLD = 0.65
# Chunks fetched before collapsing to unique cases for /search and /ask.
CASE_OVERFETCH_CHUNKS = 50
HYBRID_RRF_K = 60
HYBRID_WEIGHTS = {"bm25": 1.0, "dense": 1.0}

router = APIRouter()


def get_judgment_collection():
    """Open the persisted collection with the same MiniLM function used at build time."""
    client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
    return client.get_collection(
        name=COLLECTION_NAME,
        embedding_function=get_embedding_function(),
    )


def get_bge_judgment_collection():
    """Open the persisted BGE-M3 collection with its build-time function."""
    client = chromadb.PersistentClient(path=str(BGE_CHROMA_DB_PATH))
    return client.get_collection(
        name=BGE_COLLECTION_NAME,
        embedding_function=get_bge_embedding_function(),
    )


def _ipc_sections(value: Any) -> list[str]:
    """Decode the JSON representation used for Chroma's scalar metadata."""
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


def search_judgments(
    query: str,
    n_results: int = 5,
    distance_threshold: float | None = SEARCH_DISTANCE_THRESHOLD,
) -> list[dict[str, Any]]:
    """Return flat, frontend-ready records for the closest judgment chunks."""
    if not query.strip():
        raise ValueError("query must not be empty")
    if n_results <= 0:
        raise ValueError("n_results must be positive")
    raw_results = get_judgment_collection().query(
        query_texts=[query],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )
    documents = (raw_results.get("documents") or [[]])[0] or []
    metadatas = (raw_results.get("metadatas") or [[]])[0] or []
    distances = (raw_results.get("distances") or [[]])[0] or []
    relevant_results = []
    for document, metadata, distance in zip(documents, metadatas, distances):
        if distance_threshold is not None and (
            distance is None or distance > distance_threshold
        ):
            continue
        relevant_results.append((document, metadata, distance))

    results: list[dict[str, Any]] = []
    for document, metadata, _distance in relevant_results:
        metadata = metadata or {}
        results.append(
            {
                "case_name": metadata.get("case_name", ""),
                "court": metadata.get("court", ""),
                "year": metadata.get("year"),
                "ipc_sections": _ipc_sections(metadata.get("ipc_sections")),
                "snippet": _snippet(document or ""),
                "chunk_text": document or "",
            }
        )
    return results


def search_judgments_bge(
    query: str,
    n_results: int = 5,
    distance_threshold: float | None = SEARCH_DISTANCE_THRESHOLD,
) -> list[dict[str, Any]]:
    """Return flat, frontend-ready records from the BGE-M3 judgment collection."""
    if not query.strip():
        raise ValueError("query must not be empty")
    if n_results <= 0:
        raise ValueError("n_results must be positive")
    raw_results = get_bge_judgment_collection().query(
        query_texts=[query],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )
    documents = (raw_results.get("documents") or [[]])[0] or []
    metadatas = (raw_results.get("metadatas") or [[]])[0] or []
    distances = (raw_results.get("distances") or [[]])[0] or []
    relevant_results = []
    for document, metadata, distance in zip(documents, metadatas, distances):
        if distance_threshold is not None and (
            distance is None or distance > distance_threshold
        ):
            continue
        relevant_results.append((document, metadata, distance))

    results: list[dict[str, Any]] = []
    for document, metadata, _distance in relevant_results:
        metadata = metadata or {}
        results.append(
            {
                "case_name": metadata.get("case_name", ""),
                "court": metadata.get("court", ""),
                "year": metadata.get("year"),
                "ipc_sections": _ipc_sections(metadata.get("ipc_sections")),
                "snippet": _snippet(document or ""),
                "chunk_text": document or "",
            }
        )
    return results


def retrieve_chunks(
    query: str,
    n_chunks: int,
    retriever: str | None = None,
    distance_threshold: float | None = SEARCH_DISTANCE_THRESHOLD,
) -> list[dict[str, Any]]:
    """Return ranked chunks from the configured retriever.

    ``retriever`` defaults to ``config.SETTINGS.retriever``. BM25 drops
    STOPWORDS from the query, keeps chunks scoring above
    ``config.SETTINGS.bm25_min_score`` and has no distance threshold.
    ``distance_threshold`` applies to the dense part of ``dense`` and
    ``hybrid`` only. Hybrid is 1:1 reciprocal rank fusion and returns one
    record per case.
    """
    if not query.strip():
        raise ValueError("query must not be empty")
    if n_chunks <= 0:
        raise ValueError("n_chunks must be positive")
    retriever = retriever or config.SETTINGS.retriever

    def bm25_chunks() -> list[dict[str, Any]]:
        return bm25_search_chunks(
            query,
            n_chunks=n_chunks,
            min_score=config.SETTINGS.bm25_min_score,
            stopwords=STOPWORDS,
        )

    def dense_chunks() -> list[dict[str, Any]]:
        return search_judgments(
            query, n_results=n_chunks, distance_threshold=distance_threshold
        )

    if retriever == "bm25":
        return bm25_chunks()
    if retriever == "dense":
        return dense_chunks()
    if retriever == "hybrid":
        return weighted_rrf(
            {"bm25": bm25_chunks(), "dense": dense_chunks()},
            HYBRID_WEIGHTS,
            k=HYBRID_RRF_K,
            limit=n_chunks,
        )
    raise ValueError(f"unknown retriever {retriever!r}")


def retrieve_cases(
    query: str,
    n_cases: int,
    retriever: str | None = None,
    distance_threshold: float | None = SEARCH_DISTANCE_THRESHOLD,
) -> list[dict[str, Any]]:
    """Return the best-ranked chunk of each of the top ``n_cases`` cases."""
    if n_cases <= 0:
        raise ValueError("n_cases must be positive")
    chunks = retrieve_chunks(
        query,
        n_chunks=max(CASE_OVERFETCH_CHUNKS, n_cases),
        retriever=retriever,
        distance_threshold=distance_threshold,
    )
    return collapse_cases(chunks)[:n_cases]


@router.get("/search")
def search(
    q: str = Query(..., min_length=1, description="Natural-language legal query"),
    n_results: int = Query(5, ge=1, description="Number of matching cases to return"),
    user=Depends(require_role("lawyer", "judge")),
) -> list[dict[str, Any]]:
    """Return the top cases from the configured retriever, with badge metadata."""
    results = retrieve_cases(q, n_results)
    if not results:
        return results

    try:
        # Badge inputs are computed exactly as before, independent of RETRIEVER.
        bm25_results = bm25_search(q, n_results=15)
        bm25_case_names = list(
            dict.fromkeys(
                r.get("case_name", "") for r in bm25_results if r.get("case_name")
            )
        )
        dense_case_names = list(
            dict.fromkeys(
                r.get("case_name", "")
                for r in search_judgments(q, n_results)
                if r.get("case_name")
            )
        )
        for result in results:
            explanation = compute_match_explanation(
                query=q,
                case_name=result.get("case_name", ""),
                # Terms come from the full chunk; chunk_text is stripped below.
                snippet=result.get("chunk_text") or result.get("snippet", ""),
                dense_case_names=dense_case_names,
                bm25_case_names=bm25_case_names,
            )
            result.update(explanation)
    except Exception:
        fallback_methods = {
            "bm25": ["bm25"],
            "dense": ["dense"],
            "hybrid": ["dense", "bm25"],
        }.get(config.SETTINGS.retriever, ["dense"])
        for result in results:
            result.setdefault("matched_methods", fallback_methods)
            result.setdefault("matched_terms", [])
            result.setdefault("relevance_label", "Moderate match")

    # chunk_text stays internal (used by /ask); scores are not part of the UI shape.
    return [
        {key: value for key, value in result.items() if key not in _INTERNAL_KEYS}
        for result in results
    ]


_INTERNAL_KEYS = {"chunk_text", "score", "rrf_score"}
