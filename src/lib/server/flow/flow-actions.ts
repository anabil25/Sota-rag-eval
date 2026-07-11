import { fail, redirect } from '@sveltejs/kit';
import {
	curateEvalSet,
	exportEvalCsv,
	importEvalCsv,
	startJob,
	updateUiSession
} from '$lib/server/retrieve-api';
import { operationAuthHeaders } from '$lib/server/clients/operation-api-client';
import {
	collectArchitectureOptions,
	collectArgs,
	getBool,
	getString,
	getStrings
} from './form-parsers';
import { startStateForJob } from './progress-rules';

export const flowActions = {
	startJob: async ({ request }: { request: Request }) => {
		const authHeaders = operationAuthHeaders(request);
		const form = await request.formData();
		const kind = getString(form, 'kind');
		if (!kind) return fail(400, { message: 'Job kind is required' });

		const args = collectArgs(form, ['kind']);
		const startedAt = new Date().toISOString();
		await updateUiSession(
			{
				...args,
				...startStateForJob(kind),
				active_job_id: '',
				active_job_kind: kind,
				active_job_started_at: startedAt
			},
			authHeaders
		);
		const job = await startJob(kind, args, authHeaders);
		return { message: `Started ${kind}`, job };
	},

	saveDraft: async ({ request }: { request: Request }) => {
		const authHeaders = operationAuthHeaders(request);
		const form = await request.formData();
		await updateUiSession(collectArgs(form), authHeaders);
		return { message: 'Draft saved' };
	},

	saveConfigure: async ({ request }: { request: Request }) => {
		const authHeaders = operationAuthHeaders(request);
		const form = await request.formData();
		const selected_mode = getString(form, 'selected_mode', 'test');
		if (selected_mode === 'sota') {
			const selected_sota_path = getString(form, 'selected_sota_path');
			const sota_toggles: Record<string, string[]> = {};
			for (const key of new Set(form.keys())) {
				if (!key.startsWith('sota__')) continue;
				const component = key.slice('sota__'.length);
				sota_toggles[component] = form
					.getAll(key)
					.filter((value): value is string => typeof value === 'string');
			}
			await updateUiSession(
				{
					selected_mode,
					selected_sota_path,
					sota_toggles,
					sotaToggles: sota_toggles,
					configure_done: true,
					provision_done: false,
					run_done: false,
					compare_done: false,
					winners: []
				},
				authHeaders
			);
			redirect(303, '/flow/provision');
		}

		const selected_architectures = form
			.getAll('selected_architectures')
			.filter((value): value is string => typeof value === 'string');
		const selected_embedding = getString(form, 'selected_embedding', 'text-embedding-3-large');
		const selected_vectorizer = getString(form, 'selected_vectorizer', 'azure_openai');
		await updateUiSession(
			{
				selected_mode,
				selected_architectures,
				selected_embedding,
				selected_vectorizer,
				foundry_resource_group: getString(form, 'foundry_resource_group'),
				foundry_workspace_name: getString(form, 'foundry_workspace_name'),
				foundry_catalog_query: getString(form, 'foundry_catalog_query'),
				selected_foundry_catalog_model: getString(form, 'selected_foundry_catalog_model'),
				foundry_endpoint_name: getString(form, 'foundry_endpoint_name'),
				foundry_deployed_endpoint: getString(form, 'foundry_deployed_endpoint'),
				foundry_deployed_uri: getString(form, 'foundry_deployed_uri'),
				foundry_deployed_model_name: getString(form, 'foundry_deployed_model_name'),
				foundry_deployed_dimensions: getString(form, 'foundry_deployed_dimensions'),
				foundry_deployed_vectorizer_source: getString(form, 'foundry_deployed_vectorizer_source'),
				cohere_uri: getString(form, 'cohere_uri'),
				cohere_model_name: getString(form, 'cohere_model_name'),
				custom_embedding_uri: getString(form, 'custom_embedding_uri'),
				custom_embedding_dimensions: getString(form, 'custom_embedding_dimensions'),
				custom_embedding_header_name: getString(form, 'custom_embedding_header_name', 'api-key'),
				query_syntax: getString(form, 'query_syntax', 'simple'),
				lexical_search_mode: getString(form, 'lexical_search_mode', 'any'),
				search_fields: getString(form, 'search_fields', 'content,title'),
				filter_expression: getString(form, 'filter_expression'),
				scoring_profile: getString(form, 'scoring_profile'),
				top_k: getString(form, 'top_k', '10'),
				vector_k: getString(form, 'vector_k', '50'),
				vector_filter_mode: getString(form, 'vector_filter_mode', 'preFilter'),
				vector_weight: getString(form, 'vector_weight', '1'),
				max_text_recall_size: getString(form, 'max_text_recall_size', '1000'),
				vector_exhaustive: getBool(form, 'vector_exhaustive'),
				semantic_ranker_mode: getString(form, 'semantic_ranker_mode', 'auto'),
				semantic_captions: getString(form, 'semantic_captions', 'none'),
				semantic_answers: getString(form, 'semantic_answers', 'none'),
				query_rewrites: getString(form, 'query_rewrites', 'none'),
				semantic_max_wait_ms: getString(form, 'semantic_max_wait_ms', '1000'),
				chunk_size: getString(form, 'chunk_size', '2000'),
				chunk_overlap: getString(form, 'chunk_overlap', '500'),
				markdown_parsing_submode: getString(form, 'markdown_parsing_submode', 'oneToMany'),
				enrichment_profile: getString(form, 'enrichment_profile', 'none'),
				graphrag_index_method: getString(form, 'graphrag_index_method', 'fast'),
				graphrag_query_mode: getString(form, 'graphrag_query_mode', 'local'),
				agentic_knowledge_source: getString(form, 'agentic_knowledge_source', 'search-index'),
				agentic_reasoning_effort: getString(form, 'agentic_reasoning_effort', 'low'),
				agentic_output_mode: getString(form, 'agentic_output_mode', 'extractiveData'),
				agentic_max_runtime_seconds: getString(form, 'agentic_max_runtime_seconds', '30'),
				agentic_include_activity: getBool(form, 'agentic_include_activity'),
				lightrag_query_mode: getString(form, 'lightrag_query_mode', 'mix'),
				lightrag_storage_profile: getString(form, 'lightrag_storage_profile', 'eval-local'),
				architecture_options: collectArchitectureOptions(form),
				configure_done: true,
				provision_done: false,
				run_done: false,
				compare_done: false,
				winners: []
			},
			authHeaders
		);
		redirect(303, '/flow/provision');
	},

	saveWinners: async ({ request }: { request: Request }) => {
		const authHeaders = operationAuthHeaders(request);
		const form = await request.formData();
		const winners = form
			.getAll('winners')
			.filter((value): value is string => typeof value === 'string');
		await updateUiSession({ winners, compare_done: true, teardown_done: false }, authHeaders);
		redirect(303, '/flow/teardown');
	},

	exportCsv: async ({ request }: { request: Request }) => {
		const authHeaders = operationAuthHeaders(request);
		const form = await request.formData();
		const eval_set = getString(form, 'eval_set', 'latest');
		const output = getString(form, 'output', 'eval_questions.csv');
		const result = await exportEvalCsv(eval_set, output, authHeaders);
		return { message: `Exported ${result.rows} rows to ${result.output}` };
	},

	importCsv: async ({ request }: { request: Request }) => {
		const authHeaders = operationAuthHeaders(request);
		const form = await request.formData();
		const input = getString(form, 'input', 'eval_questions.csv');
		const version = getString(form, 'version', 'v-imported');
		const base_eval_set = getString(form, 'base_eval_set', 'latest');
		const fresh = getBool(form, 'fresh');
		const result = await importEvalCsv(input, version, base_eval_set, fresh, authHeaders);
		await updateUiSession(
			{ eval_done: true, run_done: false, compare_done: false, winners: [] },
			authHeaders
		);
		return { message: `Imported ${result.imported} questions into eval set ${result.eval_set_id}` };
	},

	curateEval: async ({ request }: { request: Request }) => {
		const authHeaders = operationAuthHeaders(request);
		const form = await request.formData();
		const source_version = getString(form, 'source_version', 'latest');
		const new_version = getString(form, 'new_version', `${source_version}-curated`);
		const corpus = getString(form, 'corpus', 'corpus');
		const steering = {
			more: getStrings(form, 'more'),
			fewer: getStrings(form, 'fewer'),
			add_categories: getStrings(form, 'add_categories'),
			remove_categories: getStrings(form, 'remove_categories'),
			question_types: getStrings(form, 'question_types'),
			notes: getString(form, 'notes')
		};
		const result = await curateEvalSet(
			{ source_version, new_version, corpus, steering },
			authHeaders
		);
		await updateUiSession(
			{ eval_done: true, run_done: false, compare_done: false, winners: [] },
			authHeaders
		);
		return { message: `Curated eval set ${result.eval_set_id}` };
	}
};
