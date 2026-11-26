"""Supreme Court judgments source for corpus v2.

Source: s3://indian-supreme-court-judgments (region ap-south-1), the Indian
Supreme Court Judgments open dataset maintained by Dattam Labs, CC-BY-4.0.
Read anonymously over HTTPS; no AWS account is needed.

This module only fetches and parses the per-year metadata parquet files. Each
row's ``raw_html`` holds the eCourts listing: a language picker, a fixed
disclaimer, then "<title> - <citation> <case_id> Coram : <judges> <headnote
excerpt> Decision Date : ... | Case No : ... | Disposal Nature : ... |
Bench : N Judges Flip view PDF". The headnote here is an excerpt (about 600
characters); the full headnote is in the PDF.

Downloads go to a work directory outside the repository (default
~/.cache/legal-research/sc_v2), never to backend/data/.
"""

from __future__ import annotations

import html
import re
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

BUCKET = "indian-supreme-court-judgments"
REGION = "ap-south-1"
BASE_URL = f"https://{BUCKET}.s3.{REGION}.amazonaws.com"
SOURCE = f"Dattam Labs, s3://{BUCKET} (CC-BY-4.0)"
DEFAULT_WORK_DIR = Path.home() / ".cache" / "legal-research" / "sc_v2"
USER_AGENT = "legal-research-corpus-builder/1.0"

Fetch = Callable[[str], bytes]

_DISCLAIMER_END = "brought to our notice for carrying out the corrections."
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_TAIL = re.compile(r"\s*Decision Date\s*:")
_FIELD = r"\s*:\s*(?P<value>[^|]*?)\s*(?:\||Flip view PDF|$)"
_CASE_NO = re.compile(r"Case No" + _FIELD)
_DECISION_DATE = re.compile(r"Decision Date" + _FIELD)
_DISPOSAL = re.compile(r"Disposal Nature" + _FIELD)
_BENCH = re.compile(r"Bench\s*:\s*(\d+)\s*Judges?")
_CORAM = re.compile(r"Coram\s*:\s*")
_NAME_TOKEN = re.compile(r"^[A-Z][A-Z.'\-]*,?$")
_CASE_TYPE_TAIL = re.compile(r"\s*NO\b.*$", re.IGNORECASE)


