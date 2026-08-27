"""Evaluate grounded QA behavior against labeled corpus-coverage questions.

Run from the repository root with:
    python backend/eval/evaluate_qa.py
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
QUESTIONS_PATH = Path(__file__).with_name("test_qa_questions.json")
INSUFFICIENT_CONTEXT_PATTERNS = (
    r"no relevant judgments were found",
    r"not enough information",
    r"insufficient information",
    r"does not contain (?:enough )?information",
    r"do not contain (?:enough )?information",
    r"cannot answer.*(?:context|information|sources)",
    r"unable to answer.*(?:context|information|sources)",
)

# qa.py uses imports relative to the backend directory.
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from qa import ask_question  # noqa: E402


def _is_insufficient_context(answer: Any) -> bool:
    """Identify an empty or explicit insufficient-context response."""
    answer_text = str(answer or "").strip()
    if not answer_text:
        return True
    return any(
        re.search(pattern, answer_text, flags=re.IGNORECASE | re.DOTALL)
        for pattern in INSUFFICIENT_CONTEXT_PATTERNS
    )


def _response_summary(response: dict[str, Any]) -> str:
    """Produce a one-line preview without printing the full model response."""
    answer = " ".join(str(response.get("answer", "")).split())
    return answer if len(answer) <= 160 else f"{answer[:157]}..."


def main() -> None:
    """Run QA evaluation and report verification and refusal behavior."""
    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    verification_matches = 0
    context_behavior_matches = 0
    overall_matches = 0
    total_unverified_citations = 0
    api_errors = 0

    for index, entry in enumerate(questions, start=1):
        question = entry["question"]
        expected_answerable = bool(entry["expected_answerable"])
        try:
            response = ask_question(question)
        except Exception as error:
            api_errors += 1
            print(f"{index}. {question}")
            print(
                "   "
                f"WARNING: API error for question {index} "
                f"({type(error).__name__}); skipping."
            )
            if index < len(questions):
                time.sleep(15)
            continue

        verified = bool(response.get("verified", False))
        insufficient_context = _is_insufficient_context(response.get("answer"))
        unverified_citations = response.get("unverified_citations") or []
        verification_match = verified is True
        context_behavior_match = insufficient_context != expected_answerable
        overall_match = verification_match and context_behavior_match

        verification_matches += verification_match
        context_behavior_matches += context_behavior_match
        overall_matches += overall_match
        total_unverified_citations += len(unverified_citations)

        print(f"{index}. {question}")
        print(
            "   "
            f"expected_answerable={expected_answerable} "
            f"verified={verified} "
            f"insufficient_context={insufficient_context}"
        )
        print(
            "   "
            f"no_fabricated_citations={verification_match} "
            f"context_behavior_match={context_behavior_match} "
            f"overall_match={overall_match}"
        )
        print(
            "   "
            f"unverified_citations={len(unverified_citations)} "
            f"retrieved_sources={len(response.get('retrieved_sources') or [])}"
        )
        print(f"   answer_preview={_response_summary(response)}")

        if index < len(questions):
            time.sleep(15)

    question_count = len(questions)
    completed_questions = question_count - api_errors
    print("\nSummary")
    print("| Metric | Result |")
    print("| --- | ---: |")
    print(f"| Questions attempted | {question_count} |")
    print(f"| Questions completed | {completed_questions} |")
    print(f"| API errors | {api_errors} |")
    print(
        "| Responses with no fabricated citations "
        f"| {verification_matches}/{completed_questions} |"
    )
    print(
        "| Insufficient-context behavior matches "
        f"| {context_behavior_matches}/{completed_questions} |"
    )
    print(f"| Overall matches | {overall_matches}/{completed_questions} |")
    average_unverified_citations = (
        total_unverified_citations / completed_questions
        if completed_questions
        else 0.0
    )
    print(f"| Average unverified citations per response | {average_unverified_citations:.3f} |")


if __name__ == "__main__":
    main()
