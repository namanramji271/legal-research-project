# IPC–BNS Legal Research

An AI-assisted legal research platform for Indian law, built as a final-year project.
It maps IPC sections to their BNS counterparts and retrieves related Indian judgments.
It provides citation-backed question answering with a citation verification safeguard.

## Requirements

- Python 3.13 (tested on 3.13.3; Python 3.15 currently fails because onnxruntime has no builds for it)
- Node.js and npm
- Tesseract OCR for image uploads (optional for PDF/TXT and other features)
- A Gemini API key and a long random JWT secret for the backend

## Setup

Create a Python virtual environment from the repository root.

**Windows (PowerShell):**

```powershell
py -m venv backend/venv
backend/venv/Scripts/Activate.ps1
pip install -r backend/requirements.txt
```

PowerShell may block `Activate.ps1` under its execution policy. Git Bash users can
activate the same environment with:

```sh
source backend/venv/Scripts/activate
```

**macOS:**

```sh
python3 -m venv backend/venv
source backend/venv/bin/activate
pip install -r backend/requirements.txt
```

Install Tesseract if you want image OCR. On Windows, install the Tesseract OCR
package and set `TESSERACT_CMD` if it is not available on `PATH`. On macOS,
install it with `brew install tesseract`. PDF and text upload do not require it.

Copy `.env.example` to `backend/.env` and set `GEMINI_API_KEY` and
`JWT_SECRET_KEY`. `HF_TOKEN` is only needed when regenerating the gated corpus.
Set `TESSERACT_CMD` only when Tesseract is not discoverable on `PATH` or at the
Windows default location.

Install frontend dependencies:

```sh
cd frontend
npm ci
```

## Regenerate local data

The judgment corpus and ChromaDB indexes are intentionally gitignored. From the
repository root, activate the Python virtual environment, then install the
corpus-build dependency:

```sh
pip install -r backend/requirements-dev.txt
```

Accept the gated IL-TUR/ILDC dataset conditions on Hugging Face and provide your
own access token as `HF_TOKEN`. Then build the corpus first and the embeddings
second:

```sh
cd backend
python scripts/build_corpus.py
python scripts/build_embeddings.py
```

`build_corpus.py` writes `data/judgments.jsonl`; `build_embeddings.py` reads it
and creates `data/chroma_db/`. The retrieval evaluations require this built index. The first
model run downloads about 2.3 GB of models. The BGE-M3 comparison additionally
requires `python scripts/build_embeddings_bge.py` from `backend/`; on CPU this
takes about 40 minutes. Mapping data is sourced from
`data/ipc_bns_mapping.csv`; `mapping.db` is generated automatically by the
backend at startup.

## Run the app

Start the backend from `backend/` with the virtual environment active:

```sh
uvicorn main:app --reload
```

Start the frontend in another terminal:

```sh
cd frontend
npm run dev
```

## Evaluation

Run the backend tests from the repository root:

```sh
pytest backend/tests
```

Run the offline retrieval evaluations from `backend/`:

```sh
python eval/evaluate_retrieval.py
python eval/evaluate_retrieval_comparison.py
python eval/evaluate_retrieval_hybrid.py
```

The QA evaluation calls Gemini and consumes API quota. Run it from `backend/`
only when you have quota available; it paces requests and records results in
`eval/qa_findings.md`:

```sh
python eval/evaluate_qa.py
```

## Retrieval settings

`RETRIEVER` selects the production retriever for `/search` and `/ask`; it
defaults to `bm25` and also accepts `dense` or `hybrid`. `BM25_MIN_SCORE` sets
the minimum BM25 score when BM25 is active and defaults to `0`. See
[`CLAUDE.md`](CLAUDE.md) for the retrieval configuration and behavior details.
