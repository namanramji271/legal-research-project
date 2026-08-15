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

## Current status
- IPC-BNS mapper: complete — SQLite-backed, real data (18 sections:
  murder/culpable homicide block IPC 299-304+304A, private defence
  block IPC 96-106), both directions working
- Judgment corpus: not yet collected
- Embeddings/search/QA: not yet built
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