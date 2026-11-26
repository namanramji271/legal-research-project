"""Headnote pre-filter, census summary and non-candidate sampler (no network)."""

from __future__ import annotations

import json
import sys
from collections import namedtuple
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from corpus import census, sample_noncandidates, sc_source  # noqa: E402
from corpus.prefilter import era, in_scope_sections, prefilter  # noqa: E402


# --- pre-filter on real headnote phrasings ------------------------------------

@pytest.mark.parametrize(
    "excerpt, reasons, sections, groups",
    [
        ("Criminal Law-Murder-Private defence, right of. Appeal against acquittal.",
         ("murder_keyword", "private_defence_keyword"), (), ("private_defence",)),
        ("Penal Code 1860: ss. 302, 307 – Two persons were done to death",
         ("ipc_section",), ("302",), ("302",)),
        ("Indian Penal Code, 1860-S.302-Murder trial-Sole eye witness",
         ("murder_keyword", "ipc_section"), ("302",), ("302",)),
        ("I.P.C. ss. 304 Part II and 34 - culpable homicide not amounting to murder",
         ("murder_keyword", "ipc_section"), ("304",), ("304",)),
        ("Panel Code-s. 300 Exception 4-Sudden fight", ("ipc_section",), ("300",), ("299-301",)),
        ("Circumstantial evidence-Criminal case-Value of. The accused was convicted for murder.",
         ("murder_keyword",), (), ("keyword_only",)),
    ],
)
def test_candidates(excerpt: str, reasons: tuple, sections: tuple, groups: tuple) -> None:
    result = prefilter(excerpt)
    assert result.candidate
    assert result.reasons == reasons
    assert result.sections == sections
    assert result.groups == groups


@pytest.mark.parametrize(
    "excerpt",
    [
        # CPC first/second appeals: s.96 / s.100 CPC.
        "Code of Civil Procedure, 1908-s. 100-Second appeal-Substantial question of law. Penal Code not relevant.",
        "Penal Code mentioned; appeal under s. 96 C.P.C. against decree",
        # Evidence Act burden of proof collides with 101-106.
        "Indian Penal Code, 1860; s. 106 of the Evidence Act - burden on accused",
        # CrPC s.100 search (OCR spacing).
        "I.P.C. offence alleged; search under s. 100(4) Cr.P .C. invalid",
        # In-scope number without any IPC name in the excerpt.
        "Arbitration Act, 1940-s. 30-Award set aside",
        "",
    ],
)
def test_non_candidates(excerpt: str) -> None:
    assert not prefilter(excerpt).candidate


def test_primary_group_is_the_rarest() -> None:
    result = prefilter("Penal Code: ss. 302 and 304 and 100 - private defence exceeded - murder")
    assert result.groups == ("private_defence", "304", "302")
    assert result.primary_group == "private_defence"


def test_section_lists_and_ranges_of_forms() -> None:
    assert in_scope_sections("ss. 302/34, 304 and 307") == ["302", "304"]
    assert in_scope_sections("Section 302 read with Section 34") == ["302"]
    assert in_scope_sections("u/s 299 r/w 300") == ["299", "300"]


@pytest.mark.parametrize("year, label", [(1950, "1950-1979"), (1979, "1950-1979"), (1980, "1980-1999"),
                                         (2009, "2000-2009"), (2010, "2010-2026"), (2026, "2010-2026")])
def test_era(year: int, label: str) -> None:
    assert era(year) == label


# --- census summary -----------------------------------------------------------

Row = namedtuple("Row", sc_source.METADATA_COLUMNS)
DISCLAIMER = "brought to our notice for carrying out the corrections."


def row(path: str, year: int, headnote: str, case_no: str) -> Row:
    raw = (f"{DISCLAIMER} A versus B - [{year}] 1 S.C.R. 1 {year} INSC 1 Coram : X. JUDGE * , Y. JUDGE "
           f"{headnote} Decision Date : 01-01-{year} | Case No : {case_no} | Bench : 2 Judges Flip view PDF")
    return Row(year=str(year), path=path, title="A versus B", citation=f"[{year}] 1 S.C.R. 1",
               case_id=f"{year} INSC 1", cnr="", decision_date=f"01-01-{year}", disposal_nature="",
               judge="X. JUDGE", raw_html=raw)


