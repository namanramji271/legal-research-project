# Annotation guideline: corpus v2 IPC scope and headnote split

You will label Supreme Court judgments for two things: whether an in-scope
IPC section is **at issue**, and whether the **headnote/body split** is
correct. There are two annotators: an LLM labels all 55 validation
documents, and a legally trained human labels a 25-document subset of them.
Each works independently and follows this guideline.

## Before you start

For the human annotator:

1. Label the 5-document **calibration sheet** (`calibration_sheet.csv`)
   first and discuss every item jointly with the project lead to settle how
   you read this guideline. Calibration labels are not scored.
2. Then label the 25-document **validation sheet**
   (`validation_sheet_human_25.csv`) **on your own**. Do not discuss items or
   look at any LLM labels until your sheet is finished.
3. Read the PDF at `pdf_url`. You are not shown any detector output or stratum;
   do not look for them (`validation_key.json` is not for annotators).
4. The inclusion rule and this guideline were fixed before labelling (see
   `validation.py`); nothing you label changes them for these documents.

The LLM annotator labels all 55 documents, one document per fresh session,
from the extracted text (headnote, body opening and full body) instead of
the PDF. It never sees the key, the detector output or any other document's
labels, and gives a one-sentence reason quoting the decisive sentence.

## Scope

In-scope sections: **IPC 96–106** (private defence) and **IPC 299–304**
(culpable homicide, murder and their punishment, including 304 Part I/II).
Section 304A (death by negligence), 304B (dowry death) and 307 (attempt to
murder) are **out of scope**.

`in_scope` is a **strict** label. A section is **at issue** only when the
court decides or reasons about it in this case:
- conviction, acquittal or sentence under it is what the court decides
  (upholding, setting aside or altering it);
- the court analyses its elements or limits to reach the outcome (e.g.
  whether the act falls under s. 300 "thirdly" or s. 304 Part II; murder vs
  culpable homicide not amounting to murder);
- the court decides a private-defence plea (e.g. whether the right under
  s. 100 extended to causing death);
- the court decides whether a charge under it should be framed, altered or
  quashed.

A section is **the charge only** (`section_as_charge = yes`, `in_scope = no`)
when it is the charge in the case, or is mentioned as the charge, but the
court decides something else: bail, a witness-protection order, juvenility,
summoning an additional accused (CrPC s. 319), recalling a witness, the
prosecution of someone else, or the section appears only in a recital of the
FIR or chargesheet. See Example 4. The strict/loose split was pre-registered
before labelling: detector precision is judged against the strict label.

A section is a **passing mention** when it appears but the court does not
apply it to this case, for example:
- in a precedent cited only for a general proposition, or in another case's
  facts;
- in a list of statutes or a recital of the case's history that is not part
  of what the court decides (e.g. a co-accused's charge not before the court);
- a number that belongs to another code: CPC s. 96/100 (appeals), CrPC
  s. 100/106 or s. 300–304, Evidence Act s. 101–106 (burden of proof),
  Bharatiya Nyaya Sanhita s. 100–105. These are never IPC mentions.

If a case is decided under the **BNS equivalents** of the in-scope sections
(BNS 100–105 for culpable homicide/murder, BNS 34–44 for private defence)
and not under the IPC, label `in_scope = no` and write `BNS` plus the
sections in `notes`. Whether such cases join the corpus is decided
separately; the note lets that happen without relabelling.

## Fields

| Field | Values | Meaning |
| --- | --- | --- |
| `in_scope` | `yes` / `no` / `unsure` | Strict: `yes` if the court decides or reasons about at least one in-scope IPC section. Use `unsure` sparingly and explain in `notes`. |
| `section_as_charge` | `yes` / `no` | `yes` if an in-scope section is the charge (or mentioned as the charge) but the court does not decide it. Always fill it in; it must be `no` when `in_scope` is `yes`. |
| `sections_at_issue` | e.g. `302;304` | In-scope sections at issue, separated by `;`. Empty if `in_scope` is `no`. |
| `passing_sections` | e.g. `300` | In-scope sections mentioned only in passing. |
| `split_correct` | `yes` / `no` / `na` | Does `body_starts_with` match where the judgment itself begins (usually the authoring judge, e.g. "KHANNA, J."), after the headnote and the list of counsel? `na` if the PDF has no headnote. |
| `notes` | free text | Anything unclear, OCR problems, why `unsure`. |

## Worked examples

These are paraphrased, not quoted.

**Example 1: at issue (in scope).** The accused were convicted by the trial
court under "section 302 read with section 34". The Supreme Court examines
whether the injuries show an intention to cause death, holds that the case
falls within s. 304 Part I, and alters the conviction.
→ `in_scope = yes`, `section_as_charge = no`,
`sections_at_issue = 302;304`. Section 34 is not in scope and is not listed.

**Example 2: passing mention only (not in scope).** A dowry-death appeal
under s. 304B; the judgment cites an earlier murder case "decided under
s. 302" for the standard of circumstantial evidence and quotes "s. 106 of the
Evidence Act" on the burden of proof.
→ `in_scope = no`, `section_as_charge = no`, `passing_sections = 302`.
304B is out of scope; Evidence Act s. 106 is not an IPC mention at all.

**Example 3: private defence at issue, with collisions.** The defence pleads
that the accused acted in exercise of the right of private defence. The court
discusses "ss. 96 to 102" and whether the right extended to causing death
under s. 100, and also refers to "s. 105 of the Evidence Act" (the accused
must prove the plea). The conviction under s. 302 is upheld.
→ `in_scope = yes`, `section_as_charge = no`, `sections_at_issue = 100;302`
(add 96–102 if the court actually applies them, not when they are only
listed). Evidence Act s. 105 is not listed anywhere.

**Example 4: the charge only (strict no, charge yes).** The section is the
charge, but the court decides something else. Typical phrasings:
- "The appellant, accused of an offence under Section 302 IPC, seeks bail
  under Section 439 CrPC." (also: an order against threats to witnesses)
- "The question is whether the accused in the FIR under Section 302 IPC was
  a juvenile on the date of the offence."
- "The investigating officer in the murder case was prosecuted for
  demanding a bribe."
- "The application under Section 319 CrPC to summon additional accused in
  the trial under Section 302 IPC" (or an order recalling a witness).
- "The chargesheet was filed under Sections 302 and 34 IPC." with nothing
  further decided on s. 302.
→ `in_scope = no`, `section_as_charge = yes`, `sections_at_issue` empty,
`passing_sections = 302`. If the court then also decides the conviction or
the framing of the s. 302 charge, it is Example 1 instead
(`in_scope = yes`, `section_as_charge = no`).

## Split check

`body_starts_with` shows the first 150 characters of what the extractor took
as the judgment body. Mark `split_correct = yes` if it starts at the beginning
of the judgment (normally the authoring judge's name, or "J U D G M E N T" /
"O R D E R" in recent reports), `no` if it starts inside the headnote, inside
the counsel list or later inside the judgment.

## Adjudication

Only after the human sheet is finished are the LLM labels for those 25
documents shown. For every disagreement (in `in_scope`, `section_as_charge`
or `split_correct`) the human reads the LLM's reason and decides the final
label; **the human label wins**. Record:

- `adjudicated_25.csv`: the final labels for all 25 (same columns as the
  sheet). Unchanged rows simply repeat the blind human label.
- `adjudication_log.csv`: one row per disagreement, with columns `doc_id`,
  `field`, `human_blind`, `llm`, `final`, `note` (why the final label was
  kept or changed).

The blind human sheet is kept as it was and not overwritten; agreement (κ)
is computed on it, not on the adjudicated labels.
