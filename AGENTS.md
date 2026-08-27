# Project: AI-Powered Legal Research Platform (IPC-BNS)

## What this is
Final year project: RAG-based legal research tool for Indian law.
Bidirectional IPC-BNS section mapping, semantic search over judgments,
citation-backed QA with a citation verification safeguard.

## Stack
- Backend: FastAPI (Python)
- Frontend: React + Vite + Tailwind
- Vector DB: ChromaDB
- Embeddings: all-MiniLM-L6-v2 (chosen for speed without GPU; BGE-M3
  comparison planned for later evaluation phase, not this week)
- LLM: Gemini API (google-genai SDK, model: gemini-2.5-flash). Free-tier
  quota observed in practice: 5 requests/minute, 20 requests/day — any
  evaluation script calling ask_question() repeatedly must pace requests
  (15-30s delay) and expect to span multiple days for larger test sets.
- Data: judgment corpus filtered from ILDC/NyayaAnumana for
  murder/culpable homicide/private defence (IPC 299-304, 96-106)

## Current status
- IPC-BNS mapper: complete — SQLite-backed, real data (18 sections:
  murder/culpable homicide block IPC 299-304+304A, private defence
  block IPC 96-106), both directions working
- Judgment corpus: complete — 48 judgments in backend/data/judgments.jsonl,
  filtered from IL-TUR/ILDC, manually triaged (2 false positives removed
  where the target IPC section appeared only in passing). Fields: case_name,
  court, year, ipc_sections, full_text. Not committed to git (IL-TUR license
  restricts redistribution — regenerate via backend/scripts/build_corpus.py
  with own Hugging Face access token)
- Embeddings/vector DB: complete — 533 chunks from 48 judgments, embedded
  with all-MiniLM-L6-v2 via a shared embedding function in backend/embeddings.py
  (JudgmentEmbeddingFunction), stored in ChromaDB at backend/data/chroma_db
  (gitignored, generated artifact, rebuild via backend/scripts/build_embeddings.py).
  Any code opening this collection MUST use the same shared embedding function
  from embeddings.py, or ChromaDB silently falls back to its own default model
  and results become meaningless — this caused a real bug once already.
  NOTE: backend/chroma_store is an unrelated leftover from an early toy-RAG
  test, not the real data — safe to delete, do not confuse the two paths.
