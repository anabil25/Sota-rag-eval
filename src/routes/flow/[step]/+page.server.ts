import type { Actions, PageServerLoad } from './$types';
import { flowActions } from '$lib/server/flow/flow-actions';
import { loadFlowStep } from '$lib/server/flow/load-flow-step';

export const load: PageServerLoad = async ({ params }) => loadFlowStep(params.step);

export const actions: Actions = flowActions;
