"""Explainability metadata for judgment retrieval results."""

from __future__ import annotations

import re
from typing import Any

STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "can't", "cannot", "could",
    "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down",
    "during", "each", "few", "for", "from", "further", "had", "hadn't", "has",
    "hasn't", "have", "haven't", "having", "he", "her", "here", "hers", "herself",
    "him", "himself", "his", "how", "i", "if", "in", "into", "is", "isn't", "it",
    "its", "itself", "me", "more", "most", "must", "my", "myself", "no", "nor",
    "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our",
    "ours", "ourselves", "out", "over", "own", "same", "she", "should", "shouldn't",
    "so", "some", "such", "than", "that", "the", "their", "theirs", "them",
    "themselves", "then", "there", "these", "they", "this", "those", "through",
    "to", "too", "under", "until", "up", "very", "was", "wasn't", "we", "were",
    "weren't", "what", "when", "where", "which", "while", "who", "whom", "why",
    "with", "won't", "would", "wouldn't", "you", "your", "yours", "yourself",
    "yourselves",
}

TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9]+")


def compute_match_explanation(
    query: str,
    case_name: str,
    snippet: str,
    dense_case_names: list[str],
    bm25_case_names: list[str],
) -> dict[str, Any]:
    """Compute retrieval explainability metadata for a single case result.

    This function reuses the project's empirical evaluation findings
    (where BM25 keyword retrieval outperformed dense MiniLM and naive RRF
    hybrid retrieval on this corpus — see backend/eval/hybrid_search_findings.md)
    as the basis for treating cross-method agreement as a confidence signal.
    When both dense semantic search and BM25 lexical search surface the same
    case independently, it represents a high-confidence consensus match.
    """
    in_dense = case_name in dense_case_names
    in_bm25 = case_name in bm25_case_names

    matched_methods: list[str] = []
    if in_dense:
        matched_methods.append("dense")
    if in_bm25:
        matched_methods.append("bm25")

    if in_dense and in_bm25:
        relevance_label = "Strong match"
    elif in_dense or in_bm25:
        relevance_label = "Moderate match"
    else:
        relevance_label = "Weak match"

    snippet_lower = snippet.lower()
    matched_terms: list[str] = []
    seen_terms: set[str] = set()

    for match in TOKEN_PATTERN.finditer(query):
        term = match.group().lower()
        if len(term) <= 1 or term in STOPWORDS:
            continue
        if term not in seen_terms and term in snippet_lower:
            seen_terms.add(term)
            matched_terms.append(term)
            if len(matched_terms) == 8:
                break

    return {
        "matched_methods": matched_methods,
        "matched_terms": matched_terms,
        "relevance_label": relevance_label,
    }
