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
- LLM: Gemini API
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
- Semantic search backend: complete — search_judgments() in backend/search.py
  returns a flat list of {case_name, court, year, ipc_sections, snippet}.
  Exposed via GET /search?q={query}&n_results={n}, registered in main.py,
  no /api prefix. Tested and confirmed working via browser/docs.
- Semantic search frontend: not yet built (current task — SearchPage.jsx,
  same style as MappingLookup.jsx, must deduplicate results by case_name
  since /search returns chunk-level hits and the same case can appear
  multiple times)
- Citation-backed QA: not yet built
- Citation verifier: not yet built

## Conventions
- Backend lives in /backend, frontend in /frontend
- API routes have NO prefix — e.g. /mapping/ipc/{section}, not
  /api/mapping/ipc/{section}. Keep all future routes (/ask, etc.)
  consistent with this, no /api prefix.
- Mapping data source of truth is backend/data/ipc_bns_mapping.csv —
  backend/data/mapping.db is a generated SQLite file built from it on
  server startup (auto-rebuilds if the CSV is newer than the DB), and
  is gitignored, not committed
- Mapper response shape: {ipc_section, bns_section, title, notes}
- Search response shape: list of {case_name, court, year, ipc_sections, snippet}
- Citation verifier must check every LLM-cited case name against
  retrieved chunk metadata before returning a response as verified