# Annotation guideline: corpus v2 IPC scope and headnote split

You will label Supreme Court judgments for two things: whether an in-scope
IPC section is **at issue**, and whether the **headnote/body split** is
correct. Two annotators label the same documents independently.

## Before you start

1. Label the 5-document **calibration sheet** together, discuss every
   disagreement, and settle how you read this guideline. Calibration labels
   are not scored.
2. Then label the 55-document **validation sheet on your own**. Do not
   discuss items until both sheets are finished.
3. Read the PDF at `pdf_url`. You are not shown any detector output; do not
   look for it (`validation_key.json` is not for annotators).
4. The inclusion rule was fixed before labelling (see `validation.py`);
   nothing you label changes it for these 55 documents.

## Scope

In-scope sections: **IPC 96–106** (private defence) and **IPC 299–304**
(culpable homicide, murder and their punishment, including 304 Part I/II).
Section 304A (death by negligence), 304B (dowry death) and 307 (attempt to
murder) are **out of scope**.

A section is **at issue** when the court has to apply or decide it in this
case, for example:
- the accused was charged, convicted, acquitted or sentenced under it in the
  proceedings before the court;
- the court analyses its ingredients or limits to reach the outcome (e.g.
  whether the right of private defence under s. 100 extended to causing
  death; whether the act falls under s. 300 "thirdly" or s. 304 Part II);
- the court alters a conviction from one in-scope section to another.

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
| `in_scope` | `yes` / `no` / `unsure` | `yes` if at least one in-scope IPC section is at issue. Use `unsure` sparingly and explain in `notes`. |
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
→ `in_scope = yes`, `sections_at_issue = 302;304`. Section 34 is not in scope
and is not listed.

**Example 2: passing mention only (not in scope).** A dowry-death appeal
under s. 304B; the judgment cites an earlier murder case "decided under
s. 302" for the standard of circumstantial evidence and quotes "s. 106 of the
Evidence Act" on the burden of proof.
→ `in_scope = no`, `passing_sections = 302`. 304B is out of scope; Evidence
Act s. 106 is not an IPC mention at all.

**Example 3: private defence at issue, with collisions.** The defence pleads
that the accused acted in exercise of the right of private defence. The court
discusses "ss. 96 to 102" and whether the right extended to causing death
under s. 100, and also refers to "s. 105 of the Evidence Act" (the accused
must prove the plea). The conviction under s. 302 is upheld.
→ `in_scope = yes`, `sections_at_issue = 100;302` (add 96–102 if the court
actually applies them, not when they are only listed). Evidence Act s. 105 is
not listed anywhere.

## Split check

`body_starts_with` shows the first 150 characters of what the extractor took
as the judgment body. Mark `split_correct = yes` if it starts at the beginning
of the judgment (normally the authoring judge's name, or "J U D G M E N T" /
"O R D E R" in recent reports), `no` if it starts inside the headnote, inside
the counsel list or later inside the judgment.

## Adjudication

After both sheets are done, the annotators compare labels. For each
disagreement they discuss and record one agreed label in
`adjudicated.csv` (same columns). Disagreements and their resolution are
kept, not overwritten.
