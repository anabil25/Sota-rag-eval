import { env } from '$env/dynamic/private';
import type { CompareContext, RunResult, RunSummary } from '$lib/api/types';
import { ARCHITECTURES } from '$lib/registry/architectures';
import * as db from '$lib/server/db';

export function getCompareContext(): CompareContext {
	const runs = db.getAllCompletedRuns();
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

	const ui = db.getUiSession();
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
		deployments.push({
			architecture_name: name,
			status: arch.status || 'unknown',
			endpoint: (resources.search_endpoint as string) || (resources.endpoint as string),
			index_name: (resources.index_name as string) || (cfgData.index_name as string),
			resource_group: (resources.resource_group as string) || fallbackResourceGroup,
			location: (resources.location as string) || fallbackLocation,
			est_monthly_usd: meta?.est_monthly_usd
		});
	}

	return {
		runs: runs as RunSummary[],
		categories,
		failures,
		latest_eval: db.getLatestEvalSet(),
		selected_mode: (ui.selected_mode as string) || '',
		arch_costs: archCosts,
		winners,
		deployments
	};
}
