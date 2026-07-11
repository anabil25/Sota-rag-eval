// Model registry — ported from retrieve-core/src/retrieve/registry/models.py.
// Embedding + reranker model catalog. Pure declarative data; shapes mirror the
// `/api/models` JSON contract exactly (ModelRegistry { embedding, reranker }).

import type { ModelDefinition, ModelRegistry } from '$lib/api/types';

export const EMBEDDING_MODELS: Record<string, ModelDefinition> = {
	'text-embedding-3-small': {
		name: 'text-embedding-3-small',
		dimensions: 1536,
		mteb_avg: 62.3,
		cost_per_1m: '$0.02',
		latency_p50: '12ms',
		notes: 'Cheapest Azure-native option',
		provider: 'azure_openai'
	},
	'text-embedding-3-large': {
		name: 'text-embedding-3-large',
		dimensions: 3072,
		mteb_avg: 64.6,
		cost_per_1m: '$0.13',
		latency_p50: '18ms',
		notes: 'Higher fidelity, still fast',
		provider: 'azure_openai'
	},
	'bge-m3': {
		name: 'BGE-M3',
		dimensions: 1024,
		mteb_avg: 66.1,
		cost_per_1m: 'Self-hosted',
		latency_p50: '25ms',
		notes: 'Dense + sparse + multi-vector in one pass',
		provider: 'self_hosted'
	},
	'cohere-embed-v3': {
		name: 'Cohere embed-v3',
		dimensions: 1024,
		mteb_avg: 64.5,
		cost_per_1m: '$0.10',
		latency_p50: '15ms',
		notes: 'Strong multilingual',
		provider: 'cohere'
	}
};

export const RERANKER_MODELS: Record<string, ModelDefinition> = {
	'azure-semantic-ranker': {
		name: 'Azure semantic ranker',
		notes:
			'Built-in cross-encoder in AI Search. No external deployment. Enable via SemanticConfiguration.',
		provider: 'azure_native'
	},
	'bge-reranker-v2-m3': {
		name: 'bge-reranker-v2-m3',
		notes: 'Strong BEIR performance, open weights, single GPU. Default cross-encoder.',
		provider: 'self_hosted'
	},
	rank1: {
		name: 'Rank1',
		notes: 'Reasoning-intensive swap-in for complex queries.',
		provider: 'self_hosted'
	},
	'cohere-reranker': {
		name: 'Cohere reranker',
		notes: 'Hosted reranker API, no self-hosting needed.',
		provider: 'cohere'
	}
};

export const MODEL_REGISTRY: ModelRegistry = {
	embedding: EMBEDDING_MODELS,
	reranker: RERANKER_MODELS
};
