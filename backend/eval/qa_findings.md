# QA Evaluation Findings

## Scope

`evaluate_qa.py` was run against `test_qa_questions.json`, which contains 13
questions: 9 in-corpus questions expected to be answerable and 4 deliberately
out-of-corpus questions expected to be declined.

## Citation-verification result

All 13 of 13 responses contained zero fabricated citations. This includes all
four deliberately off-topic questions. The result indicates that the citation
verifier reliably prevents hallucinated case citations regardless of whether a
question is answerable from the judgment corpus.

## Context-behavior result

Ten of 13 questions showed the expected answer-or-decline behavior. Three
genuine retrieval-precision misses remain: question 2 on private-defence force
limits, question 3 on private-defence-of-property timing, and question 4 on
the IPC Section 299 definition. Although these topics are represented in the
corpus, the top-five retrieved chunks did not contain the specific legal detail
requested. The system therefore declined rather than guessing.

This is consistent with the retrieval-precision limitations documented in
[`findings.md`](findings.md): a topic may be present in the corpus without the
retrieved context being sufficiently specific to support a grounded answer.

The fourth original mismatch was not a QA-system failure. Question 12, on the
legal grounds for divorce under the Hindu Marriage Act, was correctly declined
by `ask_question()`. However, the evaluator's original
`INSUFFICIENT_CONTEXT_PATTERNS` required the word “enough” and did not detect
the response phrasing “does not contain information regarding...”. After
broadening the regex to also match “does not contain information,” question 12
is correctly detected as an insufficient-context response. This raises the
context-behavior result from 9/13 to 10/13 without any new API calls.

This incident is a reminder that evaluation-script string matching must be
robust to paraphrasing: the underlying QA system was already behaving
correctly.

## Interpretation

These mismatches reflect a conservative failure mode, not a hallucination
risk. Declining when the retrieved context is insufficient is the intended
trade-off for a citation-verified legal QA system: it favors supported,
traceable answers over plausible but ungrounded legal guidance.

## Reproducibility note

Testing encountered Gemini free-tier daily rate limits (20 requests per day).
This is an operational constraint for anyone reproducing the evaluation, not a
system flaw. Re-runs should account for the request quota and the evaluator's
15-second delay between requests.
