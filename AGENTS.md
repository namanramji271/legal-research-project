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

## Frontend redesign — complete
Goal: original frontend was functional but visually plain ("basic vibe-coded"
look) — redesigned for a modern, minimal, professional look suitable for
project review/demo/conference presentation. Built entirely in Cursor
(which built the original frontend too, so it has full existing context).
Purely visual/structural — no API calls, data fetching, or page logic were
changed during this work.

- Design system: "Minimal Monochrome" — near-black/off-white palette,
  single restrained accent color, single sans-serif typeface (dropped an
  earlier navy/gold + serif direction that was tried first and replaced).
  Slow (300-400ms) ease-in-out animations only; no bounce/scale-pop effects.
- Navigation: replaced the original top tab bar with a Claude-style left
  sidebar (expanded by default, collapse/expand toggle, hover-to-preview
  when collapsed, active-page highlight).
- New Dashboard page (new default route, replacing direct landing on the
  Mapping tool): hero section (large headline + supporting text, properly
  scaled/spaced), four feature cards linking to the existing tools
  (Mapping, Judgment Search, Ask a Question, Document Upload), plus four
  additional content sections added in a follow-up pass:
  - "How It Works" pipeline (Query -> Embedding -> Vector Search -> LLM
    Generation -> Citation Verification -> Verified Answer), animated
    step-by-step on scroll.
  - Evaluation Results stat grid, using REAL project numbers only (no
    invented stats): 48 curated judgments, 533 indexed chunks, 0
    fabricated citations across 13 QA evaluation questions (9 in-corpus +
    4 deliberately out-of-scope), MRR 0.733 (this is the BM25 result
    specifically — see hybrid_search_findings.md; do not confuse with
    MiniLM's 0.595 or Hybrid's 0.645 if this section is ever edited
    again), 18 IPC<->BNS section mappings.
  - Tech Stack section (FastAPI, React, ChromaDB, Gemini, Sentence
    Transformers MiniLM/BGE-M3, SQLite) as simple typographic chips.
  - Context/Motivation section explaining the IPC-to-BNS 2024 transition
    problem and why keyword search misses conceptually related judgments.
  - All sections use scroll-triggered fade/slide-up animation (Intersection
    Observer pattern), staggered, consistent with the feature cards'
    existing animation.
- Layout: Dashboard content centered with a ~64rem max-width container
  (the four tool pages remain at the narrower ~52rem they already used).
- Design inspiration process: explored a marketing-agency-style reference
  (Outcrowd) for motion/typography confidence, but deliberately did NOT
  adopt its structure (parallax hero, fake stats/testimonials, one-time
  scroll-to-convert layout) since this is a repeatedly-used functional
  tool, not a one-time marketing page. Borrowed only: typographic
  confidence in the hero, and a tasteful scroll-triggered reveal for cards
  instead of load-triggered. Better long-term reference category for
  future frontend work: functional SaaS/dev tools (Linear, Vercel,
  Notion, Perplexity for AI-answer/citation display specifically), not
  marketing/branding agency sites.
NOT independently re-verified by Claude (no visual access to the running
app) — verify in-browser that the Evaluation Results section's MRR value
is correctly labeled as the BM25 result specifically before treating this
as final, since three different MRR values exist across the eval findings
docs and mislabeling one on the dashboard would be an easy, avoidable
inconsistency against the paper.

## AI Case Summary — complete
Builds on Document Upload (#6) + Judgment Summarization (#4) from the original
plan, combined into one feature per design decision: summarize both the
uploaded document AND individual related judgments, on demand.

- backend/documents.py: added Gemini client setup identical to qa.py's
  pattern (load_dotenv, GEMINI_API_KEY check/RuntimeError, MODEL_NAME =
  "gemini-2.5-flash", client = genai.Client(...)) — kept self-contained in
  documents.py, qa.py untouched.
- summarize_legal_text(text: str, max_chars: int = 20000) -> str: truncates
  input over max_chars (appends a truncation note to output when triggered),
  prompts Gemini for a structured summary under 200 words across four
  labeled sections (Facts / Issue/Question of Law / Holding/Decision /
  Reasoning), using only the provided text. Verified: correctly declines to
  invent Holding/Reasoning when the input doesn't state them (tested on a
  synthetic thin fact pattern), and correctly extracts real legal reasoning
  when given a real judgment (tested on ILDC case 1951_30 — Section 439 CrPC
  scope-of-revision case).
- POST /documents/summarize-uploaded: body {extracted_text: string}, returns
  {summary: string}. 400 on empty/whitespace-only extracted_text. Separate
  from /documents/upload by design — summarization is never automatic.
- GET /judgments/{case_name}/summary: looks up case_name (URL-decoded via
  unquote(), handles names with spaces e.g. "ILDC case 2013_35") against a
  cached in-memory index (_load_judgments_index(), @lru_cache(maxsize=1),
  keyed by case_name from judgments.jsonl). Returns {case_name, summary} or
  404 if not found.
