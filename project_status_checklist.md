# AI-Powered Legal Research Platform — Project Status & Roadmap

Last updated: 2026-09-08
How to use: check off `[ ]` → `[x]` as items are completed. Keep this in sync with `AGENTS.md` (AGENTS.md stays the technical source of truth; this file is the at-a-glance tracker).

---

## Part 1 — Core Platform (Built, Phase 1)

- [x] IPC–BNS bidirectional mapper (18 sections, SQLite-backed)
- [x] Judgment corpus (48 curated ILDC judgments, 533 chunks)
- [x] Vector DB / embeddings (MiniLM, `JudgmentEmbeddingFunction`)
- [x] Semantic search backend (`search_judgments()`, distance threshold 0.65)
- [x] Semantic search frontend (SearchPage.jsx, tabbed nav, empty-state handling)
- [x] Citation-backed QA backend (`ask_question()`, grounded prompt, `POST /ask`)
- [x] Citation-backed QA frontend (QuestionPage.jsx, verified/unverified banner)
- [x] Citation verifier (`find_unverifiable_citations()`, regex-based flagging)
- [x] Document upload (PDF/TXT, in-memory only, `find_related_judgments()`)
- [x] AI Case Summary (on-demand, document + per-judgment, Gemini free-tier aware)
- [x] Frontend redesign ("Minimal Monochrome," sidebar nav, dashboard landing)
- [x] Dashboard restructure (Zone 1 product / Zone 2 technical evidence)
- [x] Frontend polish (example chips, corpus-scope reminders, button-casing audit)
- [x] Explainable retrieval (dense+BM25 match explanation, SearchPage.jsx only)

## Part 2 — Evaluation & Research (Built)

- [x] Retrieval evaluation (15 labeled queries, precision/recall/MRR)
- [x] QA evaluation (13 questions, citation-safety + answerability checks)
- [x] BGE-M3 vs MiniLM embedding comparison
- [x] Hybrid search (BM25 + dense RRF) evaluation
- [x] Findings documented: **BM25 alone > dense > hybrid RRF** (key negative result)
- [x] Findings documented: 77% of corpus has ILDC anonymization corruption ("not"→"number" etc.)

---

## Part 3 — Persona-Aware Platform (Planned)

### Stage 1 — Persona toggle, no accounts, self-declared, presentational only
- [ ] Persona selector in UI (React state, 4 roles: Lawyer / Judge / Student / Public)
- [ ] `/ask` accepts optional `persona` param; prompt branches on it
- [ ] Citation visibility toggle (hidden-by-default for Public)
- [ ] "Not legal advice" disclaimer banner (Public only)
- [ ] Persona-tuned example chips/questions

### Stage 2 — Accounts + role gating (self-declared role, real backend enforcement)
- [x] `users` table (id, username, password_hash, role, created_at) — `backend/data/users.db`, gitignored
- [x] Signup endpoint (`POST /auth/signup`) — verified: 201 on new user, 400 on duplicate username, 422 on short password
- [x] Login endpoint (`POST /auth/login`, JWT issuance) — verified: 200 + correct role on success, 401 on wrong password
- [x] Frontend login/signup pages — auth flow, role-gated nav, dashboard cards, and page-level access all verified working across all 4 roles
- [x] Role-gated backend routes — /search, /documents/upload, /documents/summarize-uploaded, /judgments/{case_name}/summary restricted to lawyer+judge; verified via test script (judge 200, student 403, no token 401) (FastAPI dependency checks role from JWT)
- [ ] Sidebar/nav renders different tools per role
- [x] **Judge**: side-by-side case comparison view (parallel summaries of 2–3 picked judgments) — `POST /judgments/compare`, judge-only, verified end-to-end (2 and 3 case selection, back-navigation clears state, hidden entirely for other roles)
- [ ] **Lawyer**: "case file" export — star judgments → export citations/snippets/summaries as PDF/DOCX
- [ ] **Student**: conversational/tutor QA mode, no raw multi-result search UI
- [ ] **Public**: simplified QA + mapping only, no raw search, no document upload

### Stage 3 — True RBAC (documented as future work only, not building)
- [ ] Verified professional identity (explicitly out of scope — no ID/credential pipeline)
- [ ] Admin vs. regular-user permission boundary (not persona-based)
- [ ] Persona remains a personalization axis forever, never a security boundary

---

## Part 4 — New Feature Ideas (proposed this session)

### Voice Assistant (speech-to-text + text-to-speech)
- [ ] Decide input scope: QA page only, or QA + Search
- [ ] Speech-to-text: browser Web Speech API (free, no Gemini quota cost) vs. a hosted STT API
- [ ] Text-to-speech: browser SpeechSynthesis API (free) for reading answers aloud
- [ ] Accessibility framing for the paper: lowers barrier to entry for Public/Student personas especially — good narrative fit alongside persona work

### Image Upload
- [ ] Decide scope: scanned judgment images, lawyer evidence photos, or both
- [ ] OCR pipeline needed — current Document Upload only handles PDF/TXT (pdfplumber doesn't OCR images)
- [ ] Options: local Tesseract OCR (free, no quota, lower accuracy) vs. a vision-capable API call (better accuracy, costs quota/money)
- [ ] Extend `find_related_judgments()` to accept OCR'd text through the same path as PDF/TXT

---

## Part 5 — Paper & Deliverables

- [ ] IEEE conference paper draft
- [ ] Write up evaluation findings section (retrieval, QA, BGE-M3, hybrid — all findings already exist in `backend/eval/`)
- [ ] Future work section: persona Stage 3, voice assistant, image upload, corpus expansion, corpus-corruption fix
- [ ] Final `AGENTS.md` sync before submission

---

## Notes on scope decisions (for your own reference later)
- Stage 1 persona toggle is presentational/self-declared — no security implication.
- Stage 2 role gating is real enforcement (backend checks JWT role) but the *role itself* is still self-declared at signup — not identity-verified. This is role-based **personalization**, not role-based **security**, and should be described that way in the paper.
- Stage 3 (real credential verification of "is this actually a judge") is intentionally never built — flagged as future work, not a gap.