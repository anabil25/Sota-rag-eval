import { describe, expect, it } from 'vitest';
import type { RetrieveStatus, UiSession } from '$lib/api/types';
import { buildStepNav, getStepState, getWorkflowStep, isWorkflowStep } from './workflow';

const status: RetrieveStatus = {
	eval_set: { id: 1, version_label: 'v1', question_count: 12 },
	run_count: 1,
	architectures: ['keyword', 'hybrid'],
	provisioned_architectures: ['keyword', 'hybrid']
};

const session: UiSession = {
	ingest_done: true,
	eval_done: true,
	selected_mode: 'test',
	selected_architectures: ['hybrid'],
	configure_done: true
};

describe('workflow navigation', () => {
	it('recognizes supported workflow steps', () => {
		expect(isWorkflowStep('ingest')).toBe(true);
		expect(isWorkflowStep('index')).toBe(false);
		expect(isWorkflowStep('mode')).toBe(false);
		expect(isWorkflowStep('unknown')).toBe(false);
		expect(getWorkflowStep('ingest').title).toBe('Ingest');
	});

	it('marks the current step active and completed prerequisites done', () => {
		const nav = buildStepNav(session, status, '/flow/run');
		expect(nav).toHaveLength(7);
		expect(nav.find((step) => step.id === 'ingest')?.state).toBe('done');
		expect(nav.find((step) => step.id === 'configure')?.state).toBe('done');
		expect(nav.find((step) => step.id === 'run')?.state).toBe('active');
	});

	it('does not mark run or compare done from stale global run counts', () => {
		const nav = buildStepNav(session, status, '/flow/provision');
		expect(nav.find((step) => step.id === 'run')?.state).toBe('pending');
		expect(nav.find((step) => step.id === 'compare')?.state).toBe('pending');
	});

	it('uses explicit session progress for downstream steps', () => {
		const nav = buildStepNav(
			{ ...session, provision_done: true, run_done: true, compare_done: true },
			status,
			'/flow/ingest'
		);
		expect(nav.find((step) => step.id === 'provision')?.state).toBe('done');
		expect(nav.find((step) => step.id === 'run')?.state).toBe('done');
		expect(nav.find((step) => step.id === 'compare')?.state).toBe('done');
	});

	it('does not mark provision done from a stale session flag without provisioned rows', () => {
		const nav = buildStepNav(
			{ ...session, provision_done: true },
			{ ...status, provisioned_architectures: [] },
			'/flow/ingest'
		);
		expect(nav.find((step) => step.id === 'provision')?.state).toBe('pending');
	});

	it('keeps active cloud-action steps pending while their job is running', () => {
		const nav = buildStepNav(
			{ ...session, active_job_id: 'job-1', active_job_kind: 'provision_index' },
			status,
			'/flow/ingest'
		);
		expect(nav.find((step) => step.id === 'provision')?.state).toBe('pending');
	});

	it('keeps teardown pending until it is explicitly completed', () => {
		const base = buildStepNav({ ...session, compare_done: true }, status, '/flow/compare');
		expect(base.find((step) => step.id === 'teardown')?.state).toBe('pending');

		const done = buildStepNav(
			{ ...session, compare_done: true, teardown_done: true },
			status,
			'/flow/ingest'
		);
		expect(done.find((step) => step.id === 'teardown')?.state).toBe('done');
	});

	it('marks eval done when an eval set exists, even without an explicit flag', () => {
		// "Use an existing eval set" never sets eval_done, but the artifact exists.
		const usingExisting: UiSession = { ingest_done: true };
		const nav = buildStepNav(usingExisting, status, '/flow/configure');
		expect(nav.find((step) => step.id === 'eval')?.state).toBe('done');
	});

	it('keeps eval pending when no eval set exists and no flag is set', () => {
		const nav = buildStepNav({}, { ...status, eval_set: null }, '/flow/ingest');
		expect(nav.find((step) => step.id === 'eval')?.state).toBe('pending');
	});

	it('marks ingest done from corpus stats without an explicit flag', () => {
		const nav = buildStepNav(
			{ ingest_stats: { doc_count: 4 } },
			{ ...status, eval_set: null },
			'/flow/eval'
		);
		expect(nav.find((step) => step.id === 'ingest')?.state).toBe('done');
	});

	it('marks configure done from an architecture choice without an explicit flag', () => {
		const nav = buildStepNav(
			{ selected_architectures: ['hybrid'] },
			{ ...status, eval_set: null },
			'/flow/ingest'
		);
		expect(nav.find((step) => step.id === 'configure')?.state).toBe('done');
	});

	it('keeps ingest and configure pending with no artifact and no flag', () => {
		const nav = buildStepNav({}, { ...status, eval_set: null }, '/flow/eval');
		expect(nav.find((step) => step.id === 'ingest')?.state).toBe('pending');
		expect(nav.find((step) => step.id === 'configure')?.state).toBe('pending');
	});

	it('falls back to pending for unexpected step ids', () => {
		expect(getStepState('unexpected' as never, {}, status)).toBe('pending');
	});
});
