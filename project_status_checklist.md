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
- [x] Sidebar/nav renders different tools per role — verified during login/signup testing (Search/Upload hidden for student/public)
- [x] **Judge**: side-by-side case comparison view (parallel summaries of 2–3 picked judgments) — `POST /judgments/compare`, judge-only, verified end-to-end (2 and 3 case selection, back-navigation clears state, hidden entirely for other roles)
- [x] **Lawyer**: "case file" export — star judgments → export citations/snippets/summaries as PDF/DOCX — `POST /documents/export-case-file`, lawyer+judge, verified (docx opens correctly, content matches selection, independent selection state from judge Compare)
- [x] **Student**: conversational/tutor QA mode — multi-turn chat (frontend-held history, capped to last 5 exchanges sent to Gemini), "why this matters" section, follow-up chips, citations/verification badge stay visible. Fix applied: retrieval query now anchors to the previous question's text for vague follow-ups (e.g. "can you give an example?"), since raw follow-up text alone often lacks matchable legal vocabulary. Verified: multi-turn context works, topic-switch mid-conversation handled correctly, clear-conversation resets cleanly.
- [ ] **Public**: simplified QA + mapping only, no raw search, no document upload
- [x] Fix: Compare/Export button alignment on result cards (inconsistent position across differing case-name lengths)
- [x] Fix: Compare bar + Export bar must both be visible simultaneously (fixed positioning, stacked)

### Judge/Lawyer feature differentiation (Compare vs. Export originally showed near-identical content)
- [x] Judge: Sentencing pattern insight on Comparison page (aggregate stats from existing ipc302_themes.json labeling — no new Gemini calls) — verified: shared-theme highlighting correct across themed/untagged/out-of-scope case combinations; panel correctly hidden when no selected case is in the themed set
- [x] Judge: Citation-ready order excerpt (formats comparison output as citable paragraph; explicitly does not draft reasoning/outcome — judge remains decision-maker) — `POST /judgments/citation-excerpt`, judge-only, verified: correctly names both cases and cites specific legal principles without drafting a finding/outcome for a new matter; copy-to-clipboard confirmed working
- [x] Lawyer: Counter-argument finder (reframed adversarial retrieval query over existing corpus — surfaces precedent the opposing side may cite) — `POST /documents/counter-arguments`, lawyer+judge, verified: on-point counter-queries generated per case, no duplicate case names in results, dedup fix applied
- [x] Lawyer: Client-ready plain-language summary (reuses the plain-language prompt style planned for the Public persona) — `POST /documents/client-summary`, lawyer+judge, verified: jargon-free, no case names/citations, inline accordion expand/collapse, cached on repeat clicks
- [x] Fix: Search page query/results now persist in App.jsx state (previously lost on navigating to Compare/Export/Counter-arguments and back)
- [x] Fix: Gemini API calls now retry once on transient failure (e.g. 503) before returning a clean user-facing error instead of a raw 500

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

## Part 4.5 — Corpus Expansion (in progress, external dependency)
- [ ] Contact law-student friend re: access to additional case files
- [ ] Target: ~100+ judgments (up from current 48), ideally broader IPC section coverage to reduce the existing 302-vs-304 imbalance noted in retrieval findings
- [ ] Once expanded: re-run retrieval evaluation (precision@5/recall@5/MRR) and note delta vs. current 48-judgment baseline in the paper
- [ ] Revisit any feature with statistical framing (e.g. sentencing pattern insight) once corpus size grows — current 48-judgment base is explicitly too small for that framing to be presented as statistically meaningful; document this caveat in the paper regardless of when/whether expansion happens

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