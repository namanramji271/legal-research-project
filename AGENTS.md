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
  (generated artifact, rebuild via backend/scripts/build_embeddings.py).
  CORRECTED: backend/.gitignore originally listed the wrong path
  (chroma_store/, an unrelated leftover folder) instead of the real
  chroma_db/ path — fixed during the BGE-M3 comparison work below, so
  chroma_db/, chroma_db_bge/, and data/judgments.jsonl are now all
  correctly gitignored.
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
  RESOLVED: extract_cited_cases() now deduplicates sources_used in
  first-occurrence order. Verified via an isolated unit test
  (backend/eval/test_dedup_logic.py) that calls the function directly
  with a sample answer text containing a repeated citation, rather than
  relying on Gemini happening to produce a repeated citation in a live
  response (which would also cost API quota unnecessarily to test).
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

## BGE-M3 vs MiniLM comparison — complete
Goal: compare retrieval quality of BGE-M3 against the existing MiniLM setup,
using the same evaluation harness built in the Evaluation section above.
MiniLM's existing collection/index was untouched throughout — BGE-M3 lives in
fully separate files/paths (backend/data/chroma_db_bge, judgments_bge_m3
collection) so both coexist and can be compared side by side.

- backend/embeddings.py: `BGEM3EmbeddingFunction` (BAAI/bge-m3 via
  sentence-transformers), same Chroma embedding function interface as
  `JudgmentEmbeddingFunction`. `BGE_COLLECTION_NAME = "judgments_bge_m3"`,
  `BGE_CHROMA_DB_PATH = backend/data/chroma_db_bge`. `_get_bge_model()` /
  `get_bge_embedding_function()` cache the model process-wide so it loads
  once, not per batch/call (an earlier version let Chroma invoke the
  embedding function internally per add() batch, which reloaded the
  ~2.27GB model repeatedly and inflated build time from ~37min to ~50min
  for no benefit — fixed by embedding each batch explicitly and passing
  raw embeddings= to Chroma).
- backend/scripts/build_embeddings_bge.py: builds the BGE-M3 collection
  from the same corpus/chunking as the MiniLM build. CONFIRMED WORKING:
  533 chunks built successfully. TIMING (CPU only, no GPU): ~37-38 minutes
  (2262.7s), vs. MiniLM's near-instant build — a real, citable cost
  trade-off, not a bug.
- backend/search.py: `search_judgments_bge(query, n_results=5)` mirrors
  `search_judgments()` exactly (same 0.65 threshold, same response shape),
  querying the BGE-M3 collection instead. `search_judgments()` and the
  `/search` route are unchanged. Manually verified working via a debug
  script — plausible, on-topic results for a private-defence query.
- backend/eval/evaluate_retrieval_comparison.py: runs both
  search_judgments() and search_judgments_bge() against all 15 labeled
  queries in test_queries.json, reports precision@5/recall@5/MRR for both.

### Results (backend/eval/embedding_comparison_findings.md)
| Model | precision@5 | recall@5 | MRR |
| --- | ---: | ---: | ---: |
| MiniLM | 0.307 | 0.494 | 0.595 |
| BGE-M3 | 0.360 | 0.524 | 0.644 |

BGE-M3 improves all three aggregate metrics modestly. The improvement is
NOT uniform across queries (queries 6, 11, 12, 13 saw BGE-M3 tie or
underperform MiniLM) — it is concentrated in the previously-weak IPC 304
queries: MiniLM scored 0.000/0.000 precision/recall on both IPC 304
queries (see findings.md), BGE-M3 improved these to 0.400/0.222 each,
supporting the findings.md hypothesis that stronger embeddings handle
comparative/negation phrasing ("not amounting to murder") better.
CONCLUSION: not an unconditional upgrade — the ~37min build-time cost is
real, and gains are topic-specific. Recommended as a future-work item
(potentially combined with corpus expansion for IPC 304, or a hybrid
dense+BM25 approach) rather than an immediate wholesale switch.

## Hybrid search (BM25 + dense RRF) — complete
Goal: test whether combining BM25 keyword retrieval with dense (MiniLM)
retrieval via reciprocal rank fusion (RRF) would outperform either alone,
motivated by the IPC 304 negation-phrasing weakness found in the retrieval
evaluation above.

- backend/bm25_search.py: `bm25_search(query, n_results=10)` — BM25 index
  (rank_bm25 library) built once from the same 533 chunks/chunking as the
  dense index (reuses build_chunk_records()), cached in memory, same
  response shape as search_judgments(). Deduplicates to unique case names
  in first-occurrence order, same pattern as search_judgments().
- backend/hybrid_search.py: `hybrid_search(query, n_results=5)` — fetches
  15 candidates from both search_judgments() (dense) and bm25_search(),
  deduplicates each to unique case names in first-occurrence order, then
  merges via RRF (k=60): score = sum(1/(60+rank)) across whichever list(s)
  a case appears in, sorted descending, top n_results returned.
  LESSON LEARNED: an early version computed RRF ranks on the raw
  (un-deduplicated) result lists before removing duplicate chunks from the
  same case — this could inflate a relevant case's effective rank whenever
  duplicate chunks from an irrelevant case preceded it. Fixed by
  deduplicating both input lists to unique case names first, then assigning
  RRF ranks on the deduplicated order.
- backend/eval/evaluate_retrieval_hybrid.py: three-way comparison
  (MiniLM/BM25/Hybrid) against the same 15 labeled queries in
  test_queries.json.

### Results (backend/eval/hybrid_search_findings.md)
| Method | precision@5 | recall@5 | MRR |
| --- | ---: | ---: | ---: |
| MiniLM dense | 0.307 | 0.494 | 0.595 |
| BM25 keyword | 0.413 | 0.548 | 0.733 |
| Hybrid RRF | 0.320 | 0.475 | 0.645 |