class FakeFrame:
    def __init__(self, rows: list[Row]) -> None:
        self.rows = rows

    def itertuples(self, index: bool = False):
        return iter(self.rows)


ROWS = [
    row("1975_1_409_421", 1975, "Criminal Law-Murder-Private defence, right of.", "CRIMINAL APPEAL No. 49/1970"),
    row("1995_2_887_899", 1995, "Indian Penal Code, 1860-S.302-Murder trial.", "CRIMINAL APPEAL No. 5/1990"),
    row("2022_16_967_1001", 2022, "Penal Code 1860: ss. 302, 307 – Two persons were done to death.", "CRIMINAL APPEAL No. 9/2020"),
    row("2010_3_1106_1120", 2010, "Industrial Disputes Act, 1947-s. 25F-Retrenchment of workmen.", "CIVIL APPEAL No. 1/2005"),
    row("1952_1_110_120", 1952, "", "CIVIL APPEAL No. 2/1950"),
]


def test_census_summary_counts() -> None:
    records = census.annotate(FakeFrame(ROWS))
    summary = census.summarize(records, duplicates_dropped=3)

    assert summary["metadata_rows_unique"] == 5 and summary["duplicate_rows_dropped"] == 3
    assert summary["candidates"] == 3 and summary["non_candidates"] == 2
    assert summary["candidate_reasons"] == {"murder_keyword": 2, "private_defence_keyword": 1, "ipc_section": 2}
    assert summary["headnote_present_by_decade"]["1950s"] == {"documents": 1, "with_headnote": 0, "rate": 0.0}
    assert summary["headnote_present_by_decade"]["1970s"]["rate"] == 1.0
    primary = summary["candidates_by_era_and_primary_group"]
    assert primary["private_defence"]["1950-1979"] == 1
    assert primary["302"]["1980-1999"] == 1 and primary["302"]["2010-2026"] == 1
    assert primary["302"]["total"] == 2
    assert summary["candidates_criminal"] == {"count": 3, "share": 1.0}
    assert summary["non_candidates_criminal"] == 0
    rendered = census.render(summary)
    assert "Candidates: 3" in rendered and "1950s: 0/1 = 0.00%" in rendered
    first = next(r for r in records if r["doc_id"] == "1975_1_409_421")
    assert first["coram"] == ["X. JUDGE", "Y. JUDGE"] and first["author_judge"] == "X. JUDGE"
    assert first["pdf_url"].endswith("/year=1975/english/1975_1_409_421_EN.pdf")
    assert "full_text" not in first and "raw_html" not in first  # no text in the outputs


