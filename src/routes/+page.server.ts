import type { MetricItem } from '$lib/api/types';
import { getRuns, getStatus, getUiSession } from '$lib/server/retrieve-api';
import { buildStepNav } from '$lib/workflow';

export const load = async () => {
	const [status, runs, session] = await Promise.all([getStatus(), getRuns(), getUiSession()]);
	const metrics: MetricItem[] = [
		{
			label: 'Eval set',
			value: status.eval_set?.version_label ?? 'None',
			note: 'Latest golden questions',
			href: '/eval-sets'
		},
		{
			label: 'Completed runs',
			value: String(status.run_count),
			note: 'Ready for comparison',
			href: '/runs'
		},
		{
			label: 'Architectures',
			value: String(status.architectures.length),
			note: status.architectures.length ? status.architectures.join(', ') : 'None configured'
		}
	];
	const steps = buildStepNav(session, status);

	return { status, runs, metrics, steps };
};