def http_get(url: str, timeout: float = 60.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def metadata_url(year: int) -> str:
    return f"{BASE_URL}/metadata/parquet/year={year}/metadata.parquet"


def pdf_url(year: int, path: str) -> str:
    return f"{BASE_URL}/data/pdf/year={year}/english/{path}_EN.pdf"


def list_years(fetch: Fetch = http_get) -> list[int]:
    """Years that have a metadata/parquet/year=YYYY/ prefix in the bucket."""
    xml = fetch(f"{BASE_URL}/?list-type=2&delimiter=/&prefix=metadata/parquet/")
    root = ElementTree.fromstring(xml)
    years = []
    for element in root.iter():
        if element.tag.endswith("Prefix") and element.text:
            match = re.fullmatch(r"metadata/parquet/year=(\d{4})/", element.text)
            if match:
                years.append(int(match.group(1)))
    if not years:
        raise RuntimeError("No metadata/parquet/year=YYYY/ prefixes found in the bucket listing")
    return sorted(set(years))


def metadata_file(work_dir: Path, year: int) -> Path:
    return work_dir / "metadata" / f"metadata_{year}.parquet"


def download_metadata(
    work_dir: Path,
    years: Iterable[int] | None = None,
    fetch: Fetch = http_get,
    force: bool = False,
    out: Callable[[str], None] = print,
) -> list[Path]:
    """Download each year's metadata parquet; existing files are kept unless force."""
    years = list(years) if years is not None else list_years(fetch)
    paths = []
    for year in years:
        destination = metadata_file(work_dir, year)
        if destination.is_file() and not force:
            paths.append(destination)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = fetch(metadata_url(year))
        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(destination)
        out(f"metadata {year}: {len(data) / 1e6:.2f} MB")
        paths.append(destination)
    return paths


def visible_text(raw_html: str | None) -> str:
    """Tags stripped, entities unescaped, whitespace collapsed."""
    return _SPACE.sub(" ", html.unescape(_TAG.sub(" ", raw_html or ""))).strip()


def case_type(case_no: str) -> str:
    """'CRIMINAL APPEAL No. 12/1990' -> 'CRIMINAL APPEAL'."""
    return _SPACE.sub(" ", _CASE_TYPE_TAIL.sub("", case_no or "")).strip().upper()


def is_criminal_case_type(kind: str) -> bool:
    return bool(re.search(r"\bCRIMINAL\b|\bCRL\b", kind or "", re.IGNORECASE))


@dataclass(frozen=True)
class Listing:
    """Fields parsed from one row's raw_html."""

    heading: str = ""  # "<title> - <citation> <case_id>"
    coram: list[str] = field(default_factory=list)
    author_judge: str | None = None
    headnote_excerpt: str = ""
    decision_date: str = ""
    case_no: str = ""
    case_type: str = ""
    disposal_nature: str = ""
    bench_size: int | None = None

    @property
    def has_headnote(self) -> bool:
        """True when the listing carries headnote text (not just the metadata tail)."""
        return len(self.headnote_excerpt) >= 40


def _split_coram(text: str) -> tuple[list[str], str]:
    """Split 'A.B. NAME * , C. NAME Criminal Law-...' into judges and the rest.

    Names are runs of all-caps tokens separated by commas; '*' marks the author.
    Stops at the first token with a lowercase letter, a bare number or a bare
    single letter (SCR margin letters such as 'F G H').
    """
    tokens = text.split(" ")
    consumed = 0
    for token in tokens:
        bare = token.rstrip(",")
        single_letter = len(bare) == 1 and bare.isalpha()
        if token in ("*", "*,", ",") or (_NAME_TOKEN.match(token) and not single_letter):
            consumed += 1
            continue
        break
    names = " ".join(tokens[:consumed])
    judges = [_SPACE.sub(" ", name).strip() for name in names.split(",")]
    rest = " ".join(tokens[consumed:]).lstrip(" ,.:;")
    return [judge for judge in judges if judge.strip("* ")], rest


def parse_listing(raw_html: str | None) -> Listing:
    text = visible_text(raw_html)
    if _DISCLAIMER_END in text:
        text = text.split(_DISCLAIMER_END, 1)[1].strip()
    tail_match = _TAIL.search(text)
    body, tail = (text[: tail_match.start()], text[tail_match.start():]) if tail_match else (text, "")

    coram_match = _CORAM.search(body)
    if coram_match:
        heading = body[: coram_match.start()].strip()
        raw_judges, headnote = _split_coram(body[coram_match.end():])
    else:
        heading, raw_judges, headnote = "", [], body
    author = next((j.replace("*", "").strip() for j in raw_judges if "*" in j), None)
    coram = [j.replace("*", "").strip() for j in raw_judges]

    def tail_field(pattern: re.Pattern[str]) -> str:
        match = pattern.search(tail)
        return match.group("value").strip() if match else ""

    case_no = tail_field(_CASE_NO)
    bench = _BENCH.search(tail)
    return Listing(
        heading=heading,
        coram=coram,
        author_judge=author,
        headnote_excerpt=headnote.strip(),
        decision_date=tail_field(_DECISION_DATE),
        case_no=case_no,
        case_type=case_type(case_no),
        disposal_nature=tail_field(_DISPOSAL),
        bench_size=int(bench.group(1)) if bench else None,
    )


METADATA_COLUMNS = (
    "year", "path", "title", "citation", "case_id", "cnr", "decision_date",
    "disposal_nature", "judge", "raw_html",
)


def load_metadata(work_dir: Path, years: Iterable[int] | None = None) -> tuple[Any, int]:
    """All downloaded years as one DataFrame, one row per ``path``.

    Returns (dataframe, duplicate_rows_dropped). The bucket repeats some rows
    exactly within a year; ``path`` (also the PDF name) is the unique key.
    """
    import pandas as pd

    files = (
        [metadata_file(work_dir, y) for y in years]
        if years is not None
        else sorted((work_dir / "metadata").glob("metadata_*.parquet"))
    )
    if not files:
        raise FileNotFoundError(f"No metadata parquet files under {work_dir / 'metadata'}")
    frame = pd.concat(
        [pd.read_parquet(f, columns=list(METADATA_COLUMNS)) for f in files], ignore_index=True
    )
    before = len(frame)
    frame = frame.drop_duplicates("path", keep="first").reset_index(drop=True)
    frame["year"] = frame["year"].astype(int)
    return frame, before - len(frame)
