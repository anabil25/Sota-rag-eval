import type { ArchitectureDefinition, RunSummary, UiSession } from '$lib/api/types';

export const HOURS_PER_MONTH = 730;

export type PricingUnit =
	| '1 Hour'
	| '1K tokens'
	| '1K queries'
	| '1 GB/month'
	| '10K operations'
	| '1M RUs';

export interface PricingMeter {
	id: string;
	service: string;
	sku: string;
	meter: string;
	unit: PricingUnit;
	unitPrice: number;
	region: string;
	source: string;
	sourceUrl: string;
	fetchedAt: string;
	note?: string;
}

export interface PricingInputs {
	corpusDocuments: number;
	corpusTokens: number;
	evalQuestions: number;
	searchHours: number;
	searchUnits: number;
	storageGb: number;
	evalRunsPerMonth: number;
	monthlyQueries: number;
	llmInputTokensPerQuestion: number;
	llmOutputTokensPerQuestion: number;
}

export interface CostBreakdownLine {
	label: string;
	service: string;
	cost: number;
	note: string;
}

export interface CostEstimate {
	total: number;
	lines: CostBreakdownLine[];
}

const retailApi = 'https://prices.azure.com/api/retail/prices?api-version=2023-01-01-preview';
const sourceDate = '2026-06-02';

function priceFilter(filter: string) {
	return `${retailApi}&$filter=${encodeURIComponent(filter)}`;
}

