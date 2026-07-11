import { describe, expect, it } from 'vitest';
import {
	aggregateScores,
	computeScores,
	mrrAtK,
	ndcgAtK,
	recallAtK,
	type RetrievalScores
} from './metrics';

describe('retrieval metrics (parity with Python eval/metrics.py)', () => {
	const retrieved = ['a', 'b', 'c', 'd', 'e', 'f'];
	const relevant = ['c', 'f', 'z'];

	it('matches the Python compute_scores reference values', () => {
		// Reference produced by retrieve.eval.metrics.compute_scores in Python.
		const scores = computeScores(retrieved, relevant);
		expect(scores.recall_at_5).toBeCloseTo(0.3333333333333333, 12);
		expect(scores.recall_at_10).toBeCloseTo(0.6666666666666666, 12);
		expect(scores.mrr_at_10).toBeCloseTo(0.3333333333333333, 12);
		expect(scores.ndcg_at_10).toBeCloseTo(0.40179981797758046, 12);
	});

	it('recallAtK returns 0 when there are no relevant items', () => {
		expect(recallAtK(retrieved, [], 10)).toBe(0);
	});

	it('mrrAtK uses the first relevant rank only', () => {
		expect(mrrAtK(['x', 'y', 'a'], ['a', 'y'], 10)).toBeCloseTo(1 / 2, 12);
		expect(mrrAtK(['x', 'y', 'z'], ['a'], 10)).toBe(0);
	});

	it('ndcgAtK is 1.0 when relevant items are perfectly ranked', () => {
		expect(ndcgAtK(['a', 'b', 'c'], ['a', 'b'], 10)).toBeCloseTo(1.0, 12);
		expect(ndcgAtK(['a'], [], 10)).toBe(0);
	});

	it('aggregateScores averages each metric and handles the empty case', () => {
		const a: RetrievalScores = { recall_at_5: 1, recall_at_10: 1, mrr_at_10: 1, ndcg_at_10: 1 };
		const b: RetrievalScores = { recall_at_5: 0, recall_at_10: 0, mrr_at_10: 0, ndcg_at_10: 0 };
		expect(aggregateScores([a, b])).toEqual({
			recall_at_5: 0.5,
			recall_at_10: 0.5,
			mrr_at_10: 0.5,
			ndcg_at_10: 0.5
		});
		expect(aggregateScores([])).toEqual({
			recall_at_5: 0,
			recall_at_10: 0,
			mrr_at_10: 0,
			ndcg_at_10: 0
		});
	});
});
