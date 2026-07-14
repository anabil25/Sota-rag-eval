export type WorkflowStepId =
	| 'ingest'
	| 'eval'
	| 'configure'
	| 'provision'
	| 'run'
	| 'compare'
	| 'teardown';

export type StepState = 'pending' | 'active' | 'done' | 'error' | 'locked';

export interface StepNavItem {
	id: WorkflowStepId;
	index: number;
	title: string;
	shortTitle: string;
	subtitle: string;
	href: string;
	state: StepState;
}

export interface EvalSet {
	id: number;
	version_label: string;
	notes?: string;
	question_count?: number;
	category_counts?: Record<string, number> | string;
	created_at?: string;
}

export interface RetrieveStatus {
	eval_set: EvalSet | null;
	run_count: number;
	architectures: string[];
	provisioned_architectures?: string[];
}

export interface RetrieveConfigSummary {
	db_path: string;
	log_level?: string;
	azure_sdk_logging?: boolean;
	architectures: string[];
	corpus: {
		source: string;
		plugin: string;
		output_dir: string;
	};
	azure: {
		resource_group: string;
		location: string;
		name_prefix: string;
		subscription_id?: string;
		deployer_object_id?: string;
	};
	copilot: {
		model: string;
		provider_type?: string;
		timeout?: number;
	};
	eval: {
		mode: string;
		categories: string[];
	};
}

export interface UiSession {
	workflow_id?: string;
	workflow_started_at?: string;
	workflow_reset_mode?: 'reuse' | 'fresh' | string;
	selected_mode?: 'test' | 'sota' | string;
	selected_sota_path?: string;
	selected_architectures?: string[];
	selected_embedding?: string;
	selected_vectorizer?: string;
	foundry_resource_group?: string;
	foundry_workspace_name?: string;
	foundry_catalog_query?: string;
	foundry_deployed_endpoint?: string;
	foundry_deployed_uri?: string;
	foundry_deployed_model_name?: string;
	foundry_deployed_dimensions?: string | number;
	foundry_deployed_vectorizer_source?: string;
	cohere_uri?: string;
	cohere_model_name?: string;
	custom_embedding_uri?: string;
	custom_embedding_dimensions?: string;
	custom_embedding_header_name?: string;
	sota_toggles?: Record<string, string | string[]>;
	sotaToggles?: Record<string, string | string[]>;
	configure_done?: boolean;
	ingest_done?: boolean;
	eval_done?: boolean;
	provision_done?: boolean;
	run_done?: boolean;
	compare_done?: boolean;
	teardown_done?: boolean;
	active_job_id?: string;
	active_job_kind?: string;
	active_job_started_at?: string;
	ingest_stats?: {
		doc_count?: number;
		avg_doc_length?: number;
		cross_ref_density?: number;
	};
	winners?: string[];
	active_eval_set?: string;
	active_experiment_id?: string;
	active_experiment_eval_set_id?: number;
	active_experiment_eval_set_version?: string;
	active_experiment_corpus_fingerprint?: string;
	active_experiment_architectures?: string[];
	pending_experiment_id?: string;
	[key: string]: unknown;
}

export interface RunSummary {
	id: number;
	eval_set_id?: number;
	eval_set_version?: string;
	architecture_name: string;
	mode?: string;
	status?: string;
	aggregate_metrics?: Record<string, number>;
	recall_at_5?: number;
	recall_at_10?: number;
	mrr_at_10?: number;
	ndcg_at_10?: number;
	avg_latency_ms?: number;
	failure_count?: number;
	miss_count?: number;
	total_questions?: number;
	created_at?: string;
	completed_at?: string;
	architecture_config?: Record<string, unknown>;
}

export interface RunResult {
	id?: number;
	question_id?: number;
	question_text?: string;
	category?: string;
	retrieved_chunk_ids?: string[];
	ground_truth_chunk_ids?: string[];
	scores?: Record<string, number>;
	latency_ms?: number;
	failure_type?: string;
	failure_details?: string;
	expected_chunk_id?: string;
	top_retrieved_id?: string;
}

export interface CategoryScore {
	category: string;
	recall_at_5?: number;
	recall_at_10?: number;
	mrr_at_10?: number;
	ndcg_at_10?: number;
	failure_count?: number;
	total_questions?: number;
}

