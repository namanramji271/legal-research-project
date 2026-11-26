"""Chunk the local judgment corpus and persist BGE-M3 embeddings in ChromaDB.

Usage:
    python backend/scripts/build_embeddings_bge.py                # CORPUS_VERSION (default v1)
    python backend/scripts/build_embeddings_bge.py --corpus v2

--corpus picks the input file, Chroma path and collection from
config.corpus_paths(); --input/--chroma-path override the paths.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
for import_path in (SCRIPT_DIR, BACKEND_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

import config  # noqa: E402
from build_embeddings import (  # noqa: E402
    EMBEDDING_BATCH_SIZE,
    build_chunk_records,
)
from embeddings import (  # noqa: E402
    BGE_CHROMA_DB_PATH,
    BGE_COLLECTION_NAME,
    BGE_MODEL_NAME,
    get_bge_embedding_function,
)


DEFAULT_CHROMA_PATH = BGE_CHROMA_DB_PATH


def rebuild_collection(
    ids: list[str],
    documents: list[str],
    metadatas: list[dict[str, str | int]],
    chroma_path: Path,
    batch_size: int,
    collection_name: str = BGE_COLLECTION_NAME,
) -> tuple[int, float]:
    """Rebuild the separate BGE-M3 collection and report batch progress."""
    try:
        import chromadb
    except ImportError as error:
        raise SystemExit(
            "Missing embedding dependencies. Install with: "
            "pip install -r backend/requirements.txt"
        ) from error

    started_at = time.perf_counter()
    print(
        f"Loading {BGE_MODEL_NAME} and embedding {len(documents)} chunks "
        f"into {chroma_path / collection_name}...",
        flush=True,
    )
    client = chromadb.PersistentClient(path=str(chroma_path))
    try:
        client.delete_collection(collection_name)
    except Exception:
        # The first build has no collection to remove.
        pass
    embedding_function = get_bge_embedding_function()
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine", "embedding_model": BGE_MODEL_NAME},
        embedding_function=embedding_function,
    )

    total_chunks = len(documents)
    for start in range(0, total_chunks, batch_size):
        end = min(start + batch_size, total_chunks)
        batch_documents = documents[start:end]
        batch_embeddings = embedding_function(batch_documents)
        collection.add(
            ids=ids[start:end],
            documents=batch_documents,
            metadatas=metadatas[start:end],
            embeddings=batch_embeddings,
        )
        elapsed = time.perf_counter() - started_at
        print(
            f"Embedded {end}/{total_chunks} chunks in {elapsed:.1f}s.",
            flush=True,
        )

    return collection.count(), time.perf_counter() - started_at


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", choices=config.VALID_CORPUS_VERSIONS, default=None,
                        help="corpus version (default: CORPUS_VERSION, i.e. v1 unless set)")
    parser.add_argument("--input", type=Path, default=None, help="override the corpus judgments file")
    parser.add_argument("--chroma-path", type=Path, default=None, help="override the Chroma directory")
    parser.add_argument("--batch-size", type=int, default=EMBEDDING_BATCH_SIZE)
    args = parser.parse_args(argv)
    if args.batch_size <= 0:
        parser.error("--batch-size must be positive")
    return args


def resolve_targets(args: argparse.Namespace) -> tuple[Path, Path, str]:
    """(input file, Chroma path, collection) for the chosen corpus version."""
    # Headnote variants arrive with the v2 chunker; until then builds use the body only.
    paths = config.corpus_paths(args.corpus, "exclude")
    return (
        args.input or paths.judgments,
        args.chroma_path or paths.bge_db,
        paths.bge_collection,
    )


def main() -> None:
    args = parse_args()
    input_path, chroma_path, collection_name = resolve_targets(args)
    if not input_path.exists():
        raise SystemExit(f"Judgment corpus not found: {input_path}")

    overall_started_at = time.perf_counter()
    ids, documents, metadatas = build_chunk_records(input_path)
    chunking_elapsed = time.perf_counter() - overall_started_at
    print(f"Prepared {len(documents)} chunks in {chunking_elapsed:.1f}s.", flush=True)

    count, embedding_elapsed = rebuild_collection(
        ids, documents, metadatas, chroma_path, args.batch_size, collection_name
    )
    total_elapsed = time.perf_counter() - overall_started_at
    print(
        f"Created {count} BGE-M3 chunks in {chroma_path / collection_name} "
        f"(embedding: {embedding_elapsed:.1f}s; total: {total_elapsed:.1f}s)."
    )


if __name__ == "__main__":
    main()
