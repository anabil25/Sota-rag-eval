// Retrieval metrics — ported from retrieve-core/src/retrieve/eval/metrics.py.
// Pure functions (Recall@k, MRR@k, nDCG@k) with no external dependencies. The
// Python engine keeps its own copy for scoring runs; this TS port lets the
// SvelteKit app compute the same metrics natively (e.g. for client-side
// re-aggregation or future in-app scoring).

export interface RetrievalScores {
	recall_at_5: number;
	recall_at_10: number;
	mrr_at_10: number;
	ndcg_at_10: number;
}

/** Fraction of relevant items found in the top-k retrieved results. */
export function recallAtK(retrieved: string[], relevant: string[], k: number): number {
	if (relevant.length === 0) return 0.0;
	const topK = new Set(retrieved.slice(0, k));
	const relevantSet = new Set(relevant);
	let found = 0;
	for (const id of topK) {
		if (relevantSet.has(id)) found += 1;
	}
	return found / relevant.length;
}

/** Reciprocal rank of the first relevant result within the top-k. */
export function mrrAtK(retrieved: string[], relevant: string[], k: number): number {
	const relevantSet = new Set(relevant);
	const top = retrieved.slice(0, k);
	for (let i = 0; i < top.length; i += 1) {
		if (relevantSet.has(top[i])) return 1.0 / (i + 1);
	}
	return 0.0;
}

/** Normalized Discounted Cumulative Gain at k (binary relevance). */
export function ndcgAtK(retrieved: string[], relevant: string[], k: number): number {
	const relevantSet = new Set(relevant);

	// DCG — i+2 because log2(1) = 0.
	let dcg = 0.0;
	const top = retrieved.slice(0, k);
	for (let i = 0; i < top.length; i += 1) {
		if (relevantSet.has(top[i])) {
			dcg += 1.0 / Math.log2(i + 2);
		}
	}

	// Ideal DCG — all relevant items ranked at the top.
	const idealCount = Math.min(relevant.length, k);
	let idcg = 0.0;
	for (let i = 0; i < idealCount; i += 1) {
		idcg += 1.0 / Math.log2(i + 2);
	}

	if (idcg === 0) return 0.0;
	return dcg / idcg;
}

/** Compute all standard retrieval metrics for a single query. */
export function computeScores(retrieved: string[], relevant: string[]): RetrievalScores {
	return {
		recall_at_5: recallAtK(retrieved, relevant, 5),
		recall_at_10: recallAtK(retrieved, relevant, 10),
		mrr_at_10: mrrAtK(retrieved, relevant, 10),
		ndcg_at_10: ndcgAtK(retrieved, relevant, 10)
	};
}

/** Compute the mean of each metric across all queries. */
export function aggregateScores(allScores: RetrievalScores[]): RetrievalScores {
	if (allScores.length === 0) {
		return { recall_at_5: 0, recall_at_10: 0, mrr_at_10: 0, ndcg_at_10: 0 };
	}

	const keys: (keyof RetrievalScores)[] = [
		'recall_at_5',
		'recall_at_10',
		'mrr_at_10',
		'ndcg_at_10'
	];
	const result = {} as RetrievalScores;
	for (const key of keys) {
		const sum = allScores.reduce((acc, score) => acc + score[key], 0);
		result[key] = sum / allScores.length;
	}
	return result;
}
