"""Headnote pre-filter for corpus v2 (metadata only, before any PDF download).

A listing is a candidate when its headnote excerpt (see sc_source.Listing)
- mentions murder, culpable homicide, homicide, or private/self defence, or
- names the IPC / Penal Code and cites an in-scope section (96-106, 299-304).

Section numbers count only when the reference is not attributed to another
code or Act (CPC, CrPC, Evidence Act, Constitution, ...): CPC 96/100 are the
civil appeal sections, CrPC 100/106 and Evidence Act 101-106 collide with the
private-defence range. This is a recall-oriented screen on a ~600-character
excerpt; in-scope status is decided later from the full PDF text and
validated by hand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SCOPE_SECTIONS = frozenset(str(s) for s in [*range(96, 107), *range(299, 305)])

# Rarest first: a document counted in several groups gets the first as its primary.
SECTION_GROUPS = ("private_defence", "303", "299-301", "304", "302")
KEYWORD_ONLY = "keyword_only"
GROUP_ORDER = (*SECTION_GROUPS, KEYWORD_ONLY)

ERAS = ((1950, 1979), (1980, 1999), (2000, 2009), (2010, 2026))

def _abbreviation(letters: str) -> str:
    """'IPC' -> I.P.C. with optional dots and OCR spaces ('Cr.P .C.', 'I. P. C')."""
    return r"\b" + r"\s?\.?\s?".join(letters) + r"\b\.?"


MURDER_KEYWORDS = re.compile(r"(?i)\b(?:murder|culpable\s+homicide|homicide)\b")
PRIVATE_DEFENCE = re.compile(r"(?i)\b(?:private|self)[\s-]+defen[cs]e\b|\bright\s+of\s+defen[cs]e\b")
_IPC = rf"\b(?:Indian\s+Penal\s+Code|Penal\s+Code|Panel\s+Code)\b|{_abbreviation('IPC')}"
_OTHER_CODE = (
    rf"{_abbreviation('CPC')}|{_abbreviation('CrPC')}|\bCode\s+of\s+(?:Civil|Criminal)\s+Procedure\b|"
    r"\b(?:Civil|Criminal)\s+Procedure(?:\s+Code)?\b|\bConstitution\b|"
    # Evidence Act, incl. OCR ("Evidence Aot") and the bare "Act, 1872" (its year).
    r"\bEvidence\s+A[a-z0-9]{1,2}t\b|\bAct,?\s+1872\b|"
    # The 2023 codes that replaced IPC/CrPC/Evidence Act (BNS s.103 is murder, not IPC s.103).
    r"\b(?:Bh\w*\s+)?Nyaya\s+Sanhita\b|\bNagarik\s+Suraksha\s+Sanhita\b|\bSakshya\s+Adhiniyam\b|"
    rf"{_abbreviation('BNSS')}|{_abbreviation('BNS')}|{_abbreviation('BSA')}|"
    rf"\bArms\s+Act\b|{_abbreviation('NDPS')}|"
    # Case-sensitive: a named Act ("Representation of People's Act"), not the word "act".
    r"(?-i:\b[A-Z][\w'’]+(?:\s+(?:of\s+(?:the\s+)?)?[A-Z][\w'’]+){0,4}\s+Act\b)"
)
IPC_NAME = re.compile(_IPC, re.IGNORECASE)
SECTION_REFERENCE = re.compile(
    r"(?i)\b(?:sections?|secs?\.?|ss?\.|u/s\.?)\s*"
    r"(?P<numbers>\d{1,3}[A-Z]?(?:\s*\(\d+\))?(?:\s*(?:,|/|&|and|or|read\s+with|r/w)\s*\d{1,3}[A-Z]?(?:\s*\(\d+\))?)*)"
)
# A code named right after the reference: "s. 100 C.P.C.", "s. 106 of the Evidence Act".
# No dashes: in SCR headnotes " – " starts the next clause ("…ss.302/34 – BNS, 2023 – …").
OTHER_CODE_AFTER = re.compile(
    rf"^[\s,.;:()]{{0,4}}(?:of\s+(?:the\s+)?)?(?:{_OTHER_CODE})", re.IGNORECASE
)
# Codes named before the reference: "Code of Civil Procedure, 1908-s. 100".
CODE_BEFORE = re.compile(rf"(?P<ipc>{_IPC})|(?P<other>{_OTHER_CODE})", re.IGNORECASE)
LOOKBEHIND_CHARS = 50
NUMBER = re.compile(r"\d{1,3}")


def _attributed_to_other_code(text: str, start: int, end: int) -> bool:
    if OTHER_CODE_AFTER.match(text[end: end + 60]):
        return True
    before = list(CODE_BEFORE.finditer(text[max(0, start - LOOKBEHIND_CHARS): start]))
    return bool(before) and before[-1].group("other") is not None


@dataclass(frozen=True)
class PrefilterResult:
    candidate: bool
    reasons: tuple[str, ...]  # subset of: murder_keyword, private_defence_keyword, ipc_section
    sections: tuple[str, ...]
    groups: tuple[str, ...]

    @property
    def primary_group(self) -> str | None:
        return self.groups[0] if self.groups else None


def in_scope_sections(text: str) -> list[str]:
    """In-scope section numbers cited in ``text`` and not attributed to another code."""
    found: set[str] = set()
    for match in SECTION_REFERENCE.finditer(text):
        if _attributed_to_other_code(text, match.start(), match.end()):
            continue
        for number in NUMBER.findall(match.group("numbers")):
            if number in SCOPE_SECTIONS:
                found.add(number)
    return sorted(found, key=int)


def section_group(section: str) -> str:
    number = int(section)
    if 96 <= number <= 106:
        return "private_defence"
    if 299 <= number <= 301:
        return "299-301"
    return str(number)


def prefilter(headnote_excerpt: str) -> PrefilterResult:
    text = headnote_excerpt or ""
    reasons = []
    if MURDER_KEYWORDS.search(text):
        reasons.append("murder_keyword")
    private_defence = bool(PRIVATE_DEFENCE.search(text))
    if private_defence:
        reasons.append("private_defence_keyword")
    sections = in_scope_sections(text) if IPC_NAME.search(text) else []
    if sections:
        reasons.append("ipc_section")

    groups = {section_group(s) for s in sections}
    if private_defence:
        groups.add("private_defence")
    if reasons and not groups:
        groups.add(KEYWORD_ONLY)
    ordered = tuple(g for g in GROUP_ORDER if g in groups)
    return PrefilterResult(bool(reasons), tuple(reasons), tuple(sections), ordered)


def era(year: int) -> str:
    for start, end in ERAS:
        if start <= year <= end:
            return f"{start}-{end}"
    return "other"


def decade(year: int) -> str:
    return f"{year // 10 * 10}s"