export const PRICING_METERS: PricingMeter[] = [
	{
		id: 'ai-search-basic',
		service: 'Azure AI Search',
		sku: 'Basic',
		meter: 'Basic Unit',
		unit: '1 Hour',
		unitPrice: 0.101,
		region: 'eastus',
		source: 'Azure Retail Prices API',
		sourceUrl: priceFilter(
			"serviceName eq 'Azure Cognitive Search' and armRegionName eq 'eastus' and priceType eq 'Consumption' and productName eq 'Azure AI Search'"
		),
		fetchedAt: sourceDate,
		note: 'Non-confidential Basic search unit. Good for small dev/eval indexes.'
	},
	{
		id: 'ai-search-s1',
		service: 'Azure AI Search',
		sku: 'Standard S1',
		meter: 'Standard S1 Unit',
		unit: '1 Hour',
		unitPrice: 0.336,
		region: 'eastus',
		source: 'Azure Retail Prices API',
		sourceUrl: priceFilter(
			"serviceName eq 'Azure Cognitive Search' and armRegionName eq 'eastus' and priceType eq 'Consumption' and productName eq 'Azure AI Search'"
		),
		fetchedAt: sourceDate,
		note: 'Default Retrieve estimate for AI Search evaluation services.'
	},
	{
		id: 'semantic-ranker',
		service: 'Azure AI Search',
		sku: 'Semantic Ranker',
		meter: 'Semantic Ranker queries',
		unit: '1K queries',
		unitPrice: 1,
		region: 'eastus',
		source: 'Azure Retail Prices API',
		sourceUrl: priceFilter(
			"serviceName eq 'Azure Cognitive Search' and armRegionName eq 'eastus' and priceType eq 'Consumption' and contains(skuName, 'Semantic')"
		),
		fetchedAt: sourceDate
	},
	{
		id: 'agentic-low',
		service: 'Azure AI Search',
		sku: 'Agentic Retrieval Low Reasoning',
		meter: 'Agentic Retrieval Low Reasoning Tokens',
		unit: '1K tokens',
		unitPrice: 0.000022,
		region: 'eastus',
		source: 'Azure Retail Prices API',
		sourceUrl: priceFilter(
			"serviceName eq 'Azure Cognitive Search' and armRegionName eq 'eastus' and priceType eq 'Consumption' and contains(skuName, 'Agentic')"
		),
		fetchedAt: sourceDate
	},
	{
		id: 'agentic-medium',
		service: 'Azure AI Search',
		sku: 'Agentic Retrieval Medium Reasoning',
		meter: 'Agentic Retrieval Medium Reasoning Tokens',
		unit: '1K tokens',
		unitPrice: 0.0001,
		region: 'eastus',
		source: 'Azure Retail Prices API',
		sourceUrl: priceFilter(
			"serviceName eq 'Azure Cognitive Search' and armRegionName eq 'eastus' and priceType eq 'Consumption' and contains(skuName, 'Agentic')"
		),
		fetchedAt: sourceDate
	},
	{
		id: 'embedding-small',
		service: 'Azure OpenAI',
		sku: 'text-embedding-3-small',
		meter: 'text-embedding-3-small-glbl Tokens',
		unit: '1K tokens',
		unitPrice: 0.00002,
		region: 'eastus',
		source: 'Azure Retail Prices API',
		sourceUrl: priceFilter(
			"serviceName eq 'Foundry Models' and armRegionName eq 'eastus' and priceType eq 'Consumption' and contains(skuName, 'embedding')"
		),
		fetchedAt: sourceDate
	},
	{
		id: 'embedding-large',
		service: 'Azure OpenAI',
		sku: 'text-embedding-3-large',
		meter: 'text-embedding-3-large-glbl Tokens',
		unit: '1K tokens',
		unitPrice: 0.00013,
		region: 'eastus',
		source: 'Azure Retail Prices API',
		sourceUrl: priceFilter(
			"serviceName eq 'Foundry Models' and armRegionName eq 'eastus' and priceType eq 'Consumption' and contains(skuName, 'embedding')"
		),
		fetchedAt: sourceDate
	},
	{
		id: 'gpt-4o-mini-input',
		service: 'Azure OpenAI',
		sku: 'gpt-4o-mini-0718 global input',
		meter: 'gpt-4o-mini-0718-Inp-glbl Tokens',
		unit: '1K tokens',
		unitPrice: 0.00015,
		region: 'eastus',
		source: 'Azure Retail Prices API',
		sourceUrl: priceFilter(
			"serviceName eq 'Foundry Models' and armRegionName eq 'eastus' and priceType eq 'Consumption' and contains(meterName, '4o mini')"
		),
		fetchedAt: sourceDate,
		note: 'Used for graph/agentic prompt and extraction estimates.'
	},
	{
		id: 'gpt-4o-mini-output',
		service: 'Azure OpenAI',
		sku: 'gpt-4o-mini-0718 global output',
		meter: 'gpt-4o-mini-0718-Outp-glbl Tokens',
		unit: '1K tokens',
		unitPrice: 0.0006,
		region: 'eastus',
		source: 'Azure Retail Prices API',
		sourceUrl: priceFilter(
			"serviceName eq 'Foundry Models' and armRegionName eq 'eastus' and priceType eq 'Consumption' and contains(meterName, '4o mini')"
		),
		fetchedAt: sourceDate
	},
	{
		id: 'blob-hot-lrs',
		service: 'Blob Storage',
		sku: 'Hot LRS',
		meter: 'Hot LRS Data Stored',
		unit: '1 GB/month',
		unitPrice: 0.0208,
		region: 'eastus',
		source: 'Azure Retail Prices API',
		sourceUrl: priceFilter(
			"serviceName eq 'Storage' and armRegionName eq 'eastus' and priceType eq 'Consumption' and contains(skuName, 'Hot LRS')"
		),
		fetchedAt: sourceDate
	},
	{
		id: 'blob-hot-write',
		service: 'Blob Storage',
		sku: 'Hot LRS write operations',
		meter: 'Hot LRS Write Operations',
		unit: '10K operations',
		unitPrice: 0.05,
		region: 'eastus',
		source: 'Azure Retail Prices API',
		sourceUrl: priceFilter(
			"serviceName eq 'Storage' and armRegionName eq 'eastus' and priceType eq 'Consumption' and contains(skuName, 'Hot LRS')"
		),
		fetchedAt: sourceDate
	},
	{
		id: 'cosmos-serverless-ru',
		service: 'Azure Cosmos DB',
		sku: 'Serverless RUs',
		meter: '1M RUs',
		unit: '1M RUs',
		unitPrice: 0.25,
		region: 'eastus',
		source: 'Azure Retail Prices API',
		sourceUrl: priceFilter(
			"serviceName eq 'Azure Cosmos DB' and armRegionName eq 'eastus' and priceType eq 'Consumption'"
		),
		fetchedAt: sourceDate,
		note: 'Optional production storage/query backend for graph variants.'
	}
];

export const DEFAULT_PRICING_INPUTS: PricingInputs = {
	corpusDocuments: 100,
	corpusTokens: 250_000,
	evalQuestions: 25,
	searchHours: 4,
	searchUnits: 1,
	storageGb: 1,
	evalRunsPerMonth: 10,
	monthlyQueries: 10_000,
	llmInputTokensPerQuestion: 2_000,
	llmOutputTokensPerQuestion: 300
};

const meterMap = Object.fromEntries(PRICING_METERS.map((meter) => [meter.id, meter]));

function meter(id: string) {
	const result = meterMap[id];
	if (!result) throw new Error(`Unknown pricing meter: ${id}`);
	return result;
}

function addLine(lines: CostBreakdownLine[], line: CostBreakdownLine) {
	if (line.cost > 0) lines.push(line);
}

function tokenCost(tokens: number, meterId: string) {
	return (tokens / 1000) * meter(meterId).unitPrice;
}

