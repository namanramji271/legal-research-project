"""Shared detection of insufficient-context (decline) answers for QA evals.

Both evaluate_qa.py and evaluate_qa_v2.py import from here so the patterns
cannot drift apart. Only add a pattern when a real cached or logged answer
shows the phrasing; test it in backend/tests/test_refusal_patterns.py.
"""

from __future__ import annotations

import re
from typing import Any

INSUFFICIENT_CONTEXT_PATTERNS = (
    r"no relevant judgments were found",
    r"not enough information",
    r"insufficient information",
    r"does not contain (?:enough )?information",
    r"do not contain (?:enough )?information",
    r"cannot answer.*(?:context|information|sources)",
    r"unable to answer.*(?:context|information|sources)",
    # Added after QA v2 Q10 (GST): "there is no information about/regarding ...".
    r"\bno information (?:about|on|regarding)\b",
)


def is_insufficient_context(answer: Any) -> bool:
    """Identify an empty or explicit insufficient-context response."""
    answer_text = str(answer or "").strip()
    if not answer_text:
        return True
    return any(
        re.search(pattern, answer_text, flags=re.IGNORECASE | re.DOTALL)
        for pattern in INSUFFICIENT_CONTEXT_PATTERNS
    )
