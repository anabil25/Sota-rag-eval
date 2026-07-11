import { getEvalSets } from '$lib/server/retrieve-api';

export const load = async () => {
	const evalSets = await getEvalSets();
	return { evalSets };
};
