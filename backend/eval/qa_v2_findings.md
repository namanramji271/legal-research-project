# QA Context Evaluation v2

- Run status: **quota_exhausted**
- Model: `gemini-3.6-flash`
- Questions: 13; expected requests: 26 context/question pairs
- Uncached Gemini prompt calls this run: 21; disk-cache hits: 0
- Uncached evaluation calls remaining: 6
- Stop reason: HTTPException: 503: The AI answering service is temporarily unavailable. Please try again in a moment.

`answer/decline match` means answerable questions did not decline and unanswerable questions did decline, using the established refusal-pattern check.

Re-scored offline from the disk cache (no Gemini calls) after the refusal patterns were widened to catch "no information about/on/regarding" (`backend/eval/refusal_patterns.py`). Q10 snippet and full changed False -> True (correct GST declines), Q8 full changed True -> False (a decline on an answerable question that the old patterns missed). These cached answers came from the old dense retrieval (5 chunks, before step 2b), so the 4/10 and 8/10 describe that retrieval path, not the production BM25 path. Run metadata above is from the original run.

| Context mode | Completed | Verified | Answer/decline matches |
| --- | ---: | ---: | ---: |
| snippet | 10/13 | 10/10 | 4/10 |
| full | 10/13 | 10/10 | 8/10 |

## Per-question outcomes

| # | Context | Verified | Answer/decline match |
| ---: | --- | --- | --- |
| 1 | snippet | True | True |
| 1 | full | True | True |
| 2 | snippet | True | False |
| 2 | full | True | True |
| 3 | snippet | True | True |
| 3 | full | True | True |
| 4 | snippet | True | False |
| 4 | full | True | False |
| 5 | snippet | True | False |
| 5 | full | True | True |
| 6 | snippet | True | False |
| 6 | full | True | True |
| 7 | snippet | True | True |
| 7 | full | True | True |
| 8 | snippet | True | False |
| 8 | full | True | False |
| 9 | snippet | True | False |
| 9 | full | True | True |
| 10 | snippet | True | True |
| 10 | full | True | True |
