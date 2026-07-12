import { env } from '$env/dynamic/private';
import type { CompareContext, RunResult, RunSummary } from '$lib/api/types';
import { ARCHITECTURES } from '$lib/registry/architectures';
import * as db from '$lib/server/db';

export function getCompareContext(): CompareContext {
	const ui = db.getUiSession();
	const activeEvalVersion = String(ui.active_experiment_eval_set_version || '');
	const activeEval = activeEvalVersion
		? db.getEvalSets().find((evalSet) => evalSet.version_label === activeEvalVersion) || null
		: null;
	const activeArchitectures = Array.isArray(ui.active_experiment_architectures)
		? ui.active_experiment_architectures.map(String)
		: [];
	const experimentId = String(ui.active_experiment_id || '');
	const runs =
		experimentId && activeEval
			? db.getCompletedRunsForExperiment({
					experimentId,
					evalSetId: activeEval.id,
					architectureNames: activeArchitectures,
					corpusFingerprint: String(ui.active_experiment_corpus_fingerprint || '')
				})
			: ui.pending_experiment_id
				? []
				: db.getAllCompletedRuns();
	const categories: CompareContext['categories'] = {};
	const failures: CompareContext['failures'] = {};
	for (const run of runs) {
		categories[run.id] = db.getPerCategoryScores(run.id);
		failures[run.id] = db.getFailuresForRun(run.id) as RunResult[];
	}

	const archCosts: Record<string, number> = {};
	for (const run of runs) {
		const key = run.architecture_name;
		const cfgBlob = (run.architecture_config ?? {}) as Record<string, unknown>;
		const baseKey = (cfgBlob._variant_of as string) || key.split('[', 1)[0];
		const meta = ARCHITECTURES[baseKey];
		if (meta?.est_monthly_usd !== undefined) archCosts[key] = meta.est_monthly_usd;
	}

	const winners: string[] = (ui.winners as string[]) || [];
	const fallbackResourceGroup = env.PRIVATE_RETRIEVE_AZURE_RESOURCE_GROUP || '';
	const fallbackLocation = env.PRIVATE_RETRIEVE_AZURE_LOCATION || '';
	const deployments = [];
	for (const name of winners) {
		const arch = db.getArchitecture(name);
		if (!arch) continue;
		const cfgData = arch.config;
		const resources = arch.resources_provisioned;
		const meta = ARCHITECTURES[name];
		let handoffKind = 'azure-ai-search';
		let endpoint = (resources.search_endpoint as string) || (cfgData.search_endpoint as string);
		let queryTarget = (resources.index_name as string) || (cfgData.index_name as string);
		let handoffNote = 'Use Azure AI Search data-plane retrieval with managed identity.';
		if (name === 'agentic-kb') {
			handoffKind = 'agentic-kb';
			handoffNote =
				'This winner uses Azure AI Search Knowledge Base retrieval. Call it through the Retrieve backend adapter; it is not a docs/search request.';
		} else if (name === 'graphrag') {
			handoffKind = 'graphrag-job';
			endpoint = '';
			queryTarget = String(cfgData.graph_job_name || '');
			handoffNote =
				'This winner is queried through the Retrieve GraphRAG job adapter. No direct production HTTP endpoint is deployed.';
		} else if (name === 'lightrag') {
			endpoint = String(cfgData.container_app_endpoint || '');
			handoffKind = endpoint ? 'lightrag-http' : 'lightrag-local';
			queryTarget = String(cfgData.lightrag_working_dir || '');
			handoffNote = endpoint
				? 'Use the configured LightRAG HTTP service.'
				: 'This evaluated winner is a local LightRAG index. Deploy a persistent query service before connecting an external client.';
		}
		deployments.push({
			architecture_name: name,
			status: arch.status || 'unknown',
			handoff_kind: handoffKind,
			endpoint,
			index_name: handoffKind === 'azure-ai-search' ? queryTarget : undefined,
			query_target: queryTarget,
			artifact_prefix: cfgData.graph_worker_artifact_prefix as string,
			working_dir: cfgData.lightrag_working_dir as string,
			handoff_note: handoffNote,
			resource_group: (resources.resource_group as string) || fallbackResourceGroup,
			location: (resources.location as string) || fallbackLocation,
			est_monthly_usd: meta?.est_monthly_usd
		});
	}

	return {
		runs: runs as RunSummary[],
		categories,
		failures,
		latest_eval: activeEval || db.getLatestEvalSet(),
		experiment_id: experimentId,
		selected_mode: (ui.selected_mode as string) || '',
		arch_costs: archCosts,
		winners,
		deployments
	};
}
