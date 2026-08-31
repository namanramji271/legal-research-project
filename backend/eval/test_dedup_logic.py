"""Standalone regression check for QA source-citation deduplication.

Run from the repository root with:
    python backend/eval/test_dedup_logic.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Importing qa.py creates the Gemini client, but this test never calls it.
os.environ["GEMINI_API_KEY"] = "test-key"

from qa import extract_cited_cases  # noqa: E402


def main() -> None:
    """Assert that repeated answer citations are unique and answer-ordered."""
    first_case = "ILDC case 1978_213"
    second_case = "ILDC case 1964_288"
    answer_text = (
        f"{first_case} establishes the principle. {second_case} applies it. "
        f"The reasoning in {first_case} is reaffirmed."
    )
    known_case_names = [second_case, first_case, first_case]
    expected_sources_used = [first_case, second_case]

    actual_sources_used = extract_cited_cases(answer_text, known_case_names)
    if actual_sources_used != expected_sources_used:
        print("FAIL: sources_used was not deduplicated in answer occurrence order")
        print(f"Expected: {expected_sources_used}")
        print(f"Actual:   {actual_sources_used}")
        raise SystemExit(1)

    print("PASS: sources_used is deduplicated in first-occurrence order")


if __name__ == "__main__":
    main()
