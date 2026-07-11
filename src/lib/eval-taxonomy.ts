import type { EvalSet } from '$lib/api/types';

export type RetrievalAxis =
	| 'Lexical vs semantic'
	| 'Reasoning scope'
	| 'Precision'
	| 'Structure'
	| 'Robustness'
	| 'Temporal'
	| 'From eval questions';

export interface EvalTaxonomyItem {
	id: string;
	label: string;
	axis: RetrievalAxis;
	description: string;
}

// First-principles eval taxonomy: each category earns its slot by discriminating
// between retrieval architectures, not by mirroring labels from one eval set.
export const CANONICAL_EVAL_TAXONOMY: EvalTaxonomyItem[] = [
	{
		id: 'exact_term',
		label: 'exact_term',
		axis: 'Lexical vs semantic',
		description:
			'Literal terms, codes, dates, or numbers in the document wording. Rewards keyword/BM25; pure vector search can miss it.'
	},
	{
		id: 'paraphrase',
		label: 'paraphrase',
		axis: 'Lexical vs semantic',
		description:
			'User wording differs from the source text. Rewards vector and semantic retrieval; keyword-only search can miss it.'
	},
	{
		id: 'single_fact',
		label: 'single_fact',
		axis: 'Reasoning scope',
		description: 'Answer sits in one passage. Baseline control most architectures should pass.'
	},
	{
		id: 'multi_hop',
		label: 'multi_hop',
		axis: 'Reasoning scope',
		description:
			'Answer requires chaining two or more passages or documents. Rewards graph and hierarchical retrieval.'
	},
	{
		id: 'thematic_global',
		label: 'thematic_global',
		axis: 'Reasoning scope',
		description:
			'Themes or summaries span the whole corpus. Separates global/GraphRAG-style approaches from flat top-k retrieval.'
	},
	{
		id: 'disambiguation',
		label: 'disambiguation',
		axis: 'Precision',
		description:
			'Many near-identical passages exist; the system must pick the exactly-right one. Tests precision and re-ranking.'
	},
	{
		id: 'tabular_numeric',
		label: 'tabular_numeric',
		axis: 'Structure',
		description:
			'Answer lives in a table or needs threshold/date math. Tests table-aware chunking and extraction.'
	},
	{
		id: 'negation_exception',
		label: 'negation_exception',
		axis: 'Robustness',
		description:
			'Asks what is prohibited, excluded, or when a rule does not apply. Hard for similarity-only retrieval.'
	},
	{
		id: 'unanswerable',
		label: 'unanswerable',
		axis: 'Robustness',
		description:
			'No answer exists in the corpus; correct behavior is a grounded refusal. Guards against hallucination.'
	},
	{
		id: 'temporal_version',
		label: 'temporal_version',
		axis: 'Temporal',
		description:
			'Which version or effective date of a policy applies. Tests superseded and time-bound content.'
	}
];

export function getEvalTaxonomyItem(id: string): EvalTaxonomyItem {
	return (
		CANONICAL_EVAL_TAXONOMY.find((item) => item.id === id) ?? {
			id,
			label: id,
			axis: 'From eval questions',
			description: ''
		}
	);
}

export function evalTaxonomyWithCustom(
	values: Array<string | null | undefined>
): EvalTaxonomyItem[] {
	return [...new Set(values)]
		.filter((value): value is string => Boolean(value))
		.sort()
		.map(getEvalTaxonomyItem);
}

export function parseEvalCategoryCounts(
	counts: EvalSet['category_counts']
): Record<string, number> {
	if (!counts) return {};
	if (typeof counts !== 'string') return counts;

	try {
		const parsed = JSON.parse(counts) as unknown;
		if (typeof parsed !== 'object' || parsed === null) return {};

		return Object.fromEntries(
			Object.entries(parsed).flatMap(([key, value]) =>
				typeof value === 'number' ? [[key, value]] : []
			)
		);
	} catch (error) {
		console.warn('Unable to parse eval set category counts', error);
		return {};
	}
}

export function evalSetCategoryEntries(evalSet: EvalSet) {
	return Object.entries(parseEvalCategoryCounts(evalSet.category_counts))
		.sort(([, left], [, right]) => right - left)
		.map(([id, count]) => ({ ...getEvalTaxonomyItem(id), count }));
}
