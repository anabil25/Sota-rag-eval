import { error } from '@sveltejs/kit';
import type {
	ArchitectureDefinition,
	ArchitectureStatus,
	CompareContext,
	CorpusFilesResponse,
	EvalQuestionBrowseResult,
	EvalSet,
	EvalSummary,
	FoundryEmbeddingResponse,
	ModelRegistry,
	RetrieveConfigSummary,
	RetrieveStatus,
	RunDetail,
	RunSummary,
	SotaPathDefinition,
	SotaRecommendation,
	UiSession
} from '$lib/api/types';
import {
	curateEvalSet,
	exportEvalCsv,
	getOperationJson,
	getJobStatus,
	importEvalCsv,
	operationApiConfigured,
	resetOperationUiSession,
	startJob,
	updateOperationUiSession
} from '$lib/server/clients/operation-api-client';
import { getCorpusFiles as readCorpusFiles } from '$lib/server/data/corpus-files';
import * as db from '$lib/server/db';
import { ARCHITECTURES } from '$lib/registry/architectures';
import { MODEL_REGISTRY } from '$lib/registry/models';
import { SOTA_PATHS } from '$lib/registry/sota-paths';
import { getCompareContext as buildCompareContext } from '$lib/server/services/compare-service';
import {
	getFoundryCatalogEmbeddings as readFoundryCatalogEmbeddings,
	getFoundryDeployedEmbeddings as readFoundryDeployedEmbeddings,
	getSotaRecommendation as buildSotaRecommendation
} from '$lib/server/services/sota-service';
import {
	getArchitectureStatus as readArchitectureStatus,
	getConfig as readConfig,
	getStatus as readStatus
} from '$lib/server/services/status-service';
import { getUiSession as readUiSession } from '$lib/server/services/workflow-session-service';

export { curateEvalSet, exportEvalCsv, getJobStatus, importEvalCsv, startJob };

export async function getStatus(): Promise<RetrieveStatus> {
	if (operationApiConfigured()) return getOperationJson<RetrieveStatus>('/api/status');
	return readStatus();
}

export async function getConfig(): Promise<RetrieveConfigSummary> {
	if (operationApiConfigured()) return getOperationJson<RetrieveConfigSummary>('/api/config');
	return readConfig();
}

export async function getArchitectureStatus(): Promise<ArchitectureStatus[]> {
	if (operationApiConfigured()) {
		return getOperationJson<ArchitectureStatus[]>('/api/architecture-status');
	}
	return readArchitectureStatus();
}

export async function getCorpusFiles(output?: string): Promise<CorpusFilesResponse> {
	if (operationApiConfigured()) {
		const query = output ? `?output=${encodeURIComponent(output)}` : '';
		return getOperationJson<CorpusFilesResponse>(`/api/corpus-files${query}`);
	}
	return readCorpusFiles(output);
}

export async function getSotaRecommendation(): Promise<SotaRecommendation> {
	if (operationApiConfigured()) {
		return getOperationJson<SotaRecommendation>('/api/sota-recommendation');
	}
	return buildSotaRecommendation();
}

export async function getCompareContext(): Promise<CompareContext> {
	if (operationApiConfigured()) return getOperationJson<CompareContext>('/api/compare-context');
	return buildCompareContext();
}

export async function getRuns(): Promise<RunSummary[]> {
	if (operationApiConfigured()) return getOperationJson<RunSummary[]>('/api/runs');
	return db.getAllCompletedRuns();
}

export async function getRun(id: number | string): Promise<RunDetail> {
	if (operationApiConfigured()) return getOperationJson<RunDetail>(`/api/runs/${Number(id)}`);
	const detail = db.getRunDetail(Number(id));
	if (!detail) error(404, 'Run not found');
	return detail;
}

export async function getEvalSets(): Promise<EvalSet[]> {
	if (operationApiConfigured()) return getOperationJson<EvalSet[]>('/api/eval-sets');
	return db.getEvalSets();
}

export async function getEvalSummary(id: number): Promise<EvalSummary> {
	if (operationApiConfigured()) {
		return getOperationJson<EvalSummary>(`/api/eval-sets/${Number(id)}/summary`);
	}
	const summary = db.getEvalSummary(Number(id));
	if (!summary) error(404, 'Eval set not found');
	return summary;
}

export async function browseEvalQuestions(
	id: number,
	filters: Record<string, string | number | undefined> = {}
): Promise<EvalQuestionBrowseResult> {
	if (operationApiConfigured()) {
		const query = new URLSearchParams();
		for (const [key, value] of Object.entries(filters)) {
			if (value !== undefined) query.set(key, String(value));
		}
		return getOperationJson<EvalQuestionBrowseResult>(
			`/api/eval-sets/${Number(id)}/questions/browse?${query}`
		);
	}
	return db.browseQuestions(Number(id), {
		category: filters.category as string | undefined,
		question_type: filters.question_type as string | undefined,
		persona: filters.persona as string | undefined,
		intent_family: filters.intent_family as string | undefined,
		limit: filters.limit !== undefined ? Number(filters.limit) : undefined,
		offset: filters.offset !== undefined ? Number(filters.offset) : undefined
	});
}

export async function getArchitectures(): Promise<Record<string, ArchitectureDefinition>> {
	return ARCHITECTURES;
}

export async function getModels(): Promise<ModelRegistry> {
	return MODEL_REGISTRY;
}

export async function getFoundryDeployedEmbeddings(
	resourceGroup = '',
	workspaceName = ''
): Promise<FoundryEmbeddingResponse> {
	if (operationApiConfigured()) {
		const query = new URLSearchParams({
			resource_group: resourceGroup,
			workspace_name: workspaceName
		});
		return getOperationJson<FoundryEmbeddingResponse>(`/api/foundry/embeddings/deployed?${query}`);
	}
	return readFoundryDeployedEmbeddings(resourceGroup, workspaceName);
}

export async function getFoundryCatalogEmbeddings(
	queryText = ''
): Promise<FoundryEmbeddingResponse> {
	if (operationApiConfigured()) {
		return getOperationJson<FoundryEmbeddingResponse>(
			`/api/foundry/embeddings/catalog?query=${encodeURIComponent(queryText)}`
		);
	}
	return readFoundryCatalogEmbeddings(queryText);
}

export async function getSotaPaths(): Promise<Record<string, SotaPathDefinition>> {
	return SOTA_PATHS;
}

export async function getUiSession(): Promise<UiSession> {
	if (operationApiConfigured()) return getOperationJson<UiSession>('/api/ui/session');
	return readUiSession();
}

export async function updateUiSession(
	session: Partial<UiSession>,
	headers: HeadersInit = {}
): Promise<{ status: string; session: UiSession }> {
	return updateOperationUiSession(session, headers);
}

export async function resetUiSession(
	mode: 'reuse' | 'fresh',
	headers: HeadersInit = {}
): Promise<{ status: string; session: UiSession }> {
	return resetOperationUiSession(mode, headers);
}
