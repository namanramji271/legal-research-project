# Corpus v2: split-only validation of the Digital SCR rule

Generated from `backend/corpus/split_validation.py` (seed $seed). Scored at $scored_at (UTC).

## Why this validation exists

The frozen headnote/body split rule failed on 4 of the 5 weak_split documents
among the 25 human-labelled validation documents. All four were 2024–25
Digital SCR judgments split by the jurisdiction line alone, so the case
details and the counsel list sat at the start of the body. Those 4 documents
were then inspected and are development documents (`corpus/dev_docs.json`).
The split rule was changed and is validated here on fresh documents, for the
split only. The inclusion rule was not changed, and its validation stands.

## Pre-registered design (committed with the sheet generator, before any labelling)

- **Rule change:** after the jurisdiction line, when neither "was delivered"
  nor an uppercase JUDGMENT/ORDER heading is found within 8,000 characters,
  the case-sensitive line `Judgment / Order of the Supreme Court`
  (optionally followed by `Judgment` or `Order`) ends the proceedings block.
  Records carry `split_method = jurisdiction+digital_heading`.
- **Population:** extracted candidates with that split_method, excluding
  development documents, the 55 validation documents, the 5 calibration
  documents and failed or unextracted PDFs. Stratum populations (N_s): $population.
  Excluded: $excluded.
- **Strata** (first non-empty body line): `judge_line` (ends with ", J." or
  ", CJI.") and `no_judge_line` (anything else; oversampled).
- **Quotas:** $quotas; short strata (taken whole): $short_strata.
- **Seed:** $seed (validation base seed + 4).
- **Acceptance:** population-weighted pooled split accuracy ≥ 0.90 on the
  point estimate. If it is missed, the rule is not accepted, these documents
  become development documents, and any further change is validated on a
  fresh draw.

## Annotator

**The split sheet was labelled by one non-legal annotator (the project
author), not by the legally trained annotator of the main validation.** The
task needs no legal judgment: on a minimal sheet (`item, doc_id, title,
pdf_url, body_starts_with, split_correct, notes`) the annotator compares the
first 150 characters of the extracted body with the PDF. `yes` means the body
starts where the judgment itself begins: the authoring judge's name line, or,
when no judge is named before it, the first line of the judgment text. `no`
means it starts inside the headnote, the case details or the counsel list, or
later than the start of the judgment. `na` means the PDF has no headnote. The
4 development documents served as worked examples and are not scored.
Labelling dates: $label_dates.

## Effect of the rule on the corpus

- Records whose split changed, by year: $changed_by_year
- split_method counts before → after: $split_counts
- Re-extraction diff check: $diff_check
- Inclusion decisions (primary and looser rule) on the changed records: $inclusion_check
- Remaining known-weak splits (still `jurisdiction` only): $residual

## Results

| Stratum | N_s | n judged | Correct | Accuracy [95% Wilson] |
| --- | ---: | ---: | ---: | ---: |
$stratum_rows

- Weighted pooled accuracy (95% stratified bootstrap, $resamples resamples): **$weighted**

## Verdict

**$verdict**