KEY FINDING (counter to the original hypothesis): BM25 alone outperforms
BOTH MiniLM dense retrieval AND the RRF hybrid, on every metric. Explanation:
these legal queries share highly specific, formal vocabulary with the
judgment text itself (section numbers, doctrinal phrases like "dying
declaration"), which favors literal keyword match over semantic
approximation. Naive unweighted RRF underperforms pure BM25 because rank
fusion rewards agreement between two rankers of similar quality — when one
ranker (BM25) is consistently stronger, blending in the weaker one (dense)
dilutes rather than improves the ranking, a known limitation of unweighted
rank fusion.

DATA QUALITY FINDING (discovered during BM25 implementation): 37 of 48
judgments (77%) contain text corruption from the source ILDC dataset's
anonymization pipeline — common words are garbled (e.g. "not" → "number",
"court" → "companyrt", "convicted" → "companyvicted"). This is a pre-existing
corpus artifact, not something introduced by this project. It likely limits
BM25's ability to exploit negation phrasing specifically (e.g. "not
amounting to murder" reads as "number amounting to murder" in most of the
corpus), even though BM25 still won overall. Documented as a corpus
limitation; not fixed (targeted find-and-replace was judged too risky to
attempt safely across 37 judgments in remaining project time).

CONCLUSION / recommendation: BM25 is the strongest single retrieval method
found so far for this domain — worth considering as primary retrieval, or
revisiting with a *weighted* fusion (giving BM25 more influence than dense)
rather than unweighted RRF. This directly contradicts the original hybrid-
search hypothesis and is genuinely useful negative-result material for the
paper.

## Document Upload — complete
Goal (from original project plan, Phase 2 item #6): let a user upload a
legal document and find related judgments from the existing corpus,
reusing search_judgments() rather than building new retrieval logic.
Chosen scope: extract text + find related judgments (not summarization —
that's planned separately as Phase 2 item #7, AI Case Summary, which
depends on this).

- backend/documents.py: new FastAPI router.
  - POST /documents/upload — accepts .pdf or .txt file upload
    (multipart/form-data), extracts text in memory (pdfplumber for PDF,
    UTF-8 decode for .txt), does NOT persist the file to disk. Returns
    {filename, extracted_text, char_count, related_judgments}.
  - find_related_judgments(document_text, sample_size=3,
    n_results_per_chunk=5): chunks the uploaded document using the same
    chunker as the corpus build (chunk_text() from
    scripts/build_embeddings.py), evenly samples `sample_size` chunks
    spread across the FULL document (not just the first N — e.g. for 40
    chunks and sample_size=3, samples indices ~0, ~20, ~39), searches
    each sampled chunk via search_judgments(), and ranks matched cases by
    how many sampled chunks they matched (match_count), tie-broken by
    first-appearance order. Returns the same shape as search_judgments()
    plus a match_count field.
  - LESSON LEARNED: an initial version truncated to only the FIRST
    sample_size chunks of the document (e.g. just the first ~2 pages),
    which would silently ignore the bulk of a long real-world judgment
    (judgments frequently run 50-100+ pages per the paper's own framing).
    Fixed to sample evenly across the whole document instead.
  - requirements.txt: added python-multipart (required for FastAPI file
    uploads) and pdfplumber (PDF text extraction).
- Registered in main.py, no /api prefix (consistent with existing routes).
- frontend/src/DocumentUploadPage.jsx (built in Cursor): file input
  (.pdf/.txt), upload button with loading state, related judgments shown
  with the same result-card style as SearchPage.jsx plus a match_count
  badge, empty-state message ("no closely related judgments found"),
  collapsible raw extracted_text section, error handling matching the
  app's existing lookup-message/lookup-error pattern. Added as a new tab
  in App.jsx alongside Mapping, Search, and Ask a Question. SearchPage.jsx
  and QuestionPage.jsx were not modified.

CONFIRMED WORKING end-to-end (manually tested):
- PDF and TXT upload both extract text correctly (verified against a
  real IEEE-formatted PDF: correct char count, clean text).
- Self-retrieval sanity check: uploading a corpus judgment's own text
  correctly returned itself as the #1 related result with
  match_count=3/3 (all sampled chunks agreed) — strong validation the
  pipeline works correctly end-to-end.
- Frontend renders correctly: loading state, result cards, match_count
  badges, collapsible extracted-text section all confirmed via browser
  testing.
NOT YET TESTED: a genuinely long real-world judgment/legal document (50+
pages) to see whether sample_size=3 remains sufficient at that length, or
whether it should be increased. Also not yet tested: wrong-file-type
error path and browser console error-checking (should be confirmed
before treating this as fully verified).

## Repo hygiene — resolved
backend/.gitignore previously listed the wrong path (chroma_store/, an
unrelated leftover folder from early testing) instead of the real active
paths. Fixed: chroma_db/, chroma_db_bge/, and data/judgments.jsonl are now
correctly gitignored and untracked. git status confirmed clean working
tree after the fix. judgments.jsonl was already untracked prior to this
fix (git rm --cached had been run earlier) — the gitignore update just
prevents it from being accidentally re-added.

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
- When combining or ranking results from multiple retrieval sources (or
  reporting precision/recall over a result list), always deduplicate to
  unique case names in first-occurrence order BEFORE computing rank
  positions or applying any rank-based scoring (e.g. RRF). Computing ranks
  on a raw, duplicate-containing list can silently inflate or deflate a
  case's effective rank — this caused a real bug in hybrid_search() once
  already.