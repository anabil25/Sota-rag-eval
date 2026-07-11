import type {
	ArchitectureStatus,
	RetrieveConfigSummary,
	RetrieveStatus,
	UiSession
} from '$lib/api/types';
import { SOTA_PATHS } from '$lib/registry/sota-paths';
import { loadConfig } from '$lib/server/config';
import * as db from '$lib/server/db';

function stringList(value: unknown): string[] {
	if (Array.isArray(value)) return value.map(String).filter(Boolean);
	if (typeof value === 'string') {
		return value
			.split(',')
			.map((item) => item.trim())
			.filter(Boolean);
	}
	return [];
}

function hasActiveProvisionJob(session: UiSession): boolean {
	return (
		typeof session.active_job_id === 'string' &&
		session.active_job_id.length > 0 &&
		typeof session.active_job_kind === 'string' &&
		['provision', 'provision_index', 'index'].includes(session.active_job_kind)
	);
}

function hasCurrentProvisionCycle(session: UiSession): boolean {
	return session.provision_done === true && !hasActiveProvisionJob(session);
}

export function selectedArchitectureNames(
	session: UiSession = db.getUiSession(),
	config: RetrieveConfigSummary = loadConfig()
): string[] {
	if (session.selected_mode === 'sota' && typeof session.selected_sota_path === 'string') {
		const base = SOTA_PATHS[session.selected_sota_path]?.base_architecture;
		if (base) return [base];
	}
	const selected = stringList(session.selected_architectures);
	return selected.length ? selected : config.architectures;
}

export function getStatus(): RetrieveStatus {
	const config = loadConfig();
	const session = db.getUiSession();
	const architectures = selectedArchitectureNames(session, config);
	const latest = db.getLatestEvalSet();
	let eval_set = latest;
	const requested =
		typeof session.active_eval_set === 'string' ? session.active_eval_set.trim() : '';
	if (requested && requested !== latest?.version_label) {
		const match = db.getEvalSets().find((set) => set.version_label === requested);
		if (match) eval_set = match;
	}
	return {
		eval_set,
		run_count: db.getAllCompletedRuns().length,
		architectures,
		provisioned_architectures: hasCurrentProvisionCycle(session)
			? architectures.filter((name) => {
					const row = db.getArchitecture(name);
					return row?.status === 'provisioned' || row?.status === 'active';
				})
			: []
	};
}

export function getConfig(): RetrieveConfigSummary {
	const config = loadConfig();
	return {
		...config,
		architectures: selectedArchitectureNames(db.getUiSession(), config)
	};
}

export function getArchitectureStatus(): ArchitectureStatus[] {
	const session = db.getUiSession();
	if (!hasCurrentProvisionCycle(session)) return [];

	return selectedArchitectureNames(session).flatMap((name) => {
		const row = db.getArchitecture(name);
		return row ? [row] : [];
	});
}
