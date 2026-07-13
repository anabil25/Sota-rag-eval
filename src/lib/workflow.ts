import type {
	RetrieveStatus,
	StepNavItem,
	StepState,
	UiSession,
	WorkflowStepId
} from '$lib/api/types';

export const workflowSteps = [
	{
		id: 'ingest',
		index: 1,
		title: 'Ingest',
		shortTitle: 'Ingest',
		subtitle: 'Convert policy source material into markdown corpus files.',
		href: '/flow/ingest'
	},
	{
		id: 'eval',
		index: 2,
		title: 'Golden Eval Set',
		shortTitle: 'Eval',
		subtitle: 'Generate or import realistic operator questions.',
		href: '/flow/eval'
	},
	{
		id: 'configure',
		index: 3,
		title: 'Configure',
		shortTitle: 'Configure',
		subtitle: 'Choose the experiment preset and retrieval candidates.',
		href: '/flow/configure'
	},
	{
		id: 'provision',
		index: 4,
		title: 'Provision & Index',
		shortTitle: 'Deploy',
		subtitle: 'Deploy resources and build indexes for the selected experiments.',
		href: '/flow/provision'
	},
	{
		id: 'run',
		index: 5,
		title: 'Run Tests',
		shortTitle: 'Run Tests',
		subtitle:
			'Run the golden eval set as retrieval tests against the selected architecture matrix.',
		href: '/flow/run'
	},
	{
		id: 'compare',
		index: 6,
		title: 'Evaluate and Select',
		shortTitle: 'Compare',
		subtitle: 'Run evals, compare metrics, and choose winners.',
		href: '/flow/compare'
	},
	{
		id: 'teardown',
		index: 7,
		title: 'Teardown',
		shortTitle: 'Teardown',
		subtitle: 'Promote the winners to production and tear down the rest.',
		href: '/flow/teardown'
	}
] as const satisfies Array<Omit<StepNavItem, 'state'>>;

export function isWorkflowStep(value: string): value is WorkflowStepId {
	return workflowSteps.some((step) => step.id === value);
}

export function getWorkflowStep(id: WorkflowStepId) {
	return workflowSteps.find((step) => step.id === id) ?? workflowSteps[0];
}

/**
 * A step is "done" (green) when its durable artifact exists — the thing the
 * next step actually consumes. There are usually several ways to produce that
 * artifact (e.g. eval: generate / import / pick an existing set), so we check
 * the artifact itself rather than which button was pressed. The explicit
 * `*_done` session flag is still honored as an override.
 *
 * Cloud-action steps (provision/run/compare/teardown) stay on explicit flags:
 * their effects aren't represented by a session-local artifact, and global
 * counters like `run_count` are shared across sessions and can be stale.
 */
function hasIngestArtifact(session: UiSession): boolean {
	return (session.ingest_stats?.doc_count ?? 0) > 0;
}

function hasEvalArtifact(status: RetrieveStatus): boolean {
	return status.eval_set != null;
}

function hasConfigureChoice(session: UiSession): boolean {
	return (session.selected_architectures?.length ?? 0) > 0;
}

function hasActiveJob(session: UiSession, kinds: string[]): boolean {
	return Boolean(
		session.active_job_id &&
		typeof session.active_job_kind === 'string' &&
		kinds.includes(session.active_job_kind)
	);
}

function hasProvisionArtifact(status: RetrieveStatus): boolean {
	const selected = status.architectures;
	const provisioned = status.provisioned_architectures ?? [];
	return selected.length > 0 && selected.every((name) => provisioned.includes(name));
}

export function getStepState(
	id: WorkflowStepId,
	session: UiSession,
	status: RetrieveStatus
): StepState {
	const inferReusableArtifacts = session.workflow_reset_mode !== 'fresh';
	if (id === 'ingest')
		return session.ingest_done || (inferReusableArtifacts && hasIngestArtifact(session))
			? 'done'
			: 'pending';
	if (id === 'eval')
		return session.eval_done || (inferReusableArtifacts && hasEvalArtifact(status))
			? 'done'
			: 'pending';
	if (id === 'configure')
		return session.configure_done || (inferReusableArtifacts && hasConfigureChoice(session))
			? 'done'
			: 'pending';
	if (id === 'provision') {
		if (hasActiveJob(session, ['provision', 'provision_index', 'index'])) return 'pending';
		return hasProvisionArtifact(status) ? 'done' : 'pending';
	}
	if (id === 'run') {
		if (hasActiveJob(session, ['evaluate'])) return 'pending';
		return session.run_done ? 'done' : 'pending';
	}
	if (id === 'compare') return session.compare_done ? 'done' : 'pending';
	if (id === 'teardown') {
		if (hasActiveJob(session, ['teardown'])) return 'pending';
		return session.teardown_done ? 'done' : 'pending';
	}
	return 'pending';
}

export function buildStepNav(session: UiSession, status: RetrieveStatus): StepNavItem[] {
	let nextStepFound = false;
	return workflowSteps.map((step) => {
		const artifactState = getStepState(step.id, session, status);
		if (nextStepFound) return { ...step, state: 'locked' as const };
		if (artifactState === 'done') return { ...step, state: 'done' as const };
		nextStepFound = true;
		return { ...step, state: artifactState === 'error' ? 'error' : ('active' as const) };
	});
}
