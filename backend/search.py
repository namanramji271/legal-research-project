"""Shared ChromaDB retrieval helpers for future API routes."""

from __future__ import annotations

import json
from typing import Any

import chromadb
from fastapi import APIRouter, Query

from embeddings import CHROMA_DB_PATH, COLLECTION_NAME, get_embedding_function

SEARCH_DISTANCE_THRESHOLD = 0.65

router = APIRouter()


def get_judgment_collection():
    """Open the persisted collection with the same MiniLM function used at build time."""
    client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
    return client.get_collection(
        name=COLLECTION_NAME,
        embedding_function=get_embedding_function(),
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


def search_judgments(query: str, n_results: int = 5) -> list[dict[str, Any]]:
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
    relevant_results = [
        (document, metadata, distance)
        for document, metadata, distance in zip(documents, metadatas, distances)
        if distance is not None and distance <= SEARCH_DISTANCE_THRESHOLD
    ]

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
            }
        )
    return results


@router.get("/search")
def search(
    q: str = Query(..., min_length=1, description="Natural-language legal query"),
    n_results: int = Query(5, ge=1, description="Number of matching chunks to return"),
) -> list[dict[str, Any]]:
    """Expose semantic judgment retrieval as a frontend-ready JSON response."""
    return search_judgments(q, n_results)
