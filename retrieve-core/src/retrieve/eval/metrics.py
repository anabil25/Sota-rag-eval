"""Retrieval metrics — Recall@k, MRR@10, nDCG@10."""

from __future__ import annotations

import math


def recall_at_k(retrieved: list[str], relevant: list[str], k: int) -> float:
    """Fraction of relevant items found in the top-k retrieved results."""
    if not relevant:
        return 0.0
    top_k = set(retrieved[:k])
    found = len(top_k & set(relevant))
    return found / len(relevant)


def mrr_at_k(retrieved: list[str], relevant: list[str], k: int) -> float:
    """Mean Reciprocal Rank — reciprocal rank of the first relevant result in top-k."""
    relevant_set = set(relevant)
    for i, doc_id in enumerate(retrieved[:k]):
        if doc_id in relevant_set:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(retrieved: list[str], relevant: list[str], k: int) -> float:
    """Normalized Discounted Cumulative Gain at k."""
    relevant_set = set(relevant)

    # DCG
    dcg = 0.0
    for i, doc_id in enumerate(retrieved[:k]):
        if doc_id in relevant_set:
            dcg += 1.0 / math.log2(i + 2)  # i+2 because log2(1) = 0

    # Ideal DCG — all relevant items at the top
    ideal_count = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_count))

    if idcg == 0:
        return 0.0
    return dcg / idcg


def compute_scores(retrieved: list[str], relevant: list[str]) -> dict[str, float]:
    """Compute all standard retrieval metrics for a single query."""
    return {
        "recall_at_5": recall_at_k(retrieved, relevant, 5),
        "recall_at_10": recall_at_k(retrieved, relevant, 10),
        "mrr_at_10": mrr_at_k(retrieved, relevant, 10),
        "ndcg_at_10": ndcg_at_k(retrieved, relevant, 10),
    }


def aggregate_scores(all_scores: list[dict[str, float]]) -> dict[str, float]:
    """Compute mean of each metric across all queries."""
    if not all_scores:
        return {"recall_at_5": 0, "recall_at_10": 0, "mrr_at_10": 0, "ndcg_at_10": 0}

    keys = all_scores[0].keys()
    return {k: sum(s[k] for s in all_scores) / len(all_scores) for k in keys}