- Semantic search backend: complete — search_judgments() in backend/search.py
  returns a flat list of {case_name, court, year, ipc_sections, snippet}.
  Exposed via GET /search?q={query}&n_results={n}, registered in main.py,
  no /api prefix. Tested and confirmed working via browser/docs.
  RELEVANCE THRESHOLD (Day 4): SEARCH_DISTANCE_THRESHOLD = 0.65 (module-level
  constant in search.py). Chroma cosine distance, lower = more similar;
  chunks with distance > 0.65 are discarded inside search_judgments() before
  the response is built. Distance itself is NOT exposed in the response
  shape — filtering is internal only. IMPORTANT BEHAVIORAL CHANGE: n_results
  is now the number of candidates fetched from Chroma before filtering, not
  a guaranteed return count — a query can return fewer than n_results
  (including zero) once weak matches are dropped. Manually tested:
  on-topic queries ("murder during self defence", "culpable homicide sudden
  provocation") return relevant results; off-topic/gibberish queries
  ("dgadfad sdfsdf", "culprit") correctly return no matches instead of
  forcing weak matches through. No database/embedding changes were made.
- Semantic search frontend: complete — SearchPage.jsx, deduplicated results,
  tabbed navigation. Quality note: MiniLM is a general-purpose model, so
  results are a mix of strong and weak matches — demo with pre-tested
  queries (e.g. "right of private defence", culpable-homicide-distinction
  queries perform well) rather than arbitrary live queries. Post-threshold,
  weak matches are filtered before reaching the frontend, but empty-result
  states should still be handled gracefully in the UI (verify SearchPage.jsx
  shows a clear "no results" state, not a blank list).
- Citation-backed QA backend: complete — backend/qa.py, ask_question()
  retrieves top-n chunks via search_judgments() (n_results=10 default,
  increased from 5 since 5 was too few to reliably surface good context),
  builds a grounded prompt instructing Gemini to answer only from provided
  context and cite exact case names, calls Gemini, returns
  {answer, verified, sources_used, unverified_citations, retrieved_sources}.
  Exposed via POST /ask (JSON body: {question, n_results}), no /api prefix.
  Tested directly via Python — confirmed real, grounded answers with correct
  citations on well-supported questions (e.g. "When does the right of
  private defence exceed reasonable force?"), and confirmed honest "not
  enough information" responses rather than hallucination when retrieval
  context is weak.
  NOTE (Day 4): since search_judgments() now applies SEARCH_DISTANCE_THRESHOLD,
  ask_question()'s existing "no relevant judgments found" empty-chunks path
  can now trigger even when Chroma returned n_results candidates, if all of
  them fell above the 0.65 distance cutoff. CONFIRMED (evaluation phase):
  end-to-end behavior through POST /ask is correct — see QA evaluation below.
  KNOWN ISSUE: sources_used can contain duplicate case names (same case
  cited multiple times in one answer) — extract_cited_cases() needs to
  deduplicate while preserving first-occurrence order.
- Citation verifier: complete — folded into backend/qa.py via
  find_unverifiable_citations(), which scans the answer text for
  ILDC-case-name-shaped strings (regex pattern "ILDC case \d{4}_\d+") not
  present in the retrieved chunk set, and flags them. Response's `verified`
  field is False if any unverifiable citation is found. Tested: returns
  verified=True with zero unverified citations on a well-supported question.
  CONFIRMED (evaluation phase): verified=True with zero fabricated citations
  across all 13 QA evaluation questions, including 4 deliberately off-topic
  ones — see QA evaluation below.
- Citation-backed QA frontend: complete — QuestionPage.jsx, shows verified/
  unverified banner, deduplicated sources list. Tested and confirmed working
  on both a well-supported question (graceful honest answer) and a
  deliberately off-topic question (correctly declined rather than
  hallucinating — verifier confirmed working as intended).

## Evaluation (Day 4/5) — complete
Formal evaluation replacing manual spot-checks. All files in backend/eval/.

### Retrieval evaluation
- backend/eval/test_queries.json — 15 labeled queries covering private
  defence (96-106) and IPC 299-304, each with a manually-verified
  relevant_cases list drawn from backend/data/judgments.jsonl.
  IPC 302 queries were originally too broad (one label covered 40/48
  corpus cases, making precision/recall meaningless) and were re-derived
  via backend/eval/ipc302_themes.json, which thematically tags each
  302-labeled judgment (death penalty vs life sentencing, circumstantial
  evidence, common intention/Section 34, dying declaration, motive/
  premeditation) so queries could be split into narrower, well-labeled
  themes instead.
- backend/eval/evaluate_retrieval.py — calls search_judgments() for each
  labeled query, computes precision@5, recall@5, and reciprocal rank
  against the labeled relevant_cases (deduplicated to unique case names,
  first-occurrence order, before taking top 5). Read-only, does not
  modify search.py.
- Results (backend/eval/findings.md): mean precision@5 = 0.307, mean
  recall@5 = 0.494, MRR = 0.595, 0/15 queries returned zero results (the
  0.65 threshold is not overly aggressive for these queries).
  KEY FINDING: both IPC 304 queries scored precision@5 = recall@5 = 0.000.
  Debug output showed only 2 of 9 expected relevant cases appeared in the
  top 10 results at all (ranked 6th-7th, just outside top-5), with IPC-302-
  only judgments dominating the top 5. Explanation: corpus imbalance
  (IPC 302 ~40/48 judgments vs sparse IPC 304 coverage) biases the dense
  embedding space toward 302-adjacent language, compounded by comparative/
  negation query phrasing ("not amounting to murder") that embeddings
  handle poorly. Motivates two already-planned future work items: expanding
  corpus coverage for underrepresented sections, and hybrid (dense + BM25)
  search to catch exact-term contrasts embeddings miss.

### QA evaluation
- backend/eval/test_qa_questions.json — 13 questions: 9 in-corpus
  (expected_answerable=true) covering private defence and IPC 299-304,
  4 deliberately out-of-corpus (GST, NDPS bail, Hindu Marriage Act divorce,
  BNS-420 mapping question — expected_answerable=false).
- backend/eval/evaluate_qa.py — calls ask_question() per question, checks
  (a) verified is True (no fabricated citations — should hold regardless
  of answerability) and (b) insufficient-context behavior matches
  expected_answerable, via regex over the answer text. Paces requests with
  a delay (15-30s) to stay under Gemini free-tier rate limits (5/min,
  20/day observed) and catches API errors per-question rather than
  crashing the whole run.
  LESSON LEARNED: initial version conflated "verified" (no fabricated
  citations) with "matched expected answerability" — these are different
  properties; a correctly-behaving system should have verified=True on
  every response, answerable or not. Fixed to check verified is True
  directly.
- Results (backend/eval/qa_findings.md):
  - 13/13 responses had zero fabricated citations, including all 4
    off-topic questions — the citation verifier holds regardless of
    whether a question is answerable. This is the headline safety result.
  - 10/13 questions showed expected answer-or-decline behavior. 3 genuine
    mismatches (private-defence force limits, private-defence-of-property
    timing, IPC 299 definition) are retrieval-precision misses consistent
    with the retrieval findings above — topic present in corpus, but
    top-5 chunks lacked the specific detail asked, so the system correctly
    declined rather than guessing (conservative failure mode, not
    hallucination). A 4th apparent mismatch (Hindu Marriage Act divorce
    question) was a detection-pattern gap in evaluate_qa.py's regex
    (required the word "enough", missed "does not contain information
    regarding..."), not a system failure — fixed by broadening the regex,
    which raised the score from 9/13 to 10/13 with no new API calls needed.
  - Operational note: Gemini free-tier daily quota (20 requests/day) was
    hit mid-evaluation; reproducing this eval may require spreading runs
    across multiple days or upgrading the API plan.

## Conventions
- Backend lives in /backend, frontend in /frontend
- API routes have NO prefix — e.g. /mapping/ipc/{section}, not
  /api/mapping/ipc/{section}. Keep all future routes consistent with this,
  no /api prefix.
- Mapping data source of truth is backend/data/ipc_bns_mapping.csv —
  backend/data/mapping.db is a generated SQLite file built from it on
  server startup (auto-rebuilds if the CSV is newer than the DB), and
  is gitignored, not committed
- Mapper response shape: {ipc_section, bns_section, title, notes}
- Search response shape: list of {case_name, court, year, ipc_sections, snippet}
  (post-threshold: may be shorter than requested n_results, including empty)
- QA endpoint is POST /ask (not GET — question text as a JSON body, not a
  URL query param), request body: {question: string, n_results?: number}
- QA response shape: {answer, verified, sources_used, unverified_citations,
  retrieved_sources}
- Citation verifier must check every LLM-cited case name against
  retrieved chunk metadata before returning a response as verified
- Evaluation scripts (backend/eval/) are read-only against search.py/qa.py
  by convention — they measure behavior, they don't modify it. Any future
  eval script should follow this pattern.
- When writing eval-script text-matching logic (e.g. detecting a decline/
  insufficient-context response via regex), test against multiple real
  phrasing variants before trusting the aggregate metric — a narrow regex
  can silently misclassify correct behavior as a failure (happened once
  already with the "enough information" pattern).

## Known repo hygiene issues (flag for cleanup)
- backend/data/judgments.jsonl is currently committed to git, despite the
  note above that it shouldn't be (IL-TUR license restricts redistribution).
  Needs: git rm --cached backend/data/judgments.jsonl, then confirm it's
  covered by backend/.gitignore.
- backend/chroma_store/ is committed despite being listed in
  backend/.gitignore (added before the gitignore rule existed). Needs:
  git rm -r --cached backend/chroma_store