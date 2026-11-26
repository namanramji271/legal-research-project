"""Decline detection over real Gemini phrasings from the QA v2 cache.

The cache itself is gitignored, so the relevant sentences are copied here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from eval.refusal_patterns import is_insufficient_context  # noqa: E402


@pytest.mark.parametrize(
    "answer",
    [
        # Q10 (GST), the false negative that motivated the new pattern.
        "Based on the provided context, there is no information about how the "
        "Goods and Services Tax (GST) is calculated for a small business in India.",
        # Q8 full, same idea with "regarding".
        "Based on the provided context, there is no information regarding the "
        "factors that determine whether a death penalty or life imprisonment is "
        "awarded for murder under IPC Section 302.",
        "There is no information on bail under the NDPS Act in the context.",
        # Phrasings the original patterns already caught.
        "Based on the provided context, there is not enough information to answer "
        "how culpable homicide is defined under IPC Section 299.",
        "The provided context does not contain information regarding divorce.",
        "No relevant judgments were found for this question.",
        "",
        None,
    ],
)
def test_declines_are_detected(answer):
    assert is_insufficient_context(answer) is True


@pytest.mark.parametrize(
    "answer",
    [
        "Based on the provided context, a person can use force in private defence "
        "of person or property under the following circumstances:",
        # Partial answer that hedges but still answers; must not count as a decline.
        "Based on the provided context, the exact provisions specifying when the "
        "right of private defence of property arises under the IPC are not fully "
        "detailed (as text segments are truncated). However, the context provides "
        "the following relevant principles:",
        "Based on ILDC case 1964_288, Section 301 of the Indian Penal Code (IPC) "
        "applies as follows when a person other than the intended victim is killed:",
    ],
)
def test_answers_are_not_declines(answer):
    assert is_insufficient_context(answer) is False
