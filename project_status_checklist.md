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
- [x] **Public**: simplified QA + mapping only, no raw search, no document upload — persistent non-dismissible disclaimer banner, plain-language prompt (no jargon/case names/section numbers), citations/verified badge computed server-side but not rendered. Verified: clean plain-English answer, no citation leakage, banner and one-shot layout confirmed.
- [x] Fix: Compare/Export button alignment on result cards (inconsistent position across differing case-name lengths)
- [x] Fix: Compare bar + Export bar must both be visible simultaneously (fixed positioning, stacked)
- [x] Fix: `MODEL_NAME` updated from `gemini-2.5-flash` to `gemini-3.6-flash` in qa.py and documents.py — 2.5-flash is no longer available to new Google Cloud projects (early sign of the Oct 16 2026 deprecation); 3.6-flash confirmed working on both original and a fresh testing project

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

### Voice Assistant (speech-to-text + text-to-speech) — complete
- [x] Voice input (mic button) on QuestionPage.jsx, all 4 personas — browser Web Speech API (SpeechRecognition), free, no Gemini cost. Populates question input, does NOT auto-submit. Feature-detected with disabled+tooltip fallback for unsupported browsers (Firefox/Safari — Firefox untested, not available). Public persona gets more prominent mic styling/labeling ("Ask by voice"). Verified: works correctly, and permission-denied case now shows a clear inline message with reload instructions instead of failing silently.
- [x] Voice output (read-aloud) on every QuestionPage.jsx answer, all 4 personas — browser SpeechSynthesis API, free. Cancels/restarts if a different answer is played mid-speech (no overlapping audio). Verified working.
- [x] Voice output on Lawyer's "Client summary" card (SearchPage.jsx) — labeled "Play for client." Verified working.
- [x] Voice output on Judge's Comparison page — labeled "Listen while reviewing." Verified working.
- [ ] FLAGGED FOR FUTURE WORK, NOT BUILDING NOW: regional language support (speak in Hindi/Tamil/etc., Gemini answers in that language, spoken back). Would be the strongest extension of Public's accessibility story — English-only voice still excludes much of the population the platform's own access-to-justice framing targets. Explicitly deferred because: (1) requires backend prompt changes to answer in the target language, (2) browser TTS voice availability for Indian languages is inconsistent across devices/OS (decent on some Android phones, often missing on desktop browsers). Write this up as an honest, well-reasoned limitation in the paper's future-work section, not a hidden gap.

### Image Upload
### Image Upload — Judge/Lawyer half complete, Public/Student half not started
- [x] Judge/Lawyer: image upload extends existing Document Upload — local Tesseract OCR (server-side, pytesseract + Pillow, in-memory only, never persisted — same privacy stance as PDF/TXT), extracted text flows through the EXISTING `find_related_judgments()` unchanged. Scoped to printed/typed/scanned text — handwriting explicitly out of scope and documented as such. Verified: real printed document → correct extraction + related judgment found + accurate summary; blank/low-content image → clear "no readable text" message instead of silent blank page; found-text-but-no-corpus-match → correct "no related judgments" state; handwritten note → OCR garbles it, and the summarizer correctly refuses to fabricate a legal summary from garbage text rather than hallucinating (good anti-hallucination evidence for the paper).
- [ ] Public/Student: DESIGN LOCKED, not yet built — different backend behavior than Judge/Lawyer's search-based flow. Image → OCR → new "explain this document" plain-language prompt (reuses Public's existing simplified-QA prompt style), NOT case-law search — corpus's narrow topic scope (murder/culpable homicide/private defence only) means most real-world documents a public user would upload (notices, letters) wouldn't meaningfully match anyway, so running them through search would be misleading rather than useful.
- [ ] OUT OF SCOPE, NOT BUILDING: actual visual evidence recognition (photos of weapons/injuries/crime scenes) — this is a fundamentally different computer-vision problem (scene/object description) than OCR (text extraction), a much larger undertaking, and ethically more sensitive given real forensic imagery. Document as explicit future-work-never in the paper, not a gap.

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