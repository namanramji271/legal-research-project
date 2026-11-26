"""IPC section detection on full judgment text (corpus v2).

Finds references to in-scope IPC sections (96-106 private defence, 299-304
culpable homicide / murder) and attributes each mention:

- explicit: the IPC / Penal Code is named right after the reference
  ("section 302 Indian Penal Code", "s. 304 Part II of the Indian Penal
  Code") or is the nearest code named just before it in the same clause
  ("Penal Code, 1860 - ss. 302, 307").
- rejected: another code or Act is named right after it, or is the nearest
  code before it (CPC/CrPC, Evidence Act, Constitution, BNS/BNSS/BSA, NDPS,
  Arms Act, named Acts), or it is "of the Code"/"of the Act" (ambiguous).
- implicit: no code named nearby. Accepted only when the document names the
  IPC somewhere, and for 96-106 (which collide with CPC 96/100, CrPC
  100/106 and Evidence Act 101-106) only when the same sentence speaks of
  private defence.

OCR in older Supreme Court Reports scans is handled for the code names
("P£nal Codt", "Panel Code", "/PC", "l.P.C.", "Cr.P .C."), the section
markers ("uls." for "u/s") and private defence ("prira1e defence",
"d~fence"). Text is normalised first (soft hyphens removed, words broken
across lines rejoined); offsets refer to the normalised text.

The inclusion rule is a function of the counts (``include_sections``) so
its thresholds can be fixed after hand validation.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from corpus.prefilter import SCOPE_SECTIONS, _abbreviation, section_group

PRIVATE_DEFENCE_RANGE = frozenset(str(s) for s in range(96, 107))

# --- code names ---------------------------------------------------------------

_IPC = (
    r"\b(?:Indian\s+)?P[\w£]{3}l\s+C\w{2,3}\b"          # Penal Code, Panel Code, P£nal Codt
    r"|(?<![A-Za-z])[I1l/|]\s?\.?\s?P\s?\.?\s?C\b\.?"    # IPC, I.P.C., l.P.C., /PC
)
_OTHER = (
    rf"{_abbreviation('CPC')}|{_abbreviation('CrPC')}|\bCode\s+of\s+(?:Civil|Criminal)\s+Procedure\b|"
    r"\b(?:Civil|Criminal)\s+Procedure(?:\s+Code)?\b|\bConstitution\b|"
    r"\bEvidence\s+A[a-z0-9]{1,2}t\b|\bAct,?\s+1872\b|"
    r"\b(?:Bh\w*\s+)?Nyaya\s+Sanhita\b|\bNagarik\s+Suraksha\s+Sanhita\b|\bSakshya\s+Adhiniyam\b|"
    rf"{_abbreviation('BNSS')}|{_abbreviation('BNS')}|{_abbreviation('BSA')}|"
    rf"\bArms\s+Act\b|{_abbreviation('NDPS')}|"
    r"(?-i:\b[A-Z][\w'’]+(?:\s+(?:of\s+(?:the\s+)?)?[A-Z][\w'’]+){0,4}\s+Act\b)"
)
CODE = re.compile(rf"(?P<ipc>{_IPC})|(?P<other>{_OTHER})", re.IGNORECASE)
IPC_NAME = re.compile(_IPC, re.IGNORECASE)

# What may sit between a reference and a code named after it: "of the Indian
# Penal Code", ", I.P.C.", " IPC". No dashes (SCR headnotes use " – " between clauses).
_AFTER_GAP = r"^[\s,.;:()]{0,4}(?:(?:of|under)\s+(?:the\s+)?)?(?:said\s+)?"
CODE_AFTER = re.compile(rf"{_AFTER_GAP}(?:(?P<ipc>{_IPC})|(?P<other>{_OTHER}))", re.IGNORECASE)
AMBIGUOUS_AFTER = re.compile(rf"{_AFTER_GAP}(?:Code|Act)\b", re.IGNORECASE)
LOOKBEHIND_CHARS = 60
LOOKAHEAD_CHARS = 60

# --- references ---------------------------------------------------------------

_MARKER = r"(?:sections?|secs?\.?|ss?\s?\.|u\s?[/l]\s?s\.?|under)"
_NUM = r"\d{1,3}[A-Z]?(?:\s*\(\d+\))?(?:\s*Part\s*I{1,2}\b)?(?:\s*Exception\s*\d)?"
_JOIN = r"\s*(?:,|/|&|and|or|read\s+with|r/w|to|-)\s*"
REFERENCE = re.compile(rf"(?i)\b{_MARKER}\s*(?P<numbers>{_NUM}(?:{_JOIN}{_NUM})*)")
NUMBER = re.compile(r"\d{1,3}")
RANGE = re.compile(r"(?i)(\d{1,3})\s*(?:to|-)\s*(\d{1,3})")

PRIVATE_DEFENCE = re.compile(
    r"(?i)\b(?:p[\w~]{4,6}e|self)[\s\-]{1,3}d[\w~]{0,2}f[\w~]{0,3}n[cs]e\b|\bright\s+of\s+defen[cs]e\b"
)
SENTENCE_END = re.compile(r"[a-z]\.\s+(?=[A-Z]|$)")
SENTENCE_BREAK = re.compile(r"(?<=[.;?!])\s+(?=[A-Z(\"'])|\n\s*\n")


def normalise(text: str) -> str:
    text = (text or "").replace("\u00ad", "")
    return re.sub(r"(\w)-[ \t]*\n[ \t]*(\w)", r"\1\2", text)


def _numbers(group: str) -> list[str]:
    """Section numbers in a reference, with 'X to Y' ranges expanded."""
    found: list[str] = []
    for start, end in RANGE.findall(group):
        a, b = int(start), int(end)
        if a < b <= a + 20:
            found += [str(n) for n in range(a, b + 1)]
    found += NUMBER.findall(group)
    return list(dict.fromkeys(found))


def _sentence(text: str, start: int, end: int) -> str:
    left = max((m.end() for m in SENTENCE_BREAK.finditer(text, max(0, start - 400), start)), default=max(0, start - 400))
    right = next((m.start() for m in SENTENCE_BREAK.finditer(text, end, end + 400)), min(len(text), end + 400))
    return text[left:right]


@dataclass(frozen=True)
class Mention:
    section: str
    kind: str  # explicit | implicit | rejected
    reason: str  # e.g. ipc_after, ipc_before, implicit, other_code_after, collision_no_private_defence
    start: int
    end: int


@dataclass
class Detection:
    names_ipc: bool
    mentions: list[Mention] = field(default_factory=list)

    def accepted(self) -> list[Mention]:
        return [m for m in self.mentions if m.kind in ("explicit", "implicit")]

    def counts(self) -> dict[str, dict[str, int]]:
        table: dict[str, dict[str, int]] = {}
        for m in self.accepted():
            row = table.setdefault(m.section, {"explicit": 0, "implicit": 0})
            row[m.kind] += 1
        return dict(sorted(table.items(), key=lambda kv: int(kv[0])))

    def rejected(self) -> dict[str, int]:
        return dict(Counter(m.reason for m in self.mentions if m.kind == "rejected"))


def _attribute(text: str, start: int, end: int) -> tuple[str, str]:
    after = CODE_AFTER.match(text[end: end + LOOKAHEAD_CHARS])
    if after:
        return ("explicit", "ipc_after") if after.group("ipc") else ("rejected", "other_code_after")
    if AMBIGUOUS_AFTER.match(text[end: end + LOOKAHEAD_CHARS]):
        return "rejected", "ambiguous_code_after"
    # Nearest code named in the 60 chars before, within the same sentence. Dashes do
    # not cut (in SCR headnotes "Penal Code, 1860 – ss. 302" ties a code to its
    # sections); a sentence ends only at a period after a lowercase letter followed by
    # a capital ("Penal Code. Reliance ..."), so "l.P.C. Section 300" does not cut.
    before = text[max(0, start - LOOKBEHIND_CHARS):start]
    breaks = list(SENTENCE_END.finditer(before))
    if breaks:
        before = before[breaks[-1].end():]
    codes = list(CODE.finditer(before))
    if codes:
        return ("explicit", "ipc_before") if codes[-1].group("ipc") else ("rejected", "other_code_before")
    return "implicit", "implicit"


def detect(text: str) -> Detection:
    """In-scope IPC mentions in ``text`` (normalised first)."""
    text = normalise(text)
    detection = Detection(names_ipc=bool(IPC_NAME.search(text)))
    for match in REFERENCE.finditer(text):
        sections = [n for n in _numbers(match.group("numbers")) if n in SCOPE_SECTIONS]
        if not sections:
            continue
        kind, reason = _attribute(text, match.start(), match.end())
        if kind == "implicit":
            if not detection.names_ipc:
                kind, reason = "rejected", "implicit_no_ipc_in_document"
        for section in sections:
            k, r = kind, reason
            if k == "implicit" and section in PRIVATE_DEFENCE_RANGE and not PRIVATE_DEFENCE.search(
                _sentence(text, match.start(), match.end())
            ):
                k, r = "rejected", "collision_no_private_defence"
            detection.mentions.append(Mention(section, k, r, match.start(), match.end()))
    return detection


def include_sections(body: Detection, headnote: Detection | None = None, min_body_mentions: int = 2,
                     headnote_needs_explicit_body: bool = True) -> list[str]:
    """Sections that qualify a document: at least ``min_body_mentions`` accepted
    mentions in the body, or a headnote mention plus one body mention (explicit
    only, unless ``headnote_needs_explicit_body`` is False). Both thresholds are
    to be fixed after hand validation."""
    body_counts = body.counts()
    head_counts = headnote.counts() if headnote else {}
    chosen = []
    for section, row in body_counts.items():
        total = row["explicit"] + row["implicit"]
        body_support = row["explicit"] if headnote_needs_explicit_body else total
        if total >= min_body_mentions or (body_support >= 1 and section in head_counts):
            chosen.append(section)
    return chosen


def summarise(record: dict[str, Any], min_body_mentions: int = 2,
              headnote_needs_explicit_body: bool = True) -> dict[str, Any]:
    """Detection summary for one extracted text record (text/<doc_id>.json): counts only."""
    body = detect(record.get("body", ""))
    head = detect(record.get("headnote", ""))
    included = include_sections(body, head, min_body_mentions, headnote_needs_explicit_body)
    return {
        "doc_id": record.get("doc_id"),
        "names_ipc": body.names_ipc or head.names_ipc,
        "body_counts": body.counts(),
        "headnote_counts": head.counts(),
        "body_rejected": body.rejected(),
        "private_defence_mentions": len(PRIVATE_DEFENCE.findall(normalise(record.get("body", "")))),
        "included_sections": included,
        "included_groups": sorted({section_group(s) for s in included}),
        "in_scope": bool(included),
    }
