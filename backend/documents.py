"""In-memory text extraction for uploaded legal documents."""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from auth import require_role
from google import genai
import pdfplumber
from pydantic import BaseModel

from scripts.build_embeddings import chunk_text
from search import search_judgments

from docx import Document as DocxDocument
from fastapi.responses import StreamingResponse


load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY not found. Add it to backend/.env as "
        "GEMINI_API_KEY=your_key_here"
    )

MODEL_NAME = "gemini-2.5-flash"

client = genai.Client(api_key=GEMINI_API_KEY)
router = APIRouter()
SUPPORTED_SUFFIXES = {".pdf", ".txt"}
DATA_DIR = Path(__file__).resolve().parent / "data"
JUDGMENTS_FILE = DATA_DIR / "judgments.jsonl"


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


def summarize_legal_text(text: str, max_chars: int = 20000) -> str:
    """Produce a concise, structured legal summary of the provided text using Gemini."""
    is_truncated = len(text) > max_chars
    truncated_text = text[:max_chars] if is_truncated else text

    prompt = f"""You are a legal research assistant. Produce a concise, structured legal summary of the following document using ONLY the provided text (do not use outside knowledge).

The summary must be under 200 words and contain exactly four labeled sections:
- Facts:
- Issue/Question of Law:
- Holding/Decision:
- Reasoning:

Provided text:
{truncated_text}

Summary:"""

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
    )
    summary_text = response.text or ""

    if is_truncated:
        summary_text = f"{summary_text}\n\n[Note: Source text was truncated to {max_chars} characters for length.]"

    return summary_text


@router.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    user=Depends(require_role("lawyer", "judge")),
) -> dict[str, Any]:
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


class SummarizeUploadedRequest(BaseModel):
    extracted_text: str


@router.post("/documents/summarize-uploaded")
def summarize_uploaded(
    request: SummarizeUploadedRequest,
    user=Depends(require_role("lawyer", "judge")),
) -> dict[str, str]:
    if not request.extracted_text.strip():
        raise HTTPException(
            status_code=400, detail="extracted_text cannot be empty"
        )
    summary = summarize_legal_text(request.extracted_text)
    return {"summary": summary}


@lru_cache(maxsize=1)
def _load_judgments_index() -> dict[str, dict[str, Any]]:
    """Load judgments from judgments.jsonl indexed by case_name."""
    if not JUDGMENTS_FILE.exists():
        return {}
    index: dict[str, dict[str, Any]] = {}
    with JUDGMENTS_FILE.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            case_name = record.get("case_name")
            if case_name:
                index[case_name] = record
    return index


def find_judgment_by_case_name(case_name: str) -> dict[str, Any] | None:
    """Read backend/data/judgments.jsonl and return matching record, or None."""
    index = _load_judgments_index()
    if case_name in index:
        return index[case_name]
    if JUDGMENTS_FILE.exists():
        _load_judgments_index.cache_clear()
        return _load_judgments_index().get(case_name)
    return None


get_judgment_by_case_name = find_judgment_by_case_name


@router.get("/judgments/{case_name}/summary")
def get_judgment_summary(
    case_name: str,
    user=Depends(require_role("lawyer", "judge")),
) -> dict[str, str]:
    """Return an AI-generated structured summary for a judgment in the corpus."""
    decoded_case_name = unquote(case_name).strip()
    record = find_judgment_by_case_name(decoded_case_name)
    if record is None and decoded_case_name != case_name:
        record = find_judgment_by_case_name(case_name)

    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"No judgment found with case_name: {case_name}",
        )

    summary = summarize_legal_text(record["full_text"])
    return {"case_name": case_name, "summary": summary}

class CompareCasesRequest(BaseModel):
    case_names: list[str]


@router.post("/judgments/compare")
def compare_judgments(
    request: CompareCasesRequest,
    user=Depends(require_role("judge")),
) -> dict[str, Any]:
    """Summarize 2-3 judgments side by side for judge case comparison."""
    if not 2 <= len(request.case_names) <= 3:
        raise HTTPException(
            status_code=400,
            detail="Provide between 2 and 3 case_names to compare",
        )

    results = []
    missing = []
    for case_name in request.case_names:
        record = find_judgment_by_case_name(case_name)
        if record is None:
            missing.append(case_name)
            continue
        results.append(
            {
                "case_name": record.get("case_name", case_name),
                "court": record.get("court", ""),
                "year": record.get("year"),
                "ipc_sections": record.get("ipc_sections", []),
                "summary": summarize_legal_text(record["full_text"]),
            }
        )

    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"No judgment found for: {', '.join(missing)}",
        )

    return {"results": results}

class ExportCaseFileRequest(BaseModel):
    case_names: list[str]


@router.post("/documents/export-case-file")
def export_case_file(
    request: ExportCaseFileRequest,
    user=Depends(require_role("lawyer", "judge")),
) -> StreamingResponse:
    """Export selected judgments as a single downloadable Word document."""
    if not request.case_names:
        raise HTTPException(status_code=400, detail="Provide at least one case_name")

    doc = DocxDocument()
    doc.add_heading("Case File Export", level=0)
    doc.add_paragraph(f"Prepared by: {user.username} ({user.role})")
    doc.add_paragraph(f"Cases included: {len(request.case_names)}")

    missing = []
    for case_name in request.case_names:
        record = find_judgment_by_case_name(case_name)
        if record is None:
            missing.append(case_name)
            continue

        doc.add_heading(record.get("case_name", case_name), level=1)
        meta_parts = [record.get("court", ""), str(record.get("year", ""))]
        ipc_sections = record.get("ipc_sections", [])
        if ipc_sections:
            meta_parts.append(f"IPC {', '.join(str(s) for s in ipc_sections)}")
        doc.add_paragraph(" · ".join(p for p in meta_parts if p))

        doc.add_paragraph(summarize_legal_text(record["full_text"]))
        doc.add_page_break()

    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"No judgment found for: {', '.join(missing)}",
        )

    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=case_file_export.docx"},
    )