"""Chunk the local judgment corpus and persist MiniLM embeddings in ChromaDB.

Usage:
    python backend/scripts/build_embeddings.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

CHUNK_SIZE_TOKENS = 500
CHUNK_OVERLAP_TOKENS = 50
EMBEDDING_BATCH_SIZE = 32

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from embeddings import CHROMA_DB_PATH, COLLECTION_NAME, MODEL_NAME, get_embedding_function

DATA_DIR = BACKEND_DIR / "data"
DEFAULT_INPUT_PATH = DATA_DIR / "judgments.jsonl"
DEFAULT_CHROMA_PATH = CHROMA_DB_PATH

SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")


def token_count(text: str) -> int:
    """Count whitespace-delimited tokens; sufficient for approximate chunk sizing."""
    return len(text.split())


def split_sentences_and_paragraphs(text: str) -> list[str]:
    """Split on paragraphs first, then sentences while retaining readable chunks."""
    units: list[str] = []
    for paragraph in re.split(r"\n\s*\n+", text.strip()):
        paragraph = " ".join(paragraph.split())
        if not paragraph:
            continue
        units.extend(
            sentence.strip()
            for sentence in SENTENCE_BOUNDARY.split(paragraph)
            if sentence.strip()
        )
    return units


def split_long_unit(unit: str, max_tokens: int) -> list[str]:
    """Split exceptionally long sentences without exceeding the chunk budget."""
    words = unit.split()
    return [
        " ".join(words[start : start + max_tokens])
        for start in range(0, len(words), max_tokens)
    ]


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE_TOKENS,
    overlap: int = CHUNK_OVERLAP_TOKENS,
) -> list[str]:
    """Create approximately ``chunk_size`` token chunks with sentence-aware overlap."""
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("chunk_size must be positive and overlap must be smaller than it")

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    def flush_current() -> None:
        nonlocal current, current_tokens
        if not current:
            return
        chunks.append(" ".join(current))
        overlap_words = " ".join(current).split()[-overlap:] if overlap else []
        current = [" ".join(overlap_words)] if overlap_words else []
        current_tokens = len(overlap_words)

    for unit in split_sentences_and_paragraphs(text):
        # Reserve room for the overlap when a long sentence must be split.
        for piece in split_long_unit(unit, chunk_size - overlap):
            piece_tokens = token_count(piece)
            if current and current_tokens + piece_tokens > chunk_size:
                flush_current()
            current.append(piece)
            current_tokens += piece_tokens

            if current_tokens >= chunk_size:
                flush_current()

    if current and (not chunks or current_tokens > overlap):
        chunks.append(" ".join(current))
    return chunks


def load_judgments(input_path: Path) -> Iterable[dict[str, Any]]:
    required_fields = {"case_name", "court", "year", "ipc_sections", "full_text"}
    with input_path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                judgment = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON on line {line_number}") from error
            missing_fields = required_fields - judgment.keys()
            if missing_fields:
                missing = ", ".join(sorted(missing_fields))
                raise ValueError(f"Line {line_number} is missing required fields: {missing}")
            if not isinstance(judgment["full_text"], str) or not judgment["full_text"].strip():
                raise ValueError(f"Line {line_number} has no usable full_text")
            yield judgment


def metadata_for(judgment: dict[str, Any], chunk_index: int) -> dict[str, str | int]:
    """Convert JSONL fields into Chroma's scalar-only metadata representation."""
    year = judgment["year"]
    normalized_year: str | int = year if isinstance(year, int) else str(year or "Unknown")
    return {
        "case_name": str(judgment["case_name"]),
        "court": str(judgment["court"]),
        "year": normalized_year,
        "ipc_sections": json.dumps(judgment["ipc_sections"]),
        "chunk_index": chunk_index,
    }


def build_chunk_records(input_path: Path) -> tuple[list[str], list[str], list[dict[str, str | int]]]:
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, str | int]] = []
    for judgment in load_judgments(input_path):
        case_key = hashlib.sha256(
            f"{judgment['case_name']}\0{judgment['full_text']}".encode("utf-8")
        ).hexdigest()[:16]
        for chunk_index, chunk in enumerate(chunk_text(judgment["full_text"])):
            ids.append(f"{case_key}-{chunk_index}")
            documents.append(chunk)
            metadatas.append(metadata_for(judgment, chunk_index))
    if not documents:
        raise ValueError(f"No chunks were produced from {input_path}")
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate chunk IDs were generated")
    return ids, documents, metadatas


def rebuild_collection(
    ids: list[str],
    documents: list[str],
    metadatas: list[dict[str, str | int]],
    chroma_path: Path,
    batch_size: int,
) -> int:
    try:
        import chromadb
    except ImportError as error:
        raise SystemExit(
            "Missing embedding dependencies. Install with: "
            "pip install -r backend/requirements.txt"
        ) from error

    client = chromadb.PersistentClient(path=str(chroma_path))
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        # The first build has no collection to remove.
        pass
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine", "embedding_model": MODEL_NAME},
        embedding_function=get_embedding_function(),
    )

    for start in range(0, len(documents), batch_size):
        end = start + batch_size
        collection.add(
            ids=ids[start:end],
            documents=documents[start:end],
            metadatas=metadatas[start:end],
        )
    return collection.count()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--chroma-path", type=Path, default=DEFAULT_CHROMA_PATH)
    parser.add_argument("--batch-size", type=int, default=EMBEDDING_BATCH_SIZE)
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size must be positive")
    return args


def main() -> None:
    args = parse_args()
    if not args.input.exists():
        raise SystemExit(f"Judgment corpus not found: {args.input}")
    ids, documents, metadatas = build_chunk_records(args.input)
    count = rebuild_collection(
        ids, documents, metadatas, args.chroma_path, args.batch_size
    )
    print(f"Created {count} chunks in {args.chroma_path / COLLECTION_NAME}")


if __name__ == "__main__":
    main()
