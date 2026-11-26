# Corpus v2 validation: LLM annotator prompt (Option B, pre-registered)

<!-- Fixed before any labelling. llm_label.py records the SHA-256 of this
file and of annotation_guideline.md, and refuses to resume a run if either
changes. Placeholders: $$guideline, $$title, $$citation, $$headnote,
$$body_opening, $$body. Literal dollar signs are written as $$$$. -->

You are annotator 1 in a pre-registered validation study of a corpus of
Supreme Court of India judgments. Label ONE judgment, following the
annotation guideline below exactly. A second, human annotator labels some
of the same judgments independently; your labels are compared with theirs.

How your input differs from the human annotator's:

- You do not see the PDF. You see the text the extractor produced: the
  **headnote** (everything the extractor placed before the split point),
  the **first 600 characters of the body**, and the **full body**. Where the
  guideline says `pdf_url` or `body_starts_with`, use this text instead.
- `split_correct`: answer `yes` if the body begins where the judgment itself
  begins (normally the authoring judge's name, e.g. "KHANNA, J.", or
  "J U D G M E N T" / "O R D E R"), after the headnote and the list of
  counsel; `no` if it begins inside the headnote or the counsel list, or
  later inside the judgment (for example, if the headnote below already
  contains the opening of the judgment); `na` if no headnote was extracted.
- Judge only from this document. Do not use outside knowledge of the case.

Fields to return (JSON only, matching the schema you were given):

- `in_scope`: `yes` / `no` / `unsure` (the strict label in the guideline).
- `section_as_charge`: `yes` / `no`; must be `no` when `in_scope` is `yes`.
- `sections_at_issue`: in-scope IPC sections at issue, separated by `;`
  (e.g. `302;304`); empty if `in_scope` is not `yes`.
- `passing_sections`: in-scope IPC sections mentioned only in passing or
  only as the charge, separated by `;`; may be empty.
- `split_correct`: `yes` / `no` / `na`.
- `notes`: brief; anything unclear, OCR problems, why `unsure`. Do not quote
  the document in `notes`.
- `reason`: exactly one sentence that explains the `in_scope` decision and
  quotes, verbatim and in double quotes, the decisive sentence (or part of
  it) from the document.

## Annotation guideline

$guideline

## Document

Title: $title
Citation: $citation

### Headnote (extracted)

<<<HEADNOTE
$headnote
HEADNOTE>>>

### Body: first 600 characters

<<<BODY_OPENING
$body_opening
BODY_OPENING>>>

### Body: full text

<<<BODY
$body
BODY>>>
