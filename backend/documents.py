"""In-memory text extraction for uploaded legal documents."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import pdfplumber
from fastapi import APIRouter, File, HTTPException, UploadFile

from scripts.build_embeddings import chunk_text
from search import search_judgments


router = APIRouter()
SUPPORTED_SUFFIXES = {".pdf", ".txt"}


def _extract_pdf_text(file_bytes: bytes) -> str:
    """Extract available text from a PDF held entirely in memory."""
    try:
        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as error:
        raise HTTPException(
            status_code=400, detail="Unable to extract text from PDF"
        ) from error


def _extract_text_file(file_bytes: bytes) -> str:
    """Decode a UTF-8 plain-text upload."""
    try:
        return file_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HTTPException(
            status_code=400, detail="Plain-text files must use UTF-8 encoding"
        ) from error


def _sample_document_chunks(chunks: list[str], sample_size: int) -> list[str]:
    """Evenly sample chunks, always retaining the first and last when possible."""
    if sample_size >= len(chunks):
        return chunks
    if sample_size == 1:
        return [chunks[0]]

    last_index = len(chunks) - 1
    divisor = sample_size - 1
    indices = [
        (position * last_index + divisor // 2) // divisor
        for position in range(sample_size)
    ]
    return [chunks[index] for index in indices]


def find_related_judgments(
    document_text: str,
    sample_size: int = 3,
    n_results_per_chunk: int = 5,
) -> list[dict[str, Any]]:
    """Rank cases by matches across evenly sampled document chunks."""
    if not document_text.strip():
        raise ValueError("document_text must not be empty")
    if sample_size <= 0:
        raise ValueError("sample_size must be positive")
    if n_results_per_chunk <= 0:
        raise ValueError("n_results_per_chunk must be positive")

    document_chunks = _sample_document_chunks(chunk_text(document_text), sample_size)
    case_matches: dict[str, dict[str, Any]] = {}
    first_appearance = 0

    for document_chunk in document_chunks:
        results = search_judgments(document_chunk, n_results=n_results_per_chunk)
        seen_in_chunk: set[str] = set()
        for result in results:
            case_name = str(result.get("case_name", ""))
            if not case_name or case_name in seen_in_chunk:
                continue
            seen_in_chunk.add(case_name)

            if case_name not in case_matches:
                case_matches[case_name] = {
                    "record": result,
                    "match_count": 0,
                    "first_appearance": first_appearance,
                }
                first_appearance += 1
            case_matches[case_name]["match_count"] += 1

    ranked_matches = sorted(
        case_matches.values(),
        key=lambda match: (-match["match_count"], match["first_appearance"]),
    )
    return [
        {**match["record"], "match_count": match["match_count"]}
        for match in ranked_matches
    ]


@router.post("/documents/upload")
async def upload_document(file: UploadFile = File(...)) -> dict[str, Any]:
    """Extract PDF or plain-text content without storing the uploaded file."""
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        allowed = ", ".join(sorted(SUPPORTED_SUFFIXES))
        await file.close()
        raise HTTPException(
            status_code=400, detail=f"Unsupported file type. Upload one of: {allowed}"
        )

    try:
        file_bytes = await file.read()
    finally:
        await file.close()

    if suffix == ".pdf":
        extracted_text = _extract_pdf_text(file_bytes)
    else:
        extracted_text = _extract_text_file(file_bytes)
    related_judgments = (
        find_related_judgments(extracted_text) if extracted_text.strip() else []
    )

    return {
        "filename": filename,
        "extracted_text": extracted_text,
        "char_count": len(extracted_text),
        "related_judgments": related_judgments,
    }
