import type { Actions } from './$types';
import { operationAuthHeaders } from '$lib/server/clients/operation-api-client';
import {
	getArchitectures,
	getConfig,
	getModels,
	getStatus,
	getUiSession,
	updateUiSession
} from '$lib/server/retrieve-api';

export const load = async () => {
	const [status, session, architectures, models, config] = await Promise.all([
		getStatus(),
		getUiSession(),
		getArchitectures(),
		getModels(),
		getConfig()
	]);
	return { status, session, architectures, models, config };
};

function getString(form: FormData, key: string) {
	const value = form.get(key);
	return typeof value === 'string' ? value.trim() : '';
}

export const actions: Actions = {
	save: async ({ request }) => {
		const authHeaders = operationAuthHeaders(request);
		const form = await request.formData();
		await updateUiSession(
			{
				source: getString(form, 'source'),
				plugin: getString(form, 'plugin'),
				output: getString(form, 'output'),
				delay: getString(form, 'delay'),
				operator_context: getString(form, 'operator_context'),
				eval_mode: getString(form, 'eval_mode'),
				eval_corpus: getString(form, 'eval_corpus'),
				base_eval_set: getString(form, 'base_eval_set'),
				selected_embedding: getString(form, 'selected_embedding'),
				selected_vectorizer: getString(form, 'selected_vectorizer') || 'azure_openai',
				resource_group: getString(form, 'resource_group'),
				location: getString(form, 'location'),
				name_prefix: getString(form, 'name_prefix'),
				copilot_model: getString(form, 'copilot_model'),
				copilot_provider_type: getString(form, 'copilot_provider_type'),
				copilot_timeout: getString(form, 'copilot_timeout')
			},
			authHeaders
		);
		return { message: 'Settings saved' };
	}
};
