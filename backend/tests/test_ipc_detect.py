"""corpus/ipc_detect.py on real Supreme Court Reports phrasings (shortened)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from corpus.ipc_detect import detect, include_sections, normalise, summarise  # noqa: E402

IPC_CONTEXT = "The appellants were tried under the Indian Penal Code. "


def kinds(text: str) -> list[tuple[str, str, str]]:
    return [(m.section, m.kind, m.reason) for m in detect(text).mentions]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("were convicted under section 302 Indian Penal Code for causing the death",
         [("302", "explicit", "ipc_after")]),
        ("s. 304 Part II of the Indian Penal Code and sentenced", [("304", "explicit", "ipc_after")]),
        ("ss. 302 and 436 of the Indian Penal Code.", [("302", "explicit", "ipc_after")]),
        ("Penal Code, 1860 – ss. 302, 307 – Two persons were done to death",
         [("302", "explicit", "ipc_before")]),
        # OCR: "P£nal Codt", "/PC", "uls." for u/s.
        ("B P£nal Codt-S. 302 and 364-Acquittal under s. 364.", [("302", "explicit", "ipc_before")]),
        ("convicting accused uls.302, /PC - Justification", [("302", "explicit", "ipc_after")]),
        ("The ingredients of l.P.C. section 300 are", [("300", "explicit", "ipc_before")]),
    ],
)
def test_explicit_attribution(text: str, expected: list) -> None:
    assert kinds(text) == expected


@pytest.mark.parametrize(
    "text, reason",
    [
        ("Section 105 of the Indian Evidence Act, 1972 (in short", "other_code_after"),
        ("search under s. 100(4) Cr.P .C. was invalid", "other_code_after"),
        ("Code of Civil Procedure, 1908 - s. 100 - second appeal", "other_code_before"),
        ("Bharatiya Nyaya Sanhita, 2023 – ss. 103(1)/3(5)", "other_code_before"),
        ("Representation of People's Act, 1951 – s. 100(1)(c)", "other_code_before"),
        ("the provisions of section 300 of the Code bar a second trial", "ambiguous_code_after"),
    ],
)
def test_rejected_attribution(text: str, reason: str) -> None:
    mentions = detect(IPC_CONTEXT + text).mentions
    assert mentions and all(m.kind == "rejected" and m.reason == reason for m in mentions)


def test_implicit_needs_ipc_named_in_the_document() -> None:
    assert kinds(IPC_CONTEXT + "He was convicted under section 302 and sentenced.") == [("302", "implicit", "implicit")]
    assert kinds("He was convicted under section 302 and sentenced.") == [
        ("302", "rejected", "implicit_no_ipc_in_document")]


def test_implicit_private_defence_range_needs_private_defence_in_the_sentence() -> None:
    plain = kinds(IPC_CONTEXT + "Reliance was placed on section 106 to shift the burden.")
    assert plain == [("106", "rejected", "collision_no_private_defence")]
    with_context = kinds(IPC_CONTEXT + "Under section 100 the right of private defence extends to causing death.")
    assert with_context == [("100", "implicit", "implicit")]
    ocr = kinds(IPC_CONTEXT + "Section 97 gives the prira1e d~fence of the body.")
    assert ocr == [("97", "implicit", "implicit")]


def test_ranges_lists_and_bare_under() -> None:
    assert [m[0] for m in kinds("Indian Penal Code (Act 45 of 1860), ss. 96 to 106--Right of private defence")] == [
        str(n) for n in range(96, 107)]
    assert [m[0] for m in kinds(IPC_CONTEXT + "conviction under 302 is altered to one under Section 304 Part II")] == [
        "302", "304"]
    assert [m[0] for m in kinds(IPC_CONTEXT + "Sections 302 read with 34 and 304")] == ["302", "304"]


def test_citation_page_numbers_are_not_sections() -> None:
    assert kinds(IPC_CONTEXT + "see AIR 1974 SC 302 and (1975) 3 SCC 304 and [1975] 1 S.C.R. 300") == []


def test_normalise_rejoins_broken_words_and_soft_hyphens() -> None:
    assert normalise("pri­vate de-\nfence") == "private defence"


def test_include_rule() -> None:
    body = detect(IPC_CONTEXT + "convicted under section 302 IPC for murder. The conviction under section 302 stands. "
                  "One reference to section 304 Indian Penal Code.")
    head = detect("Penal Code, 1860 – s. 304 – Culpable homicide")
    assert body.counts() == {"302": {"explicit": 1, "implicit": 1}, "304": {"explicit": 1, "implicit": 0}}
    assert include_sections(body) == ["302"]
    assert include_sections(body, head) == ["302", "304"]  # one explicit body mention + headnote
    assert include_sections(body, head, min_body_mentions=3) == ["304"]


def test_summarise_record_counts_only() -> None:
    record = {"doc_id": "1975_1_906_913",
              "headnote": "B P£nal Codt-S. 302 and 364-Acquittal",
              "body": "KHANNA, J.-Godhu and Banwari were convicted under section 302 Indian Penal Code. "
                      "The conviction under section 302 is upheld."}
    summary = summarise(record)
    assert summary["included_sections"] == ["302"] and summary["included_groups"] == ["302"]
    assert summary["in_scope"] and summary["names_ipc"]
    assert "body" not in summary and "headnote" not in summary


def test_sentence_ending_in_an_abbreviation_does_not_cut_but_a_code_after_still_rejects() -> None:
    # "IPC." could be an abbreviation, so the next sentence still sees the IPC ...
    assert kinds("convicted under s. 302 IPC. The conviction under section 302 stands.")[1] == (
        "302", "explicit", "ipc_before")
    # ... but a code named right after a reference always wins.
    assert kinds("convicted under s. 302 IPC. Section 106 of the Evidence Act applies.")[1] == (
        "106", "rejected", "other_code_after")


def test_include_rule_variant_accepts_implicit_body_with_headnote() -> None:
    body = detect(IPC_CONTEXT + "The appeal concerns the conviction under section 302 alone.")
    head = detect("Penal Code, 1860: Sections 302, 303, 341 - Death sentence")
    assert include_sections(body, head) == []
    assert include_sections(body, head, headnote_needs_explicit_body=False) == ["302"]
