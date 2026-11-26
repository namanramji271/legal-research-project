"""corpus/pdf_pipeline.py: split, resumable download, extraction, trial selection.

No network and no real PDFs: the opener and page reader are faked.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from corpus import pdf_pipeline as pp  # noqa: E402

HEADNOTE = "Criminal Law-Murder-Private defence, right of. HELD: The right of private defence ends with the necessity.\n"
JUDGMENT = "CHANDRACHUD, J. On the morning of June 7, 1970 the deceased went to the market. " * 20


def scr(jurisdiction: str = "CRIMINAL APPELLATE JURISDICTION: Criminal Appeal No. 49 of 1970.",
        delivered: str = "The Judgment of the Court was delivered by") -> str:
    return (
        f"{HEADNOTE}{HEADNOTE}\n{jurisdiction}\nAppeal by Special Leave from the Judgment and Order dated 12th April.\n"
        f"R. K. Garg for the Appellant.\n{delivered}\n{JUDGMENT}"
    )


# --- split --------------------------------------------------------------------

def test_split_jurisdiction_and_delivered() -> None:
    result = pp.split_headnote_body(scr())
    assert result["split_method"] == "jurisdiction+delivered" and not result["split_suspect"]
    assert result["headnote"].startswith("Criminal Law-Murder") and "JURISDICTION" not in result["headnote"]
    assert result["proceedings"].startswith("CRIMINAL APPELLATE JURISDICTION")
    assert "R. K. Garg for the Appellant." in result["proceedings"]
    assert result["body"].startswith("CHANDRACHUD, J. On the morning")


def test_split_tolerates_ocr_and_multi_judge_delivery() -> None:
    text = scr("CalMINArt~PBLLATB JURISDICTION: Crimi!l'al Appeal No .. 142",
               "The Judgment of P. N. Bhagwati and R. S. Sarkaria was delivered\nby Bhagwati, J.")
    result = pp.split_headnote_body(text)
    assert result["split_method"] == "jurisdiction+delivered"
    assert result["body"].startswith("by Bhagwati, J.") or result["body"].startswith("CHANDRACHUD")


def test_split_ignores_lowercase_jurisdiction_in_headnote() -> None:
    text = "The arbitrator exceeded his jurisdiction. " * 5 + "\n" + scr()
    result = pp.split_headnote_body(text)
    assert result["headnote"].startswith("The arbitrator exceeded his jurisdiction.")
    assert result["split_method"] == "jurisdiction+delivered"


def test_split_heading_and_fallbacks() -> None:
    with_heading = scr(delivered="O R D E R")
    assert pp.split_headnote_body(with_heading)["split_method"] == "jurisdiction+heading"
    jurisdiction_only = scr(delivered="")
    result = pp.split_headnote_body(jurisdiction_only)
    assert result["split_method"] == "jurisdiction" and result["body"].startswith("CRIMINAL APPELLATE")
    delivered_only = f"{HEADNOTE}The Judgment of the Court was delivered by\n{JUDGMENT}"
    assert pp.split_headnote_body(delivered_only)["split_method"] == "delivered"
    none = pp.split_headnote_body(JUDGMENT)
    assert none == {"split_method": "none", "split_suspect": False, "headnote": "", "proceedings": "",
                    "body": JUDGMENT.strip()}


def test_split_flags_suspect_short_body() -> None:
    text = HEADNOTE * 30 + "CRIMINAL APPELLATE JURISDICTION: Criminal Appeal No. 1.\nThe Judgment of the Court was delivered by\nShort."
    assert pp.split_headnote_body(text)["split_suspect"] is True


# --- download -----------------------------------------------------------------

def records(n: int = 3) -> list[dict]:
    return [{"doc_id": f"1975_1_{i}_{i + 9}", "year": 1975, "era": "1950-1979",
             "pdf_url": f"https://example.invalid/{i}.pdf"} for i in range(n)]


class FakeOpener:
    def __init__(self, plan: dict[str, list] | None = None) -> None:
        self.plan = plan or {}
        self.calls: list[str] = []

    def __call__(self, url: str):
        self.calls.append(url)
        steps = self.plan.get(url)
        if steps:
            step = steps.pop(0)
            if isinstance(step, BaseException):
                raise step
        return (b"%PDF-1.4 " + url.encode()), {"ETag": '"abc123"'}


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO())


def test_download_records_etag_size_sha_and_resumes(tmp_path: Path) -> None:
    opener = FakeOpener()
    summary = pp.download_all(records(), tmp_path, workers=2, opener=opener, sleep=lambda s: None, out=lambda _: None)
    assert summary["counts"] == {"ok": 3}
    manifest = [json.loads(line) for line in (tmp_path / "pdf_manifest.jsonl").read_text().splitlines()]
    first = next(m for m in manifest if m["doc_id"] == "1975_1_0_9")
    data = pp.pdf_path(tmp_path, "1975_1_0_9").read_bytes()
    assert first["bytes"] == len(data) and first["etag"] == "abc123"
    assert first["sha256"] == hashlib.sha256(data).hexdigest()
    assert not list(tmp_path.rglob("*.part"))

    again = pp.download_all(records(), tmp_path, workers=2, opener=opener, sleep=lambda s: None, out=lambda _: None)
    assert again["counts"] == {"skipped": 3} and len(opener.calls) == 3


def test_download_redoes_truncated_file(tmp_path: Path) -> None:
    opener = FakeOpener()
    pp.download_all(records(1), tmp_path, workers=1, opener=opener, sleep=lambda s: None, out=lambda _: None)
    pp.pdf_path(tmp_path, "1975_1_0_9").write_bytes(b"trunc")
    again = pp.download_all(records(1), tmp_path, workers=1, opener=opener, sleep=lambda s: None, out=lambda _: None)
    assert again["counts"] == {"ok": 1} and len(opener.calls) == 2


def test_download_retries_with_backoff_and_reports_missing_and_failed(tmp_path: Path) -> None:
    rs = records(3)
    opener = FakeOpener({
        rs[0]["pdf_url"]: [http_error(503), TimeoutError("slow")],  # then succeeds
        rs[1]["pdf_url"]: [http_error(404)],
        rs[2]["pdf_url"]: [http_error(500)] * pp.RETRIES,
    })
    sleeps: list[float] = []
    summary = pp.download_all(rs, tmp_path, workers=1, opener=opener, sleep=sleeps.append, out=lambda _: None)
    assert summary["counts"] == {"ok": 1, "missing": 1, "failed": 1}
    assert sleeps.count(pp.BACKOFF_SECONDS) == 2  # first retry of each retried doc
    state = pp.Manifest(tmp_path / "pdf_manifest.jsonl").state
    assert state[rs[1]["doc_id"]]["http_status"] == 404
    assert state[rs[2]["doc_id"]]["error"] == "HTTP 500"
    # A failed or missing document is retried on the next run.
    again = pp.download_all(rs, tmp_path, workers=1, opener=FakeOpener(), sleep=lambda s: None, out=lambda _: None)
    assert again["counts"] == {"skipped": 1, "ok": 2}


def test_ctrl_c_keeps_finished_downloads_and_rerun_resumes(tmp_path: Path) -> None:
    rs = records(3)
    opener = FakeOpener({rs[1]["pdf_url"]: [KeyboardInterrupt()]})
    with pytest.raises(KeyboardInterrupt):
        pp.download_all(rs, tmp_path, workers=1, opener=opener, sleep=lambda s: None, out=lambda _: None)
    assert pp.pdf_path(tmp_path, rs[0]["doc_id"]).is_file()
    resumed = pp.download_all(rs, tmp_path, workers=1, opener=FakeOpener(), sleep=lambda s: None, out=lambda _: None)
    assert resumed["counts"]["skipped"] == 1 and resumed["counts"]["ok"] == 2


# --- extraction ---------------------------------------------------------------

def test_extract_writes_split_text_and_skips_done(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for r in records(2):
        path = pp.pdf_path(tmp_path, r["doc_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF")
    pages_read: list[Path] = []

    def fake_read_pages(path: Path):
        pages_read.append(path)
        if path.name.startswith("1975_1_1_"):
            raise ValueError("broken xref")
        return [(scr()[:400], True), (scr()[400:], True)]

    monkeypatch.setattr(pp, "read_pages", fake_read_pages)
    summary = pp.extract_all([r["doc_id"] for r in records(2)], tmp_path, workers=1, out=lambda _: None)
    assert summary["extracted"] == 2

    ok = json.loads(pp.text_path(tmp_path, "1975_1_0_9").read_text(encoding="utf-8"))
    assert ok["pages"] == 2 and ok["scanned"] is True and ok["split_method"] == "jurisdiction+delivered"
    assert ok["body"].startswith("CHANDRACHUD")
    broken = json.loads(pp.text_path(tmp_path, "1975_1_1_10").read_text(encoding="utf-8"))
    assert broken["error"] == "ValueError: broken xref"

    pp.extract_all([r["doc_id"] for r in records(2)], tmp_path, workers=1, out=lambda _: None)
    assert len(pages_read) == 2  # both already extracted: nothing re-read

    rep = pp.report(records(2), tmp_path)
    assert rep["failures"] == ["1975_1_1_10"] and rep["split_by_era"] == {"1950-1979": {"jurisdiction+delivered": 1, "error": 1}}


# --- selection ----------------------------------------------------------------

def test_select_trial_mixes_eras_excludes_dev_and_is_seeded() -> None:
    pool = [{"doc_id": f"{y}_1_{i}", "year": y, "era": pp.era(y)} for y in range(1950, 2027) for i in range(3)]
    dev = {"1955_1_0", "2015_1_1"}
    a = pp.select_trial(pool, 20, 10, seed=1, exclude=dev)
    assert a == pp.select_trial(list(reversed(pool)), 20, 10, seed=1, exclude=dev)
    assert len(a) == 20 and sum(r["year"] < 1980 for r in a) == 10
    assert not {r["doc_id"] for r in a} & dev
    assert {r["era"] for r in a if r["year"] >= 1980} == {"1980-1999", "2000-2009", "2010-2026"}


def test_load_records_from_jsonl_and_sample_json(tmp_path: Path) -> None:
    (tmp_path / "c.jsonl").write_text(json.dumps({"doc_id": "1975_1_409_421", "year": 1975}) + "\n", encoding="utf-8")
    (tmp_path / "s.json").write_text(json.dumps({"documents": [{"doc_id": "S_1995_2_629_636", "year": 1995}]}), encoding="utf-8")
    [a] = pp.load_records(tmp_path / "c.jsonl")
    [b] = pp.load_records(tmp_path / "s.json")
    assert a["pdf_url"].endswith("/year=1975/english/1975_1_409_421_EN.pdf") and a["era"] == "1950-1979"
    assert b["era"] == "1980-1999"


@pytest.mark.parametrize(
    "jurisdiction",
    [
        "CRIMINAL APPELLATE JURISnICTION : Criminal Appeal No. 146 of 1967.",   # D -> n
        "CiUMINAL APPELLATE JURISDI~ION : Criminat Aprea! No. 12",              # CT -> ~
        "D CRIMINALAPPELLATE jLJRISDICTION : Criminal Appeal No. 9",           # U -> LJ, no space
    ],
)
def test_split_ocr_jurisdiction_variants_from_the_trial(jurisdiction: str) -> None:
    result = pp.split_headnote_body(scr(jurisdiction))
    assert result["split_method"] == "jurisdiction+delivered"
    assert "for the Appellant" in result["proceedings"] and "for the Appellant" not in result["headnote"]


def test_split_ocr_garbled_was_delivered() -> None:
    result = pp.split_headnote_body(scr(delivered="The Judgment of the Court wai delivered, by"))
    assert result["split_method"] == "jurisdiction+delivered"
    assert result["body"].startswith("CHANDRACHUD")


def test_headnote_uppercase_appellate_without_colon_does_not_split() -> None:
    text = "Criminal Law - powers of the APPELLATE COURT in appeals against acquittal. " * 3 + "\n" + scr()
    result = pp.split_headnote_body(text)
    assert result["headnote"].startswith("Criminal Law - powers of the APPELLATE COURT")


def test_uppercase_appellate_court_with_colon_is_not_a_jurisdiction_line() -> None:
    text = "Powers of the APPELLATE COURT: interference with findings of fact. " * 3 + "\n" + scr()
    result = pp.split_headnote_body(text)
    assert result["headnote"].startswith("Powers of the APPELLATE COURT:")
    assert result["proceedings"].startswith("CRIMINAL APPELLATE JURISDICTION")
