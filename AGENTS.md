# Project: AI-Powered Legal Research Platform (IPC-BNS)

## What this is
Final year project: RAG-based legal research tool for Indian law.
Bidirectional IPC-BNS section mapping, semantic search over judgments,
citation-backed QA with a citation verification safeguard.

## Stack
- Backend: FastAPI (Python)
- Frontend: React + Vite + Tailwind
- Vector DB: ChromaDB
- Embeddings: BGE-M3 (or MiniLM as fallback)
- LLM: Gemini API
- Data: judgment corpus filtered from ILDC/NyayaAnumana for
  murder/culpable homicide/private defence (IPC 299-304, 96-106)
- Embeddings: all-MiniLM-L6-v2 (chosen for speed without GPU; BGE-M3
  comparison planned for later evaluation phase, not this week)

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
- Embeddings/vector DB: not yet built (today's task — chunk judgments,
  embed with all-MiniLM-L6-v2, store in ChromaDB at backend/data/chroma_db)
- Semantic search: not yet built (today's task — /search endpoint + React UI)
- Citation-backed QA: not yet built
- Citation verifier: not yet built

## Conventions
- Backend lives in /backend, frontend in /frontend
- API routes have NO prefix — e.g. /mapping/ipc/{section}, not
  /api/mapping/ipc/{section}. Keep all future routes (/search, /ask,
  etc.) consistent with this, no /api prefix.
- Mapping data source of truth is backend/data/ipc_bns_mapping.csv —
  backend/data/mapping.db is a generated SQLite file built from it on
  server startup (auto-rebuilds if the CSV is newer than the DB), and
  is gitignored, not committed
- Mapper response shape: {ipc_section, bns_section, title, notes}
- Citation verifier must check every LLM-cited case name against
  retrieved chunk metadata before returning a response as verified