export interface RunDetail {
	run: RunSummary;
	results: RunResult[];
	categories: CategoryScore[];
	failures: RunResult[];
}

export interface EvalQuestion {
	id: number;
	question_text: string;
	category: string;
	question_type?: string;
	persona?: string;
	intent_family?: string;
	ground_truth_chunk_ids?: string[];
	source_doc_id?: string;
}

export interface EvalQuestionBrowseResult {
	total: number;
	items: EvalQuestion[];
}

export interface EvalSummary {
	eval_set: EvalSet;
	categories: Record<string, number>;
	examples: Record<string, string[]>;
}

export interface ArchitectureDefinition {
	name?: string;
	display_name?: string;
	description?: string;
	accuracy?: string;
	cost?: string;
	latency?: string;
	best_for?: string;
	est_monthly_usd?: number;
	required_azure_resources?: string[];
	toggleable_components?: string[];
	[key: string]: unknown;
}

export interface ArchitectureStatus {
	id?: number;
	name: string;
	config?: Record<string, unknown>;
	resources_provisioned?: Record<string, unknown>;
	status: string;
	desired_status?: string;
	observed_at?: string;
	status_detail?: string;
	created_at?: string;
}

export interface CorpusFileItem {
	name: string;
	size: number;
}

export interface CorpusFilesResponse {
	output: string;
	files: CorpusFileItem[];
}

export interface ModelDefinition {
	name: string;
	dimensions?: number;
	mteb_avg?: number;
	cost_per_1m?: string;
	latency_p50?: string;
	notes?: string;
	provider?: string;
	[key: string]: unknown;
}

export interface ModelRegistry {
	embedding: Record<string, ModelDefinition>;
	reranker: Record<string, ModelDefinition>;
}

export interface FoundryEmbeddingItem {
	name: string;
	label?: string;
	provider?: string;
	dimensions?: number;
	vectorizer_source?: string;
	model_id?: string;
	uri?: string;
	deployable?: boolean;
	source?: string;
}

export interface FoundryEmbeddingResponse {
	items: FoundryEmbeddingItem[];
	errors?: string[];
}

export interface SotaComponentOption {
	name: string;
	label?: string;
	description?: string;
	default?: string;
	options?: string[];
	[key: string]: unknown;
}

export interface SotaPathDefinition {
	name: string;
	description?: string;
	base_architecture?: string;
	components?: SotaComponentOption[];
	[key: string]: unknown;
}

export interface SotaRecommendation {
	recommended_sota: SotaPathDefinition | null;
	rationale: string;
}

export interface DeploymentSummary {
	architecture_name: string;
	status?: string;
	handoff_kind?: string;
	endpoint?: string;
	index_name?: string;
	query_target?: string;
	artifact_prefix?: string;
	working_dir?: string;
	handoff_note?: string;
	resource_group?: string;
	location?: string;
	est_monthly_usd?: number;
}

export interface CompareContext {
	runs: RunSummary[];
	categories: Record<string, Record<string, Record<string, number>>>;
	failures: Record<string, RunResult[]>;
	latest_eval: EvalSet | null;
	experiment_id?: string;
	selected_mode: string;
	arch_costs: Record<string, number>;
	winners: string[];
	deployments: DeploymentSummary[];
}

export type JobKind =
	| 'ingest'
	| 'eval_generate'
	| 'provision'
	| 'provision_index'
	| 'index'
	| 'evaluate'
	| 'teardown'
	| 'deploy_foundry_embedding';

export interface JobStartResponse {
	job_id: string;
	kind: JobKind | string;
	operation_id: string;
}

export interface JobStatus {
	id: string;
	kind: JobKind | string;
	operation_id: string;
	done: boolean;
	error: string;
	result: Record<string, unknown>;
}

export interface CsvExportResponse {
	status: string;
	rows: number;
	output: string;
}

export interface CsvImportResponse {
	status: string;
	eval_set_id: number;
	imported: number;
}

export interface CurateEvalResponse {
	status: string;
	eval_set_id: number;
}

export interface MetricItem {
	label: string;
	value: string;
	note?: string;
	tone?: 'neutral' | 'success' | 'warning' | 'danger';
	href?: string;
}
