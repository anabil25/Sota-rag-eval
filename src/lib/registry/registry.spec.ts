import { describe, expect, it } from 'vitest';
import { ARCHITECTURES, getArchitecture } from './architectures';
import { MODEL_REGISTRY } from './models';
import {
	SOTA_PATHS,
	generateToggleCombinations,
	recommendSotaPath,
	type SotaPath
} from './sota-paths';

describe('architecture registry', () => {
	it('exposes the nine built-in architectures keyed by id', () => {
		expect(Object.keys(ARCHITECTURES)).toEqual([
			'keyword',
			'single-vector',
			'hybrid',
			'hybrid-reranker',
			'hybrid-llm-enriched',
			'multi-vector',
			'agentic-kb',
			'graphrag',
			'lightrag'
		]);
	});

	it('keeps display name + monthly estimate for catalog rendering', () => {
		expect(ARCHITECTURES.keyword.name).toBe('Keyword only');
		expect(ARCHITECTURES.keyword.est_monthly_usd).toBe(70);
		expect(ARCHITECTURES['hybrid-reranker'].toggleable_components).toContain('semantic_reranker');
	});

	it('throws on an unknown architecture id', () => {
		expect(getArchitecture('hybrid').name).toBe('Hybrid (keyword + vector)');
		expect(() => getArchitecture('does-not-exist')).toThrow(/Unknown architecture/);
	});
});

describe('model registry', () => {
	it('splits embedding and reranker catalogs', () => {
		expect(Object.keys(MODEL_REGISTRY.embedding)).toContain('text-embedding-3-small');
		expect(Object.keys(MODEL_REGISTRY.reranker)).toContain('azure-semantic-ranker');
		expect(MODEL_REGISTRY.embedding['text-embedding-3-large'].dimensions).toBe(3072);
	});
});

describe('sota path registry', () => {
	it('exposes the four use-case paths', () => {
		expect(Object.keys(SOTA_PATHS)).toEqual([
			'government-policy',
			'product-docs',
			'legal-contracts',
			'knowledge-base-faq'
		]);
	});

	it('does not leak the dropped max_avg_doc_length quirk', () => {
		// The Python SOTAPath model never declared max_avg_doc_length, so it is
		// absent from the serialized contract — the TS port must match.
		for (const path of Object.values(SOTA_PATHS)) {
			expect('max_avg_doc_length' in path).toBe(false);
		}
	});

	it('recommends the cross-reference path for dense, long corpora', () => {
		const recommended = recommendSotaPath(500, 6000, 3.0) as SotaPath;
		expect(recommended).not.toBeNull();
		expect(recommended.name).toBe('Legal & Contract Corpus');
	});

	it('recommends the FAQ path for short, low-cross-ref corpora', () => {
		const recommended = recommendSotaPath(50, 400, 0.1) as SotaPath;
		expect(recommended).not.toBeNull();
		expect(recommended.name).toBe('Knowledge Base / FAQ');
	});

	it('returns null when corpus characteristics match no SOTA path', () => {
		expect(recommendSotaPath(1_000_000, 10, 1000)).toBeNull();
		expect(recommendSotaPath(100, 10, 0.75)).toBeNull();
		expect(recommendSotaPath(100, 100, 1.5)?.name).toBe('Government Benefits Policy');
	});

	it('generates the default combination first, then one variant per non-default option', () => {
		const path = SOTA_PATHS['product-docs'];
		const combinations = generateToggleCombinations(path);
		const variantCount = path.components.reduce(
			(sum, component) => sum + ((component.options?.length ?? 0) - 1),
			0
		);
		expect(combinations).toHaveLength(1 + variantCount);
		expect(combinations[0]).toEqual({
			semantic_reranker: 'on'
		});
		expect(generateToggleCombinations({ ...path, components: [{ name: 'custom' }] })).toEqual([
			{ custom: '' }
		]);
	});
});
