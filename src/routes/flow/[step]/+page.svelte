<script lang="ts">
	import { resolve } from '$app/paths';
	import { invalidateAll } from '$app/navigation';
	import { workflowSteps } from '$lib/workflow';
	import JobProgressStream from '$lib/components/JobProgressStream.svelte';
	import MetricGrid from '$lib/components/MetricGrid.svelte';
	import RouteHeader from '$lib/components/RouteHeader.svelte';
	import { evalTaxonomyWithCustom, getEvalTaxonomyItem } from '$lib/eval-taxonomy';
	import {
		estimateArchitectureEvalCost,
		estimateExperimentEvalCost,
		estimateMonthlyProductionCost,
		formatUsd,
		pricingInputsFromCorpus
	} from '$lib/pricing';
	import {
		advancedControlHelp,
		advancedOptionHelp,
		agenticSearchKeys,
		aiSearchExperimentKeys,
		architecturePresentation,
		architectureResourceFallback,
		azureServiceCatalog,
		buildRowControls,
		experimentPresets,
		graphRetrievalKeys,
		searchBaselineResources
	} from '$lib/flow/configure-model';
	import type {
		ArchitectureOptionValue,
		ArchitectureOptions,
		ExperimentPreset,
		ExperimentPresetId,
		RowControl
	} from '$lib/flow/configure-model';
	import type {
		ArchitectureStatus,
		ArchitectureDefinition,
		JobKind,
		MetricItem,
		RunResult,
		RunSummary,
		SotaComponentOption
	} from '$lib/api/types';

	let { data, form } = $props();
	let pendingJobKind = $state<string | null>(null);
	let pendingJobToken = $state(0);

	const formJobId = $derived(typeof form?.job?.job_id === 'string' ? form.job.job_id : '');
	const formJobKind = $derived(typeof form?.job?.kind === 'string' ? form.job.kind : '');
	const effectivePendingJobKind = $derived(formJobId ? null : pendingJobKind);
	const sessionJobId = $derived(sessionString('active_job_id'));
	const sessionJobKind = $derived(sessionString('active_job_kind'));
	const streamResetKey = $derived(`${pendingJobToken}:${formJobId}:${sessionJobId}`);
	const provisionLifecycleJobKinds = ['provision', 'provision_index', 'index'];

	function submittedJobKind(event: SubmitEvent): string {
		const submitter = event.submitter;
		if (
			(submitter instanceof HTMLButtonElement || submitter instanceof HTMLInputElement) &&
			submitter.name === 'kind'
		) {
			return submitter.value;
		}
		const formElement = event.currentTarget;
		if (formElement instanceof HTMLFormElement) {
			const value = new FormData(formElement).get('kind');
			return typeof value === 'string' ? value : '';
		}
		return '';
	}

	function handleStartJobSubmit(event: SubmitEvent) {
		const kind = submittedJobKind(event);
		if (!kind) return;
		pendingJobKind = kind;
		pendingJobToken += 1;
	}

	function streamJobId(kinds: Array<JobKind | string>): string | undefined {
		if (effectivePendingJobKind && kinds.includes(effectivePendingJobKind)) return undefined;
		if (formJobId && (!formJobKind || kinds.includes(formJobKind))) return formJobId;
		if (sessionJobId && kinds.includes(sessionJobKind)) return sessionJobId;
		return undefined;
	}

	function streamPending(kinds: Array<JobKind | string>): boolean {
		return effectivePendingJobKind != null && kinds.includes(effectivePendingJobKind);
	}

	function architectureStatusRows() {
		return effectivePendingJobKind && provisionLifecycleJobKinds.includes(effectivePendingJobKind)
			? []
			: data.architectureStatus;
	}

	function shortHandle(value: unknown): string {
		const text = typeof value === 'string' ? value : '';
		return text.length > 12 ? `${text.slice(0, 8)}...` : text;
	}

	function architectureIndexLabel(architecture: ArchitectureStatus): string {
		const config = architecture.config ?? {};
		if (typeof config.graph_worker_job_id === 'string' && config.graph_worker_job_id) {
			if (config.cloud_index_status === 'failed') {
				return `GraphRAG indexing failed · ${config.cloud_index_error ?? 'check worker logs'}`;
			}
			const estimate =
				typeof config.graph_worker_estimate === 'string'
					? config.graph_worker_estimate
					: '20-90 minutes for large corpora';
			return `GraphRAG background job ${shortHandle(config.graph_worker_job_id)} · ${estimate}`;
		}
		if (Array.isArray(config.lightrag_track_ids) && config.lightrag_track_ids.length > 0) {
			if (config.cloud_index_status === 'failed') {
				return `LightRAG indexing failed · ${config.cloud_index_error ?? 'check server logs'}`;
			}
			const estimate =
				typeof config.lightrag_estimate === 'string'
					? config.lightrag_estimate
					: '10-60 minutes after batches are accepted';
			return `LightRAG background ${config.lightrag_track_ids.length} batches · ${estimate}`;
		}
		return typeof config.index_name === 'string' ? config.index_name : 'n/a';
	}

	function streamKey(scope: string, kinds: Array<JobKind | string>): string {
		return `${scope}:${streamResetKey}:${streamJobId(kinds) ?? ''}:${streamPending(kinds)}`;
	}

	async function refreshAfterJob() {
		pendingJobKind = null;
		await invalidateAll();
	}

	const evalMetrics = $derived<MetricItem[]>([
		{
			label: 'Questions',
			value: String(data.status.eval_set?.question_count ?? data.questions.length),
			note: 'In current set'
		},
		{ label: 'Runs', value: String(data.runs.length), note: 'Evaluation history' },
		{
			label: 'Architectures',
			value: String(Object.keys(data.architectures).length),
			note: 'Available variants'
		}
	]);

	let selectedSotaPath = $state(initialSelectedSotaPath());
	const currentEvalVersion = $derived(
		data.status.eval_set?.version_label ?? data.evalSets[0]?.version_label ?? 'latest'
	);
	// Run-step eval selection: defaults to the set saved in step 2, but editable
	// here so a run can target any saved version without leaving the page.
	let runEvalVersion = $state(initialRunEvalVersion());
	const nextEvalVersionSuggestion = $derived(
		`v${Math.max(0, ...data.evalSets.map((set) => set.id)) + 1}`
	);
	const evalGenerationMode = $derived(
		sessionString('eval_mode', data.config.eval.mode || 'sample')
	);
	const evalCorpus = $derived(sessionString('eval_corpus', 'corpus'));
	const baseEvalSet = $derived(sessionString('base_eval_set', 'latest'));
	const selectedMode = $derived(String(data.session.selected_mode || 'test'));
	const selectedSota = $derived(data.sotaPaths[selectedSotaPath]);
	const compareContext = $derived(data.compareContext);
	const compareRuns = $derived(compareContext?.runs ?? data.runs);
	const compareFailures = $derived(compareContext?.failures ?? {});
	const compareCategories = $derived(compareContext?.categories ?? {});
	const deployments = $derived(compareContext?.deployments ?? []);
	const categoryNames = $derived(
		Array.from(
			new Set(
				Object.values(compareCategories).flatMap((categoryMap) => Object.keys(categoryMap ?? {}))
			)
		).sort()
	);

	const compareMetricOptions = [
		{ key: 'ndcg_at_10' as const, label: 'nDCG@10' },
		{ key: 'recall_at_10' as const, label: 'Recall@10' },
		{ key: 'mrr_at_10' as const, label: 'MRR@10' }
	];
	type ComparePrimaryMetric = (typeof compareMetricOptions)[number]['key'];
	let comparePrimaryMetric = $state<ComparePrimaryMetric>('ndcg_at_10');
	let promotedWinners = $state<string[]>(initialPromotedWinners());
	const comparePrimaryLabel = $derived(
		compareMetricOptions.find((option) => option.key === comparePrimaryMetric)?.label ?? 'nDCG@10'
	);
	const rankedCompareRuns = $derived(
		[...compareRuns].sort(
			(a, b) =>
				(metricNumber(b, comparePrimaryMetric) ?? -1) -
				(metricNumber(a, comparePrimaryMetric) ?? -1)
		)
	);
	const compareWinner = $derived(rankedCompareRuns[0]);
	const compareRunnerUp = $derived(rankedCompareRuns[1]);
	const compareWinnerDelta = $derived(
		compareWinner && compareRunnerUp
			? (metricNumber(compareWinner, comparePrimaryMetric) ?? 0) -
					(metricNumber(compareRunnerUp, comparePrimaryMetric) ?? 0)
			: 0
	);
	const compareWinnerStrengths = $derived(
		compareWinner
			? categoryNames
					.filter(
						(category) =>
							categoryLeader(category)?.id === compareWinner.id &&
							(categoryScore(compareWinner, category) ?? 0) > 0
					)
					.slice(0, 3)
			: []
	);

	function bestMetricValue(key: string) {
		let best = -Infinity;
		for (const run of compareRuns) {
			const value = metricNumber(run, key);
			if (typeof value === 'number' && value > best) best = value;
		}
		return best;
	}

	function initialPromotedWinners() {
		return [...(data.session.winners ?? [])];
	}

	function isBestMetric(run: RunSummary, key: string) {
		if (compareRuns.length < 2) return false;
		const value = metricNumber(run, key);
		return typeof value === 'number' && value === bestMetricValue(key);
	}

	function isBestLatency(run: RunSummary) {
		if (compareRuns.length < 2) return false;
		const value = metricNumber(run, 'avg_latency_ms');
		if (typeof value !== 'number') return false;
		let best = Infinity;
		for (const candidate of compareRuns) {
			const candidateValue = metricNumber(candidate, 'avg_latency_ms');
			if (typeof candidateValue === 'number' && candidateValue < best) best = candidateValue;
		}
		return value === best;
	}

	function categoryLeader(category: string) {
		let leader: RunSummary | undefined;
		let best = -Infinity;
		for (const run of compareRuns) {
			const score = categoryScore(run, category) ?? -1;
			if (score > best) {
				best = score;
				leader = run;
			}
		}
		return leader;
	}

	function humanizeLabel(value: string) {
		return value.replace(/[_-]+/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
	}

	function compareCategoryLabel(category: string) {
		const item = getEvalTaxonomyItem(category);
		return item.label && item.label !== category ? item.label : humanizeLabel(category);
	}

	function compareCategoryDescription(category: string) {
		return getEvalTaxonomyItem(category).description ?? '';
	}

	function categoryHeatTone(score: number | undefined) {
		if (typeof score !== 'number') return 'empty';
		if (score >= 0.8) return 'high';
		if (score >= 0.6) return 'mid';
		if (score >= 0.4) return 'low';
		return 'poor';
	}

	let ingestPlugin = $state(initialIngestPlugin());
	let ingestSource = $state(initialIngestSource());
	let ingestOutput = $state(initialIngestOutput());
	let ingestDelay = $state(sessionString('delay', '0.5'));
	const corpusDocCount = $derived(
		data.session.ingest_stats?.doc_count ?? data.corpusFiles.files.length
	);
	const corpusBytes = $derived(
		data.corpusFiles.files.reduce((sum: number, file) => sum + (file.size ?? 0), 0)
	);
	const corpusTokenEstimate = $derived(
		Math.max(1, Math.round(corpusBytes / 4) || Math.max(1, corpusDocCount || 100) * 2500)
	);
	const provisionPricingInputs = $derived(
		pricingInputsFromCorpus({
			corpusDocuments: Math.max(1, corpusDocCount || data.corpusFiles.files.length || 100),
			corpusTokens: corpusTokenEstimate,
			evalQuestions: data.status.eval_set?.question_count ?? data.questions.length ?? 25,
			storageGb: Math.max(1, Math.ceil(corpusBytes / 1024 ** 3)),
			searchHours: 4
		})
	);
	const corpusReady = $derived(
		Boolean(data.session.ingest_done) || corpusDocCount > 0 || data.corpusFiles.files.length > 0
	);
	let operatorContext = $state(sessionString('operator_context'));
	const selectedVectorizer = 'azure_openai';
	let selectedEmbedding = $state(initialOpenAiEmbedding());
	let provisionResourceGroup = $state(initialProvisionResourceGroup());
	let provisionLocation = $state(initialProvisionLocation());
	let selectedArchitectureKeys = $state<string[]>(initialArchitectures());
	let architectureOptions = $state<ArchitectureOptions>(initialArchitectureOptions());
	let chatInput = $state('');
	let chatBusy = $state(false);
	let chatStatus = $state('');
	let sotaSelections = $state<Record<string, string[]>>({});
	let evalAdvancedOpen = $state(false);
	let evalCsvMode = $state<'export' | 'import'>('export');
	let evalCurateOpen = $state(false);
	let curateAdvancedOpen = $state(false);
	let evalSetModeOverride = $state<'existing' | 'new' | null>(null);
	const evalSetMode = $derived<'existing' | 'new'>(
		evalSetModeOverride ?? (data.evalSets.length > 0 ? 'existing' : 'new')
	);
	let evalSwitchBusy = $state(false);
	let evalSwitchStatus = $state('');

	async function switchActiveEvalSet(versionLabel: string) {
		if (!versionLabel || versionLabel === currentEvalVersion) return;
		evalSwitchBusy = true;
		evalSwitchStatus = 'Switching...';
		try {
			const response = await fetch(resolve('/api/ui/session'), {
				method: 'POST',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify({ active_eval_set: versionLabel })
			});
			if (response.ok) {
				await invalidateAll();
				evalSwitchStatus = '';
			} else {
				evalSwitchStatus = 'Switch failed';
			}
		} catch (err) {
			evalSwitchStatus = err instanceof Error ? err.message : 'Switch failed';
		} finally {
			evalSwitchBusy = false;
		}
	}

	const curateCategories = $derived(evalTaxonomyWithCustom(data.questions.map((q) => q.category)));
	const curateQTypes = $derived(evalTaxonomyWithCustom(data.questions.map((q) => q.question_type)));

	// Per-category mix intent for the curate form. 'keep' is the no-op default.
	type MixIntent = 'more' | 'keep' | 'fewer' | 'remove';
	let categoryMix = $state<Record<string, MixIntent>>({});
	const mixOf = (id: string): MixIntent => categoryMix[id] ?? 'keep';
	function setMix(id: string, intent: MixIntent) {
		categoryMix = { ...categoryMix, [id]: intent };
	}

	let selectedExperimentPreset = $state<ExperimentPresetId>(initialExperimentPreset());

	function searchArchitectures() {
		return Object.entries(data.architectures).filter(([key]) => aiSearchExperimentKeys.has(key));
	}

	function agenticSearchArchitectures() {
		return Object.entries(data.architectures).filter(([key]) => agenticSearchKeys.has(key));
	}

	function graphRetrievalArchitectures() {
		return Object.entries(data.architectures).filter(([key]) => graphRetrievalKeys.has(key));
	}

	function needsEmbeddings() {
		// keyword is the only search mode that doesn't use embeddings
		const selected = currentArchitectures();
		return (
			selected.filter((key) => key !== 'keyword' && Boolean(data.architectures[key])).length > 0
		);
	}

	function currentArchitectures() {
		return selectedArchitectureKeys.length ? selectedArchitectureKeys : data.status.architectures;
	}

	// Run-step readiness: an architecture can only be evaluated once its Azure
	// resources are actually provisioned. The real per-architecture status comes
	// from the DB (data.architectureStatus), so the Run page never starts a job
	// that would fail against a search service that was never deployed.
	function architectureProvisionState(name: string): string {
		return data.architectureStatus.find((row) => row.name === name)?.status ?? 'registered';
	}

	function architectureCloudIndexStatus(name: string): string {
		const row = data.architectureStatus.find((item) => item.name === name);
		return typeof row?.config?.cloud_index_status === 'string' ? row.config.cloud_index_status : '';
	}

	function architectureBackgroundIndexing(name: string): boolean {
		return architectureCloudIndexStatus(name) === 'started';
	}

	function architectureCloudIndexFailed(name: string): boolean {
		return architectureCloudIndexStatus(name) === 'failed';
	}

	function isArchitectureIndexed(name: string): boolean {
		return architectureProvisionState(name) === 'active';
	}

	function isArchitectureRunnable(name: string): boolean {
		return (
			isArchitectureIndexed(name) &&
			!architectureBackgroundIndexing(name) &&
			!architectureCloudIndexFailed(name)
		);
	}

	function provisionedRunArchitectures() {
		return currentArchitectures().filter(isArchitectureRunnable);
	}

	function unprovisionedRunArchitectures() {
		return currentArchitectures().filter((name) => !isArchitectureRunnable(name));
	}

	function initialArchitectures() {
		return data.session.selected_architectures?.length
			? [...data.session.selected_architectures]
			: [...data.status.architectures];
	}

	function availableArchitectureKeys(keys: string[]) {
		return keys.filter((key) => Boolean(data.architectures[key]));
	}

	function sameArchitectureSet(left: string[], right: string[]) {
		if (left.length !== right.length) return false;
		const rightSet = new Set(right);
		return left.every((key) => rightSet.has(key));
	}

	function initialExperimentPreset(): ExperimentPresetId {
		const selected = initialArchitectures();
		for (const preset of experimentPresets) {
			if (sameArchitectureSet(selected, availableArchitectureKeys(preset.architectures))) {
				return preset.id;
			}
		}
		return 'custom';
	}

	function applyExperimentPreset(preset: ExperimentPreset) {
		selectedExperimentPreset = preset.id;
		selectedArchitectureKeys = availableArchitectureKeys(preset.architectures);
	}

	function markCustomPreset() {
		selectedExperimentPreset = 'custom';
	}

	function initialSelectedSotaPath() {
		return String(data.session.selected_sota_path || Object.keys(data.sotaPaths)[0] || '');
	}

	function sessionString(key: string, fallback = '') {
		const value = data.session[key];
		if (typeof value === 'number') return String(value);
		return typeof value === 'string' && value.trim() ? value : fallback;
	}

	function initialIngestPlugin() {
		return sessionString('plugin', data.config.corpus.plugin || 'html');
	}

	function initialIngestSource() {
		return sessionString('source', data.config.corpus.source || 'corpus');
	}

	function initialIngestOutput() {
		return sessionString('output', data.config.corpus.output_dir || 'corpus');
	}

	function initialProvisionResourceGroup() {
		return sessionString('resource_group', data.config.azure.resource_group || '');
	}

	function initialProvisionLocation() {
		return sessionString('location', data.config.azure.location || 'eastus');
	}

	function initialRunEvalVersion() {
		return data.status.eval_set?.version_label ?? data.evalSets[0]?.version_label ?? 'latest';
	}

	function initialArchitectureOptions() {
		const raw = data.session.architecture_options;
		const parsed: ArchitectureOptions = {};
		if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return parsed;
		for (const [architecture, values] of Object.entries(raw as Record<string, unknown>)) {
			if (!values || typeof values !== 'object' || Array.isArray(values)) continue;
			parsed[architecture] = {};
			for (const [field, value] of Object.entries(values as Record<string, unknown>)) {
				if (typeof value === 'boolean') parsed[architecture][field] = value;
				else if (typeof value === 'string' || typeof value === 'number') {
					parsed[architecture][field] = String(value);
				}
			}
		}
		return parsed;
	}

	function advancedName(architecture: string, field: string) {
		return `advanced__${architecture}__${field}`;
	}

	function setArchitectureOption(
		architecture: string,
		field: string,
		value: ArchitectureOptionValue
	) {
		architectureOptions[architecture] = {
			...(architectureOptions[architecture] ?? {}),
			[field]: value
		};
	}

	function architectureOption(
		architecture: string,
		field: string,
		fallback: ArchitectureOptionValue
	) {
		return architectureOptions[architecture]?.[field] ?? fallback;
	}

	function optionString(architecture: string, control: RowControl) {
		const value = architectureOption(architecture, control.field, control.fallback);
		return typeof value === 'boolean' ? String(value) : value;
	}

	function optionBoolean(architecture: string, control: RowControl) {
		const value = architectureOption(architecture, control.field, control.fallback);
		return typeof value === 'boolean' ? value : value === 'true';
	}

	function controlHelpText(control: RowControl) {
		return advancedControlHelp[control.field] ?? 'Controls this advanced experiment option.';
	}

	function optionHelpText(control: RowControl, option: { value: string; label: string }) {
		return advancedOptionHelp[control.field]?.[option.value] ?? controlHelpText(control);
	}

	function rowControls(architecture: string): RowControl[] {
		return buildRowControls(architecture, sessionString);
	}

	function isArchitectureSelected(key: string) {
		return currentArchitectures().includes(key);
	}

	function architectureDisplayName(key: string, architecture?: ArchitectureDefinition) {
		return (
			architecturePresentation[key]?.name ?? architecture?.display_name ?? architecture?.name ?? key
		);
	}

	function architectureSummary(key: string, architecture?: ArchitectureDefinition) {
		return architecturePresentation[key]?.summary ?? architecture?.description ?? '';
	}

	function architectureBusinessValue(key: string) {
		return architecturePresentation[key]?.businessValue ?? '';
	}

	function architectureFamily(key: string) {
		if (aiSearchExperimentKeys.has(key)) return 'Classic search';
		if (agenticSearchKeys.has(key)) return 'Agentic Search';
		if (key === 'graphrag' || key === 'lightrag') return 'Graph retrieval';
		if (key === 'multi-vector') return 'Advanced vector retrieval';
		return 'Separate retrieval system';
	}

	function graphCardDefault(key: string) {
		if (key === 'graphrag') {
			return 'Default: fast index + local search. Open Advanced for global, DRIFT, community, and storage controls.';
		}
		if (key === 'lightrag') {
			return 'Default: mix mode. Open Advanced for local/global/hybrid modes, top-K, reranking, and storage profile.';
		}
		return '';
	}

	function architectureUses(key: string) {
		const embedding = selectedEmbedding || 'selected embedding';
		const uses: Record<string, string[]> = {
			keyword: ['full-text search', 'BM25 lexical ranking'],
			'single-vector': ['vector search', embedding],
			hybrid: ['full-text search', 'vector search', embedding, 'hybrid fusion'],
			'hybrid-reranker': ['full-text search', 'vector search', embedding, 'semantic ranker'],
			'hybrid-llm-enriched': [
				'full-text search',
				'vector search',
				embedding,
				'index-time enrichment',
				'semantic ranker'
			],
			'multi-vector': ['multiple vector fields', embedding, 'advanced vector retrieval'],
			'agentic-kb': ['knowledge base', 'query planning', 'parallel subqueries'],
			graphrag: [
				'entity + relationship extraction',
				'hierarchical community detection',
				'community reports',
				'global / local / DRIFT search'
			],
			lightrag: [
				'entity-relation graph',
				'vector chunks',
				`${rowValue('lightrag', 'lightrag_query_mode', 'mix')} query mode`,
				'optional reranking'
			]
		};
		return uses[key] ?? ['custom retrieval path'];
	}

	function architectureExcludes(key: string) {
		const excludes: Record<string, string[]> = {
			keyword: ['embeddings', 'vector search', 'semantic ranker', 'graph traversal'],
			'single-vector': ['keyword matching', 'semantic ranker', 'graph traversal'],
			hybrid: ['semantic ranker', 'graph traversal', 'query planning'],
			'hybrid-reranker': ['graph traversal', 'query planning'],
			'hybrid-llm-enriched': ['graph traversal', 'query planning'],
			'multi-vector': ['graph traversal', 'query planning'],
			'agentic-kb': ['graph traversal unless configured as a source'],
			graphrag: ['plain AI Search mode semantics', 'LightRAG built-in server/UI'],
			lightrag: [
				'community detection',
				'community reports',
				'native AI Search vector store adapter'
			]
		};
		return excludes[key] ?? [];
	}

	function selectedArchitectureEntries() {
		return currentArchitectures()
			.map((key) => [key, data.architectures[key]] as const)
			.filter(([, architecture]) => Boolean(architecture));
	}

	function naturalList(items: string[]) {
		if (items.length === 0) return '';
		if (items.length === 1) return items[0];
		if (items.length === 2) return `${items[0]} and ${items[1]}`;
		return `${items.slice(0, -1).join(', ')}, and ${items[items.length - 1]}`;
	}

	function rowValue(architecture: string, field: string, fallback: string) {
		const value = architectureOptions[architecture]?.[field];
		if (typeof value === 'boolean') return String(value);
		return value ?? fallback;
	}

	function aiSearchLeverSummary(keys: string[]) {
		const levers: string[] = [];
		if (keys.includes('single-vector')) levers.push('pure vector search');
		if (keys.includes('hybrid')) levers.push('keyword-vector fusion');
		if (keys.includes('hybrid-reranker')) levers.push('semantic reranking');
		if (keys.includes('hybrid-llm-enriched')) levers.push('index-time enrichment');
		if (levers.length === 0) return 'plain keyword matching';
		return naturalList(levers);
	}

	function configureSummary() {
		const keys = currentArchitectures().filter((key) => Boolean(data.architectures[key]));
		const count = currentArchitectures().length;
		const aiSearchKeys = keys.filter((key) => aiSearchExperimentKeys.has(key));
		const agenticKeys = keys.filter((key) => agenticSearchKeys.has(key));
		const graphKeys = keys.filter((key) => graphRetrievalKeys.has(key));
		const aiSearchNames = aiSearchKeys.map((key) =>
			architectureDisplayName(key, data.architectures[key])
		);
		const agenticNames = agenticKeys.map((key) =>
			architectureDisplayName(key, data.architectures[key])
		);
		const graphNames = graphKeys.map((key) =>
			architectureDisplayName(key, data.architectures[key])
		);
		const candidateNames = keys.map((key) => architectureDisplayName(key, data.architectures[key]));
		if (count === 0) {
			return {
				headline: 'Pick at least one candidate to create a measurement plan.',
				body: 'Nothing leaves this page yet. Choose a preset or add candidates manually, then Retrieve will explain the exact comparison before you continue.'
			};
		}

		if (keys.length === 2 && keys.includes('keyword') && keys.includes('hybrid')) {
			return {
				headline: 'You are checking whether Hybrid beats the Keyword baseline.',
				body: `Keyword shows what plain text matching gets you. Hybrid keeps that keyword signal and adds vector similarity with ${selectedEmbedding}, so the run answers whether embeddings are worth the extra moving part.`
			};
		}

		if (keys.length === 2 && keys.includes('keyword') && keys.includes('single-vector')) {
			return {
				headline: 'You are comparing literal keyword matching against pure semantic matching.',
				body: `Keyword is the no-embedding baseline. Single vector search ignores lexical matching and uses ${selectedEmbedding} to find similar meaning, so the result shows whether semantic similarity helps your questions.`
			};
		}

		if (aiSearchKeys.length > 0 && (agenticKeys.length > 0 || graphKeys.length > 0)) {
			const separateNames = [...agenticNames, ...graphNames];
			return {
				headline: `You are comparing ${naturalList(aiSearchNames)} against ${naturalList(separateNames)}.`,
				body: `Retrieve will keep the corpus and eval questions fixed, but it will not blur these into one bucket. The AI Search candidates test ${aiSearchLeverSummary(aiSearchKeys)}; the other candidates run as separate retrieval systems so their scores are not mistaken for "Hybrid plus graph."`
			};
		}

		if (graphKeys.length > 0 && aiSearchKeys.length === 0 && agenticKeys.length === 0) {
			return {
				headline: `You are comparing ${naturalList(graphNames)} as standalone graph retrieval systems.`,
				body: 'These are not extra switches on keyword or hybrid search. Each candidate builds its own graph-shaped retrieval path, then runs the same eval questions so you can judge whether graph context is worth the build cost.'
			};
		}

		if (agenticKeys.length > 0 && aiSearchKeys.length === 0 && graphKeys.length === 0) {
			return {
				headline: `You are measuring ${naturalList(agenticNames)} as a query-planning candidate.`,
				body: 'It still uses a search source, but the differentiator is planning: the system can break one question into subqueries before retrieving evidence.'
			};
		}

		if (aiSearchKeys.length > 0) {
			return {
				headline: `You are comparing ${naturalList(aiSearchNames)} inside Azure AI Search.`,
				body: `All candidates use the same corpus and eval questions. The difference is the retrieval lever: ${aiSearchLeverSummary(aiSearchKeys)}. That makes the score change easier to attribute.`
			};
		}

		return {
			headline: `You are comparing ${naturalList(candidateNames)}.`,
			body: 'Retrieve will run each candidate over the same corpus and eval set so the score changes reflect the retrieval choice, not a different workload.'
		};
	}

	function openAiEmbeddingEntries() {
		return Object.entries(data.models.embedding).filter(([, model]) => {
			const provider = typeof model.provider === 'string' ? model.provider : '';
			return provider === 'azure_openai' || provider === 'openai';
		});
	}

	function initialOpenAiEmbedding() {
		const configured = sessionString('selected_embedding');
		const options = openAiEmbeddingEntries();
		if (configured && options.some(([key]) => key === configured)) return configured;
		return options[0]?.[0] ?? 'text-embedding-3-large';
	}

	function selectedToggleValues(component: SotaComponentOption) {
		const raw =
			data.session.sota_toggles?.[component.name] ?? data.session.sotaToggles?.[component.name];
		if (Array.isArray(raw)) return raw.map(String);
		if (typeof raw === 'string' && raw) return [raw];
		return component.default ? [component.default] : [];
	}

	function isSotaOptionSelected(component: SotaComponentOption, option: string) {
		return (sotaSelections[component.name] ?? selectedToggleValues(component)).includes(option);
	}

	function toggleSotaOption(component: SotaComponentOption, option: string) {
		const current = [...(sotaSelections[component.name] ?? selectedToggleValues(component))];
		const index = current.indexOf(option);
		if (index >= 0) current.splice(index, 1);
		else current.push(option);
		sotaSelections[component.name] = current.length ? current : [component.default ?? option];
	}

	function sotaVariantCount() {
		if (!selectedSota) return 0;
		return (selectedSota.components ?? []).reduce((count, component) => {
			const selected = sotaSelections[component.name] ?? selectedToggleValues(component);
			return count * Math.max(selected.length, 1);
		}, 1);
	}

	function runMetric(run: RunSummary, key: string) {
		const runRecord = run as unknown as Record<string, unknown>;
		const aggregate = runRecord.aggregate_metrics;
		const source = aggregate && typeof aggregate === 'object' ? aggregate : run;
		return (source as Record<string, unknown>)[key];
	}

	function metricNumber(run: RunSummary | undefined, key: string) {
		if (!run) return undefined;
		const value = runMetric(run, key);
		return typeof value === 'number' ? value : undefined;
	}

	function metricLabel(run: RunSummary, key: string, decimals = 3) {
		const value = runMetric(run, key);
		return typeof value === 'number' ? value.toFixed(decimals) : 'n/a';
	}

	function architectureEvalCost(name: string) {
		return estimateArchitectureEvalCost(name, provisionPricingInputs).total;
	}

	function architectureMonthlyCost(name: string) {
		return estimateMonthlyProductionCost(name, provisionPricingInputs).total;
	}

	function architectureResources(key: string) {
		const declared = data.architectures[key]?.required_azure_resources ?? [];
		return declared.length ? declared : (architectureResourceFallback[key] ?? []);
	}

	function azureService(resource: string) {
		return (
			azureServiceCatalog[resource] ?? {
				label: resource,
				plan: 'Default',
				role: 'Provisioned resource'
			}
		);
	}

	function provisionPlanGroups() {
		const groups: Record<string, string[]> = {};
		for (const key of currentArchitectures()) {
			if (!data.architectures[key]) continue;
			const family = architectureFamily(key);
			groups[family] ??= [];
			groups[family].push(key);
		}
		return Object.entries(groups);
	}

	function provisionTotalCost() {
		return estimateExperimentEvalCost(currentArchitectures(), provisionPricingInputs).total;
	}

	function configEntries(run: RunSummary) {
		return Object.entries(run.architecture_config ?? {}).filter(
			([key]) => !['base', '_variant_of'].includes(key)
		);
	}

	function categoryScore(run: RunSummary, category: string) {
		return compareCategories[String(run.id)]?.[category]?.ndcg_at_10;
	}

	function runFailures(run: RunSummary): RunResult[] {
		return compareFailures[String(run.id)] ?? [];
	}

	function formatBytes(bytes: number) {
		return `${(bytes / 1024).toFixed(1)} KB`;
	}

	function formatEvalSetLabel(set: {
		version_label: string;
		question_count?: number;
		created_at?: string;
	}) {
		const parts = [set.version_label];
		if (typeof set.question_count === 'number') parts.push(`${set.question_count}q`);
		if (set.created_at) {
			const date = new Date(set.created_at);
			if (!Number.isNaN(date.getTime())) {
				parts.push(date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }));
			}
		}
		return parts.join(' · ');
	}

	function appendSteering() {
		const text = chatInput.trim();
		if (!text) return;
		const stamp = new Date().toISOString().slice(0, 16).replace('T', ' ');
		operatorContext = `${operatorContext || ''}\n\n[steer @ ${stamp}] ${text}`.trim();
		chatInput = '';
	}

	async function appendAndSave() {
		appendSteering();
		if (!operatorContext) return;
		chatBusy = true;
		chatStatus = 'Saving...';
		try {
			const response = await fetch(resolve('/api/ui/session'), {
				method: 'POST',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify({ operator_context: operatorContext })
			});
			chatStatus = response.ok ? 'Saved' : 'Save failed';
		} catch (error) {
			chatStatus = error instanceof Error ? error.message : 'Save failed';
		} finally {
			chatBusy = false;
		}
	}

	function setIngestPlugin(event: Event) {
		const target = event.currentTarget as HTMLSelectElement;
		ingestPlugin = target.value;
	}
