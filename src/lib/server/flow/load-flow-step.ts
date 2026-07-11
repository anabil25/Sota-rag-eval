import { error } from '@sveltejs/kit';
import {
	browseEvalQuestions,
	getArchitectureStatus,
	getArchitectures,
	getCompareContext,
	getConfig,
	getCorpusFiles,
	getEvalSets,
	getFoundryCatalogEmbeddings,
	getFoundryDeployedEmbeddings,
	getModels,
	getRuns,
	getSotaPaths,
	getStatus,
	getUiSession
} from '$lib/server/retrieve-api';
import { getWorkflowStep, isWorkflowStep } from '$lib/workflow';

export async function loadFlowStep(step: string) {
	if (!isWorkflowStep(step)) error(404, 'Unknown workflow step');

	const [status, session, evalSets, runs, architectures, models, sotaPaths, config] =
		await Promise.all([
			getStatus(),
			getUiSession(),
			getEvalSets(),
			getRuns(),
			getArchitectures(),
			getModels(),
			getSotaPaths(),
			getConfig()
		]);

	const foundryResourceGroup =
		typeof session.foundry_resource_group === 'string'
			? session.foundry_resource_group
			: config.azure.resource_group;
	const foundryWorkspaceName =
		typeof session.foundry_workspace_name === 'string' ? session.foundry_workspace_name : '';
	const foundryCatalogQuery =
		typeof session.foundry_catalog_query === 'string' ? session.foundry_catalog_query : '';
	const currentEvalSetId = status.eval_set?.id ?? evalSets[0]?.id ?? 1;
	const questionBrowse = await browseEvalQuestions(currentEvalSetId, { limit: 20 });
	const [
		corpusFiles,
		architectureStatus,
		compareContext,
		foundryDeployedEmbeddings,
		foundryCatalogEmbeddings
	] = await Promise.all([
		step === 'ingest' || step === 'provision' || step === 'run'
			? getCorpusFiles(typeof session.output === 'string' ? session.output : undefined)
			: Promise.resolve({ output: '', files: [] }),
		step === 'provision' || step === 'run' ? getArchitectureStatus() : Promise.resolve([]),
		step === 'compare' || step === 'teardown' ? getCompareContext() : Promise.resolve(null),
		step === 'configure'
			? getFoundryDeployedEmbeddings(foundryResourceGroup, foundryWorkspaceName)
			: Promise.resolve({ items: [], errors: [] }),
		step === 'configure'
			? getFoundryCatalogEmbeddings(foundryCatalogQuery)
			: Promise.resolve({ items: [], errors: [] })
	]);

	return {
		step,
		stepMeta: getWorkflowStep(step),
		currentEvalSetId,
		status,
		session,
		evalSets,
		runs,
		architectures,
		config,
		models,
		sotaPaths,
		foundryDeployedEmbeddings,
		foundryCatalogEmbeddings,
		questions: questionBrowse.items,
		corpusFiles,
		sotaRecommendation: { recommended_sota: null, rationale: '' },
		architectureStatus,
		compareContext
	};
}