- DESIGN CONSTRAINT (deliberate): summarization is entirely on-demand,
  never automatic on upload/search/page-load. Same Gemini free-tier limits
  as before (5 req/min, 20/day) — auto-summarizing every upload or search
  result would burn quota fast. Every summary requires an explicit user
  click on its specific button.
- Frontend (built in Cursor initially, finished in Antigravity after a
  Cursor rate limit): DocumentUploadPage.jsx only — SearchPage.jsx and
  QuestionPage.jsx untouched.
  - "Summarize Document" button near the collapsible extracted-text
    section; result rendered via a new SummaryBody component that splits
    on **Label:** markdown-bold tokens into labeled .summary-section
    blocks, falling back to plain text if the format doesn't parse
    (defensive against Gemini output drift).
  - Per-card "Summarize" button on each related-judgment card. State is
    tracked per-card via a Map<case_name, {loading, error, summary}> —
    clicking one card's button has zero effect on any other card.
  - case_name URL-encoded via encodeURIComponent() before the GET request.
  - 404s shown as an inline error on the specific card.
  - All summary state clears on new file selection/upload.

CONFIRMED WORKING end-to-end (manually tested, screenshots reviewed):
- Document summary: real 37,019-char PDF upload, truncation note appeared
  correctly, all four sections rendered as distinct visual blocks.
- Per-card judgment summary: tested on ILDC case 1974_115 (Bombay
  Municipal Corporation Act / Article 14 case) — accurate four-section
  summary, only that card updated, all other cards (1971_142, 1957_64,
  2002_580, 1964_288, 1955_0) remained independently clickable and
  unaffected.
- No auto-summarization observed anywhere; all summaries required explicit
  clicks.

KNOWN MINOR ISSUE (not yet fixed): Gemini sometimes prepends an
unrequested preamble sentence before the Facts section (e.g. "Here is a
concise, structured legal summary based *only* on the provided text:").
SummaryBody's fallback rendering handles this gracefully (shown as plain
text above the labeled sections), so it's cosmetic, not a functional bug.
Fix if revisited: tighten the prompt in summarize_legal_text() to
explicitly forbid preamble/introductory sentences.

## Dashboard restructure — complete
Context: Phase 1 academic review is complete; going forward the
Dashboard's primary audience is resume/portfolio viewers and future
conference reviewers, not an evaluator checking the live site against a
rubric. Goal: make the Dashboard read as a confident, usable product
first, with technical/evaluation depth repositioned as secondary
supporting evidence rather than primary content.

- frontend/src/DashboardPage.jsx restructured into two visually distinct
  zones on the same page (no route split — no router exists in this app,
  page state is a single useState in App.jsx):
  - Zone 1 (product, unchanged): hero + 4 feature cards, primary
    above-the-fold content.
  - Zone 2 (technical/evidence, demoted not deleted): How It Works
    pipeline, Evaluation Results stat grid, Tech Stack, Context
    paragraph — now wrapped in a distinct container with a lighter
    background shade shift and a "ARCHITECTURE & EVALUATION / Technical
    reference" section intro, marking a deliberate transition rather
    than a plain divider.
  - Not made collapsible/accordion — still visible on scroll, just
    repositioned as secondary.
  - Evaluation Results stat grid also rebalanced during this pass (was
    4-then-1-orphaned across rows; now displays as a clean 3+2 layout at
    all breakpoints).
  - All existing scroll-triggered reveal animations (useInView,
    dashboardCardReveal stagger, connector line animations) preserved
    exactly as they worked before.
- Confirmed working via screenshots: clean product-first landing, clear
  visual break before the technical section, stat grid no longer
  orphaned.

## Frontend polish pass — complete
Goal: fix large empty dead-zones below the input on every tool page
(Mapping, Search, Ask a Question), add scope calibration, and audit
button-label consistency.

- Suggested/example chips added below the input on:
  - frontend/src/components/SearchPage.jsx — 3 example queries (sudden
    provocation, private defence/reasonable force, common intention
    Section 34).
  - frontend/src/components/QuestionPage.jsx — 3 example questions,
    same topics.
  - frontend/src/components/MappingLookup.jsx — 3 example sections
    (302, 304, 96).
  - Clicking a chip auto-populates the input AND auto-submits (no
    second click needed) — confirmed working via screenshot (Section
    302 chip → correct Punishment for murder / IPC 302 → BNS 103(1)
    result returned automatically).
  - Chips only shown before a result exists.
- Corpus scope reminder added below the page description on all three
  tool pages above: "Corpus scope: Murder & Culpable Homicide (IPC
  299–304) · Private Defence (IPC 96–106)" — small, muted styling,
  doesn't compete with the heading.
