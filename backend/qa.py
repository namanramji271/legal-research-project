"""
Citation-backed question answering over the judgment corpus.

Retrieves relevant judgment chunks via semantic search, asks Gemini to
answer strictly from that context, then verifies every case the model
cites actually appears in the retrieved source set before returning the
answer as "verified".
"""
import os
import re

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from google import genai
from pydantic import BaseModel

from search import search_judgments



load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY not found. Add it to backend/.env as "
        "GEMINI_API_KEY=your_key_here"
    )

# If this model name errors out, run list_models() (see bottom of file)
# to see what's currently available on your account/tier and swap it in.
MODEL_NAME = "gemini-2.5-flash"

client = genai.Client(api_key=GEMINI_API_KEY)
router = APIRouter()


class AskRequest(BaseModel):
    question: str
    n_results: int = 10


def build_prompt(question: str, chunks: list[dict]) -> str:
    context_blocks = []
    for i, chunk in enumerate(chunks, start=1):
        context_blocks.append(
            f"[Source {i}] Case: {chunk['case_name']} "
            f"({chunk['court']}, {chunk['year']}) — IPC: {chunk['ipc_sections']}\n"
            f"{chunk['snippet']}"
        )
    context_text = "\n\n".join(context_blocks)

    return f"""You are a legal research assistant. Answer the question below
using ONLY the context provided. Every claim you make must be traceable to
one of the sources listed. When you refer to a case, use its exact case
name as given in the context (e.g. "ILDC case 1970_1"), do not paraphrase
or invent case names.

If the context does not contain enough information to answer the question,
say so explicitly rather than guessing or using outside knowledge.

Context:
{context_text}

Question: {question}

Answer:"""


def extract_cited_cases(answer_text: str, known_case_names: list[str]) -> list[str]:
    """Find which known case names are actually mentioned in the answer,
    each returned once, in the order they first appear in the text."""
    mentions = []
    for name in known_case_names:
        if name in answer_text and name not in mentions:
            mentions.append(name)
    return mentions


def find_unverifiable_citations(answer_text: str, known_case_names: list[str]) -> list[str]:
    """
    Look for things that look like case references in the answer text but
    don't match any of the retrieved source case names. Catches patterns
    like 'ILDC case 1999_12' that weren't actually in our retrieved context.
    """
    mentioned_ilcd_style = set(re.findall(r"ILDC case \d{4}_\d+", answer_text))
    known_set = set(known_case_names)
    return sorted(mentioned_ilcd_style - known_set)


def ask_question(question: str, n_results: int = 5) -> dict:
    chunks = search_judgments(question, n_results=n_results)

    if not chunks:
        return {
            "answer": "No relevant judgments were found in the corpus for this question.",
            "verified": False,
            "sources_used": [],
            "unverified_citations": [],
        }

    prompt = build_prompt(question, chunks)

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
    )
    answer_text = response.text

    known_case_names = [c["case_name"] for c in chunks]
    cited_cases = extract_cited_cases(answer_text, known_case_names)
    unverified = find_unverifiable_citations(answer_text, known_case_names)

    return {
        "answer": answer_text,
        "verified": len(unverified) == 0,
        "sources_used": cited_cases,
        "unverified_citations": unverified,
        "retrieved_sources": known_case_names,
    }


@router.post("/ask")
def ask(request: AskRequest):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    return ask_question(request.question, request.n_results)


# --- Utility: run this directly if MODEL_NAME above ever errors out ---
# python -c "from qa import list_models; list_models()"
def list_models():
    for m in client.models.list():
        print(m.name)