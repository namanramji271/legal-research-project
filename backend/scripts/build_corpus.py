"""Build a focused IPC judgment corpus from the ILDC portion of IL-TUR.

Before running, accept the IL-TUR access conditions at
https://huggingface.co/datasets/Exploration-Lab/IL-TUR and authenticate with
``huggingface-cli login`` (or set HF_TOKEN).  The dataset is research-only.

Usage:
    python backend/scripts/build_corpus.py
    python backend/scripts/build_corpus.py --token "$HF_TOKEN" --target 50
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

DATASET_NAME = "Exploration-Lab/IL-TUR"
DATASET_CONFIG = "cjpe"
DEFAULT_TARGET = 50
MIN_TARGET = 40
MAX_TARGET = 60

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = SCRIPT_DIR.parent / "data" / "judgments.jsonl"

# The project scope covers culpable homicide/murder (299–304) and private
# defence (96–106).  Section 304A is intentionally excluded: it concerns
# death by negligence rather than culpable homicide.
TARGET_SECTIONS = frozenset(
    {str(section) for section in range(96, 107)}
    | {str(section) for section in range(299, 305)}
)

IPC_NAME = r"(?:Indian\s+Penal\s+Code|IPC)"
SECTION_REFERENCE = re.compile(
    rf"\b(?:section|sections|sec\.?|ss\.?|u/s)\s+"
    rf"(?P<references>[^.;:\n]{{0,140}}?)\s+"
    rf"(?:of\s+the\s+)?{IPC_NAME}\b",
    re.IGNORECASE,
)
CODE_FIRST_REFERENCE = re.compile(
    rf"\b{IPC_NAME}\s*(?:,|:|-)?\s*"
    r"(?:section|sections|sec\.?|ss\.?)?\s*"
    r"(?P<references>\d{1,3}[A-Za-z]?(?:\(\d+\))?(?:\s*(?:,|/|and|or|to|-)\s*"
    r"\d{1,3}[A-Za-z]?(?:\(\d+\))?)*)",
    re.IGNORECASE,
)
SECTION_NUMBER = re.compile(r"\b(\d{1,3}[A-Za-z]?)(?:\(\d+\))?\b")
SECTION_RANGE = re.compile(r"\b(\d{1,3})\s*(?:to|-)\s*(\d{1,3})\b", re.IGNORECASE)
CASE_NAME = re.compile(
    r"(?mi)^\s*([A-Z][A-Z .,'&()/\-]{2,100}?)\s+"
    r"(?:v\.?|vs\.?|versus)\s+([A-Z][A-Z .,'&()/\-]{2,100}?)\s*$"
)
COURT = re.compile(r"(?im)^\s*(SUPREME COURT OF INDIA|[A-Z][A-Z ]{3,80}HIGH COURT)\s*$")
DATED_YEAR = re.compile(
    r"(?i)\b(?:dated|date of (?:judgment|decision)|pronounced on)\D{0,45}?"
    r"((?:19|20)\d{2})\b"
)
ANY_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")


def as_text(value: Any) -> str:
    """Normalize IL-TUR's string/list text fields into one document string."""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return "\n".join(as_text(item) for item in value.values())
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        return "\n".join(as_text(item) for item in value)
    return ""


def text_from_record(record: Mapping[str, Any]) -> str:
    for key in ("text", "full_text", "document", "judgment", "content"):
        if key in record and (text := as_text(record[key]).strip()):
            return text
    return ""


def normalize_sections(value: Any) -> set[str]:
    """Return in-scope IPC section numbers from a text or metadata value."""
    sections = set()
    text = as_text(value)
    for match in SECTION_RANGE.finditer(text):
        start, end = (int(number) for number in match.groups())
        if start <= end:
            sections.update(
                str(section)
                for section in range(start, end + 1)
                if str(section) in TARGET_SECTIONS
            )
    for match in SECTION_NUMBER.finditer(text):
        section = match.group(1).upper()
        if section in TARGET_SECTIONS:
            sections.add(section)
    return sections


def cited_ipc_sections(text: str) -> set[str]:
    """Extract target IPC sections only when an IPC citation context is present."""
    sections = set()
    for pattern in (SECTION_REFERENCE, CODE_FIRST_REFERENCE):
        for match in pattern.finditer(text):
            sections.update(normalize_sections(match.group("references")))
    return sections


