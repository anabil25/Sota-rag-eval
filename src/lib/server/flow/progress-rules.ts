import type { UiSession } from '$lib/api/types';

export function startStateForJob(kind: string): Partial<UiSession> {
	if (kind === 'ingest') {
		return {
			ingest_done: false,
			eval_done: false,
			configure_done: false,
			provision_done: false,
			run_done: false,
			compare_done: false,
			teardown_done: false,
			winners: []
		};
	}

	if (kind === 'eval_generate') {
		return {
			eval_done: false,
			run_done: false,
			compare_done: false,
			teardown_done: false,
			winners: []
		};
	}

	if (kind === 'provision' || kind === 'provision_index' || kind === 'index') {
		return {
			provision_done: false,
			run_done: false,
			compare_done: false,
			teardown_done: false,
			winners: []
		};
	}

	if (kind === 'teardown') {
		return {
			teardown_done: false
		};
	}

	if (kind === 'evaluate') {
		return {
			run_done: false,
			compare_done: false,
			teardown_done: false,
			winners: []
		};
	}

	return {};
}
