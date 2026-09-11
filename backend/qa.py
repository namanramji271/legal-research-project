"""
Citation-backed question answering over the judgment corpus.

Retrieves relevant judgment chunks via semantic search, asks Gemini to
answer strictly from that context, then verifies every case the model
cites actually appears in the retrieved source set before returning the
answer as "verified".
"""
import os
import re
import time

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


class ConversationTurn(BaseModel):
    question: str
    answer: str


class AskRequest(BaseModel):
    question: str
    n_results: int = 10
    persona: str | None = None
    conversation_history: list[ConversationTurn] = []


MAX_HISTORY_TURNS = 5  # cap forwarded to Gemini; older turns stay in the UI only

PERSONA_INSTRUCTIONS = {
    "student": (
        "\n\nAfter answering, add a section titled 'Why this matters:' that "
        "explains the underlying legal principle in plain terms suitable for "
        "someone learning the law for the first time."
    ),
    "public": (
        "\n\nWrite the answer in plain, everyday English suitable for someone "
        "with no legal background. Do not use legal jargon. Do not mention "
        "case names, section numbers, or court names in your answer text "
        "itself - explain the underlying idea in plain terms instead."
    ),
}


def build_prompt(
    question: str,
    chunks: list[dict],
    persona: str | None = None,
    conversation_history: list[ConversationTurn] | None = None,
) -> str:
    context_blocks = []
    for i, chunk in enumerate(chunks, start=1):
        context_blocks.append(
            f"[Source {i}] Case: {chunk['case_name']} "
            f"({chunk['court']}, {chunk['year']}) — IPC: {chunk['ipc_sections']}\n"
            f"{chunk['snippet']}"
        )
    context_text = "\n\n".join(context_blocks)

    history_block = ""
    if conversation_history:
        recent_turns = conversation_history[-MAX_HISTORY_TURNS:]
        history_lines = [
            f"Q: {turn.question}\nA: {turn.answer}" for turn in recent_turns
        ]
        history_block = (
            "\n\nPrevious conversation in this session (for context only - "
            "still answer strictly from the Context below, not from memory "
            "of these prior answers):\n" + "\n\n".join(history_lines)
        )

    persona_instructions = PERSONA_INSTRUCTIONS.get(persona, "")

    return f"""You are a legal research assistant. Answer the question below
using ONLY the context provided. Every claim you make must be traceable to
one of the sources listed. When you refer to a case, use its exact case
name as given in the context (e.g. "ILDC case 1970_1"), do not paraphrase
or invent case names.

If the context does not contain enough information to answer the question,
say so explicitly rather than guessing or using outside knowledge.{persona_instructions}
{history_block}

Context:
{context_text}

Question: {question}

Answer:"""


def extract_cited_cases(answer_text: str, known_case_names: list[str]) -> list[str]:
    """Find which known case names are actually mentioned in the answer,
    each returned once, in the order they first appear in the text."""
    mentions: list[tuple[int, str]] = []
    seen_case_names: set[str] = set()
    for name in known_case_names:
        if name in seen_case_names:
            continue
        seen_case_names.add(name)
        position = answer_text.find(name)
        if position >= 0:
            mentions.append((position, name))
    return [name for _position, name in sorted(mentions)]


def find_unverifiable_citations(answer_text: str, known_case_names: list[str]) -> list[str]:
    """
    Look for things that look like case references in the answer text but
    don't match any of the retrieved source case names. Catches patterns
    like 'ILDC case 1999_12' that weren't actually in our retrieved context.
    """
    mentioned_ilcd_style = set(re.findall(r"ILDC case \d{4}_\d+", answer_text))
    known_set = set(known_case_names)
    return sorted(mentioned_ilcd_style - known_set)


def _call_gemini_with_retry(prompt: str):
    last_error = None
    for attempt in range(2):
        try:
            return client.models.generate_content(model=MODEL_NAME, contents=prompt)
        except Exception as error:
            last_error = error
            time.sleep(2)
    raise HTTPException(
        status_code=503,
        detail="The AI answering service is temporarily unavailable. Please try again in a moment.",
    ) from last_error


def _build_retrieval_query(question: str, conversation_history: list[ConversationTurn] | None) -> str:
    """For vague follow-ups ('give an example', 'why?'), the raw question
    alone often lacks enough legal vocabulary for retrieval to match
    anything. Anchor retrieval with the most recent prior question's text
    too, so follow-ups inherit that topic's search terms. Does not affect
    what's shown to the user or sent to Gemini as 'the question' - only
    what's used to find source chunks."""
    if not conversation_history:
        return question
    last_question = conversation_history[-1].question
    return f"{last_question} {question}"


def ask_question(
    question: str,
    n_results: int = 5,
    persona: str | None = None,
    conversation_history: list[ConversationTurn] | None = None,
) -> dict:
    retrieval_query = _build_retrieval_query(question, conversation_history)
    chunks = search_judgments(retrieval_query, n_results=n_results)

    if not chunks:
        return {
            "answer": "No relevant judgments were found in the corpus for this question.",
            "verified": False,
            "sources_used": [],
            "unverified_citations": [],
        }

    prompt = build_prompt(question, chunks, persona=persona, conversation_history=conversation_history)

    response = _call_gemini_with_retry(prompt)
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
    return ask_question(
        request.question,
        request.n_results,
        persona=request.persona,
        conversation_history=request.conversation_history,
    )


# --- Utility: run this directly if MODEL_NAME above ever errors out ---
# python -c "from qa import list_models; list_models()"
def list_models():
    for m in client.models.list():
        print(m.name)
