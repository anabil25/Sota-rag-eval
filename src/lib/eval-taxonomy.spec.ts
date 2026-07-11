import { describe, expect, it } from 'vitest';
import {
	CANONICAL_EVAL_TAXONOMY,
	evalSetCategoryEntries,
	evalTaxonomyWithCustom,
	getEvalTaxonomyItem,
	parseEvalCategoryCounts
} from './eval-taxonomy';

describe('eval taxonomy', () => {
	it('returns canonical and custom taxonomy items', () => {
		expect(getEvalTaxonomyItem('exact_term').axis).toBe('Lexical vs semantic');
		expect(getEvalTaxonomyItem('custom_case')).toEqual({
			id: 'custom_case',
			label: 'custom_case',
			axis: 'From eval questions',
			description: ''
		});
		expect(CANONICAL_EVAL_TAXONOMY.length).toBeGreaterThan(0);
	});

	it('deduplicates, sorts, and filters taxonomy values', () => {
		expect(
			evalTaxonomyWithCustom(['paraphrase', null, 'exact_term', 'paraphrase', undefined]).map(
				(item) => item.id
			)
		).toEqual(['exact_term', 'paraphrase']);
	});

	it('parses category counts from objects, JSON strings, and invalid values', () => {
		expect(parseEvalCategoryCounts({ a: 2 })).toEqual({ a: 2 });
		expect(parseEvalCategoryCounts('{"a":2,"b":"skip"}')).toEqual({ a: 2 });
		expect(parseEvalCategoryCounts('[]')).toEqual({});
		expect(parseEvalCategoryCounts('null')).toEqual({});
		expect(parseEvalCategoryCounts('{bad json')).toEqual({});
		expect(parseEvalCategoryCounts(undefined)).toEqual({});
	});

	it('sorts eval set category entries by count', () => {
		const entries = evalSetCategoryEntries({
			id: 1,
			version_label: 'v',
			category_counts: '{"paraphrase":1,"exact_term":3}'
		});
		expect(entries.map((entry) => [entry.id, entry.count])).toEqual([
			['exact_term', 3],
			['paraphrase', 1]
		]);
	});
});
