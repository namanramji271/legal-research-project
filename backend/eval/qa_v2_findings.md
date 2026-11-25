# QA Context Evaluation v2

- Run status: **quota_exhausted**
- Model: `gemini-3.6-flash`
- Questions: 13; expected requests: 26 context/question pairs
- Uncached Gemini prompt calls this run: 21; disk-cache hits: 0
- Uncached evaluation calls remaining: 6
- Stop reason: HTTPException: 503: The AI answering service is temporarily unavailable. Please try again in a moment.

`answer/decline match` means answerable questions did not decline and unanswerable questions did decline, using the established refusal-pattern check.

| Context mode | Completed | Verified | Answer/decline matches |
| --- | ---: | ---: | ---: |
| snippet | 10/13 | 10/10 | 3/10 |
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
| 8 | full | True | True |
| 9 | snippet | True | False |
| 9 | full | True | True |
| 10 | snippet | True | False |
| 10 | full | True | False |