function searchRuntimeCost(inputs: PricingInputs) {
	return meter('ai-search-s1').unitPrice * inputs.searchHours * Math.max(1, inputs.searchUnits);
}

function monthlySearchCost(searchUnits = 1) {
	return meter('ai-search-s1').unitPrice * HOURS_PER_MONTH * Math.max(1, searchUnits);
}

export function architectureNeedsVector(architecture: string) {
	return [
		'single-vector',
		'hybrid',
		'hybrid-reranker',
		'hybrid-llm-enriched',
		'multi-vector',
		'lightrag'
	].includes(architecture);
}

export function architectureUsesSearch(architecture: string) {
	return [
		'keyword',
		'single-vector',
		'hybrid',
		'hybrid-reranker',
		'hybrid-llm-enriched',
		'multi-vector',
		'agentic-kb'
	].includes(architecture);
}

export function architectureUsesSemanticRanker(architecture: string) {
	return ['hybrid-reranker', 'hybrid-llm-enriched'].includes(architecture);
}

export function architectureUsesLlm(architecture: string) {
	return ['hybrid-llm-enriched', 'agentic-kb', 'graphrag', 'lightrag'].includes(architecture);
}

export function estimateArchitectureEvalCost(
	architecture: string,
	inputs: PricingInputs = DEFAULT_PRICING_INPUTS
): CostEstimate {
	const lines: CostBreakdownLine[] = [];

	if (architectureUsesSearch(architecture)) {
		addLine(lines, {
			label: 'Temporary AI Search capacity',
			service: 'Azure AI Search',
			cost: searchRuntimeCost(inputs),
			note: `${inputs.searchUnits} S1 search unit(s) for ${inputs.searchHours} hour(s)`
		});
	}

	if (architectureNeedsVector(architecture)) {
		addLine(lines, {
			label: 'Corpus embeddings',
			service: 'Azure OpenAI',
			cost: tokenCost(inputs.corpusTokens, 'embedding-large'),
			note: `${formatNumber(inputs.corpusTokens)} corpus tokens embedded once`
		});
	}

	if (architectureUsesSemanticRanker(architecture)) {
		addLine(lines, {
			label: 'Semantic ranker eval queries',
			service: 'Azure AI Search',
			cost: (inputs.evalQuestions / 1000) * meter('semantic-ranker').unitPrice,
			note: `${formatNumber(inputs.evalQuestions)} eval questions`
		});
	}

	if (architecture === 'agentic-kb') {
		const tokens = inputs.evalQuestions * inputs.llmInputTokensPerQuestion;
		addLine(lines, {
			label: 'Agentic retrieval planning',
			service: 'Azure AI Search',
			cost: tokenCost(tokens, 'agentic-low'),
			note: `${formatNumber(tokens)} low-reasoning retrieval tokens`
		});
	}

	if (architecture === 'hybrid-llm-enriched') {
		const inputTokens = Math.round(inputs.corpusTokens * 0.35);
		const outputTokens = Math.round(inputs.corpusDocuments * 150);
		addLine(lines, {
			label: 'LLM metadata enrichment',
			service: 'Azure OpenAI',
			cost:
				tokenCost(inputTokens, 'gpt-4o-mini-input') + tokenCost(outputTokens, 'gpt-4o-mini-output'),
			note: `${formatNumber(inputTokens)} input + ${formatNumber(outputTokens)} output tokens`
		});
	}

	if (architecture === 'graphrag' || architecture === 'lightrag') {
		const graphMultiplier = architecture === 'graphrag' ? 1.4 : 0.55;
		const inputTokens = Math.round(inputs.corpusTokens * graphMultiplier);
		const outputTokens = Math.round(
			inputs.corpusDocuments * (architecture === 'graphrag' ? 450 : 180)
		);
		addLine(lines, {
			label:
				architecture === 'graphrag' ? 'Graph extraction + summaries' : 'Light graph extraction',
			service: 'Azure OpenAI',
			cost:
				tokenCost(inputTokens, 'gpt-4o-mini-input') + tokenCost(outputTokens, 'gpt-4o-mini-output'),
			note: `${formatNumber(inputTokens)} input + ${formatNumber(outputTokens)} output tokens`
		});
		addLine(lines, {
			label: 'Graph artifacts',
			service: 'Blob Storage',
			cost:
				meter('blob-hot-lrs').unitPrice * inputs.storageGb * (inputs.searchHours / HOURS_PER_MONTH),
			note: `${formatNumber(inputs.storageGb)} GB prorated for ${inputs.searchHours} hour(s)`
		});
	}

	return {
		total: lines.reduce((sum, line) => sum + line.cost, 0),
		lines
	};
}