def metadata_ipc_sections(record: Mapping[str, Any]) -> set[str]:
    """Read explicit statute metadata without treating CJPE's outcome label as one."""
    sections = set()
    for key, value in record.items():
        lowered = key.lower()
        if any(marker in lowered for marker in ("ipc", "statute", "section")):
            sections.update(normalize_sections(value))
    return sections


def case_name_from_text(text: str, record: Mapping[str, Any]) -> str:
    for key in ("case_name", "title", "name"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    match = CASE_NAME.search(text[:8000])
    if match:
        return " ".join(f"{match.group(1)} v. {match.group(2)}".split())
    return f"ILDC case {record.get('id', 'unknown')}"


def court_from_text(text: str, record: Mapping[str, Any]) -> str:
    value = record.get("court")
    if isinstance(value, str) and value.strip():
        return " ".join(value.split())
    match = COURT.search(text[:8000])
    if match:
        court = match.group(1)
        if court == "SUPREME COURT OF INDIA":
            return "Supreme Court of India"
        return court.title()
    # ILDC's CJPE records are Indian Supreme Court judgments.
    return "Supreme Court of India"


def year_from_text(text: str, record: Mapping[str, Any]) -> int | None:
    value = record.get("year")
    if isinstance(value, int) and 1900 <= value <= 2100:
        return value
    if isinstance(value, str) and value.isdigit() and 1900 <= int(value) <= 2100:
        return int(value)
    match = DATED_YEAR.search(text[:12000]) or ANY_YEAR.search(text[:12000])
    return int(match.group(1)) if match else None


def to_output_record(record: Mapping[str, Any]) -> dict[str, Any] | None:
    full_text = text_from_record(record)
    if not full_text:
        return None
    ipc_sections = cited_ipc_sections(full_text) | metadata_ipc_sections(record)
    if not ipc_sections:
        return None
    return {
        "case_name": case_name_from_text(full_text, record),
        "court": court_from_text(full_text, record),
        "year": year_from_text(full_text, record),
        "ipc_sections": sorted(ipc_sections, key=lambda section: int(re.match(r"\d+", section).group())),
        "full_text": full_text,
    }


def stream_cjpe_records(token: str | None):
    """Yield ILDC records from every public CJPE split without downloading all data."""
    try:
        from datasets import get_dataset_split_names, load_dataset
    except ImportError as error:
        raise SystemExit(
            "Missing dependency 'datasets'. Install it with: pip install datasets"
        ) from error

    try:
        split_names = get_dataset_split_names(
            DATASET_NAME, DATASET_CONFIG, token=token
        )
    except Exception as error:
        raise SystemExit(
            "Could not list IL-TUR CJPE splits. Accept the dataset conditions and "
            "authenticate with 'huggingface-cli login' or provide --token.\n"
            f"Original error: {error}"
        ) from error

    for split_name in split_names:
        yield from load_dataset(
            DATASET_NAME,
            DATASET_CONFIG,
            split=split_name,
            streaming=True,
            token=token,
        )


def build_corpus(target: int, token: str | None, output_path: Path) -> int:
    selected: list[dict[str, Any]] = []
    seen_documents: set[str] = set()
    for record in stream_cjpe_records(token):
        output_record = to_output_record(record)
        if output_record is None:
            continue
        document_id = str(record.get("id") or hash(output_record["full_text"]))
        if document_id in seen_documents:
            continue
        seen_documents.add(document_id)
        selected.append(output_record)
        if len(selected) == target:
            break

    if len(selected) < MIN_TARGET:
        raise RuntimeError(
            f"Found only {len(selected)} relevant judgments; expected at least {MIN_TARGET}. "
            "No output file was written."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as destination:
        for record in selected:
            destination.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(selected)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        type=int,
        default=DEFAULT_TARGET,
        help=f"Number of judgments to write ({MIN_TARGET}-{MAX_TARGET}; default: {DEFAULT_TARGET}).",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("HF_TOKEN"),
        help="Hugging Face token. Defaults to the HF_TOKEN environment variable.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help=f"JSONL output path (default: {OUTPUT_PATH}).",
    )
    args = parser.parse_args()
    if not MIN_TARGET <= args.target <= MAX_TARGET:
        parser.error(f"--target must be between {MIN_TARGET} and {MAX_TARGET}")
    return args


def main() -> None:
    args = parse_args()
    count = build_corpus(args.target, args.token, args.output)
    print(f"Wrote {count} relevant judgments to {args.output}")


if __name__ == "__main__":
    main()