</script>

<section class="route-shell">
	<div class="content-wide route-stack">
		<RouteHeader title={data.stepMeta.title} subtitle={data.stepMeta.subtitle}>
			{#snippet actions()}
				<a class="button" href={resolve('/')}>Dashboard</a>
				<a class="button" href={resolve('/runs')}>Runs</a>
			{/snippet}
		</RouteHeader>

		{#if form?.message}
			<p class="panel notice" role="status">{form.message}</p>
		{/if}

		{#if data.step === 'ingest'}
			<section class="section-stack">
				{#if corpusReady}
					<div class="panel corpus-ready">
						<div>
							<p class="eyebrow">Corpus ready · Step 1 of 7</p>
							<h2>{corpusDocCount} document{corpusDocCount === 1 ? '' : 's'} in the corpus</h2>
							<p class="muted">
								Saved to <code>{data.corpusFiles.output || ingestOutput}</code>. This corpus is the
								foundation Retrieve measures against — the golden eval set and every index are built
								from it.
							</p>
						</div>
						<a class="button primary" href={resolve('/flow/eval')}>Continue to Golden Eval Set →</a>
					</div>
				{:else}
					<div class="panel intro-panel section-stack">
						<p class="eyebrow">Step 1 of 7 · Foundation</p>
						<h2>Build the corpus Retrieve measures against</h2>
						<p class="muted">
							Retrieve helps you stop guessing which search architecture works and measure it
							instead. It converts your source material into a clean markdown corpus, generates a
							golden evaluation set from that corpus, then scores keyword, hybrid, and reranked
							pipelines so you can pick the best one for your domain.
						</p>
						<p class="muted">
							Ingest is where it starts — the eval questions, the indexes, and every score are built
							from the corpus you create here. Point it at a website or a local folder to begin.
						</p>
						<ol class="flow-strip" aria-label="Workflow steps">
							{#each workflowSteps as step (step.id)}
								<li class:current={step.id === 'ingest'}>{step.shortTitle}</li>
							{/each}
						</ol>
					</div>
				{/if}

				<div class="split-view">
					<form
						class="panel section-stack"
						method="POST"
						action="?/startJob"
						onsubmit={handleStartJobSubmit}
					>
						<input type="hidden" name="kind" value="ingest" />
						<div>
							<p class="eyebrow">Source</p>
							<h2>Ingest your content</h2>
							<p class="muted">
								Same path as <code>retrieve ingest</code>. Tell Retrieve where your documents live
								and how to parse them; it crawls and converts them to markdown.
							</p>
						</div>
						<label>
							<span>{ingestPlugin === 'markdown' ? 'Corpus directory' : 'Source URL or path'}</span>
							<input name="source" bind:value={ingestSource} />
							<small class="field-hint">
								{ingestPlugin === 'markdown'
									? 'A folder of existing .md files to use as-is.'
									: 'A website to crawl or a local folder of source documents.'}
							</small>
						</label>
						<label>
							<span>Plugin</span>
							<select name="plugin" bind:value={ingestPlugin} onchange={setIngestPlugin}>
								<option value="html">HTML — crawl &amp; convert web pages</option>
								<option value="markdown">Markdown — use existing .md files</option>
							</select>
						</label>
						{#if ingestPlugin !== 'markdown'}
							<label>
								<span>Output directory</span>
								<input name="output" bind:value={ingestOutput} />
							</label>
							<label>
								<span>Request delay seconds</span>
								<input name="delay" type="number" min="0" step="0.1" bind:value={ingestDelay} />
								<small class="field-hint">Politeness pause between requests while crawling.</small>
							</label>
						{/if}
						<div class="cluster">
							<button class="button primary" type="submit">Start Ingest</button>
							<button class="button" type="submit" formaction="?/saveDraft">Save Draft</button>
						</div>
					</form>

					<div class="section-stack">
						{#key streamKey('ingest', ['ingest'])}
							<JobProgressStream
								jobId={streamJobId(['ingest'])}
								label="Ingest progress"
								pending={streamPending(['ingest'])}
								onDone={refreshAfterJob}
							/>
						{/key}
						{#if data.corpusFiles.files.length > 0}
							<details class="panel corpus-browse">
								<summary>
									Browse corpus files <span class="muted">({corpusDocCount} total)</span>
								</summary>
								<div class="table-scroll compact-table">
									<table>
										<thead><tr><th>File</th><th>Size</th></tr></thead>
										<tbody>
											{#each data.corpusFiles.files as file (file.name)}
												<tr>
													<td>{file.name}</td>
													<td>{formatBytes(file.size)}</td>
												</tr>
											{/each}
										</tbody>
									</table>
								</div>
								<small class="field-hint">A sample of files, to confirm content landed.</small>
							</details>
						{/if}
					</div>
				</div>
			</section>
		{:else if data.step === 'eval'}
			<section class="section-stack">
				<MetricGrid metrics={evalMetrics} />

				<!-- Current eval set context + quick switcher -->
				<div class="panel eval-context">
					<div class="eval-context-summary">
						<p class="eyebrow">Currently using</p>
						{#if data.status.eval_set}
							<h3 class="eval-context-title">
								{data.status.eval_set.version_label}
								<span class="status-pill">{data.status.eval_set.question_count ?? 0} questions</span
								>
							</h3>
							{#if data.status.eval_set.created_at}
								<p class="muted eval-context-meta">
									Created {new Date(data.status.eval_set.created_at).toLocaleString(undefined, {
										dateStyle: 'medium',
										timeStyle: 'short'
									})}
								</p>
							{/if}
						{:else}
							<h3 class="eval-context-title">No eval set yet</h3>
							<p class="muted eval-context-meta">
								Generate one below, or import questions from CSV.
							</p>
						{/if}
					</div>
					{#if data.evalSets.length > 0}
						<label class="eval-context-switcher">
							<span>Switch active eval set</span>
							<select
								value={currentEvalVersion}
								disabled={evalSwitchBusy}
								onchange={(event) =>
									switchActiveEvalSet((event.currentTarget as HTMLSelectElement).value)}
							>
								{#each data.evalSets as evalSet (evalSet.id)}
									<option value={evalSet.version_label}>{formatEvalSetLabel(evalSet)}</option>
								{/each}
							</select>
							{#if evalSwitchStatus}<small class="field-hint">{evalSwitchStatus}</small>{/if}
						</label>
					{/if}
				</div>

				<!-- ── Primary: Generate / pick / preview ── -->
				<div class="split-view">
					<form
						class="panel section-stack"
						method="POST"
						action="?/startJob"
						onsubmit={handleStartJobSubmit}
					>
						<input type="hidden" name="kind" value="eval_generate" />
						<div>
							<p class="eyebrow">Golden Questions</p>
							<h2>
								{evalSetMode === 'existing' ? 'Use an Existing Eval Set' : 'Generate New Eval Set'}
							</h2>
							<p class="muted">
								{evalSetMode === 'existing'
									? 'Pick one you already have. No need to remember the name.'
									: 'Create a fresh set of golden questions from your corpus.'}
							</p>
						</div>

						<div class="seg eval-mode-seg" role="group" aria-label="Eval set source">
							<button
								type="button"
								class="seg-btn"
								class:active={evalSetMode === 'existing'}
								aria-pressed={evalSetMode === 'existing'}
								disabled={data.evalSets.length === 0}
								onclick={() => (evalSetModeOverride = 'existing')}
							>
								Use existing
							</button>
							<button
								type="button"
								class="seg-btn"
								class:active={evalSetMode === 'new'}
								aria-pressed={evalSetMode === 'new'}
								onclick={() => (evalSetModeOverride = 'new')}
							>
								Generate new
							</button>
						</div>

						{#if evalSetMode === 'existing'}
							<label>
								<span>Eval set</span>
								<select
									value={currentEvalVersion}
									disabled={evalSwitchBusy || data.evalSets.length === 0}
									onchange={(event) =>
										switchActiveEvalSet((event.currentTarget as HTMLSelectElement).value)}
								>
									{#each data.evalSets as evalSet (evalSet.id)}
										<option value={evalSet.version_label}>{formatEvalSetLabel(evalSet)}</option>
									{/each}
								</select>
								<small class="field-hint">
									Picking a set makes it the active one across every step of the flow.
								</small>
							</label>
							<div class="cluster">
								<a class="button primary" href={resolve('/flow/configure')}>
									Continue with this set →
								</a>
								<button type="button" class="button" onclick={() => (evalSetModeOverride = 'new')}>
									Or generate a new one
								</button>
							</div>
						{:else}
							<label>
								<span>Generation mode</span>
								<select name="mode">
									<option value="sample" selected={evalGenerationMode === 'sample'}
										>Sample (~25 questions, quick)</option
									>
									<option value="full" selected={evalGenerationMode === 'full'}
										>Full (~two-thirds of docs, thorough)</option
									>
								</select>
							</label>

							<label>
								<span
									>Operator context <span class="field-hint"
										>— describe your use case to guide question style</span
									></span
								>
								<textarea name="operator_context" rows="4" bind:value={operatorContext}></textarea>
							</label>

							<label>
								<span>Steer with chat</span>
								<div class="input-row">
									<input
										bind:value={chatInput}
										placeholder="more cross-doc questions, fewer direct lookups…"
										onkeydown={(event) => {
											if (event.key === 'Enter') {
												event.preventDefault();
												appendAndSave();
											}
										}}
									/>
									<button
										class="button"
										type="button"
										disabled={chatBusy || !chatInput.trim()}
										onclick={appendAndSave}
									>
										{chatBusy ? 'Saving...' : 'Add'}
									</button>
								</div>
								{#if chatStatus}<small>{chatStatus}</small>{/if}
							</label>

							<!-- Advanced options (incl. auto-suggested version label) -->
							<button
								class="toggle-advanced"
								type="button"
								aria-expanded={evalAdvancedOpen}
								onclick={() => (evalAdvancedOpen = !evalAdvancedOpen)}
							>
								<span class="toggle-arrow" class:open={evalAdvancedOpen}>▶</span>
								Advanced options
								<span class="muted toggle-hint">(version label, base set, corpus)</span>
							</button>

							{#if evalAdvancedOpen}
								<div class="advanced-fields">
									<label>
										<span>New version label</span>
										<input name="version" value={nextEvalVersionSuggestion} />
										<small class="field-hint">
											Auto-suggested as the next version. Leave it alone unless you have a naming
											convention.
										</small>
									</label>
									<label>
										<span>Corpus directory</span>
										<input name="corpus" value={evalCorpus} />
									</label>
									<label>
										<span>Base eval set</span>
										<select name="base_eval_set">
											<option value="latest" selected={baseEvalSet === 'latest'}>latest</option>
											{#each data.evalSets as evalSet (evalSet.id)}
												<option
													value={evalSet.version_label}
													selected={baseEvalSet === evalSet.version_label}
													>{evalSet.version_label}</option
												>
											{/each}
										</select>
									</label>
									<label class="checkbox-row">
										<input name="fresh" type="checkbox" value="true" />
										<span>Start fresh instead of building on latest</span>
									</label>
								</div>
							{:else}
								<input type="hidden" name="version" value={nextEvalVersionSuggestion} />
							{/if}

							<div class="cluster">
								<button class="button primary" type="submit">
									Generate {nextEvalVersionSuggestion}
								</button>
								<button class="button" type="submit" formaction="?/saveDraft">Save Steering</button>
							</div>
						{/if}
					</form>

					<div class="panel section-stack">
						<div class="questions-head">
							<div>
								<p class="eyebrow">Current set · {data.status.eval_set?.version_label ?? 'none'}</p>
								<h2>{evalCsvMode === 'import' ? 'Import CSV' : 'Export CSV'}</h2>
							</div>
							<div class="seg csv-seg" role="group" aria-label="Transfer mode">
								<button
									type="button"
									class="seg-btn"
									class:active={evalCsvMode === 'export'}
									aria-pressed={evalCsvMode === 'export'}
									onclick={() => (evalCsvMode = 'export')}>Export</button
								>
								<button
									type="button"
									class="seg-btn"
									class:active={evalCsvMode === 'import'}
									aria-pressed={evalCsvMode === 'import'}
									onclick={() => (evalCsvMode = 'import')}>Import</button
								>
							</div>
						</div>

						{#if evalCsvMode === 'export'}
							<form class="csv-mini" method="POST" action="?/exportCsv">
								<label>
									<span>Eval set version</span>
									<select name="eval_set">
										<option value="latest">latest (current — {currentEvalVersion})</option>
										{#each data.evalSets as evalSet (evalSet.id)}
											<option
												value={evalSet.version_label}
												selected={evalSet.version_label === currentEvalVersion}
												>{formatEvalSetLabel(evalSet)}</option
											>
										{/each}
									</select>
								</label>
								<label>
									<span>Output path</span>
									<input name="output" value="eval_questions.csv" />
								</label>
								<button class="button primary csv-mini-go" type="submit">Export CSV</button>
							</form>
						{:else if evalCsvMode === 'import'}
							<form class="csv-mini" method="POST" action="?/importCsv">
								<label>
									<span>Input path</span>
									<input name="input" value="eval_questions.csv" />
								</label>
								<label>
									<span>New version label</span>
									<input name="version" value={`${nextEvalVersionSuggestion}-imported`} />
									<small class="field-hint"
										>Auto-suggested. Edit if you have a naming convention.</small
									>
								</label>
								<label>
									<span>Base eval set</span>
									<select name="base_eval_set">
										<option value="latest" selected={baseEvalSet === 'latest'}
											>latest (current)</option
										>
										{#each data.evalSets as evalSet (evalSet.id)}
											<option
												value={evalSet.version_label}
												selected={baseEvalSet === evalSet.version_label ||
													(baseEvalSet === 'latest' &&
														evalSet.version_label === currentEvalVersion)}
												>{formatEvalSetLabel(evalSet)}</option
											>
										{/each}
									</select>
								</label>
								<label class="checkbox-row csv-mini-fresh">
									<input name="fresh" type="checkbox" value="true" />
									<span>Fresh set</span>
								</label>
								<button class="button primary csv-mini-go" type="submit">Import CSV</button>
							</form>
						{/if}
					</div>
				</div>

				<!-- ── Curate & Steer (collapsed, power users) ── -->
				<div class="collapsible-section">
					<button
						class="collapsible-header"
						type="button"
						aria-expanded={evalCurateOpen}
						onclick={() => (evalCurateOpen = !evalCurateOpen)}
					>
						<span class="toggle-arrow" class:open={evalCurateOpen}>▶</span>
						Curate & Steer
						<span class="collapsible-hint">Adjust category mix and regenerate</span>
					</button>
					{#if evalCurateOpen}
						<form class="panel section-stack collapsible-body" method="POST" action="?/curateEval">
							<div class="curate-top">
								<label>
									<span>Source version</span>
									<select name="source_version">
										<option value="latest">latest (current — {currentEvalVersion})</option>
										{#each data.evalSets as es (es.id)}
											<option
												value={es.version_label}
												selected={es.version_label === currentEvalVersion}
												>{formatEvalSetLabel(es)}</option
											>
										{/each}
									</select>
								</label>
								<label>
									<span>New version label</span>
									<input name="new_version" value={`${currentEvalVersion}-curated`} />
									<small class="field-hint">Auto-suggested from the source version.</small>
								</label>
							</div>

							{#if curateCategories.length === 0}
								<p class="curate-empty muted">
									Generate or import questions first to steer the category mix.
								</p>
							{:else}
								<fieldset class="mix-group">
									<legend>Category mix</legend>
									<p class="chip-hint">
										Each category targets a retrieval failure mode. Hover a name to see what it
										tests and which architecture it separates. Adjust how the next generation
										weights each one.
									</p>
									<div class="mix-table">
										{#each curateCategories as t (t.id)}
											<div class="mix-row" class:is-remove={mixOf(t.id) === 'remove'}>
												<div class="mix-info">
													<span class="mix-name">
														{t.label}
														<span class="mix-axis">{t.axis}</span>
													</span>
													{#if t.description}
														<span class="mix-desc">{t.description}</span>
													{/if}
												</div>
												<div class="seg" role="group" aria-label={`${t.label} weighting`}>
													<button
														type="button"
														class="seg-btn seg-more"
														class:active={mixOf(t.id) === 'more'}
														aria-pressed={mixOf(t.id) === 'more'}
														onclick={() => setMix(t.id, mixOf(t.id) === 'more' ? 'keep' : 'more')}
														>More</button
													>
													<button
														type="button"
														class="seg-btn"
														class:active={mixOf(t.id) === 'keep'}
														aria-pressed={mixOf(t.id) === 'keep'}
														onclick={() => setMix(t.id, 'keep')}>Keep</button
													>
													<button
														type="button"
														class="seg-btn seg-fewer"
														class:active={mixOf(t.id) === 'fewer'}
														aria-pressed={mixOf(t.id) === 'fewer'}
														onclick={() => setMix(t.id, mixOf(t.id) === 'fewer' ? 'keep' : 'fewer')}
														>Less</button
													>
													<button
														type="button"
														class="seg-btn seg-remove"
														class:active={mixOf(t.id) === 'remove'}
														aria-pressed={mixOf(t.id) === 'remove'}
														title="Drop this category from the new set entirely"
														onclick={() =>
															setMix(t.id, mixOf(t.id) === 'remove' ? 'keep' : 'remove')}
														>Remove</button
													>
												</div>
												<input
													type="checkbox"
													name="more"
													value={t.id}
													checked={mixOf(t.id) === 'more'}
													hidden
												/>
												<input
													type="checkbox"
													name="fewer"
													value={t.id}
													checked={mixOf(t.id) === 'fewer'}
													hidden
												/>
												<input
													type="checkbox"
													name="remove_categories"
													value={t.id}
													checked={mixOf(t.id) === 'remove'}
													hidden
												/>
											</div>
										{/each}
									</div>
								</fieldset>
							{/if}

							<button
								class="curate-advanced-toggle"
								type="button"
								onclick={() => (curateAdvancedOpen = !curateAdvancedOpen)}
							>
								<span class="toggle-arrow" class:open={curateAdvancedOpen}>▶</span>
								Advanced
							</button>
							{#if curateAdvancedOpen}
								<div class="advanced-fields">
									{#if curateQTypes.length}
										<fieldset class="chip-group">
											<legend>Emphasize question types</legend>
											<p class="chip-hint">Bias the question_type label toward these styles.</p>
											<div class="chip-row">
												{#each curateQTypes as qt (qt.id)}
													<label class="chip" title={qt.description}>
														<input type="checkbox" name="question_types" value={qt.id} />
														<span>{qt.label}</span>
													</label>
												{/each}
											</div>
										</fieldset>
									{/if}
									<label>
										<span>Add new categories</span>
										<input name="add_categories" placeholder="fraud_referrals, appeals" />
										<span class="field-hint"
											>Comma-separated — create categories not in the list above.</span
										>
									</label>
									<label>
										<span>Corpus directory</span>
										<input name="corpus" value={evalCorpus} />
									</label>
									<label>
										<span>Notes</span>
										<textarea name="notes" rows="3"></textarea>
									</label>
								</div>
							{/if}

							<button class="button primary" type="submit">Curate Eval Set</button>
						</form>
					{/if}
				</div>

				{#key streamKey('eval', ['eval_generate'])}
					<JobProgressStream
						jobId={streamJobId(['eval_generate'])}
						label="Eval generation"
						pending={streamPending(['eval_generate'])}
						onDone={refreshAfterJob}
					/>
				{/key}

				<div class="step-footer">
					<a class="button" href={resolve('/flow/ingest')}>← Back to Ingest</a>
					<a class="button primary" href={resolve('/flow/configure')}>Continue to Configure →</a>
				</div>
			</section>
		{:else if data.step === 'configure'}
			<form class="page-section section-stack" method="POST" action="?/saveConfigure">
				<input type="hidden" name="selected_mode" value={selectedMode} />

				{#if selectedMode === 'sota'}
					<!-- ── SOTA eval path ────────────────────────────── -->
					<div>
						<p class="eyebrow">SOTA Evaluation</p>
						<h2>Configure SOTA Eval Path</h2>
						<p class="muted">Choose a SOTA path and one coherent variant per component.</p>
					</div>

					<label class="panel">
						<span>SOTA path</span>
						<select name="selected_sota_path" bind:value={selectedSotaPath}>
							{#each Object.entries(data.sotaPaths) as [key, path] (key)}
								<option value={key}>{path.name}</option>
							{/each}
						</select>
						{#if selectedSota}
							<small>{selectedSota.description}</small>
						{/if}
					</label>

					{#if selectedSota}
						<p class="muted">
							Select one option for a single eval run, or multiple options to expand a bounded
							matrix.
							{sotaVariantCount()} variant{sotaVariantCount() === 1 ? '' : 's'} will be evaluated.
						</p>
						<div class="sota-component-list">
							{#each selectedSota.components ?? [] as component (component.name)}
								<div class="sota-component-card">
									<div class="sota-component-header">
										<strong>{component.name}</strong>
										{#if component.description}
											<span class="muted small-text">{component.description}</span>
										{/if}
									</div>
									<div class="choice-grid">
										{#each component.options ?? [] as option (option)}
											<label class="inline-choice">
												<input
													type="checkbox"
													name={`sota__${component.name}`}
													value={option}
													checked={isSotaOptionSelected(component, option)}
													onchange={() => toggleSotaOption(component, option)}
												/>
												<span>{option}</span>
											</label>
										{/each}
									</div>
								</div>
							{/each}
						</div>
					{/if}
				{:else}
					<section class="configure-hero panel">
						<div>
							<p class="eyebrow">Experiment design</p>
							<h2>Build candidates to measure</h2>
							<p class="muted">
								Start with a preset, then tune the candidate set. Each selected candidate is shown
								below in plain language so the comparison stays easy to hold in your head.
							</p>
						</div>
						<div class="configure-hero-note">
							<strong>Safe state</strong>
							<span
								>Nothing deploys from this page. You are choosing what Retrieve should measure.</span
							>
						</div>
					</section>

					<section class="section-stack" aria-labelledby="preset-heading">
						<div>
							<p class="eyebrow">1. Pick a shape</p>
							<h2 id="preset-heading">Experiment presets</h2>
						</div>
						<div class="preset-grid">
							{#each experimentPresets as preset (preset.id)}
								<button
									class="preset-card"
									class:selected={selectedExperimentPreset === preset.id}
									type="button"
									aria-pressed={selectedExperimentPreset === preset.id}
									onclick={() => applyExperimentPreset(preset)}
								>
									<span class="status-pill">{preset.tag}</span>
									<strong>{preset.name}</strong>
									<span class="preset-technical">{preset.description}</span>
									{#if preset.businessValue}
										<span class="preset-business-value">{preset.businessValue}</span>
									{/if}
								</button>
							{/each}
							<button
								class="preset-card"
								class:selected={selectedExperimentPreset === 'custom'}
								type="button"
								aria-pressed={selectedExperimentPreset === 'custom'}
								onclick={markCustomPreset}
							>
								<span class="status-pill">Manual</span>
								<strong>Custom builder</strong>
								<span>Choose exact candidates and expose advanced levers only when needed.</span>
							</button>
						</div>
					</section>

					<div class="model-strip panel">
						<div class="model-strip-main">
							<span class="model-strip-label">Embedding model</span>
							{#if needsEmbeddings()}
								<select name="selected_embedding" bind:value={selectedEmbedding}>
									{#each openAiEmbeddingEntries() as [key, model] (key)}
										<option value={key}>{model.name}</option>
									{/each}
								</select>
								<input type="hidden" name="selected_vectorizer" value={selectedVectorizer} />
							{:else}
								<span class="muted small-text"
									>Not needed — only keyword candidates are selected.</span
								>
								<input type="hidden" name="selected_vectorizer" value={selectedVectorizer} />
								<input type="hidden" name="selected_embedding" value={selectedEmbedding} />
							{/if}
						</div>
						<div class="model-strip-aside">
							<span class="muted small-text"
								>Shared by vector, hybrid, ranked, and graph/agentic candidates. Keyword baseline
								skips it.</span
							>
						</div>
					</div>

					<section class="section-stack" aria-labelledby="family-heading">
						<div>
							<p class="eyebrow">2. Choose families</p>
							<h2 id="family-heading">Azure AI Search vs graph retrieval</h2>
						</div>

						{#if searchArchitectures().length > 0}
							<fieldset class="search-deployment">
								<legend class="search-deployment-legend">
									<strong>Classic search</strong>
									<span class="muted small-text"
										>Full-text, vector, hybrid, enrichment, and semantic ranking inside AI Search</span
									>
								</legend>

								<div class="search-toggles">
									{#each searchArchitectures() as [key, architecture] (key)}
										<details class="row-expander" class:selected={isArchitectureSelected(key)}>
											<summary class="search-toggle">
												<input
													type="checkbox"
													name="selected_architectures"
													value={key}
													bind:group={selectedArchitectureKeys}
													onchange={markCustomPreset}
													onclick={(event) => event.stopPropagation()}
												/>
												<span class="search-toggle-content">
													<span class="candidate-kicker"
														>{architecturePresentation[key]?.pattern}</span
													>
													<strong>{architectureDisplayName(key, architecture)}</strong>
													<span class="muted small-text"
														>{architectureSummary(key, architecture)}</span
													>
													{#if architectureBusinessValue(key)}
														<span class="arch-business-value">{architectureBusinessValue(key)}</span
														>
													{/if}
												</span>
												<span class="row-advanced-cue">
													<span aria-hidden="true">⚙</span>
													<span>Advanced</span>
												</span>
												{#if architecture.accuracy || architecture.cost}
													<span class="search-toggle-meta">
														{#if architecture.accuracy}<span>{architecture.accuracy}</span>{/if}
														{#if architecture.cost}<span>{architecture.cost}</span>{/if}
														{#if architecture.est_monthly_usd}<span
																>${architecture.est_monthly_usd}/mo</span
															>{/if}
													</span>
												{/if}
											</summary>
											<div class="row-advanced-panel">
												<div>
													<p class="eyebrow">
														Advanced for {architectureDisplayName(key, architecture)}
													</p>
													<p class="muted small-text">
														These controls apply only to this row's experiment candidate.
													</p>
												</div>
												<div class="row-control-grid">
													{#each rowControls(key) as control (`${key}-${control.field}`)}
														<label class="row-control" title={controlHelpText(control)}>
															{#if control.kind === 'checkbox'}
																<input
																	type="hidden"
																	name={advancedName(key, control.field)}
																	value="false"
																/>
																<input
																	type="checkbox"
																	name={advancedName(key, control.field)}
																	value="true"
																	checked={optionBoolean(key, control)}
																	title={controlHelpText(control)}
																	onchange={(event) =>
																		setArchitectureOption(
																			key,
																			control.field,
																			(event.currentTarget as HTMLInputElement).checked
																		)}
																/>
																<span class="control-label">
																	<span>{control.label}</span>
																	<span
																		class="info-dot"
																		title={controlHelpText(control)}
																		aria-label={`About ${control.label}`}>i</span
																	>
																</span>
															{:else}
																<span class="control-label">
																	<span>{control.label}</span>
																	<span
																		class="info-dot"
																		title={controlHelpText(control)}
																		aria-label={`About ${control.label}`}>i</span
																	>
																</span>
																{#if control.kind === 'select'}
																	<select
																		name={advancedName(key, control.field)}
																		value={optionString(key, control)}
																		title={controlHelpText(control)}
																		onchange={(event) =>
																			setArchitectureOption(
																				key,
																				control.field,
																				(event.currentTarget as HTMLSelectElement).value
																			)}
																	>
																		{#each control.options ?? [] as option (option.value)}
																			<option
																				value={option.value}
																				title={optionHelpText(control, option)}
																				>{option.label}</option
																			>
																		{/each}
																	</select>
																{:else}
																	<input
																		name={advancedName(key, control.field)}
																		type={control.kind}
																		min={control.min}
																		max={control.max}
																		step={control.step}
																		placeholder={control.placeholder}
																		value={optionString(key, control)}
																		title={controlHelpText(control)}
																		oninput={(event) =>
																			setArchitectureOption(
																				key,
																				control.field,
																				(event.currentTarget as HTMLInputElement).value
																			)}
																	/>
																{/if}
															{/if}
														</label>
													{/each}
												</div>
											</div>
										</details>
									{/each}
								</div>
							</fieldset>
						{/if}

						{#if agenticSearchArchitectures().length > 0}
							<fieldset class="search-deployment agentic-family">
								<legend class="search-deployment-legend">
									<strong>Agentic Search</strong>
									<span class="muted small-text"
										>Azure AI Search knowledge bases, query planning, and retrieval reasoning</span
									>
								</legend>
								<div class="deploy-grid">
									{#each agenticSearchArchitectures() as [key, architecture] (key)}
										<details
											class="row-expander arch-row"
											class:selected={isArchitectureSelected(key)}
										>
											<summary class="arch-card">
												<input
													type="checkbox"
													name="selected_architectures"
													value={key}
													bind:group={selectedArchitectureKeys}
													onchange={markCustomPreset}
													onclick={(event) => event.stopPropagation()}
												/>
												<span class="candidate-kicker">{architectureFamily(key)}</span>
												<strong>{architectureDisplayName(key, architecture)}</strong>
												<span class="arch-card-summary"
													>{architectureSummary(key, architecture)}</span
												>
												{#if graphCardDefault(key)}
													<span class="graph-card-default">{graphCardDefault(key)}</span>
												{/if}
												<span class="row-advanced-cue">
													<span aria-hidden="true">⚙</span>
													<span>Advanced</span>
												</span>
												{#if architecture.required_azure_resources?.length}
													<span class="deploy-resources">
														{#each architecture.required_azure_resources.filter((r) => !searchBaselineResources.has(r)) as resource (resource)}
															<span class="status-pill">{resource.replace('_', ' ')}</span>
														{/each}
													</span>
												{/if}
												{#if architectureBusinessValue(key)}
													<span class="arch-business-value">{architectureBusinessValue(key)}</span>
												{/if}
											</summary>
											<div class="row-advanced-panel">
												<div>
													<p class="eyebrow">
														Advanced for {architectureDisplayName(key, architecture)}
													</p>
													<p class="muted small-text">
														These controls apply only to this row's experiment candidate.
													</p>
												</div>
												<div class="row-control-grid">
													{#each rowControls(key) as control (`${key}-${control.field}`)}
														<label class="row-control" title={controlHelpText(control)}>
															{#if control.kind === 'checkbox'}
																<input
																	type="hidden"
																	name={advancedName(key, control.field)}
																	value="false"
																/>
																<input
																	type="checkbox"
																	name={advancedName(key, control.field)}
																	value="true"
																	checked={optionBoolean(key, control)}
																	title={controlHelpText(control)}
																	onchange={(event) =>
																		setArchitectureOption(
																			key,
																			control.field,
																			(event.currentTarget as HTMLInputElement).checked
																		)}
																/>
																<span class="control-label">
																	<span>{control.label}</span>
																	<span
																		class="info-dot"
																		title={controlHelpText(control)}
																		aria-label={`About ${control.label}`}>i</span
																	>
																</span>
															{:else}
																<span class="control-label">
																	<span>{control.label}</span>
																	<span
																		class="info-dot"
																		title={controlHelpText(control)}
																		aria-label={`About ${control.label}`}>i</span
																	>
																</span>
																{#if control.kind === 'select'}
																	<select
																		name={advancedName(key, control.field)}
																		value={optionString(key, control)}
																		title={controlHelpText(control)}
																		onchange={(event) =>
																			setArchitectureOption(
																				key,
																				control.field,
																				(event.currentTarget as HTMLSelectElement).value
																			)}
																	>
																		{#each control.options ?? [] as option (option.value)}
																			<option
																				value={option.value}
																				title={optionHelpText(control, option)}
																				>{option.label}</option
																			>
																		{/each}
																	</select>
																{:else}
																	<input
																		name={advancedName(key, control.field)}
																		type={control.kind}
																		min={control.min}
																		max={control.max}
																		step={control.step}
																		placeholder={control.placeholder}
																		value={optionString(key, control)}
																		title={controlHelpText(control)}
																		oninput={(event) =>
																			setArchitectureOption(
																				key,
																				control.field,
																				(event.currentTarget as HTMLInputElement).value
																			)}
																	/>
																{/if}
															{/if}
														</label>
													{/each}
												</div>
											</div>
										</details>
									{/each}
								</div>
							</fieldset>
						{/if}

						{#if graphRetrievalArchitectures().length > 0}
							<fieldset class="search-deployment separate-family">
								<legend class="search-deployment-legend">
									<strong>Graph retrieval</strong>
									<span class="muted small-text"
										>Open-source GraphRAG and LightRAG systems measured against Azure AI Search</span
									>
								</legend>
								<div class="deploy-grid">
									{#each graphRetrievalArchitectures() as [key, architecture] (key)}
										<details
											class="row-expander arch-row"
											class:selected={isArchitectureSelected(key)}
										>
											<summary class="arch-card">
												<input
													type="checkbox"
													name="selected_architectures"
													value={key}
													bind:group={selectedArchitectureKeys}
													onchange={markCustomPreset}
													onclick={(event) => event.stopPropagation()}
												/>
												<span class="candidate-kicker">{architectureFamily(key)}</span>
												<strong>{architectureDisplayName(key, architecture)}</strong>
												<span class="arch-card-summary"
													>{architectureSummary(key, architecture)}</span
												>
												<span class="row-advanced-cue">
													<span aria-hidden="true">⚙</span>
													<span>Advanced</span>
												</span>
												{#if architecture.required_azure_resources?.length}
													<span class="deploy-resources">
														{#each architecture.required_azure_resources.filter((r) => !searchBaselineResources.has(r)) as resource (resource)}
															<span class="status-pill">{resource.replace('_', ' ')}</span>
														{/each}
													</span>
												{/if}
												{#if architectureBusinessValue(key)}
													<span class="arch-business-value">{architectureBusinessValue(key)}</span>
												{/if}
											</summary>
											<div class="row-advanced-panel">
												<div>
													<p class="eyebrow">
														Advanced for {architectureDisplayName(key, architecture)}
													</p>
													<p class="muted small-text">
														These controls apply only to this row's experiment candidate.
													</p>
												</div>
												<div class="row-control-grid">
													{#each rowControls(key) as control (`${key}-${control.field}`)}
														<label class="row-control" title={controlHelpText(control)}>
															{#if control.kind === 'checkbox'}
																<input
																	type="hidden"
																	name={advancedName(key, control.field)}
																	value="false"
																/>
																<input
																	type="checkbox"
																	name={advancedName(key, control.field)}
																	value="true"
																	checked={optionBoolean(key, control)}
																	title={controlHelpText(control)}
																	onchange={(event) =>
																		setArchitectureOption(
																			key,
																			control.field,
																			(event.currentTarget as HTMLInputElement).checked
																		)}
																/>
																<span class="control-label">
																	<span>{control.label}</span>
																	<span
																		class="info-dot"
																		title={controlHelpText(control)}
																		aria-label={`About ${control.label}`}>i</span
																	>
																</span>
															{:else}
																<span class="control-label">
																	<span>{control.label}</span>
																	<span
																		class="info-dot"
																		title={controlHelpText(control)}
																		aria-label={`About ${control.label}`}>i</span
																	>
																</span>
																{#if control.kind === 'select'}
																	<select
																		name={advancedName(key, control.field)}
																		value={optionString(key, control)}
																		title={controlHelpText(control)}
																		onchange={(event) =>
																			setArchitectureOption(
																				key,
																				control.field,
																				(event.currentTarget as HTMLSelectElement).value
																			)}
																	>
																		{#each control.options ?? [] as option (option.value)}
																			<option
																				value={option.value}
																				title={optionHelpText(control, option)}
																				>{option.label}</option
																			>
																		{/each}
																	</select>
																{:else}
																	<input
																		name={advancedName(key, control.field)}
																		type={control.kind}
																		min={control.min}
																		max={control.max}
																		step={control.step}
																		placeholder={control.placeholder}
																		value={optionString(key, control)}
																		title={controlHelpText(control)}
																		oninput={(event) =>
																			setArchitectureOption(
																				key,
																				control.field,
																				(event.currentTarget as HTMLInputElement).value
																			)}
																	/>
																{/if}
															{/if}
														</label>
													{/each}
												</div>
											</div>
										</details>
									{/each}
								</div>
							</fieldset>
						{/if}
					</section>

					<section class="section-stack" aria-labelledby="summary-heading">
						<section class="summary-panel" aria-labelledby="summary-heading">
							<p class="eyebrow">3. Read the generated plan</p>
							<h2 id="summary-heading">What will happen next</h2>
							<p class="summary-lede">{configureSummary().headline}</p>
							<p class="muted">{configureSummary().body}</p>
						</section>

						<div>
							<p class="eyebrow">Candidate explanations</p>
							<h2 id="candidate-heading">What each candidate means</h2>
						</div>

						{#if selectedArchitectureEntries().length > 0}
							<div class="candidate-grid">
								{#each selectedArchitectureEntries() as [key, architecture], index (key)}
									<article class="candidate-card">
										<div class="candidate-card-header">
											<span class="candidate-index"
												>Candidate {String.fromCharCode(65 + index)}</span
											>
											<span class="status-pill">{architectureFamily(key)}</span>
										</div>
										<div>
											<h3>{architectureDisplayName(key, architecture)}</h3>
											<p class="muted">{architectureSummary(key, architecture)}</p>
										</div>
										<div class="candidate-lists">
											<div>
												<strong>Uses</strong>
												<ul>
													{#each architectureUses(key) as item (item)}
														<li>{item}</li>
													{/each}
												</ul>
											</div>
											{#if architectureExcludes(key).length > 0}
												<div>
													<strong>Does not use</strong>
													<ul>
														{#each architectureExcludes(key) as item (item)}
															<li>{item}</li>
														{/each}
													</ul>
												</div>
											{/if}
										</div>
									</article>
								{/each}
							</div>
						{:else}
							<p class="panel muted">No candidates selected yet.</p>
						{/if}
					</section>
				{/if}

				<div class="configure-footer">
					<a class="button" href={resolve('/flow/eval')}>← Back to Eval</a>
					<div class="configure-footer-status">
						<strong>Saved automatically as you build</strong>
						<span class="muted small-text"
							>Your experiment set is kept safe here. Nothing is provisioned or charged yet.</span
						>
					</div>
					<button class="button primary" type="submit">Save &amp; Continue</button>
				</div>
			</form>
		{:else if data.step === 'provision'}
			<section class="section-stack">
				<div class="split-view provision-grid">
					<form
						class="panel section-stack provision-rail"
						method="POST"
						onsubmit={handleStartJobSubmit}
					>
						<div>
							<p class="eyebrow">Deploy boundary</p>
							<h2>Provision & Index</h2>
							<p class="muted">
								This is the first step that creates real Azure resources. Nothing is deployed until
								you start. Review the plan, then deploy and build indexes in one run.
							</p>
						</div>
						<label>
							<span>Resource group</span>
							<input
								name="resource_group"
								bind:value={provisionResourceGroup}
								placeholder="rg-retrieve-dev"
							/>
						</label>
						<label>
							<span>Region (Azure location)</span>
							<input name="location" bind:value={provisionLocation} placeholder="eastus" />
						</label>
						<label>
							<span>Keep on teardown</span>
							<input
								name="keep"
								value={(data.session.winners ?? []).join(',')}
								placeholder="hybrid, hybrid-reranker"
							/>
						</label>
						{#each currentArchitectures() as architectureName (architectureName)}
							<input type="hidden" name="architectures" value={architectureName} />
						{/each}
						<div class="cluster">
							<button
								class="button primary"
								type="submit"
								formaction="?/startJob"
								name="kind"
								value="provision_index"
							>
								Start Provision & Indexing
							</button>
							<button
								class="button"
								type="submit"
								formaction="?/startJob"
								name="kind"
								value="index"
							>
								Re-run Indexing
							</button>
							<button
								class="button danger"
								type="submit"
								formaction="?/startJob"
								name="kind"
								value="teardown"
								onclick={(event) => {
									if (!confirm('Tear down provisioned architectures outside the keep list?'))
										event.preventDefault();
								}}
							>
								Teardown
							</button>
						</div>
					</form>

					<div class="section-stack">
						<div class="panel section-stack">
							<div class="plan-header">
								<div>
									<p class="eyebrow">Deployment plan</p>
									<h2>What will be provisioned</h2>
								</div>
								<dl class="plan-meta">
									<div>
										<dt>Region</dt>
										<dd>{provisionLocation || 'not set'}</dd>
									</div>
									<div>
										<dt>Resource group</dt>
										<dd>{provisionResourceGroup || 'not set'}</dd>
									</div>
									<div>
										<dt>Candidates</dt>
										<dd>{currentArchitectures().length}</dd>
									</div>
									<div>
										<dt>Est. eval cycle</dt>
										<dd>{provisionTotalCost() ? formatUsd(provisionTotalCost()) : 'n/a'}</dd>
									</div>
								</dl>
							</div>
							<p class="muted small-text">
								Estimate covers a temporary provision/index/run cycle, not a monthly production
								bill:
								{provisionPricingInputs.searchHours} search-hours, {provisionPricingInputs.evalQuestions}
								eval questions, and about {Math.round(provisionPricingInputs.corpusTokens / 1000)}K
								corpus tokens.
							</p>
							{#if needsEmbeddings()}
								<p class="muted small-text">
									Embedding model <strong>{selectedEmbedding}</strong> applies to every vector-using candidate.
									The keyword baseline needs no embeddings.
								</p>
							{/if}

							{#if currentArchitectures().length === 0}
								<p class="muted">
									No candidates selected. Go back to Configure to choose experiments before
									provisioning.
								</p>
							{:else}
								{#each provisionPlanGroups() as [family, keys] (family)}
									<div class="plan-group">
										<div class="plan-group-head">
											<h3>{family}</h3>
											<span class="muted small-text"
												>{keys.length} candidate{keys.length === 1 ? '' : 's'}</span
											>
										</div>
										<div class="plan-card-grid">
											{#each keys as key (key)}
												<article class="plan-card">
													<header class="plan-card-head">
														<div>
															<strong
																>{architectureDisplayName(key, data.architectures[key])}</strong
															>
															<p class="muted small-text">
																{architectureSummary(key, data.architectures[key])}
															</p>
														</div>
														<span class="plan-cost"
															>{architectureEvalCost(key)
																? `${formatUsd(architectureEvalCost(key))}/eval`
																: 'cost n/a'}</span
														>
													</header>
													<ul class="service-list">
														{#each architectureResources(key) as resource (resource)}
															{@const service = azureService(resource)}
															<li>
																<span class="service-name">{service.label}</span>
																<span class="service-plan">{service.plan}</span>
																<span class="service-role muted small-text">{service.role}</span>
																<span class="service-region muted small-text"
																	>{provisionLocation || 'region not set'}</span
																>
															</li>
														{/each}
													</ul>
												</article>
											{/each}
										</div>
									</div>
								{/each}
							{/if}
						</div>
					</div>
				</div>

				<div class="panel section-stack">
					<div>
						<p class="eyebrow">Current state</p>
						<h2>Architecture Status</h2>
					</div>
					<div class="table-scroll compact-table">
						<table>
							<thead><tr><th>Name</th><th>Status</th><th>Index</th></tr></thead>
							<tbody>
								{#each architectureStatusRows() as architecture (architecture.name)}
									<tr>
										<td>{architecture.name}</td>
										<td><span class="status-pill">{architecture.status}</span></td>
										<td>{architectureIndexLabel(architecture)}</td>
									</tr>
								{:else}
									<tr>
										<td colspan="3" class="muted">No architecture status for this run yet.</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
				{#key streamKey('provision', ['provision', 'provision_index', 'index', 'teardown'])}
					<JobProgressStream
						jobId={streamJobId(['provision', 'provision_index', 'index', 'teardown'])}
						label="Provision and index stream"
						pending={streamPending(['provision', 'provision_index', 'index', 'teardown'])}
						onDone={refreshAfterJob}
					/>
				{/key}

				<div class="step-footer">
					<a class="button" href={resolve('/flow/configure')}>← Back to Configure</a>
					<a class="button primary" href={resolve('/flow/run')}>Continue to Run Tests →</a>
				</div>
			</section>
		{:else if data.step === 'run'}
			<section class="section-stack">
				<div class="split-view">
					<form
						class="panel section-stack"
						method="POST"
						action="?/startJob"
						onsubmit={handleStartJobSubmit}
					>
						<input type="hidden" name="kind" value="evaluate" />
						{#each provisionedRunArchitectures() as architectureName (architectureName)}
							<input type="hidden" name="architectures" value={architectureName} />
						{/each}
						<div>
							<p class="eyebrow">Retrieval tests</p>
							<h2>Run Tests</h2>
							<p class="muted">
								Running your configured experiment matrix against the golden eval set. These default
								to your last deployment — confirm or change them before you run.
							</p>
						</div>

						<div class="run-config">
							<label>
								<span>Golden eval set</span>
								<select name="eval_set_version" bind:value={runEvalVersion}>
									{#if data.evalSets.length === 0}
										<option value="latest">latest</option>
									{/if}
									{#each data.evalSets as evalSet (evalSet.id)}
										<option value={evalSet.version_label}>{formatEvalSetLabel(evalSet)}</option>
									{/each}
								</select>
								<small class="field-hint"
									>Saved from the Golden Eval Set step. Run any version.</small
								>
							</label>
							<label>
								<span>Resource group</span>
								<input
									name="resource_group"
									bind:value={provisionResourceGroup}
									placeholder="rg-retrieve-dev"
								/>
								<small class="field-hint"
									>From your deployment. Tests run against this resource group.</small
								>
							</label>
							<label>
								<span>Region (Azure location)</span>
								<input name="location" bind:value={provisionLocation} placeholder="eastus" />
							</label>
						</div>

						<dl class="run-summary">
							<div class="run-summary-row">
								<dt>Architectures ({currentArchitectures().length})</dt>
								<dd class="run-summary-chips">
									{#if currentArchitectures().length}
										{#each currentArchitectures() as architectureName (architectureName)}
											{@const ready = isArchitectureRunnable(architectureName)}
											{@const backgrounding = architectureBackgroundIndexing(architectureName)}
											{@const failedCloudIndex = architectureCloudIndexFailed(architectureName)}
											<span
												class="status-pill"
												class:success={ready}
												class:warn={!ready}
												title={ready
													? 'Provisioned and ready to test'
													: backgrounding
														? 'Graph indexing is still running in the background'
														: failedCloudIndex
															? 'Background indexing failed; rerun indexing before testing'
														: 'Not provisioned yet'}
											>
												{architectureDisplayName(
													architectureName,
													data.architectures[architectureName]
												)}
												<small>
													· {ready
														? 'ready'
														: backgrounding
															? 'indexing'
															: failedCloudIndex
																? 'failed'
																: 'not provisioned'}
												</small>
											</span>
										{/each}
									{:else}
										<span class="muted small-text">No architectures selected</span>
									{/if}
								</dd>
							</div>
						</dl>

						{#if provisionedRunArchitectures().length === 0}
							<div class="run-warning" role="alert">
								<strong>Nothing to test yet.</strong>
								<span>
									None of your selected architectures are provisioned in
									<code>{provisionResourceGroup || 'this resource group'}</code>. Deploy them on the
									Provision &amp; Index step first — running now would fail against a search service
									that doesn't exist.
								</span>
								<a class="button primary" href={resolve('/flow/provision')}>← Back to Deploy</a>
							</div>
						{:else if unprovisionedRunArchitectures().length}
							<div class="run-warning subtle" role="status">
								<strong>{unprovisionedRunArchitectures().length} not provisioned</strong>
								<span>
									Only the {provisionedRunArchitectures().length} provisioned
									{provisionedRunArchitectures().length === 1 ? 'architecture' : 'architectures'} will
									run. {unprovisionedRunArchitectures()
										.map((name) => architectureDisplayName(name, data.architectures[name]))
										.join(', ')} will be skipped until deployed.
								</span>
							</div>
						{/if}

						<button
							class="button primary"
							type="submit"
							disabled={provisionedRunArchitectures().length === 0}>Run Tests</button
						>
						<a class="run-summary-edit small-text" href={resolve('/flow/configure')}
							>Change architectures</a
						>
					</form>
					{#key streamKey('run', ['evaluate'])}
						<JobProgressStream
							jobId={streamJobId(['evaluate'])}
							label="Test run stream"
							pending={streamPending(['evaluate'])}
							onDone={refreshAfterJob}
						/>
					{/key}
				</div>

				<div class="step-footer">
					<a class="button" href={resolve('/flow/provision')}>← Back to Deploy</a>
					<a class="button primary" href={resolve('/flow/compare')}>Continue to Compare →</a>
				</div>
			</section>
		{:else if data.step === 'compare'}
			<section class="section-stack">
				{#if compareRuns.length === 0}
					<div class="panel section-stack">
						<div>
							<p class="eyebrow">Comparison</p>
							<h2>No completed runs yet</h2>
							<p class="muted">
								Run your selected architectures against the eval set first. Their results land here
								for a side-by-side comparison.
							</p>
						</div>
						<div class="cluster">
							<a class="button primary" href={resolve('/flow/run')}>Go to Run Tests →</a>
						</div>
					</div>
				{:else}
					<section class="verdict" aria-labelledby="verdict-heading">
						<div class="verdict-head">
							<div>
								<p class="eyebrow">Verdict</p>
								<h2 id="verdict-heading">
									{#if compareWinner}
										{compareWinner.architecture_name} leads on {comparePrimaryLabel}
									{:else}
										Pick a metric to rank architectures
									{/if}
								</h2>
							</div>
							<div class="metric-toggle" role="group" aria-label="Primary metric">
								{#each compareMetricOptions as option (option.key)}
									<button
										type="button"
										class="metric-toggle-btn"
										class:active={comparePrimaryMetric === option.key}
										aria-pressed={comparePrimaryMetric === option.key}
										onclick={() => (comparePrimaryMetric = option.key)}>{option.label}</button
									>
								{/each}
							</div>
						</div>
						{#if compareWinner}
							<div class="verdict-grid">
								<div class="verdict-score">
									<span class="verdict-score-value"
										>{metricLabel(compareWinner, comparePrimaryMetric)}</span
									>
									<span class="verdict-score-label">{comparePrimaryLabel}</span>
								</div>
								<p class="verdict-why">
									{#if compareRunnerUp}
										Beats <strong>{compareRunnerUp.architecture_name}</strong> by
										<strong
											>{compareWinnerDelta >= 0 ? '+' : ''}{compareWinnerDelta.toFixed(3)}</strong
										>
										on {comparePrimaryLabel}.
									{:else}
										Only completed architecture in this comparison.
									{/if}
									{#if compareWinnerStrengths.length}
										Strongest on
										{#each compareWinnerStrengths as category, i (category)}{i > 0
												? ', '
												: ''}{compareCategoryLabel(category)}{/each}.
									{/if}
								</p>
							</div>
						{/if}
					</section>

					<form class="section-stack" method="POST" action="?/saveWinners">
						<div class="cluster spread">
							<div>
								<p class="eyebrow">Architectures</p>
								<h2>Side-by-side</h2>
							</div>
							{#if compareContext?.selected_mode === 'sota'}<span class="status-pill"
									>SOTA eval mode</span
								>{/if}
						</div>
						<div class="arch-card-grid">
							{#each rankedCompareRuns as run, index (run.id)}
								<article class="arch-card" class:winner={index === 0}>
									<header class="arch-card-head">
										<div class="arch-card-title">
											<a class="arch-card-name" href={resolve(`/runs/${run.id}`)}
												>{run.architecture_name}</a
											>
											{#if index === 0}<span class="status-pill success"
													>Top {comparePrimaryLabel}</span
												>{/if}
										</div>
										<label class="promote-toggle">
											<input
												type="checkbox"
												name="winners"
												value={run.architecture_name}
												bind:group={promotedWinners}
											/>
											<span>Promote</span>
										</label>
									</header>
									<div class="metric-tiles">
										{#each [['ndcg_at_10', 'nDCG@10'], ['recall_at_10', 'Recall@10'], ['mrr_at_10', 'MRR@10'], ['recall_at_5', 'Recall@5']] as [key, label] (key)}
											<div
												class="metric-tile"
												data-tone={isBestMetric(run, key) ? 'success' : 'plain'}
											>
												<span class="metric-tile-value">{metricLabel(run, key)}</span>
												<span class="metric-tile-label">{label}</span>
											</div>
										{/each}
									</div>
									<dl class="arch-card-stats">
										<div>
											<dt>Latency</dt>
											<dd class:best={isBestLatency(run)}>
												{metricLabel(run, 'avg_latency_ms', 0)} ms
											</dd>
										</div>
										<div>
											<dt>Est $/mo</dt>
											<dd>
												{architectureMonthlyCost(run.architecture_name)
													? formatUsd(architectureMonthlyCost(run.architecture_name))
													: 'n/a'}
											</dd>
										</div>
										<div>
											<dt>Misses</dt>
											<dd>{run.failure_count ?? run.miss_count ?? 'n/a'}</dd>
										</div>
									</dl>
									{#if configEntries(run).length}
										<div class="badge-row">
											{#each configEntries(run) as [key, value] (key)}
												<span class="status-pill" title={key}>{key}: {String(value)}</span>
											{/each}
										</div>
									{/if}
								</article>
							{/each}
						</div>
						<div class="cluster spread arch-footer">
							<p class="muted small-text">
								{promotedWinners.length} architecture{promotedWinners.length === 1 ? '' : 's'} promoted.
								They carry into Teardown.
							</p>
							<button class="button primary" type="submit">Continue to Teardown →</button>
						</div>
					</form>

					{#if categoryNames.length > 0}
						<section class="panel section-stack" aria-labelledby="heatmap-heading">
							<div>
								<p class="eyebrow">Strengths by category</p>
								<h2 id="heatmap-heading">Taxonomy heatmap</h2>
								<p class="muted small-text">
									Each cell is nDCG@10 for that question category. Darker green = stronger
									retrieval.
								</p>
							</div>
							<div class="heatmap" style:--heat-cols={rankedCompareRuns.length}>
								<div class="heatmap-row heatmap-head">
									<div class="heatmap-cat">Category</div>
									{#each rankedCompareRuns as run (run.id)}
										<div class="heatmap-cell-head">{run.architecture_name}</div>
									{/each}
								</div>
								{#each categoryNames as category (category)}
									<div class="heatmap-row">
										<div class="heatmap-cat" title={compareCategoryDescription(category)}>
											<span>{compareCategoryLabel(category)}</span>
											{#if compareCategoryDescription(category)}<small
													>{compareCategoryDescription(category)}</small
												>{/if}
										</div>
										{#each rankedCompareRuns as run (run.id)}
											{@const score = categoryScore(run, category)}
											<div
												class="heatmap-cell"
												data-heat={categoryHeatTone(score)}
												class:leader={categoryLeader(category)?.id === run.id &&
													typeof score === 'number'}
											>
												{typeof score === 'number' ? score.toFixed(2) : '—'}
											</div>
										{/each}
									</div>
								{/each}
							</div>
						</section>
					{/if}

					{#if compareRuns.some((run) => runFailures(run).length > 0)}
						<section class="panel section-stack" aria-labelledby="miss-heading">
							<div>
								<p class="eyebrow">Miss analysis</p>
								<h2 id="miss-heading">Where they failed</h2>
							</div>
							{#each rankedCompareRuns as run (run.id)}
								{#if runFailures(run).length > 0}
									<details>
										<summary
											>{run.architecture_name} — {runFailures(run).length} miss{runFailures(run)
												.length === 1
												? ''
												: 'es'}</summary
										>
										<div class="table-scroll compact-table">
											<table>
												<thead
													><tr
														><th>Question</th><th>Type</th><th>Expected</th><th>Top retrieved</th
														><th>Why it missed</th></tr
													></thead
												>
												<tbody>
													{#each runFailures(run).slice(0, 20) as failure (failure.id ?? `${failure.question_id}-${failure.failure_type}`)}
														<tr>
															<td>{failure.question_text ?? `Question ${failure.question_id}`}</td>
															<td
																><span class="status-pill">{failure.failure_type ?? 'miss'}</span
																></td
															>
															<td class="mono-cell"
																>{failure.expected_chunk_id ??
																	failure.ground_truth_chunk_ids?.[0] ??
																	'n/a'}</td
															>
															<td class="mono-cell"
																>{failure.top_retrieved_id ??
																	failure.retrieved_chunk_ids?.[0] ??
																	'n/a'}</td
															>
															<td>{failure.failure_details ?? 'n/a'}</td>
														</tr>
													{/each}
												</tbody>
											</table>
										</div>
									</details>
								{/if}
							{/each}
						</section>
					{/if}
				{/if}
			</section>
		{:else if data.step === 'teardown'}
			<section class="section-stack">
				<section class="panel section-stack" aria-labelledby="winners-heading">
					<div>
						<p class="eyebrow">Promoted</p>
						<h2 id="winners-heading">Winning architectures</h2>
						<p class="muted">
							These stay deployed. Everything else can be torn down so it stops incurring cost.
						</p>
					</div>
					{#if (data.session.winners ?? []).length}
						<div class="badge-row">
							{#each data.session.winners ?? [] as winner (winner)}
								<span class="status-pill success">{winner}</span>
							{/each}
						</div>
					{:else}
						<p class="muted">No winners promoted. Go back to Compare to promote at least one.</p>
					{/if}
				</section>

				{#if deployments.length > 0}
					<section class="panel section-stack" aria-labelledby="deployment-heading">
						<div>
							<p class="eyebrow">Production handoff</p>
							<h2 id="deployment-heading">Deployment Summary</h2>
						</div>
						{#each deployments as deployment (deployment.architecture_name)}
							<article class="deployment-card">
								<div class="cluster">
									<strong>{deployment.architecture_name}</strong>
									<span class="status-pill">{deployment.status ?? 'active'}</span>
									{#if deployment.est_monthly_usd}<span class="status-pill"
											>~${deployment.est_monthly_usd}/mo</span
										>{/if}
								</div>
								<dl class="definition-grid">
									{#if deployment.endpoint}
										<div>
											<dt>{deployment.handoff_kind === 'azure-ai-search' ? 'Search endpoint' : 'Service endpoint'}</dt>
											<dd>{deployment.endpoint}</dd>
										</div>
									{/if}
									{#if deployment.query_target}
										<div>
											<dt>{deployment.handoff_kind === 'azure-ai-search'
												? 'Index name'
												: deployment.handoff_kind === 'agentic-kb'
													? 'Knowledge base'
													: deployment.handoff_kind === 'graphrag-job'
														? 'Container Apps job'
														: 'Working directory'}</dt>
											<dd>{deployment.query_target}</dd>
										</div>
									{/if}
									{#if deployment.artifact_prefix}
										<div><dt>Artifact prefix</dt><dd>{deployment.artifact_prefix}</dd></div>
									{/if}
									<div>
										<dt>Resource group</dt>
										<dd>{deployment.resource_group ?? 'n/a'}</dd>
									</div>
									<div>
										<dt>Location</dt>
										<dd>{deployment.location ?? 'n/a'}</dd>
									</div>
								</dl>
								{#if deployment.handoff_note}<p class="muted">{deployment.handoff_note}</p>{/if}
								{#if deployment.handoff_kind === 'azure-ai-search'}
									<details>
										<summary>Copilot Studio HTTP action snippet</summary>
										<pre>{`POST ${deployment.endpoint ?? '<search-endpoint>'}/indexes/${deployment.index_name ?? '<index-name>'}/docs/search?api-version=2024-07-01
Authorization: Bearer <managed-identity-token>
Content-Type: application/json

{
  "search": "{userQuestion}",
  "queryType": "semantic",
  "semanticConfiguration": "default",
  "top": 5
}`}</pre>
									</details>
								{/if}
							</article>
						{/each}
					</section>
				{/if}

				<form
					class="panel section-stack"
					method="POST"
					action="?/startJob"
					onsubmit={handleStartJobSubmit}
				>
					<input type="hidden" name="kind" value="teardown" />
					<div>
						<p class="eyebrow">Cleanup</p>
						<h2>Tear down non-winners</h2>
						<p class="muted">
							Deletes indexes and deployments for every architecture except the ones you keep. This
							frees the running cost.
						</p>
					</div>
					<label>
						<span>Keep architectures</span>
						<input
							name="keep"
							value={(data.session.winners ?? []).join(',')}
							placeholder="hybrid"
						/>
					</label>
					<button class="button danger" type="submit">Start teardown</button>
				</form>

				{#key streamKey('teardown', ['teardown'])}
					<JobProgressStream
						jobId={streamJobId(['teardown'])}
						label="Teardown stream"
						pending={streamPending(['teardown'])}
						onDone={refreshAfterJob}
					/>
				{/key}
			</section>
		{/if}
	</div>
</section>

<style>
	.notice {
		border-color: color-mix(in oklab, var(--color-success) 50%, var(--color-border));
		color: var(--color-success);
	}

	h2 {
		font-size: clamp(1.3rem, 2vw, 1.8rem);
	}

	h3 {
		margin: 0;
		font-size: 1.05rem;
	}

	label {
		display: grid;
		gap: var(--space-xs);
		color: var(--color-muted);
		font-weight: 700;
	}

	input,
	select,
	textarea {
		inline-size: 100%;
		min-block-size: var(--tap-target);
		padding-block: var(--space-xs);
		padding-inline: var(--space-sm);
		border: var(--rule-size) solid var(--color-border-strong);
		border-radius: var(--radius-sm);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
	}

	textarea {
		resize: vertical;
	}

	.input-row {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: var(--space-xs);
		align-items: center;
	}

	code {
		padding: 0.1rem 0.25rem;
		border-radius: var(--radius-xs);
		background: var(--color-surface-raised);
		color: var(--color-text);
	}

	input[type='checkbox'],
	input[type='radio'] {
		inline-size: 1rem;
		min-block-size: 1rem;
	}

	.checkbox-row,
	.inline-choice {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		min-inline-size: 0;
	}

	.choice-grid {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-xs);
	}

	.badge-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-xs);
		justify-content: space-between;
	}

	.inline-choice {
		padding: 0.35rem 0.55rem;
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface);
	}

	.deployment-card,
	.definition-grid {
		display: grid;
		gap: var(--space-sm);
	}

	.definition-grid {
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 18rem), 1fr));
	}

	.definition-grid div {
		display: grid;
		gap: var(--space-2xs);
	}

	dt {
		color: var(--color-muted);
		font-size: 0.78rem;
		font-weight: 900;
		text-transform: uppercase;
	}

	dd {
		min-inline-size: 0;
		margin: 0;
		overflow-wrap: anywhere;
		font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
	}

	pre {
		overflow-x: auto;
		padding: var(--space-sm);
		border-radius: var(--radius-sm);
		background: var(--color-surface-raised);
		font-size: 0.86rem;
	}

	.small-text,
	small {
		font-size: 0.84rem;
	}

	.button.danger {
		border-color: color-mix(in oklab, var(--color-danger) 50%, var(--color-border));
		color: var(--color-danger);
	}

	.cluster.spread {
		justify-content: space-between;
		align-items: flex-end;
	}

	.status-pill.success {
		border-color: color-mix(in oklab, var(--color-success) 55%, var(--color-border));
		color: var(--color-success);
		background: color-mix(in oklab, var(--color-success) 12%, transparent);
	}

	.status-pill.warn {
		border-color: color-mix(in oklab, var(--color-warning) 55%, var(--color-border));
		color: var(--color-warning);
		background: color-mix(in oklab, var(--color-warning) 12%, transparent);
	}

	.status-pill small {
		opacity: 0.85;
		font-weight: 600;
	}

	.run-warning {
		display: grid;
		gap: var(--space-xs);
		padding: var(--space-md);
		border: var(--rule-size) solid
			color-mix(in oklab, var(--color-warning) 50%, var(--color-border));
		border-radius: var(--radius-md);
		background: color-mix(in oklab, var(--color-warning) 8%, transparent);
		color: var(--color-warning);
	}

	.run-warning span {
		color: var(--color-text);
	}

	.run-warning code {
		color: var(--color-warning);
	}

	.run-warning .button {
		justify-self: start;
		margin-top: var(--space-xs);
	}

	.run-warning.subtle {
		border-color: color-mix(in oklab, var(--color-warning) 35%, var(--color-border));
	}

	.verdict {
		display: grid;
		gap: var(--space-md);
		padding: var(--space-lg);
		border: var(--rule-size) solid
			color-mix(in oklab, var(--color-success) 35%, var(--color-border));
		border-radius: var(--radius-md);
		background: color-mix(in oklab, var(--color-success) 7%, var(--color-surface));
	}

	.verdict-head {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-sm);
		justify-content: space-between;
		align-items: flex-start;
	}

	.metric-toggle {
		display: inline-flex;
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-sm);
		overflow: hidden;
		background: var(--color-surface);
	}

	.metric-toggle-btn {
		padding: 0.4rem 0.8rem;
		border: none;
		background: transparent;
		color: var(--color-muted);
		font-weight: 800;
		font-size: 0.82rem;
		cursor: pointer;
	}

	.metric-toggle-btn.active {
		background: var(--color-success);
		color: var(--color-surface);
	}

	.verdict-grid {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-lg);
		align-items: center;
	}

	.verdict-score {
		display: grid;
		gap: var(--space-2xs);
	}

	.verdict-score-value {
		font-size: clamp(2rem, 5vw, 3rem);
		font-weight: 900;
		line-height: 1;
		color: var(--color-success);
	}

	.verdict-score-label {
		font-size: 0.8rem;
		font-weight: 800;
		text-transform: uppercase;
		color: var(--color-muted);
	}

	.verdict-why {
		flex: 1 1 16rem;
		margin: 0;
		font-size: 0.95rem;
	}

	.arch-card-grid {
		display: grid;
		gap: var(--space-md);
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 18rem), 1fr));
	}

	.arch-card {
		display: grid;
		gap: var(--space-sm);
		padding: var(--space-md);
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}

	.arch-card.winner {
		border-color: color-mix(in oklab, var(--color-success) 50%, var(--color-border));
		box-shadow: 0 0 0 1px color-mix(in oklab, var(--color-success) 35%, transparent);
	}

	.arch-card-head {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-sm);
		justify-content: space-between;
		align-items: flex-start;
	}

	.arch-card-title {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2xs);
	}

	.arch-card-name {
		font-weight: 900;
		font-size: 1.05rem;
	}

	.promote-toggle {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2xs);
		font-size: 0.82rem;
		font-weight: 800;
		text-transform: uppercase;
		color: var(--color-muted);
		cursor: pointer;
	}

	.metric-tiles {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: var(--space-xs);
	}

	.metric-tile {
		display: grid;
		gap: var(--space-2xs);
		padding: var(--space-xs) var(--space-sm);
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface-raised);
	}

	.metric-tile[data-tone='success'] {
		border-color: color-mix(in oklab, var(--color-success) 45%, var(--color-border));
		background: color-mix(in oklab, var(--color-success) 10%, var(--color-surface-raised));
	}

	.metric-tile-value {
		font-size: 1.1rem;
		font-weight: 900;
		line-height: 1;
	}

	.metric-tile-label {
		font-size: 0.72rem;
		font-weight: 800;
		text-transform: uppercase;
		color: var(--color-muted);
	}

	.arch-card-stats {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: var(--space-xs);
		margin: 0;
	}

	.arch-card-stats div {
		display: grid;
		gap: var(--space-2xs);
	}

	.arch-card-stats dd {
		font-family: inherit;
		font-weight: 800;
	}

	.arch-card-stats dd.best {
		color: var(--color-success);
	}

	.heatmap {
		display: grid;
		gap: 2px;
		overflow-x: auto;
	}

	.heatmap-row {
		display: grid;
		grid-template-columns: minmax(11rem, 1.4fr) repeat(var(--heat-cols, 3), minmax(5rem, 1fr));
		gap: 2px;
	}

	.heatmap-cat {
		display: grid;
		gap: var(--space-2xs);
		padding: var(--space-xs) var(--space-sm);
		background: var(--color-surface-raised);
		border-radius: var(--radius-sm);
		font-weight: 700;
		font-size: 0.86rem;
	}

	.heatmap-cat small {
		font-weight: 500;
		color: var(--color-muted);
	}

	.heatmap-cell-head {
		padding: var(--space-xs) var(--space-sm);
		font-size: 0.78rem;
		font-weight: 800;
		text-transform: uppercase;
		color: var(--color-muted);
		text-align: center;
	}

	.heatmap-cell {
		display: flex;
		align-items: center;
		justify-content: center;
		padding: var(--space-xs);
		border-radius: var(--radius-sm);
		font-weight: 800;
		font-variant-numeric: tabular-nums;
		background: var(--color-surface-raised);
	}

	.heatmap-cell[data-heat='high'] {
		background: color-mix(in oklab, var(--color-success) 55%, var(--color-surface));
		color: var(--color-surface);
	}

	.heatmap-cell[data-heat='mid'] {
		background: color-mix(in oklab, var(--color-success) 35%, var(--color-surface));
	}

	.heatmap-cell[data-heat='low'] {
		background: color-mix(in oklab, var(--color-success) 18%, var(--color-surface));
	}

	.heatmap-cell[data-heat='poor'] {
		background: color-mix(in oklab, var(--color-danger) 14%, var(--color-surface));
	}

	.heatmap-cell[data-heat='empty'] {
		color: var(--color-muted);
	}

	.heatmap-cell.leader {
		outline: 2px solid color-mix(in oklab, var(--color-success) 60%, transparent);
		outline-offset: -2px;
	}

	.compact-table {
		max-block-size: 24rem;
	}

	.mono-cell {
		max-inline-size: 18rem;
		overflow-wrap: anywhere;
		font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
		font-size: 0.82rem;
	}

	table {
		inline-size: 100%;
		border-collapse: collapse;
	}

	th,
	td {
		padding: var(--space-xs) var(--space-sm);
		border-block-end: var(--rule-size) solid var(--color-border);
		text-align: start;
	}

	th {
		color: var(--color-muted);
		font-size: 0.78rem;
		text-transform: uppercase;
	}

	.configure-hero {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(14rem, 0.38fr);
		gap: var(--space-md);
		align-items: end;
	}

	.configure-hero-note {
		display: grid;
		gap: var(--space-2xs);
		padding: var(--space-sm);
		border: var(--rule-size) solid color-mix(in oklab, var(--color-accent) 45%, var(--color-border));
		border-radius: var(--radius-md);
		background: color-mix(in oklab, var(--color-accent) 8%, var(--color-surface));
	}

	.preset-grid,
	.candidate-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 16rem), 1fr));
		gap: var(--space-md);
	}

	.preset-card {
		display: grid;
		gap: var(--space-xs);
		min-block-size: 11rem;
		padding: var(--space-md);
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		color: inherit;
		text-align: start;
		cursor: pointer;
	}

	.preset-card.selected,
	.preset-card[aria-pressed='true'] {
		border-color: color-mix(in oklab, var(--color-accent) 65%, var(--color-border));
		background: var(--color-surface-raised);
		box-shadow: 0 0 0 0.18rem color-mix(in oklab, var(--color-accent) 16%, transparent);
	}

	.preset-card strong {
		font-size: 1.08rem;
	}

	.preset-technical {
		font-size: 0.875rem;
		color: var(--color-muted);
	}

	.preset-business-value {
		font-size: 0.875rem;
		font-style: italic;
		padding-block-start: var(--space-xs);
		border-block-start: var(--rule-size) solid var(--color-border);
	}

	.arch-business-value {
		font-size: 0.84rem;
		font-style: italic;
	}

	.candidate-kicker,
	.candidate-index {
		color: var(--color-muted);
		font-size: 0.72rem;
		font-weight: 900;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.candidate-card,
	.summary-panel {
		display: grid;
		gap: var(--space-md);
		padding: var(--space-md);
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}

	.candidate-card-header {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-xs);
		align-items: center;
		justify-content: space-between;
	}

	.candidate-lists {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 12rem), 1fr));
		gap: var(--space-md);
	}

	.candidate-lists ul {
		display: grid;
		gap: var(--space-2xs);
		margin: var(--space-2xs) 0 var(--space-sm);
		padding-inline-start: var(--space-md);
	}

	.summary-panel {
		position: relative;
		overflow: hidden;
		gap: var(--space-sm);
		border-color: color-mix(in oklab, var(--color-accent) 55%, var(--color-border));
		background: color-mix(in oklab, var(--color-accent) 6%, var(--color-surface));
	}

	.summary-panel::before {
		content: '';
		position: absolute;
		inset-block: 0;
		inset-inline-start: 0;
		inline-size: 0.22rem;
		background: var(--color-accent);
	}

	.summary-lede {
		margin: 0;
		color: var(--color-text);
		font-size: clamp(1rem, 0.92rem + 0.35vw, 1.24rem);
		font-weight: 850;
	}

	/* ── AI Search deployment panel ─────────────────── */
	.search-deployment {
		display: grid;
		gap: var(--space-md);
		margin: 0;
		padding: var(--space-md);
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}

	.search-deployment-legend {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: var(--space-2xs) var(--space-sm);
		padding: 0 var(--space-2xs);
	}

	.search-toggles {
		display: grid;
		gap: var(--space-2xs);
	}

	.row-expander {
		border-radius: var(--radius-sm);
	}

	.row-expander > summary {
		list-style: none;
	}

	.row-expander > summary::-webkit-details-marker {
		display: none;
	}

	.search-toggle {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto auto;
		gap: var(--space-2xs) var(--space-md);
		align-items: center;
		padding: var(--space-xs) var(--space-sm);
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-bg-soft);
		cursor: pointer;
		transition:
			border-color 0.15s,
			background 0.15s;
	}

	.search-toggle:has(input:checked) {
		border-color: color-mix(in oklab, var(--color-accent) 65%, var(--color-border));
		background: var(--color-surface-raised);
	}

	.search-toggle input[type='checkbox'] {
		inline-size: 1rem;
		min-block-size: 1rem;
	}

	.search-toggle-content {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: var(--space-2xs) var(--space-sm);
	}

	.search-toggle-meta {
		display: flex;
		gap: var(--space-xs);
		font-size: 0.78rem;
		color: var(--color-subtle);
		white-space: nowrap;
	}

	.row-advanced-cue {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2xs);
		padding: 0.2rem 0.55rem;
		border: var(--rule-size) solid var(--color-border);
		border-radius: 999px;
		color: var(--color-muted);
		font-size: 0.78rem;
		font-weight: 900;
		white-space: nowrap;
	}

	.row-expander[open] .row-advanced-cue {
		border-color: color-mix(in oklab, var(--color-accent) 65%, var(--color-border));
		color: var(--color-text);
	}

	.row-advanced-panel {
		display: grid;
		gap: var(--space-sm);
		margin-block-start: var(--space-2xs);
		padding: var(--space-md);
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-bg-soft);
	}

	.row-control-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 14rem), 1fr));
		gap: var(--space-sm);
	}

	.row-control {
		display: grid;
		gap: var(--space-2xs);
		font-size: 0.88rem;
	}

	.control-label {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2xs);
	}

	.info-dot {
		display: inline-grid;
		place-items: center;
		inline-size: 1rem;
		block-size: 1rem;
		border: var(--rule-size) solid color-mix(in oklab, var(--color-accent) 48%, var(--color-border));
		border-radius: 999px;
		color: var(--color-accent);
		font-size: 0.68rem;
		font-weight: 900;
		line-height: 1;
		cursor: help;
	}

	.info-dot:focus-visible {
		outline: 2px solid var(--color-accent);
		outline-offset: 2px;
	}

	/* ── Separate deployment cards ──────────────────── */
	.deploy-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 18rem), 1fr));
		gap: var(--space-md);
	}

	.deploy-resources {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2xs);
	}

	.arch-card {
		position: relative;
		display: grid;
		gap: var(--space-xs);
		padding: var(--space-md);
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		cursor: pointer;
		transition:
			border-color 0.15s,
			background 0.15s;
	}

	.arch-card:has(input:checked) {
		border-color: color-mix(in oklab, var(--color-accent) 65%, var(--color-border));
		background: var(--color-surface-raised);
	}

	.arch-card input[type='checkbox'] {
		inline-size: 1rem;
		min-block-size: 1rem;
	}

	.arch-card-summary {
		display: grid;
		gap: var(--space-md);
		padding-block-start: var(--space-sm);
		border-block-start: var(--rule-size) solid var(--color-border);
	}

	.graph-card-default {
		padding: var(--space-xs) var(--space-sm);
		border: var(--rule-size) solid color-mix(in oklab, var(--color-accent) 35%, var(--color-border));
		border-radius: var(--radius-sm);
		background: color-mix(in oklab, var(--color-accent) 7%, var(--color-surface));
		color: var(--color-muted);
		font-size: 0.84rem;
	}

	.model-strip {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-sm) var(--space-lg);
		padding-block: var(--space-sm);
	}

	.configure-footer {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-sm) var(--space-lg);
		padding-block-start: var(--space-md);
		border-block-start: var(--rule-size) solid var(--color-border);
	}

	.step-footer {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-sm) var(--space-lg);
		padding-block-start: var(--space-md);
		border-block-start: var(--rule-size) solid var(--color-border);
	}

	.run-summary {
		display: grid;
		gap: var(--space-sm);
		margin: 0;
		padding: var(--space-sm) var(--space-md);
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
	}

	.run-config {
		display: grid;
		gap: var(--space-md);
	}

	.run-summary-row {
		display: grid;
		gap: var(--space-2xs);
	}

	.run-summary dt {
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--color-muted);
	}

	.run-summary dd {
		margin: 0;
	}

	.run-summary-chips {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2xs);
	}

	.run-summary-edit {
		justify-self: start;
		color: var(--color-muted);
	}

	.configure-footer-status {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.model-strip-main {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		flex-wrap: wrap;
	}

	.model-strip-label {
		font-weight: 700;
		font-size: 0.9rem;
	}

	.model-strip-main select {
		min-width: 16rem;
	}

	.model-strip-aside {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 2px;
		text-align: end;
	}

	/* ── SOTA component cards ────────────────────────── */
	.sota-component-list {
		display: grid;
		gap: var(--space-md);
	}

	.sota-component-card {
		display: grid;
		gap: var(--space-sm);
		padding: var(--space-md);
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}

	.sota-component-header {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: var(--space-xs) var(--space-md);
	}

	.intro-panel p {
		max-inline-size: 72ch;
	}

	.flow-strip {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-xs);
		margin: 0;
		padding: 0;
		list-style: none;
		counter-reset: flow;
	}

	.flow-strip li {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2xs, 0.4rem);
		padding-block: var(--space-2xs, 0.3rem);
		padding-inline: var(--space-sm);
		border: var(--rule-size) solid var(--color-border);
		border-radius: 999rem;
		background: var(--color-surface-raised);
		color: var(--color-muted);
		font-size: 0.82rem;
		font-weight: 700;
		counter-increment: flow;
	}

	.flow-strip li::before {
		content: counter(flow);
		display: inline-flex;
		align-items: center;
		justify-content: center;
		inline-size: 1.35rem;
		block-size: 1.35rem;
		border-radius: 999rem;
		background: color-mix(in oklab, var(--color-border) 60%, transparent);
		color: var(--color-text);
		font-size: 0.72rem;
	}

	.flow-strip li.current {
		border-color: var(--color-accent);
		color: var(--color-text);
		background: color-mix(in oklab, var(--color-accent) 16%, var(--color-surface-raised));
	}

	.flow-strip li.current::before {
		background: var(--color-accent);
		color: var(--color-surface);
	}

	.corpus-ready {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-md);
		border-color: color-mix(in oklab, var(--color-success) 45%, var(--color-border));
	}

	.corpus-ready > div {
		display: grid;
		gap: var(--space-2xs, 0.35rem);
		flex: 1 1 24rem;
		min-inline-size: 0;
	}

	.field-hint {
		font-weight: 600;
		font-size: 0.8rem;
		color: var(--color-muted);
	}

	/* ── Collapsible accordion sections (eval page) ── */
	.collapsible-section {
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-md);
		overflow: hidden;
	}

	.collapsible-header {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		width: 100%;
		padding: var(--space-sm) var(--space-md);
		background: var(--color-surface);
		border: none;
		cursor: pointer;
		font-weight: 600;
		text-align: start;
	}

	.collapsible-header:hover {
		background: var(--color-surface-raised, var(--color-surface));
	}

	.collapsible-hint {
		margin-inline-start: auto;
		font-size: 0.85rem;
		font-weight: 400;
		color: var(--color-muted);
	}

	.collapsible-body {
		padding: var(--space-md);
	}

	/* ── Advanced options inline toggle ── */
	.toggle-advanced {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		background: none;
		border: none;
		cursor: pointer;
		color: var(--color-accent);
		font-size: 0.9rem;
		padding: 0;
	}

	.toggle-arrow {
		display: inline-block;
		font-size: 0.7rem;
		transition: transform 0.15s;
	}

	.toggle-arrow.open {
		transform: rotate(90deg);
	}

	.advanced-fields {
		display: grid;
		gap: var(--space-sm);
		padding-block-start: var(--space-xs);
		border-block-start: var(--rule-size) solid var(--color-border);
	}

	.toggle-hint {
		font-size: 0.8rem;
		font-weight: normal;
	}

	/* Eval-step header card with current set + switcher */
	.eval-context {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: var(--space-md);
		align-items: center;
	}

	.eval-context-summary {
		display: grid;
		gap: var(--space-2xs, 0.25rem);
	}

	.eval-context-title {
		margin: 0;
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		font-size: 1.05rem;
	}

	.eval-context-meta {
		margin: 0;
		font-size: 0.85rem;
	}

	.eval-context-switcher {
		display: grid;
		gap: var(--space-2xs, 0.25rem);
		min-width: 16rem;
	}

	.eval-mode-seg {
		justify-self: start;
	}

	@media (max-width: 720px) {
		.eval-context {
			grid-template-columns: 1fr;
		}
		.eval-context-switcher {
			min-width: 0;
		}
	}

	/* Curate form: clean chip toggles instead of native multi-selects */
	.curate-top {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
		gap: var(--space-sm);
	}

	.curate-empty {
		margin: 0;
		padding: var(--space-sm);
		border: var(--rule-size) dashed var(--color-border);
		border-radius: var(--radius-sm, 6px);
		font-size: 0.85rem;
	}

	.chip-group {
		margin: 0;
		padding: 0;
		border: 0;
		display: grid;
		gap: var(--space-2xs);
	}

	.chip-group legend {
		padding: 0;
		font-size: 0.75rem;
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--color-text-muted, #9aa4b2);
	}

	.chip-hint {
		margin: 0;
		font-size: 0.8rem;
		color: var(--color-text-muted, #9aa4b2);
	}

	.chip-row {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2xs);
		margin-block-start: var(--space-2xs);
	}

	.chip {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.35rem 0.7rem;
		border: var(--rule-size) solid var(--color-border);
		border-radius: 999px;
		font-size: 0.85rem;
		font-weight: 500;
		color: var(--color-text, #e5e9f0);
		background: transparent;
		cursor: pointer;
		user-select: none;
		transition:
			background 0.12s ease,
			border-color 0.12s ease,
			color 0.12s ease;
	}

	.chip input {
		position: absolute;
		opacity: 0;
		pointer-events: none;
		inline-size: 0;
		block-size: 0;
	}

	.chip:hover {
		border-color: var(--color-accent, #6ea8fe);
	}

	.chip:has(input:focus-visible) {
		outline: 2px solid var(--color-accent, #6ea8fe);
		outline-offset: 2px;
	}

	.chip span::before {
		content: '+';
		display: inline-block;
		margin-inline-end: 0.1rem;
		font-weight: 700;
		opacity: 0.5;
	}

	.chip:has(input:checked) {
		background: color-mix(in srgb, var(--color-accent, #6ea8fe) 18%, transparent);
		border-color: var(--color-accent, #6ea8fe);
		color: var(--color-accent, #6ea8fe);
	}

	.chip:has(input:checked) span::before {
		content: '✓';
		opacity: 1;
	}

	.mix-group {
		display: flex;
		flex-direction: column;
		gap: var(--space-2xs);
		border: 0;
		padding: 0;
		margin: 0;
	}

	.mix-group legend {
		font-weight: 800;
		font-size: 0.95rem;
		padding: 0;
	}

	.mix-table {
		display: flex;
		flex-direction: column;
		margin-block-start: var(--space-2xs);
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-md, 8px);
		overflow: hidden;
	}

	.questions-head {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-md);
		flex-wrap: wrap;
	}

	.csv-seg {
		margin-block-start: 0.2rem;
	}

	.csv-mini {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
		align-items: end;
		gap: var(--space-sm);
		margin-block-start: var(--space-2xs);
	}

	.csv-mini label {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		min-inline-size: 0;
	}

	.csv-mini label > span {
		font-size: 0.78rem;
		font-weight: 600;
		color: var(--color-text-muted, #9aa4b2);
	}

	.csv-mini-fresh {
		flex-direction: row !important;
		align-items: center;
		gap: 0.45rem;
		min-block-size: 2.4rem;
	}

	.csv-mini-fresh > span {
		font-size: 0.85rem;
		color: var(--color-text, #e5e9f0);
	}

	.csv-mini-go {
		min-block-size: 2.4rem;
		white-space: nowrap;
	}

	.mix-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-md);
		padding: 0.7rem 0.8rem;
		border-block-start: var(--rule-size) solid var(--color-border);
	}

	.mix-row:first-child {
		border-block-start: 0;
	}

	.mix-row.is-remove {
		opacity: 0.55;
	}

	.mix-info {
		display: flex;
		flex-direction: column;
		gap: 0.2rem;
		min-inline-size: 0;
	}

	.mix-name {
		display: inline-flex;
		align-items: baseline;
		gap: 0.5rem;
		font-weight: 600;
		font-size: 0.9rem;
	}

	.mix-desc {
		font-size: 0.8rem;
		line-height: 1.4;
		color: var(--color-text-muted, #9aa4b2);
		max-inline-size: 60ch;
	}

	.mix-axis {
		font-size: 0.68rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-muted, #9aa4b2);
		opacity: 0.8;
	}

	.seg {
		display: inline-flex;
		flex-shrink: 0;
		border: var(--rule-size) solid var(--color-border);
		border-radius: 999px;
		overflow: hidden;
	}

	.seg-btn {
		appearance: none;
		border: 0;
		border-inline-start: var(--rule-size) solid var(--color-border);
		background: transparent;
		color: var(--color-text-muted, #9aa4b2);
		font-size: 0.78rem;
		font-weight: 600;
		padding: 0.3rem 0.7rem;
		cursor: pointer;
		transition:
			background 0.12s ease,
			color 0.12s ease;
	}

	.seg-btn:first-child {
		border-inline-start: 0;
	}

	.seg-btn:hover {
		color: var(--color-text, #e5e9f0);
		background: color-mix(in srgb, var(--color-accent, #6ea8fe) 10%, transparent);
	}

	.seg-btn.active {
		color: var(--color-text, #e5e9f0);
		background: color-mix(in srgb, var(--color-accent, #6ea8fe) 22%, transparent);
	}

	.seg-btn.seg-more.active {
		color: #4ade80;
		background: color-mix(in srgb, #4ade80 20%, transparent);
	}

	.seg-btn.seg-fewer.active {
		color: #fbbf24;
		background: color-mix(in srgb, #fbbf24 20%, transparent);
	}

	.seg-btn.seg-remove.active {
		color: #f87171;
		background: color-mix(in srgb, #f87171 20%, transparent);
	}

	.curate-advanced-toggle {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		align-self: flex-start;
		padding: 0;
		border: 0;
		background: transparent;
		color: var(--color-text-muted, #9aa4b2);
		font-size: 0.85rem;
		font-weight: 600;
		cursor: pointer;
	}

	.curate-advanced-toggle:hover {
		color: var(--color-text, #e5e9f0);
	}

	.corpus-browse > summary {
		cursor: pointer;
		font-weight: 800;
		display: flex;
		gap: var(--space-xs);
		align-items: baseline;
	}

	.corpus-browse[open] > summary {
		margin-block-end: var(--space-sm);
	}

	.plan-header {
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
	}

	.plan-meta {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 8rem), 1fr));
		gap: var(--space-sm);
		margin: 0;
		padding-top: var(--space-md);
		border-top: var(--rule-size) solid var(--color-border);
	}

	.plan-meta div {
		display: grid;
		gap: var(--space-2xs);
		padding: var(--space-sm) var(--space-md);
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface-raised);
	}

	.plan-meta dt {
		color: var(--color-muted);
		font-size: 0.72rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.plan-meta dd {
		margin: 0;
		font-weight: 600;
	}

	.plan-group {
		display: grid;
		gap: var(--space-sm);
	}

	.plan-group-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-sm);
		border-block-end: var(--rule-size) solid var(--color-border);
		padding-block-end: var(--space-2xs);
	}

	.plan-group-head h3 {
		margin: 0;
		font-size: 0.92rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-accent-strong);
	}

	.plan-card {
		display: grid;
		gap: var(--space-sm);
		padding: var(--space-md);
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}

	.plan-card-head {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: var(--space-md);
	}

	.plan-card-head p {
		margin: var(--space-2xs) 0 0;
	}

	.plan-cost {
		white-space: nowrap;
		font-weight: 600;
		color: var(--color-text);
	}

	.service-list {
		display: grid;
		gap: var(--space-2xs);
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.service-list li {
		display: grid;
		grid-template-columns: minmax(0, 1.2fr) minmax(0, 0.8fr) minmax(0, 1.4fr) minmax(0, 0.7fr);
		gap: var(--space-xs);
		align-items: baseline;
		padding-block: var(--space-2xs);
		border-block-start: var(--rule-size) solid var(--color-border);
	}

	.service-list li:first-child {
		border-block-start: none;
	}

	.service-name {
		font-weight: 600;
	}

	.service-plan {
		font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
		font-size: 0.8rem;
		color: var(--color-accent);
	}

	.service-region {
		text-align: end;
	}

	.provision-grid {
		grid-template-columns: minmax(var(--evidence-panel-min), 0.42fr) minmax(0, 1fr);
	}

	.provision-rail {
		position: sticky;
		top: var(--space-lg);
		align-self: start;
	}

	.plan-card-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 20rem), 1fr));
		gap: var(--space-sm);
	}

	@media (max-width: 60rem) {
		.provision-grid {
			grid-template-columns: 1fr;
		}

		.provision-rail {
			position: static;
		}
	}

	@media (max-width: 38rem) {
		.service-list li {
			grid-template-columns: 1fr;
		}

		.service-region {
			text-align: start;
		}
	}
</style>
