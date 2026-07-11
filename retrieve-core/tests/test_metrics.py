"""Tests for eval/metrics.py — retrieval metric calculators."""

import math

import pytest

from retrieve.eval.metrics import (
    aggregate_scores,
    compute_scores,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
)


class TestRecallAtK:
    def test_perfect_recall(self):
        assert recall_at_k(["a", "b", "c"], ["a", "b"], 5) == 1.0

    def test_partial_recall(self):
        assert recall_at_k(["a", "b", "c"], ["a", "d"], 5) == 0.5

    def test_no_recall(self):
        assert recall_at_k(["a", "b", "c"], ["d", "e"], 5) == 0.0

    def test_recall_respects_k(self):
        # "b" is at position 2, but k=1 only looks at first
        assert recall_at_k(["a", "b"], ["b"], 1) == 0.0
        assert recall_at_k(["a", "b"], ["b"], 2) == 1.0

    def test_empty_relevant(self):
        assert recall_at_k(["a", "b"], [], 5) == 0.0

    def test_empty_retrieved(self):
        assert recall_at_k([], ["a", "b"], 5) == 0.0

    def test_multiple_relevant_partial(self):
        assert recall_at_k(["a", "b", "c", "d", "e"], ["a", "c", "f"], 5) == pytest.approx(2 / 3)


class TestMRRAtK:
    def test_first_position(self):
        assert mrr_at_k(["a", "b", "c"], ["a"], 10) == 1.0

    def test_second_position(self):
        assert mrr_at_k(["a", "b", "c"], ["b"], 10) == 0.5

    def test_third_position(self):
        assert mrr_at_k(["a", "b", "c"], ["c"], 10) == pytest.approx(1 / 3)

    def test_not_found(self):
        assert mrr_at_k(["a", "b", "c"], ["d"], 10) == 0.0

    def test_respects_k(self):
        assert mrr_at_k(["a", "b", "c"], ["c"], 2) == 0.0  # c at pos 3, k=2
        assert mrr_at_k(["a", "b", "c"], ["c"], 3) == pytest.approx(1 / 3)

    def test_multiple_relevant_takes_first(self):
        # MRR only cares about first relevant hit
        assert mrr_at_k(["a", "b", "c"], ["b", "c"], 10) == 0.5


class TestNDCGAtK:
    def test_perfect_single(self):
        ndcg = ndcg_at_k(["a"], ["a"], 10)
        assert ndcg == pytest.approx(1.0)

    def test_perfect_multiple(self):
        ndcg = ndcg_at_k(["a", "b"], ["a", "b"], 10)
        assert ndcg == pytest.approx(1.0)

    def test_wrong_order(self):
        # Both relevant but "b" should ideally be first
        ndcg = ndcg_at_k(["x", "a"], ["a"], 10)
        # DCG = 1/log2(3) ≈ 0.63, IDCG = 1/log2(2) = 1.0
        expected = (1 / math.log2(3)) / (1 / math.log2(2))
        assert ndcg == pytest.approx(expected)

    def test_no_relevant(self):
        assert ndcg_at_k(["a", "b"], ["x"], 10) == 0.0

    def test_empty_relevant(self):
        assert ndcg_at_k(["a", "b"], [], 10) == 0.0

    def test_empty_retrieved(self):
        assert ndcg_at_k([], ["a"], 10) == 0.0

    def test_respects_k(self):
        # Relevant item at position 3, but k=2
        assert ndcg_at_k(["x", "y", "a"], ["a"], 2) == 0.0
        assert ndcg_at_k(["x", "y", "a"], ["a"], 3) > 0.0


class TestComputeScores:
    def test_perfect_retrieval(self):
        scores = compute_scores(["a", "b", "c"], ["a"])
        assert scores["recall_at_5"] == 1.0
        assert scores["recall_at_10"] == 1.0
        assert scores["mrr_at_10"] == 1.0
        assert scores["ndcg_at_10"] == pytest.approx(1.0)

    def test_all_keys_present(self):
        scores = compute_scores(["a"], ["b"])
        assert set(scores.keys()) == {"recall_at_5", "recall_at_10", "mrr_at_10", "ndcg_at_10"}


class TestAggregateScores:
    def test_single_run(self):
        agg = aggregate_scores([{"recall_at_5": 0.8, "mrr_at_10": 0.5}])
        assert agg["recall_at_5"] == 0.8
        assert agg["mrr_at_10"] == 0.5

    def test_multiple_runs(self):
        agg = aggregate_scores(
            [
                {"recall_at_5": 1.0, "mrr_at_10": 0.5},
                {"recall_at_5": 0.0, "mrr_at_10": 1.0},
            ]
        )
        assert agg["recall_at_5"] == pytest.approx(0.5)
        assert agg["mrr_at_10"] == pytest.approx(0.75)

    def test_empty_list(self):
        agg = aggregate_scores([])
        assert agg["recall_at_5"] == 0
        assert agg["ndcg_at_10"] == 0
