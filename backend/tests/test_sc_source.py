"""corpus/sc_source.py: listing parser, bucket listing, metadata download/load.

No network: fetch is faked. Listing fixtures follow the real raw_html layout
(Dattam Labs dataset, CC-BY-4.0), shortened.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from corpus import sc_source  # noqa: E402

PICKER_AND_DISCLAIMER = (
    "<select class='form-select' id='language7'><option value=''>English</option>"
    "<option value='HIN'>&#2361;&#2367;&#2344;&#2381;&#2342;&#2368; - Hindi</option></select><br>"
    "<div class='modal-body'><p> Due care and caution has been taken by the Editorial Section, "
    "Supreme Court of India ... we shall be obliged if errors/omissions are "
    "brought to our notice for carrying out the corrections.</p></div>"
)


def listing_html(heading: str, coram: str, headnote: str, tail: str) -> str:
    return (
        f"{PICKER_AND_DISCLAIMER}<div><b>{heading}</b> Coram : {coram} <p>{headnote}</p>"
        f"<span>{tail}</span> <a>Flip view PDF</a></div>"
    )


RAM_SWARUP = listing_html(
    "STATE OF U.P. versus RAM SWARUP &amp; ANR. - [1975] 1 S.C.R. 409 1974 INSC 116",
    "M. HAMEEDULLAH BEG * , Y.V. CHANDRACHUD, V.R. KRISHNA IYER",
    "Criminal Law-Murder-Private defence, right of. Appeal against acquittal.",
    "Decision Date : 08-08-1974 | Case No : CRIMINAL APPEAL No. 49/1970 | "
    "Disposal Nature : Appeal(s) allowed | Bench : 3 Judges",
)


def test_parse_listing_real_layout() -> None:
    listing = sc_source.parse_listing(RAM_SWARUP)
    assert listing.heading == "STATE OF U.P. versus RAM SWARUP & ANR. - [1975] 1 S.C.R. 409 1974 INSC 116"
    assert listing.coram == ["M. HAMEEDULLAH BEG", "Y.V. CHANDRACHUD", "V.R. KRISHNA IYER"]
    assert listing.author_judge == "M. HAMEEDULLAH BEG"
    assert listing.headnote_excerpt == "Criminal Law-Murder-Private defence, right of. Appeal against acquittal."
    assert listing.has_headnote
    assert listing.decision_date == "08-08-1974"
    assert listing.case_no == "CRIMINAL APPEAL No. 49/1970"
    assert listing.case_type == "CRIMINAL APPEAL"
    assert sc_source.is_criminal_case_type(listing.case_type)
    assert listing.disposal_nature == "Appeal(s) allowed"
    assert listing.bench_size == 3


@pytest.mark.parametrize(
    "coram_and_headnote, judges, headnote_start",
    [
        # SCR margin letters and page numbers end the judge list.
        ("HANS RAJ KHANNA * , Y.V. CHANDRACHUD F G H 747 STATE OF PUNJAB v. BHAJAN SINGH",
         ["HANS RAJ KHANNA", "Y.V. CHANDRACHUD"], "F G H 747"),
        ("S.B. SINHA * , DALVEER BHANDARI 4 S.C.R. 881 DINESH BORTHAKUR v. STATE OF ASSAM",
         ["S.B. SINHA", "DALVEER BHANDARI"], "4 S.C.R. 881"),
        # OCR punctuation right after the names.
        ("N.L. UNTWALIA * , P.N. SHINGAL .: Criminal Procedure Code 1973-Sections 226, 227",
         ["N.L. UNTWALIA", "P.N. SHINGAL"], "Criminal Procedure Code"),
        # No author star (common before the 1970s).
        ("MEHR CHAND MAHAJAN, BIJAN KUMAR MUKHERJEA, SIR SYED FAZL ALI Court Reports.",
         ["MEHR CHAND MAHAJAN", "BIJAN KUMAR MUKHERJEA", "SIR SYED FAZL ALI"], "Court Reports."),
    ],
)
def test_coram_split_variants(coram_and_headnote: str, judges: list[str], headnote_start: str) -> None:
    raw = f"{PICKER_AND_DISCLAIMER} X versus Y - [1975] 1 S.C.R. 1 1975 INSC 1 Coram : {coram_and_headnote} Decision Date : 01-01-1975 | Case No : CIVIL APPEAL No. 1/1975 | Bench : {len(judges)} Judges"
    listing = sc_source.parse_listing(raw)
    assert listing.coram == judges
    assert listing.headnote_excerpt.startswith(headnote_start)
    assert listing.bench_size == len(judges)


def test_listing_without_headnote() -> None:
    raw = (
        f"{PICKER_AND_DISCLAIMER} K. VENKATACHALAM versus A. SWAMICKAN AND ANR. - [1999] 2 S.C.R. 857 "
        "1999 INSC 202 Coram : D.P. WADHWA * , N. SANTOSH HEGDE Decision Date : 26-04-1999 | "
        "Case No : CIVIL APPEAL No. 1719/1986 | Disposal Nature : Dismissed | Bench : 2 Judges Flip view PDF"
    )
    listing = sc_source.parse_listing(raw)
    assert listing.headnote_excerpt == ""
    assert not listing.has_headnote
    assert listing.coram == ["D.P. WADHWA", "N. SANTOSH HEGDE"]
    assert listing.case_type == "CIVIL APPEAL" and not sc_source.is_criminal_case_type(listing.case_type)


def test_empty_listing_does_not_crash() -> None:
    listing = sc_source.parse_listing(None)
    assert listing.coram == [] and listing.case_type == "" and not listing.has_headnote


@pytest.mark.parametrize(
    "case_no, kind, criminal",
    [
        ("CRIMINAL APPEAL No. 687/2007", "CRIMINAL APPEAL", True),
        ("SPECIAL LEAVE PETITION (CRIMINAL) No. 5/2010", "SPECIAL LEAVE PETITION (CRIMINAL)", True),
        ("WRIT PETITION (CIVIL) no. 12/2001", "WRIT PETITION (CIVIL)", False),
        ("CIVIL APPEAL No. 1/1975", "CIVIL APPEAL", False),
    ],
)
def test_case_type(case_no: str, kind: str, criminal: bool) -> None:
    assert sc_source.case_type(case_no) == kind
    assert sc_source.is_criminal_case_type(kind) is criminal


def test_urls() -> None:
    assert sc_source.metadata_url(1975) == (
        "https://indian-supreme-court-judgments.s3.ap-south-1.amazonaws.com/metadata/parquet/year=1975/metadata.parquet"
    )
    assert sc_source.pdf_url(1995, "S_1995_2_629_636").endswith("/data/pdf/year=1995/english/S_1995_2_629_636_EN.pdf")


LISTING_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Name>indian-supreme-court-judgments</Name>
<Prefix>metadata/parquet/</Prefix><Delimiter>/</Delimiter><IsTruncated>false</IsTruncated>
<CommonPrefixes><Prefix>metadata/parquet/year=1951/</Prefix></CommonPrefixes>
<CommonPrefixes><Prefix>metadata/parquet/year=1950/</Prefix></CommonPrefixes>
<CommonPrefixes><Prefix>metadata/parquet/year=2026/</Prefix></CommonPrefixes></ListBucketResult>"""


