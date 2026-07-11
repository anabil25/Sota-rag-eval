import type { FoundryEmbeddingResponse, SotaRecommendation } from '$lib/api/types';
import { recommendSotaPath } from '$lib/registry/sota-paths';
import * as db from '$lib/server/db';

export function getSotaRecommendation(): SotaRecommendation {
	const ingestStats = db.getUiSession().ingest_stats ?? {};
	const docCount = Number(ingestStats.doc_count ?? 0);
	const avgDocLength = Number(ingestStats.avg_doc_length ?? 0);
	const crossRefDensity = Number(ingestStats.cross_ref_density ?? 0);
	const recommended = recommendSotaPath(docCount, avgDocLength, crossRefDensity);
	return {
		recommended_sota: recommended,
		rationale: recommended
			? `doc_count=${docCount}, avg_doc_length=${avgDocLength.toFixed(0)}, cross_ref_density=${crossRefDensity.toFixed(2)} - matches the ${recommended.name} pattern.`
			: ''
	};
}

export function getFoundryDeployedEmbeddings(
	_resource_group = '',
	_workspace_name = ''
): FoundryEmbeddingResponse {
	void _resource_group;
	void _workspace_name;
	return { items: [], errors: [] };
}

export function getFoundryCatalogEmbeddings(_queryText = ''): FoundryEmbeddingResponse {
	void _queryText;
	return { items: [], errors: [] };
}