def test_census_run_end_to_end_without_network(tmp_path: Path) -> None:
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    for year in (1975, 2022):
        target = sc_source.metadata_file(tmp_path, year)
        target.parent.mkdir(parents=True, exist_ok=True)
        rows = [r._asdict() for r in ROWS if int(r.year) == year]
        pd.DataFrame(rows + rows).to_parquet(target)  # duplicated rows on purpose

    lines: list[str] = []
    summary = census.run(tmp_path, skip_download=True, out=lines.append)

    assert summary["metadata_rows_unique"] == 2 and summary["duplicate_rows_dropped"] == 2
    assert json.loads((tmp_path / "census.json").read_text(encoding="utf-8"))["candidates"] == 2
    assert len((tmp_path / "candidates.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    assert (tmp_path / "non_candidates.jsonl").read_text(encoding="utf-8") == ""


# --- non-candidate sampler ----------------------------------------------------

def _non_candidates(tmp_path: Path) -> list[dict]:
    records = []
    for e, years in (("1950-1979", range(1950, 1980)), ("1980-1999", range(1980, 2000)),
                     ("2000-2009", range(2000, 2010)), ("2010-2026", range(2010, 2027))):
        for i, y in enumerate(years):
            records.append({"doc_id": f"{y}_1_{i}", "year": y, "era": e, "title": "T", "citation": "C",
                            "case_id": "I", "case_type": "CRIMINAL APPEAL" if i % 3 == 0 else "CIVIL APPEAL",
                            "criminal": i % 3 == 0, "pdf_url": "u"})
    (tmp_path / "non_candidates.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return records


def test_sampler_is_era_stratified_seeded_and_order_independent(tmp_path: Path) -> None:
    records = _non_candidates(tmp_path)
    a = sample_noncandidates.stratified_sample(records, 20, seed=7)
    b = sample_noncandidates.stratified_sample(list(reversed(records)), 20, seed=7)
    assert a == b
    assert [sum(r["era"] == e for r in a) for e in sample_noncandidates.ERA_LABELS] == [5, 5, 5, 5]
    assert len({r["doc_id"] for r in a}) == 20
    assert sample_noncandidates.stratified_sample(records, 20, seed=8) != a


def test_sampler_remainder_and_small_pools() -> None:
    records = [{"doc_id": f"d{i}", "era": "1950-1979", "year": 1960} for i in range(3)] + [
        {"doc_id": f"e{i}", "era": "2010-2026", "year": 2015} for i in range(50)]
    for r in records:
        r.update(title="", citation="", case_id="", case_type="", criminal=False, pdf_url="")
    sample = sample_noncandidates.stratified_sample(records, 22, seed=1)
    # quotas 6/6/5/5; the 1950-79 pool has only 3; the empty eras give nothing.
    assert sum(r["era"] == "1950-1979" for r in sample) == 3
    assert sum(r["era"] == "2010-2026" for r in sample) == 5


def test_sampler_run_criminal_pool_writes_ids_only(tmp_path: Path) -> None:
    _non_candidates(tmp_path)
    sample = sample_noncandidates.run(tmp_path, n=8, seed=3, pool="criminal", out=lambda _: None)
    assert len(sample) == 8 and all(r["criminal"] for r in sample)
    saved = json.loads((tmp_path / "noncandidate_sample_criminal_seed3.json").read_text(encoding="utf-8"))
    assert saved["pool"] == "criminal" and len(saved["documents"]) == 8
    assert set(saved["documents"][0]) == set(sample_noncandidates.FIELDS)


@pytest.mark.parametrize(
    "excerpt, sections",
    [
        # The word "act" (lowercase) is not a named Act.
        ("The act done in exercise of the right of private defence - Penal Code, s. 100", ["100"]),
        ("I.P.C. - the act of the accused - s. 302 - murder", ["302"]),
        # A named Act just before the reference still attributes it elsewhere.
        ("I.P.C. charge dropped; Industrial Disputes Act, 1947-s. 100", []),
    ],
)
def test_lowercase_act_is_not_a_code(excerpt: str, sections: list[str]) -> None:
    assert in_scope_sections(excerpt) == sections


@pytest.mark.parametrize(
    "excerpt, sections",
    [
        # Real census false positives, now rejected.
        ("Penal Code, 1860 – ss.302/34, 201 – Bhartatiya Nyaya Sanhita, 2023 – ss.103(1)/3(5) – Circumstantial evidence", ["302"]),
        ("Indian Penal Code (Act 45 of 1860), s. 84-Indian Evidence Aot (1 of 1872), s. 105. The appellant", []),
        ("Penal Code, 1860 - High Court upheld conviction - Act, 1872-Section 106-Burden of proving fact", []),
        ("Penal Code mentioned. Election Laws: Representation of People’s Act, 1951 – s. 100(1)(c) – Improper rejection", []),
        ("I.P.C.; B.N.S.S. s. 100 search", []),
        # Real private-defence headnotes, still accepted.
        ("Indian Penal Code (Act 45 of 1860), Ss. 100 and 102-Right of private defence-Scope of.", ["100", "102"]),
        ("Evidence Act, 1872-Section 105-Penal Code, 1860-Sections 96, 302, 304 Part II & 323-Criminal Procedure Code", ["96", "302", "304"]),
        ("Indian Penal Code-Sec. 99-302-304 Part II-Causing murder in exercise of right", ["99"]),
    ],
)
def test_real_census_cases(excerpt: str, sections: list[str]) -> None:
    assert in_scope_sections(excerpt) == sections
