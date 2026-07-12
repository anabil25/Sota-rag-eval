// SOTA path registry — ported from retrieve-core/src/retrieve/registry/sota_paths.py.
// Recommended pipelines per use case plus corpus-based recommendation and toggle
// combination helpers. Shapes mirror the `/api/sota-paths` JSON contract exactly.
//
// Note: the Python SOTAPath model only declares `min_avg_doc_length` (no
// `max_avg_doc_length`), so the knowledge-base-faq quirk in Python is silently
// dropped on serialization. We reproduce the serialized contract faithfully here.

import type { SotaComponentOption, SotaPathDefinition } from '$lib/api/types';

export interface SotaPath extends SotaPathDefinition {
	name: string;
	description: string;
	base_architecture: string;
	components: SotaComponentOption[];
	min_doc_count: number;
	max_doc_count: number;
	min_cross_ref_density: number;
	max_cross_ref_density: number;
	min_avg_doc_length: number;
}

function path(
	partial: Pick<SotaPath, 'name' | 'description' | 'base_architecture' | 'components'> &
		Partial<
			Pick<
				SotaPath,
				| 'min_doc_count'
				| 'max_doc_count'
				| 'min_cross_ref_density'
				| 'max_cross_ref_density'
				| 'min_avg_doc_length'
			>
		>
): SotaPath {
	return {
		min_doc_count: 0,
		max_doc_count: 999999,
		min_cross_ref_density: 0.0,
		max_cross_ref_density: 999.0,
		min_avg_doc_length: 0.0,
		...partial
	};
}

export const SOTA_PATHS: Record<string, SotaPath> = {
	'government-policy': path({
		name: 'Government Benefits Policy',
		description:
			'For government benefits manuals, administrative procedures, and regulatory documents with dense cross-references between policies. Optimized for caseworker lookup queries and eligibility determination.',
		base_architecture: 'hybrid-reranker',
		components: [
			{
				name: 'semantic_reranker',
				options: ['on', 'off'],
				default: 'on',
				description: 'Azure AI Search built-in semantic reranker (L2 cross-encoder)'
			}
		],
		min_cross_ref_density: 1.0
	}),
	'product-docs': path({
		name: 'Product Documentation',
		description:
			'For product manuals, API docs, and technical documentation. Mostly standalone pages with clear headings.',
		base_architecture: 'hybrid-reranker',
		components: [
			{ name: 'semantic_reranker', options: ['on', 'off'], default: 'on', description: '' }
		],
		max_cross_ref_density: 1.0,
		min_avg_doc_length: 1500.0
	}),
	'legal-contracts': path({
		name: 'Legal & Contract Corpus',
		description:
			'For legal documents, contracts, and compliance materials. Long documents, precise terminology, and heavy cross-referencing.',
		base_architecture: 'hybrid-reranker',
		components: [
			{ name: 'semantic_reranker', options: ['on', 'off'], default: 'on', description: '' }
		],
		min_cross_ref_density: 2.0,
		min_avg_doc_length: 5000.0
	}),
	'knowledge-base-faq': path({
		name: 'Knowledge Base / FAQ',
		description:
			'For FAQs, help center articles, and short-form knowledge bases. Short, self-contained documents with minimal cross-references.',
		base_architecture: 'hybrid',
		components: [],
		max_cross_ref_density: 0.5
	})
};

/**
 * Recommend a SOTA path based on corpus characteristics observed during ingestion.
 * Returns the best-matching path, or null if no path matches.
 */
export function recommendSotaPath(
	docCount: number,
	avgDocLength: number,
	crossRefDensity: number
): SotaPath | null {
	let best: SotaPath | null = null;
	let bestScore = -1;

	for (const candidate of Object.values(SOTA_PATHS)) {
		if (!(candidate.min_doc_count <= docCount && docCount <= candidate.max_doc_count)) continue;
		if (
			!(
				candidate.min_cross_ref_density <= crossRefDensity &&
				crossRefDensity <= candidate.max_cross_ref_density
			)
		)
			continue;
		if (avgDocLength < candidate.min_avg_doc_length) continue;

		// Simple scoring: prefer paths with more specific constraints.
		let score = 0;
		if (candidate.min_cross_ref_density > 0) score += 1;
		if (candidate.max_cross_ref_density < 999) score += 1;
		if (candidate.min_avg_doc_length > 0) score += 1;
		if (candidate.max_doc_count < 999999) score += 1;

		if (score > bestScore) {
			best = candidate;
			bestScore = score;
		}
	}

	return best;
}

/**
 * Generate all meaningful toggle combinations for a SOTA path.
 * Returns a list of records mapping component name → selected option.
 * The first entry is always the full default path.
 */
export function generateToggleCombinations(sotaPath: SotaPath): Record<string, string>[] {
	const defaults: Record<string, string> = {};
	for (const component of sotaPath.components) {
		defaults[component.name] = component.default ?? '';
	}
	const combinations: Record<string, string>[] = [{ ...defaults }];

	for (const component of sotaPath.components) {
		for (const option of component.options ?? []) {
			if (option === component.default) continue;
			const variant = { ...defaults };
			variant[component.name] = option;
			combinations.push(variant);
		}
	}

	return combinations;
}
