import type { PageServerLoad } from './$types';
import { getRun } from '$lib/server/retrieve-api';

export const load: PageServerLoad = async ({ params }) => {
	const run = await getRun(params.id);
	return { run };
};