def test_list_years_parses_bucket_prefixes() -> None:
    assert sc_source.list_years(lambda url: LISTING_XML) == [1950, 1951, 2026]


def test_download_metadata_is_resumable(tmp_path: Path) -> None:
    fetched: list[str] = []

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return b"PAR1-fake"

    paths = sc_source.download_metadata(tmp_path, [1975, 1995], fetch=fetch, out=lambda _: None)
    assert [p.name for p in paths] == ["metadata_1975.parquet", "metadata_1995.parquet"]
    assert all(p.read_bytes() == b"PAR1-fake" for p in paths)
    assert len(fetched) == 2

    sc_source.download_metadata(tmp_path, [1975, 1995, 2010], fetch=fetch, out=lambda _: None)
    assert fetched[2:] == [sc_source.metadata_url(2010)]  # existing years are not re-fetched
    assert not list(tmp_path.rglob("*.tmp"))


def test_load_metadata_drops_exact_duplicate_paths(tmp_path: Path) -> None:
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    row = {c: "" for c in sc_source.METADATA_COLUMNS}
    rows = [
        {**row, "year": "1975", "path": "1975_1_409_421", "title": "A"},
        {**row, "year": "1975", "path": "1975_1_409_421", "title": "A"},
        {**row, "year": "1975", "path": "1975_1_561_574", "title": "B"},
    ]
    target = sc_source.metadata_file(tmp_path, 1975)
    target.parent.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(target)

    frame, dropped = sc_source.load_metadata(tmp_path)

    assert dropped == 1
    assert list(frame.path) == ["1975_1_409_421", "1975_1_561_574"]
    assert frame.year.dtype.kind == "i"