- Button label casing audited across SearchPage.jsx, QuestionPage.jsx,
  MappingLookup.jsx, DocumentUploadPage.jsx, and Sidebar.jsx —
  standardized to sentence case throughout.
- Confirmed working via screenshots on all three tool pages plus one
  live chip-click test.

## Explainable Retrieval — complete
Goal (from original Phase 1 plan, item #8, "planned for Month 3"): make
retrieval results interpretable rather than a black-box ranking — show
why a result surfaced, not just that it did. Scoped as a three-layer
feature building directly on the project's own evaluation findings
(BM25 alone outperforming both dense and hybrid RRF — see
backend/eval/hybrid_search_findings.md) rather than inventing a new,
unrelated scoring heuristic.

- backend/explainability.py: new standalone module,
  compute_match_explanation(query, case_name, snippet, dense_case_names,
  bm25_case_names) -> dict. Does not call ChromaDB/BM25 itself — takes
  already-retrieved case-name lists as input. Returns:
  - matched_methods: ["dense"] and/or ["bm25"] depending on which
    retrieval method(s) surfaced this case.
  - matched_terms: non-stopword query terms found (case-insensitive
    substring match) in the snippet, order-preserved, deduplicated,
    capped at 8. Hardcoded stopword list, no new NLP dependency.
  - relevance_label: "Strong match" if both dense and BM25 agree on this
    case (method-agreement-as-confidence is the project's own empirical
    finding, not an invented heuristic), "Moderate match" if only one
    method surfaced it, "Weak match" if neither (shouldn't occur in
    normal use, handled gracefully rather than erroring).
  Verified via a standalone test script (no server/API calls) across 4
  scenarios: both-methods-agree, dense-only, bm25-only, and a no-match
  edge case — all returned correct labels/methods with clean term
  extraction.
- backend/search.py: GET /search route handler (not search_judgments()
  itself, which is untouched) now additionally calls bm25_search()
  (n_results=15) per query, then compute_match_explanation() per result,
  merging matched_methods/matched_terms/relevance_label into each result
  object alongside the existing 5 fields. Backward-compatible additive
  change — existing consumers of the original 5-field shape are
  unaffected. Wrapped in try/except so that if BM25 or explanation
  computation fails, core search results still return with fallback
  values (matched_methods: ["dense"], matched_terms: [], relevance_label:
  "Moderate match") rather than the endpoint erroring out.
  Verified via TestClient (all 8 keys present, correct types) AND a real
  running-server request (both agree) — top result on a well-tested
  private-defence query correctly returned "Strong match"/both methods.
- frontend/src/components/SearchPage.jsx: term highlighting
  (HighlightedSnippet — wraps matched_terms in a subtle, monochrome-
  consistent <mark>, not a jarring yellow), method-attribution badge
  (methodLabel — "Matched by keyword + semantic search" / "...semantic
  search" / "...keyword search", omitted if empty), relevance badge
  (Strong match visually more prominent via accent-bordered style,
  Moderate more muted, both distinct from the existing IPC-section tags).
  deduplicateByCaseName updated to reconcile duplicate case_name entries
  (same case can appear once per matching chunk) by keeping whichever
  duplicate has the stronger relevance_label, rather than silently
  dropping the new explainability fields during dedup.
  NOTE: relevance_label reflects cross-method retrieval agreement, not
  literal term overlap — a result can correctly show "Strong match" with
  no highlighted terms if the specific chunk shown doesn't happen to
  repeat the query's exact wording. This is intentional, not a bug (see
  QuestionPage.jsx/SearchPage.jsx design: matched_terms and
  relevance_label are computed independently).

CONFIRMED WORKING end-to-end (manually tested, screenshots reviewed):
- "Sudden provocation reducing murder to culpable homicide": top result
  Strong match/both methods with correctly highlighted terms; two
  Moderate match/dense-only results below, giving a real, visible
  illustration of the project's own BM25-vs-dense findings.
- "Common intention under Section 34": mostly Strong match/both methods
  results, one Moderate match/semantic-only result at the tail —
  confirms method-attribution varies correctly across different result
  positions, not hardcoded.
- No duplicate case_name cards observed across either test.
- Gibberish/off-topic query: existing empty-results message still
  displays correctly, no crash from the new explainability code path.
- No backend calls beyond the existing free /search endpoint were needed
  for any of this testing — no Gemini quota impact anywhere in this
  feature.

Scoped to SearchPage.jsx only, per design — QuestionPage.jsx uses a
different data shape (QA answer + sources, not a ranked result list) and
was intentionally left out of this feature's scope.

## Authentication & Role-Based Access — Stage 2 in progress
Context: see "Future work" section below for the full staged plan. Stage 1
(frontend-only persona toggle) was skipped; went straight to Stage 2 based
on a clearer articulation of the actual goal — role-gated features per
persona, not just prompt/UI framing. Role is self-declared at signup, NOT
identity-verified — this is role-based PERSONALIZATION enforced at the API
layer, not a security boundary against someone falsely claiming a
professional identity. State this explicitly in the paper if this feature
is described there.

- backend/auth.py: new standalone module. users table (id, username,
  password_hash, role, created_at) in a dedicated SQLite file
  (backend/data/users.db), kept fully separate from mapping.db (which is a
  generated artifact rebuilt from ipc_bns_mapping.csv on startup). Only
  CREATE TABLE IF NOT EXISTS is used — users.db must never be
  regenerated/dropped, unlike mapping.db.
  - Password hashing: bcrypt directly (NOT passlib — passlib's bcrypt
    backend-detection is broken on newer bcrypt/Python versions, causing a
    "password cannot be longer than 72 bytes" error during passlib's own
    internal self-test, unrelated to actual password length. Fixed by
    calling bcrypt.hashpw()/bcrypt.checkpw() directly instead).
  - JWT via python-jose, HS256, 24h expiry, secret from JWT_SECRET_KEY in
    .env (same pattern as GEMINI_API_KEY). No refresh-token flow, no email
    verification, no password reset — deliberately out of scope.
  - POST /auth/signup and POST /auth/login, both return
    {access_token, token_type, username, role}.
  - require_role(*roles) dependency factory for gating other routers.
  - Roles: lawyer, judge, student, public.
  - Verified via test script: all 4 roles signup (201), login returns
    correct role (200), wrong password (401), duplicate username (400).
- Role-gated backend routes (require_role("lawyer", "judge")): GET /search
  (search.py), POST /documents/upload, POST /documents/summarize-uploaded,
  GET /judgments/{case_name}/summary (all in documents.py). POST /ask and
  all /mapping/* routes remain open to all roles.
  Verified via test script: judge -> 200, student -> 403, no token -> 401.
- Frontend: frontend/src/api.js exports authFetch() (wraps fetch(), attaches
  Authorization: Bearer <token> from localStorage key "auth" if present).
  New LoginPage.jsx and SignupPage.jsx (role dropdown: Lawyer/Judge/
  Student/Public). App.jsx blocks all tool pages until auth exists in
  localStorage; renders LoginPage/SignupPage otherwise. Sidebar.jsx hides
  Search/Document Upload nav links for student/public roles and shows
  username/role/logout in a footer.
  - Route-level enforcement (not just nav-link hiding): App.jsx also
    blocks direct navigation to search/upload pages for student/public
    roles, and Dashboard's feature cards for those two tools are
    hidden/disabled for student/public — closes a bypass where the nav
    link was hidden but the page was still reachable via dashboard cards.
  - Collapsed sidebar shows icon-only avatar/logout, matching the existing
    collapsed nav-link treatment.
  - SearchPage.jsx and the three gated DocumentUploadPage.jsx calls use
    authFetch() instead of fetch(); QuestionPage.jsx and MappingLookup.jsx
    are untouched (their routes aren't gated).
  Verified end-to-end in-browser across all 4 roles: signup, login/logout,
  nav gating, dashboard-card gating, and direct search access all correct.

NOT YET BUILT (next): the four persona-specific features this gating
exists to support — judge side-by-side case comparison, lawyer case-file
export (star judgments -> PDF/DOCX), student conversational/tutor QA mode,
public simplified QA (no raw citations). See project_status_checklist.md
for the up-to-date tracker.

## Future work (not yet built, documented for later)
Persona-aware legal research platform, staged plan (updated — see
"Authentication & Role-Based Access" section above for what's actually
built): Stage 1 (frontend-only persona toggle, no accounts) was skipped.
Stage 2 (accounts + role-gated features, self-declared role) is in
progress — auth and route gating are done; the four persona-specific
features (judge comparison view, lawyer case-file export, student tutor
mode, public simplified QA) are not yet built. Stage 3 (true
identity-verified RBAC) remains deliberately out of scope — no credential
verification pipeline (e.g. against Bar Council enrollment or judicial ID
systems) is planned; role stays self-declared/personalization-only
forever. Document Stage 3's absence explicitly as a scoping decision in
the paper, not an oversight.

Other deferred ideas (not yet scoped into a stage): voice assistant
(speech-to-text/text-to-speech, likely browser-native APIs to avoid
Gemini quota cost), image upload with OCR (current Document Upload only
handles PDF/TXT).

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
- Auth: role is self-declared at signup, never treated as identity-verified
  anywhere in the codebase or docs. Any new route that should be
  restricted uses require_role(*roles) from auth.py as a Depends() — don't
  invent a second gating pattern.
- users.db (backend/data/users.db) follows the same rule as chroma_db/ and
  judgments.jsonl: gitignored, never committed, never assumed to exist on
  a fresh clone.