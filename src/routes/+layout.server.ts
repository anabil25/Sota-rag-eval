import type { LayoutServerLoad } from './$types';
import { buildStepNav } from '$lib/workflow';
import { getStatus, getUiSession } from '$lib/server/retrieve-api';

export const load: LayoutServerLoad = async ({ url }) => {
	const [status, session] = await Promise.all([getStatus(), getUiSession()]);

	return {
		status,
		session,
		steps: buildStepNav(session, status),
		currentPath: url.pathname
	};
};
