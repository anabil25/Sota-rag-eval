import { describe, expect, it } from 'vitest';
import {
	advancedControlHelp,
	advancedOptionHelp,
	agenticSearchKeys,
	aiSearchExperimentKeys,
	architecturePresentation,
	architectureResourceFallback,
	azureServiceCatalog,
	buildRowControls,
	experimentPresets,
	graphRetrievalKeys,
	searchBaselineResources
} from './configure-model';

function sessionString(key: string, fallback = '') {
	const values: Record<string, string> = {
		query_syntax: 'full',
		vector_exhaustive: 'true'
	};
	return values[key] ?? fallback;
}

describe('configure model', () => {
	it('exposes architecture families, presets, services, and help text', () => {
		expect(architecturePresentation.hybrid.pattern).toBe('Keyword + vector fusion');
		expect(aiSearchExperimentKeys.has('hybrid-reranker')).toBe(true);
		expect(agenticSearchKeys.has('agentic-kb')).toBe(true);
		expect(graphRetrievalKeys.has('graphrag')).toBe(true);
		expect(searchBaselineResources.has('search')).toBe(true);
		expect(azureServiceCatalog.search.label).toBe('Azure AI Search');
		expect(architectureResourceFallback.graphrag).toContain('cosmosdb');
		expect(experimentPresets.map((preset) => preset.id)).toEqual([
			'quick-baseline',
			'quality-sweep',
			'cross-paradigm'
		]);
		expect(advancedControlHelp.query_syntax).toContain('keyword query');
		expect(advancedOptionHelp.query_syntax.full).toContain('advanced search operators');
	});

	it('builds advanced controls for every architecture family', () => {
		const expectations: Record<string, string[]> = {
			keyword: ['query_syntax', 'top_k'],
			'single-vector': ['vector_k', 'vector_exhaustive'],
			hybrid: ['max_text_recall_size', 'vector_weight'],
			'hybrid-reranker': ['semantic_ranker_mode', 'query_rewrites'],
			'hybrid-llm-enriched': ['enrichment_profile', 'chunk_overlap'],
			'multi-vector': ['vector_k'],
			'agentic-kb': ['agentic_knowledge_source', 'agentic_include_activity'],
			graphrag: ['graphrag_query_mode', 'graphrag_prompt_tuning'],
			lightrag: ['lightrag_query_mode', 'lightrag_stream']
		};

		for (const [architecture, fields] of Object.entries(expectations)) {
			const controls = buildRowControls(architecture, sessionString);
			const controlFields = controls.map((control) => control.field);
			for (const field of fields) expect(controlFields).toContain(field);
		}
		expect(buildRowControls('unknown', sessionString)).toEqual([]);
	});
});
