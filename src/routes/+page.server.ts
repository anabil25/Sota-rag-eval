import type { MetricItem } from '$lib/api/types';
import { fail, redirect } from '@sveltejs/kit';
import type { Actions, PageServerLoad } from './$types';
import { operationAuthHeaders } from '$lib/server/clients/operation-api-client';
import { getRuns, getStatus, getUiSession, resetUiSession } from '$lib/server/retrieve-api';
import { buildStepNav } from '$lib/workflow';

export const load: PageServerLoad = async () => {
	const [status, runs, session] = await Promise.all([getStatus(), getRuns(), getUiSession()]);
	const metrics: MetricItem[] = [
		{
			label: 'Eval set',
			value: status.eval_set?.version_label ?? 'None',
			note: 'Latest golden questions',
			href: '/eval-sets'
		},
		{
			label: 'Stored runs',
			value: String(status.run_count),
			note: 'Available under Review',
			href: '/runs'
		},
		{
			label: 'Architectures',
			value: String(status.architectures.length),
			note: status.architectures.length ? status.architectures.join(', ') : 'None configured'
		}
	];
	const steps = buildStepNav(session, status);
	const currentStep = steps.find((step) => step.state === 'active' || step.state === 'error');
	const workflowComplete = steps.every((step) => step.state === 'done');

	return { status, runs, metrics, steps, session, currentStep, workflowComplete };
};

export const actions: Actions = {
	startExperiment: async ({ request }) => {
		const form = await request.formData();
		const rawMode = form.get('mode');
		if (rawMode !== 'reuse' && rawMode !== 'fresh') {
			return fail(400, { message: 'Choose how to start the experiment.' });
		}
		const result = await resetUiSession(rawMode, operationAuthHeaders(request));
		const status = await getStatus();
		const steps = buildStepNav(result.session, status);
		const next = steps.find((step) => step.state === 'active') ?? steps[0];
		redirect(303, next.href);
	}
};
