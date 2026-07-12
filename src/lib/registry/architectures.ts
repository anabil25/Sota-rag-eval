// Architecture registry — ported from retrieve-core/src/retrieve/registry/architectures.py.
// Pure declarative catalog of built-in retrieval architectures with directional
// metadata. Owned by the SvelteKit app so the configure/compare/pricing surfaces
// no longer need the Python backend just to render the catalog.
//
// The Python engine keeps its own copy for eval runs and provisioning; this file
// must stay in sync with that registry. Shapes mirror the `/api/architectures`
// JSON contract exactly.

import type { ArchitectureDefinition } from '$lib/api/types';

export const ARCHITECTURES: Record<string, ArchitectureDefinition> = {
	keyword: {
		name: 'Keyword only',
		accuracy: '★★',
		cost: '$',
		latency: '★★★★★',
		best_for: 'Exact policy lookups, known terminology',
		required_azure_resources: ['storage', 'search'],
		description: 'AI Search keyword-only index. No embeddings.',
		est_monthly_usd: 70,
		toggleable_components: []
	},
	'single-vector': {
		name: 'Single vector',
		accuracy: '★★★',
		cost: '$$',
		latency: '★★★★',
		best_for: 'Semantic similarity, paraphrased questions',
		required_azure_resources: ['storage', 'search', 'ai_foundry'],
		description: '',
		est_monthly_usd: 180,
		toggleable_components: []
	},
	hybrid: {
		name: 'Hybrid (keyword + vector)',
		accuracy: '★★★★',
		cost: '$$',
		latency: '★★★★',
		best_for: 'General-purpose, covers both retrieval modes',
		required_azure_resources: ['storage', 'search', 'ai_foundry'],
		description: '',
		est_monthly_usd: 190,
		toggleable_components: []
	},
	'hybrid-reranker': {
		name: 'Hybrid + reranker',
		accuracy: '★★★★½',
		cost: '$$$',
		latency: '★★★',
		best_for: 'High-precision ranking on ambiguous queries',
		required_azure_resources: ['storage', 'search', 'ai_foundry'],
		description: '',
		est_monthly_usd: 280,
		toggleable_components: ['semantic_reranker']
	},
	'hybrid-llm-enriched': {
		name: 'Hybrid + LLM enrichment',
		accuracy: '★★★★½',
		cost: '$$$',
		latency: '★★★',
		best_for: 'Cross-ref extraction and topic tagging at index time',
		required_azure_resources: ['storage', 'search', 'ai_foundry'],
		description: '',
		est_monthly_usd: 290,
		toggleable_components: ['semantic_reranker']
	},
	'multi-vector': {
		name: 'Multi-vector',
		accuracy: '★★★★½',
		cost: '$$$',
		latency: '★★★',
		best_for: 'Dense, sparse, and token-level retrieval signals',
		required_azure_resources: ['storage', 'search', 'aci'],
		description:
			'Multiple vector representations per chunk; embedding source is configured separately.',
		est_monthly_usd: 320,
		toggleable_components: []
	},
	'agentic-kb': {
		name: 'Agentic retrieval',
		accuracy: '★★★★★',
		cost: '$$$$',
		latency: '★★',
		best_for: "Multi-hop, 'depends on X and Y' questions",
		required_azure_resources: ['storage', 'search', 'ai_foundry'],
		description: 'LLM-guided query planning and multi-step retrieval over search sources.',
		est_monthly_usd: 520,
		toggleable_components: []
	},
	graphrag: {
		name: 'GraphRAG',
		accuracy: '★★★★★',
		cost: '$$$$$',
		latency: '★',
		best_for: 'Cross-document reasoning, relationship traversal',
		required_azure_resources: ['storage', 'search', 'ai_foundry', 'cosmos', 'functions'],
		description: '',
		est_monthly_usd: 850,
		toggleable_components: []
	},
	lightrag: {
		name: 'LightRAG',
		accuracy: '★★★★½',
		cost: '$$$$',
		latency: '★★',
		best_for: 'Graph-augmented retrieval, lighter than full GraphRAG',
		required_azure_resources: ['storage', 'search', 'ai_foundry', 'container_apps', 'postgresql'],
		description: '',
		est_monthly_usd: 480,
		toggleable_components: []
	}
};

export function getArchitecture(name: string): ArchitectureDefinition {
	const architecture = ARCHITECTURES[name];
	if (!architecture) {
		throw new Error(
			`Unknown architecture '${name}'. Available: ${Object.keys(ARCHITECTURES).join(', ')}`
		);
	}
	return architecture;
}