export function estimateExperimentEvalCost(
	architectures: string[],
	inputs: PricingInputs = DEFAULT_PRICING_INPUTS
): CostEstimate {
	const lines = architectures.flatMap((architecture) =>
		estimateArchitectureEvalCost(architecture, inputs).lines.map((line) => ({
			...line,
			label: `${architecture}: ${line.label}`
		}))
	);
	return { total: lines.reduce((sum, line) => sum + line.cost, 0), lines };
}

export function estimateMonthlyProductionCost(
	architecture: string,
	inputs: PricingInputs = DEFAULT_PRICING_INPUTS
): CostEstimate {
	const lines: CostBreakdownLine[] = [];

	if (architectureUsesSearch(architecture)) {
		addLine(lines, {
			label: 'AI Search service',
			service: 'Azure AI Search',
			cost: monthlySearchCost(inputs.searchUnits),
			note: `${inputs.searchUnits} S1 search unit(s) running 730 hours`
		});
	}

	if (architectureUsesSemanticRanker(architecture)) {
		addLine(lines, {
			label: 'Semantic ranker queries',
			service: 'Azure AI Search',
			cost: (inputs.monthlyQueries / 1000) * meter('semantic-ranker').unitPrice,
			note: `${formatNumber(inputs.monthlyQueries)} production queries/month`
		});
	}

	if (architecture === 'agentic-kb') {
		const tokens = inputs.monthlyQueries * inputs.llmInputTokensPerQuestion;
		addLine(lines, {
			label: 'Agentic retrieval planning',
			service: 'Azure AI Search',
			cost: tokenCost(tokens, 'agentic-low'),
			note: `${formatNumber(tokens)} low-reasoning retrieval tokens/month`
		});
	}

	if (architectureUsesLlm(architecture) && architecture !== 'agentic-kb') {
		const inputTokens = inputs.monthlyQueries * inputs.llmInputTokensPerQuestion;
		const outputTokens = inputs.monthlyQueries * inputs.llmOutputTokensPerQuestion;
		addLine(lines, {
			label: 'LLM retrieval/generation calls',
			service: 'Azure OpenAI',
			cost:
				tokenCost(inputTokens, 'gpt-4o-mini-input') + tokenCost(outputTokens, 'gpt-4o-mini-output'),
			note: `${formatNumber(inputs.monthlyQueries)} queries/month`
		});
	}

	addLine(lines, {
		label: 'Corpus/artifact storage',
		service: 'Blob Storage',
		cost: meter('blob-hot-lrs').unitPrice * inputs.storageGb,
		note: `${formatNumber(inputs.storageGb)} GB stored/month`
	});

	return { total: lines.reduce((sum, line) => sum + line.cost, 0), lines };
}

export function bestArchitectureFromRuns(
	runs: RunSummary[],
	session: UiSession,
	architectures: Record<string, ArchitectureDefinition>
) {
	const winner = session.winners?.find((name) => architectures[name]);
	if (winner) return { architecture: winner, reason: 'Selected winner from Compare' };

	const completed = runs
		.filter((run) => run.status === 'completed')
		.filter((run) => architectures[run.architecture_name])
		.sort((left, right) => (metric(right, 'ndcg_at_10') ?? 0) - (metric(left, 'ndcg_at_10') ?? 0));
	if (completed[0])
		return { architecture: completed[0].architecture_name, reason: 'Highest nDCG@10 run' };

	const selected = session.selected_architectures?.find((name) => architectures[name]);
	if (selected) return { architecture: selected, reason: 'First configured candidate' };

	const first = Object.keys(architectures)[0] ?? 'hybrid';
	return { architecture: first, reason: 'Default architecture' };
}

function metric(run: RunSummary, key: string) {
	const value = run.aggregate_metrics?.[key] ?? (run as unknown as Record<string, unknown>)[key];
	return typeof value === 'number' ? value : undefined;
}

export function pricingInputsFromCorpus(args: Partial<PricingInputs>): PricingInputs {
	return { ...DEFAULT_PRICING_INPUTS, ...args };
}

export function formatUsd(value: number) {
	if (!Number.isFinite(value)) return '$0.00';
	if (value > 0 && value < 0.01) return '<$0.01';
	return new Intl.NumberFormat('en-US', {
		style: 'currency',
		currency: 'USD',
		minimumFractionDigits: 2,
		maximumFractionDigits: 2
	}).format(value);
}

export function formatUnitPrice(value: number) {
	if (!Number.isFinite(value)) return '$0.00';
	if (value > 0 && value < 0.01) {
		return `$${value.toFixed(6).replace(/0+$/, '').replace(/\.$/, '')}`;
	}
	return formatUsd(value);
}

export function formatNumber(value: number) {
	return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(value);
}
