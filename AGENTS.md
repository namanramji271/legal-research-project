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
- LLM: Gemini API (google-genai SDK, model: gemini-2.5-flash)
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
  them fell above the 0.65 distance cutoff. This was not re-tested directly
  against the QA endpoint this session — worth a follow-up check with a
  deliberately vague/off-topic question through POST /ask specifically
  (not just search_judgments()) to confirm the empty-chunks message still
  reads correctly end-to-end.
  KNOWN ISSUE: sources_used can contain duplicate case names (same case
  cited multiple times in one answer) — extract_cited_cases() needs to
  deduplicate while preserving first-occurrence order.
- Citation verifier: complete — folded into backend/qa.py via
  find_unverifiable_citations(), which scans the answer text for
  ILDC-case-name-shaped strings (regex pattern "ILDC case \d{4}_\d+") not
  present in the retrieved chunk set, and flags them. Response's `verified`
  field is False if any unverifiable citation is found. Tested: returns
  verified=True with zero unverified citations on a well-supported question.
- Citation-backed QA frontend: complete — QuestionPage.jsx, shows verified/
  unverified banner, deduplicated sources list. Tested and confirmed working
  on both a well-supported question (graceful honest answer) and a
  deliberately off-topic question (correctly declined rather than
  hallucinating — verifier confirmed working as intended).

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

## Known repo hygiene issues (flag for cleanup)
- backend/data/judgments.jsonl is currently committed to git, despite the
  note above that it shouldn't be (IL-TUR license restricts redistribution).
  Needs: git rm --cached backend/data/judgments.jsonl, then confirm it's
  covered by backend/.gitignore.
- backend/chroma_store/ is committed despite being listed in
  backend/.gitignore (added before the gitignore rule existed). Needs:
  git rm -r --cached backend/chroma_store