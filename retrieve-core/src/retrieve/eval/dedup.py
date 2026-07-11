"""Semantic deduplication — detect near-duplicate questions via text similarity.

Uses difflib.SequenceMatcher for local dedup (no embedding model required).
When an embedding endpoint is available, falls back to cosine similarity
for higher-quality semantic matching.
"""

from __future__ import annotations

import logging
from difflib import SequenceMatcher
from typing import Any

log = logging.getLogger(__name__)


def find_near_duplicates(
    questions: list[dict[str, Any]],
    threshold: float = 0.90,
    key_field: str = "question",
) -> list[tuple[int, int, float]]:
    """Find near-duplicate question pairs using text similarity.

    Args:
        questions: List of question dicts with a text field.
        threshold: Similarity threshold (0.0-1.0). Pairs above this are duplicates.
        key_field: Dict key containing the question text.

    Returns:
        List of (index_i, index_j, similarity) tuples for duplicate pairs.
    """
    texts = [q.get(key_field, "").strip().lower() for q in questions]
    duplicates: list[tuple[int, int, float]] = []

    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if not texts[i] or not texts[j]:
                continue
            # Quick length check — very different lengths can't be near-duplicates
            len_ratio = min(len(texts[i]), len(texts[j])) / max(len(texts[i]), len(texts[j]))
            if len_ratio < 0.5:
                continue
            sim = SequenceMatcher(None, texts[i], texts[j]).ratio()
            if sim >= threshold:
                duplicates.append((i, j, sim))

    return duplicates


def deduplicate_questions(
    questions: list[dict[str, Any]],
    threshold: float = 0.90,
    key_field: str = "question",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Remove near-duplicate questions, keeping the first occurrence.

    Args:
        questions: List of question dicts.
        threshold: Similarity threshold for dedup.
        key_field: Dict key containing the question text.

    Returns:
        Tuple of (kept_questions, removed_questions).
    """
    if not questions:
        return [], []

    duplicates = find_near_duplicates(questions, threshold, key_field)

    # Build set of indices to remove (keep the earlier occurrence)
    to_remove: set[int] = set()
    for i, j, sim in duplicates:
        if i not in to_remove:
            to_remove.add(j)
            log.debug(
                "Near-duplicate (%.2f): '%s' ≈ '%s'",
                sim,
                questions[i].get(key_field, "")[:60],
                questions[j].get(key_field, "")[:60],
            )

    kept = [q for idx, q in enumerate(questions) if idx not in to_remove]
    removed = [q for idx, q in enumerate(questions) if idx in to_remove]

    if removed:
        log.info(
            "Semantic dedup: removed %d near-duplicate questions (threshold=%.2f)",
            len(removed),
            threshold,
        )

    return kept, removed
