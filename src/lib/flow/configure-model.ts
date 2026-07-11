export type ExperimentPresetId = 'quick-baseline' | 'quality-sweep' | 'cross-paradigm' | 'custom';

export type ExperimentPreset = {
	id: ExperimentPresetId;
	name: string;
	tag: string;
	description: string;
	businessValue: string;
	architectures: string[];
};

export type ArchitectureOptionValue = string | boolean;
export type ArchitectureOptions = Record<string, Record<string, ArchitectureOptionValue>>;

export type RowControl = {
	kind: 'select' | 'text' | 'number' | 'checkbox';
	field: string;
	label: string;
	fallback: ArchitectureOptionValue;
	options?: Array<{ value: string; label: string }>;
	min?: number;
	max?: number;
	step?: number;
	placeholder?: string;
};

export const architecturePresentation: Record<
	string,
	{ name: string; pattern: string; summary: string; businessValue: string }
> = {
	keyword: {
		name: 'Keyword',
		pattern: 'Lexical search',
		summary: 'Term matching over policy text.',
		businessValue:
			'Pick this when exact terms must match — part numbers, clause references, product SKUs. If your users type the exact words in the document, this is your baseline.'
	},
	'single-vector': {
		name: 'Single vector',
		pattern: 'Vector search',
		summary: 'One embedding field for semantic similarity.',
		businessValue:
			'Pick this for conversational questions where users phrase things naturally. "How do I cancel my account?" should match "account termination procedure" — embeddings do that; keyword matching does not.'
	},
	hybrid: {
		name: 'Hybrid',
		pattern: 'Keyword + vector fusion',
		summary: 'Lexical and semantic retrieval combined at query time.',
		businessValue:
			'The safe default for most search features. Handles both exact-term lookups and natural-language questions in a single query — no need to pick one strategy and hope.'
	},
	'hybrid-reranker': {
		name: 'Hybrid + reranker',
		pattern: 'Hybrid + second-stage ranking',
		summary: 'Hybrid candidate retrieval with a precision ranking pass.',
		businessValue:
			'Pick this when the top result really matters — chatbots that cite a single source, "find me the right policy" tools, anything where position 1 being wrong is a user failure.'
	},
	'hybrid-llm-enriched': {
		name: 'Hybrid + enrichment',
		pattern: 'Hybrid + enriched index fields',
		summary: 'Hybrid retrieval over extracted metadata and policy text.',
		businessValue:
			'Pick this when document quality is poor — scanned forms, tables, image-heavy PDFs. Enrichment extracts structured fields during indexing so search has something meaningful to work with.'
	},
	'multi-vector': {
		name: 'Multi-vector',
		pattern: 'Multiple vector representations',
		summary: 'Separate retrieval signals stored for each chunk.',
		businessValue:
			'Pick this for specialist corpora where different aspects of a document (title, summary, body) deserve separate semantic matching. Rarely needed as a first choice.'
	},
	'agentic-kb': {
		name: 'Agentic Search',
		pattern: 'Query planning',
		summary: 'LLM-guided multi-step retrieval over search sources.',
		businessValue:
			'Pick this for complex multi-part questions — "What are all the risks in this contract?" or research assistants that need to decompose a question before searching. Higher latency, higher quality ceiling.'
	},
	graphrag: {
		name: 'GraphRAG',
		pattern: 'Hierarchical graph retrieval',
		summary:
			'Builds entities, relationships, communities, and community reports for broad cross-document reasoning.',
		businessValue:
			'Pick this when your documents form a web of relationships — regulations that reference regulations, cases with precedent chains, entities that link across files. Answers "how is X connected to Y?" questions flat search cannot.'
	},
	lightrag: {
		name: 'LightRAG',
		pattern: 'Lightweight entity graph',
		summary:
			'Builds a simpler entity-relation graph plus vector chunks for lower-cost graph-augmented retrieval.',
		businessValue:
			'Same relationship-reasoning value as GraphRAG at lower build cost. Good for medium-complexity graphs where you want relationship context without the full community-detection pipeline.'
	}
};

export const aiSearchExperimentKeys = new Set([
	'keyword',
	'single-vector',
	'hybrid',
	'hybrid-reranker',
	'hybrid-llm-enriched'
]);
export const agenticSearchKeys = new Set(['agentic-kb']);
export const graphRetrievalKeys = new Set(['graphrag', 'lightrag']);
export const searchBaselineResources = new Set(['storage', 'search', 'ai_foundry']);

export const azureServiceCatalog: Record<string, { label: string; plan: string; role: string }> = {
	search: { label: 'Azure AI Search', plan: 'Standard S1', role: 'Index + query engine' },
	storage: { label: 'Azure Storage', plan: 'Standard LRS', role: 'Corpus + build artifacts' },
	ai_foundry: {
		label: 'Azure AI Foundry',
		plan: 'Standard',
		role: 'Embeddings + semantic enrichment'
	},
	openai: { label: 'Azure OpenAI', plan: 'Standard', role: 'Embedding deployment' },
	cosmosdb: { label: 'Azure Cosmos DB', plan: 'Serverless', role: 'Graph + vector store' },
	container_app: { label: 'Azure Container Apps', plan: 'Consumption', role: 'LightRAG server' },
	postgres: {
		label: 'Azure Database for PostgreSQL',
		plan: 'Flexible B1ms',
		role: 'Graph storage'
	}
};

export const architectureResourceFallback: Record<string, string[]> = {
	keyword: ['storage', 'search'],
	'single-vector': ['storage', 'search', 'ai_foundry'],
	hybrid: ['storage', 'search', 'ai_foundry'],
	'hybrid-reranker': ['storage', 'search', 'ai_foundry'],
	'hybrid-llm-enriched': ['storage', 'search', 'ai_foundry'],
	'multi-vector': ['storage', 'search', 'ai_foundry'],
	'agentic-kb': ['storage', 'search', 'ai_foundry'],
	graphrag: ['storage', 'ai_foundry', 'cosmosdb'],
	lightrag: ['storage', 'ai_foundry', 'container_app']
};

export const experimentPresets: ExperimentPreset[] = [
	{
		id: 'quick-baseline',
		name: 'Quick baseline',
		tag: 'Start here',
		description: 'Shows what lexical, vector, hybrid, and ranked hybrid each buy you.',
		businessValue:
			'Use when you need to calibrate what your corpus can actually do before committing to any specific architecture. Answers: does semantic search help here at all?',
		architectures: ['keyword', 'single-vector', 'hybrid', 'hybrid-reranker']
	},
	{
		id: 'quality-sweep',
		name: 'Quality sweep',
		tag: 'AI Search depth',
		description: 'Keeps the comparison inside AI Search and adds enrichment as the upper bound.',
		businessValue:
			'Use when you are already on AI Search and want to know whether the reranker or enrichment earns its added cost. Answers: how much better can this get?',
		architectures: ['keyword', 'hybrid', 'hybrid-reranker', 'hybrid-llm-enriched']
	},
	{
		id: 'cross-paradigm',
		name: 'Cross-paradigm',
		tag: 'Bigger question',
		description: 'Compares the best AI Search shapes against graph and agentic retrieval families.',
		businessValue:
			'Use when you are deciding whether to stay on flat search or move to a graph or agentic system. Answers: is my corpus too relational or complex for a standard index?',
		architectures: ['hybrid-reranker', 'agentic-kb', 'graphrag', 'lightrag']
	}
];

export const advancedControlHelp: Record<string, string> = {
	query_syntax: 'Choose how fancy the keyword query can be. Simple is safest.',
	lexical_search_mode: 'Decide whether a result can match some words or must match every word.',
	search_fields: 'Choose which fields should count for keyword matching.',
	filter_expression:
		'Limit results to a subset, like one category, date range, source, or permission group.',
	scoring_profile: 'Use a saved relevance recipe that boosts certain fields or business signals.',
	top_k: 'How many final results this candidate returns for scoring.',
	vector_k: 'How many semantic neighbors to consider before picking final results.',
	vector_filter_mode: 'Choose whether filters happen before or after semantic matching.',
	vector_weight: 'Decide how strongly semantic similarity should influence hybrid results.',
	vector_exhaustive: 'Run a slower exact vector search to see the quality ceiling.',
	max_text_recall_size:
		'How many keyword matches can compete with vector matches in hybrid search.',
	semantic_ranker_mode: 'Turn the second-stage meaning-based reranker on or off.',
	semantic_captions: 'Return short snippets that explain why each result matched.',
	semantic_answers: 'Try to pull a direct answer sentence from the matched documents.',
	query_rewrites: 'Let search rewrite the question into better search phrases.',
	semantic_max_wait_ms: 'Set how long to wait for semantic ranking before giving up.',
	chunk_size: 'Choose how large each searchable passage should be.',
	chunk_overlap: 'Repeat some text between neighboring chunks to avoid split answers.',
	markdown_parsing_submode: 'Choose whether a markdown file is one result or split by headings.',
	enrichment_profile: 'Add extra fields during indexing, such as summaries or extracted metadata.',
	agentic_knowledge_source: 'Choose where the agentic retriever gets its source material.',
	agentic_reasoning_effort: 'Choose how much planning the retriever does before searching.',
	agentic_output_mode: 'Choose whether to return source material only or a generated answer.',
	agentic_max_runtime_seconds: 'Stop long agentic searches after this many seconds.',
	agentic_include_activity: 'Show the query plan so you can debug why it chose sources.',
	graphrag_index_method: 'Choose cheaper graph setup for eval or fuller graph extraction.',
	graphrag_query_mode:
		'Choose how GraphRAG answers: nearby entities, broad communities, iterative search, or vector baseline.',
	graphrag_storage_target: 'Choose where GraphRAG stores its graph files and reports.',
	graphrag_chunk_size: 'Choose how much text GraphRAG reads at once when building the graph.',
	graphrag_chunk_overlap: 'Repeat text between graph chunks so relationships are not split apart.',
	graphrag_entity_types: 'Tell GraphRAG what kinds of things to extract into the graph.',
	graphrag_max_gleanings: 'Allow extra passes to find missed entities and relationships.',
	graphrag_community_level: 'Choose how broad or narrow the community summaries should be.',
	graphrag_dynamic_community_selection:
		'Let GraphRAG choose the best community level for each question.',
	graphrag_max_context_tokens: 'Limit how much graph context can be sent to the model.',
	graphrag_response_type: 'Choose the answer format GraphRAG should produce.',
	graphrag_prompt_tuning: 'Tune GraphRAG extraction prompts to this domain before indexing.',
	lightrag_query_mode: 'Choose how LightRAG combines graph lookup and vector chunks.',
	lightrag_storage_profile: 'Choose where LightRAG stores graph, vectors, and chunks.',
	lightrag_top_k: 'How many graph entities or relationships LightRAG should retrieve.',
	lightrag_chunk_top_k: 'How many source text chunks LightRAG should include.',
	lightrag_enable_rerank: 'Reorder LightRAG context before answer generation.',
	lightrag_response_type: 'Choose the answer format LightRAG should produce.',
	lightrag_conversation_turns: 'Include prior chat turns when testing follow-up questions.',
	lightrag_debug_mode: 'Show retrieved context or prompt details instead of the normal answer.',
	lightrag_stream: 'Show the answer as it is generated instead of waiting.'
};

export const advancedOptionHelp: Record<string, Record<string, string>> = {
	query_syntax: {
		simple: 'Best default. Good for normal words and phrases.',
		full: 'Use when you need advanced search operators like fuzzy or proximity.',
		semantic: 'Use when semantic ranking should drive the query.'
	},
	lexical_search_mode: {
		any: 'Broader search. Results can match some words.',
		all: 'Stricter search. Results must match every word.'
	},
	vector_filter_mode: {
		preFilter: 'Filter first, then do semantic matching.',
		postFilter: 'Find semantic matches first, then filter.',
		strictPostFilter: 'Only keep filtered items from the global best semantic matches.'
	},
	semantic_ranker_mode: {
		auto: 'Use the ranker only where the candidate expects it.',
		on: 'Always rerank this candidate by meaning.',
		off: 'Turn reranking off to measure the first-stage search alone.'
	},
	semantic_captions: {
		none: 'No snippets.',
		extractive: 'Return short matching snippets.',
		'extractive|highlight-true': 'Return snippets with highlighted matches.'
	},
	semantic_answers: {
		none: 'No direct answer extraction.',
		extractive: 'Try to extract a direct answer from matched documents.'
	},
	query_rewrites: {
		none: 'Search with the original question.',
		generative: 'Let search create better search phrases first.'
	},
	markdown_parsing_submode: {
		oneToMany: 'Split files by headings.',
		oneToOne: 'Keep each file as one document.'
	},
	enrichment_profile: {
		none: 'Do not add extra fields.',
		llm_metadata: 'Use an LLM to add summaries or metadata.',
		content_understanding: 'Extract richer document structure.',
		ocr_layout: 'Extract text/layout from PDFs and images.'
	},
	agentic_knowledge_source: {
		'search-index': 'Use the existing search index.',
		blob: 'Read from Blob Storage.',
		web: 'Read from web sources.',
		'multi-source': 'Combine several source types.'
	},
	agentic_reasoning_effort: {
		minimal: 'Fastest. Little or no planning.',
		low: 'Balanced default.',
		medium: 'More planning for harder questions.'
	},
	agentic_output_mode: {
		extractiveData: 'Return source material for another model to use.',
		answerSynthesis: 'Generate a cited answer directly.'
	},
	graphrag_index_method: {
		fast: 'Cheaper and faster graph build for experiments.',
		standard: 'Full graph build with deeper extraction.'
	},
	graphrag_query_mode: {
		local: 'Best for questions about a specific entity or policy.',
		global: 'Best for broad themes across the corpus.',
		drift: 'Best for questions that need broad context and follow-up exploration.',
		basic: 'Vector RAG baseline without graph reasoning.'
	},
	graphrag_storage_target: {
		file: 'Local files. Fastest for eval.',
		blob: 'Store graph files in Blob Storage.',
		cosmosdb: 'Use Cosmos DB for production-style graph storage.'
	},
	graphrag_response_type: {
		'multiple-paragraphs': 'Longer narrative answer.',
		'bullet-points': 'Concise bullet list.',
		'short-answer': 'Shortest answer.'
	},
	lightrag_query_mode: {
		mix: 'Recommended. Combines graph and vector chunk retrieval.',
		hybrid: 'Combines local entity and global relationship lookup.',
		local: 'Use nearby entities in the graph.',
		global: 'Use relationship-level graph matches.',
		naive: 'Vector chunks only, no graph.',
		bypass: 'No retrieval. Direct model answer.'
	},
	lightrag_storage_profile: {
		'eval-local': 'Local workspace for quick eval.',
		'container-postgres': 'Container app with PostgreSQL storage.',
		'mongo-vcore': 'Mongo-compatible storage on Cosmos DB vCore.'
	},
	lightrag_response_type: {
		'multiple-paragraphs': 'Longer narrative answer.',
		'bullet-points': 'Concise bullet list.',
		'short-answer': 'Shortest answer.'
	},
	lightrag_debug_mode: {
		none: 'Normal answer.',
		context: 'Show only retrieved context.',
		prompt: 'Show only the generated prompt.'
	}
};

function textControl(field: string, label: string, fallback: string, placeholder = ''): RowControl {
	return { kind: 'text', field, label, fallback, placeholder };
}

function numberControl(
	field: string,
	label: string,
	fallback: string,
	min: number,
	max: number,
	step = 1
): RowControl {
	return { kind: 'number', field, label, fallback, min, max, step };
}

function selectControl(
	field: string,
	label: string,
	fallback: string,
	options: Array<{ value: string; label: string }>
): RowControl {
	return { kind: 'select', field, label, fallback, options };
}

function checkboxControl(field: string, label: string, fallback = false): RowControl {
	return { kind: 'checkbox', field, label, fallback };
}

export function buildRowControls(
	architecture: string,
	sessionString: (key: string, fallback?: string) => string
): RowControl[] {
	const fullText = [
		selectControl('query_syntax', 'Query syntax', sessionString('query_syntax', 'simple'), [
			{ value: 'simple', label: 'Simple query syntax' },
			{ value: 'full', label: 'Full Lucene syntax' },
			{ value: 'semantic', label: 'Semantic query' }
		]),
		selectControl(
			'lexical_search_mode',
			'Term matching',
			sessionString('lexical_search_mode', 'any'),
			[
				{ value: 'any', label: 'Any term can match' },
				{ value: 'all', label: 'All terms must match' }
			]
		),
		textControl('search_fields', 'Search fields', sessionString('search_fields', 'content,title')),
		textControl('filter_expression', 'Filter expression', sessionString('filter_expression')),
		textControl('scoring_profile', 'Scoring profile', sessionString('scoring_profile')),
		numberControl('top_k', 'Returned results', sessionString('top_k', '10'), 1, 100)
	];
	const vector = [
		numberControl('top_k', 'Returned results', sessionString('top_k', '10'), 1, 100),
		numberControl('vector_k', 'Vector neighbors', sessionString('vector_k', '50'), 1, 1000),
		selectControl(
			'vector_filter_mode',
			'Vector filter mode',
			sessionString('vector_filter_mode', 'preFilter'),
			[
				{ value: 'preFilter', label: 'Pre-filter before vector search' },
				{ value: 'postFilter', label: 'Post-filter after vector search' },
				{ value: 'strictPostFilter', label: 'Strict post-filter' }
			]
		),
		numberControl(
			'vector_weight',
			'Vector weight',
			sessionString('vector_weight', '1'),
			0.1,
			5,
			0.1
		),
		checkboxControl('vector_exhaustive', 'Use exhaustive KNN for exact vector comparison')
	];
	const hybrid = [
		...fullText,
		...vector.filter((control) => control.field !== 'top_k'),
		numberControl(
			'max_text_recall_size',
			'Hybrid text recall window',
			sessionString('max_text_recall_size', '1000'),
			1,
			10000
		)
	];
	const semantic = [
		...hybrid,
		selectControl(
			'semantic_ranker_mode',
			'Semantic ranker',
			sessionString('semantic_ranker_mode', 'auto'),
			[
				{ value: 'auto', label: 'Auto for ranked candidates' },
				{ value: 'on', label: 'Force on' },
				{ value: 'off', label: 'Force off' }
			]
		),
		selectControl('semantic_captions', 'Captions', sessionString('semantic_captions', 'none'), [
			{ value: 'none', label: 'None' },
			{ value: 'extractive', label: 'Extractive captions' },
			{ value: 'extractive|highlight-true', label: 'Extractive + highlights' }
		]),
		selectControl('semantic_answers', 'Answers', sessionString('semantic_answers', 'none'), [
			{ value: 'none', label: 'None' },
			{ value: 'extractive', label: 'Extractive answers' }
		]),
		selectControl('query_rewrites', 'Query rewrites', sessionString('query_rewrites', 'none'), [
			{ value: 'none', label: 'None' },
			{ value: 'generative', label: 'Generative rewrites' }
		]),
		numberControl(
			'semantic_max_wait_ms',
			'Semantic max wait ms',
			sessionString('semantic_max_wait_ms', '1000'),
			100,
			10000,
			100
		)
	];
	const enrichment = [
		...semantic,
		numberControl('chunk_size', 'Chunk size', sessionString('chunk_size', '2000'), 128, 8192),
		numberControl('chunk_overlap', 'Chunk overlap', sessionString('chunk_overlap', '500'), 0, 2048),
		selectControl(
			'markdown_parsing_submode',
			'Markdown parsing',
			sessionString('markdown_parsing_submode', 'oneToMany'),
			[
				{ value: 'oneToMany', label: 'One heading section per search document' },
				{ value: 'oneToOne', label: 'One source file per search document' }
			]
		),
		selectControl(
			'enrichment_profile',
			'Enrichment profile',
			sessionString('enrichment_profile', 'none'),
			[
				{ value: 'none', label: 'No extra enrichment' },
				{ value: 'llm_metadata', label: 'LLM metadata extraction' },
				{ value: 'content_understanding', label: 'Content Understanding' },
				{ value: 'ocr_layout', label: 'OCR / layout extraction' }
			]
		)
	];

	if (architecture === 'keyword') return fullText;
	if (architecture === 'single-vector' || architecture === 'multi-vector') return vector;
	if (architecture === 'hybrid') return hybrid;
	if (architecture === 'hybrid-reranker') return semantic;
	if (architecture === 'hybrid-llm-enriched') return enrichment;
	if (architecture === 'agentic-kb') {
		return [
			selectControl(
				'agentic_knowledge_source',
				'Knowledge source',
				sessionString('agentic_knowledge_source', 'search-index'),
				[
					{ value: 'search-index', label: 'Search index knowledge source' },
					{ value: 'blob', label: 'Blob knowledge source' },
					{ value: 'web', label: 'Web knowledge source' },
					{ value: 'multi-source', label: 'Multiple knowledge sources' }
				]
			),
			selectControl(
				'agentic_reasoning_effort',
				'Reasoning effort',
				sessionString('agentic_reasoning_effort', 'low'),
				[
					{ value: 'minimal', label: 'Minimal: fastest, no LLM planning' },
					{ value: 'low', label: 'Low: balanced planning' },
					{ value: 'medium', label: 'Medium: maximum relevance work' }
				]
			),
			selectControl(
				'agentic_output_mode',
				'Output mode',
				sessionString('agentic_output_mode', 'extractiveData'),
				[
					{ value: 'extractiveData', label: 'Extractive grounding data' },
					{ value: 'answerSynthesis', label: 'Citation-backed answer synthesis' }
				]
			),
			numberControl(
				'agentic_max_runtime_seconds',
				'Max runtime seconds',
				sessionString('agentic_max_runtime_seconds', '30'),
				5,
				120
			),
			checkboxControl('agentic_include_activity', 'Include query plan/activity in results', true)
		];
	}
	if (architecture === 'graphrag') {
		return [
			selectControl(
				'graphrag_index_method',
				'Indexing method',
				sessionString('graphrag_index_method', 'fast'),
				[
					{ value: 'fast', label: 'Fast eval index' },
					{ value: 'standard', label: 'Standard graph extraction' }
				]
			),
			selectControl(
				'graphrag_query_mode',
				'Query mode',
				sessionString('graphrag_query_mode', 'local'),
				[
					{ value: 'local', label: 'Local entity-neighborhood search' },
					{ value: 'global', label: 'Global community report search' },
					{ value: 'drift', label: 'DRIFT iterative graph search' },
					{ value: 'basic', label: 'Basic vector RAG baseline' }
				]
			),
			selectControl(
				'graphrag_storage_target',
				'Artifact storage',
				sessionString('graphrag_storage_target', 'file'),
				[
					{ value: 'file', label: 'Local parquet/files for eval' },
					{ value: 'blob', label: 'Blob artifact storage' },
					{ value: 'cosmosdb', label: 'Cosmos DB production storage' }
				]
			),
			numberControl(
				'graphrag_chunk_size',
				'Chunk size tokens',
				sessionString('graphrag_chunk_size', '1200'),
				128,
				4000
			),
			numberControl(
				'graphrag_chunk_overlap',
				'Chunk overlap tokens',
				sessionString('graphrag_chunk_overlap', '100'),
				0,
				1000
			),
			textControl(
				'graphrag_entity_types',
				'Entity types',
				sessionString(
					'graphrag_entity_types',
					'organization, person, geo, event, policy, regulation'
				),
				'policy, regulation, program, form'
			),
			numberControl(
				'graphrag_max_gleanings',
				'Max gleanings',
				sessionString('graphrag_max_gleanings', '1'),
				0,
				5
			),
			numberControl(
				'graphrag_community_level',
				'Community level',
				sessionString('graphrag_community_level', '2'),
				0,
				5
			),
			checkboxControl('graphrag_dynamic_community_selection', 'Dynamic community selection', false),
			numberControl(
				'graphrag_max_context_tokens',
				'Max context tokens',
				sessionString('graphrag_max_context_tokens', '12000'),
				1000,
				64000,
				1000
			),
			selectControl(
				'graphrag_response_type',
				'Response style',
				sessionString('graphrag_response_type', 'multiple-paragraphs'),
				[
					{ value: 'multiple-paragraphs', label: 'Multiple paragraphs' },
					{ value: 'bullet-points', label: 'Bullet points' },
					{ value: 'short-answer', label: 'Short answer' }
				]
			),
			checkboxControl('graphrag_prompt_tuning', 'Run domain prompt tuning first')
		];
	}
	if (architecture === 'lightrag') {
		return [
			selectControl(
				'lightrag_query_mode',
				'Query mode',
				sessionString('lightrag_query_mode', 'mix'),
				[
					{ value: 'mix', label: 'Mix: KG + vector chunks' },
					{ value: 'hybrid', label: 'Hybrid: local + global graph' },
					{ value: 'local', label: 'Local entity search' },
					{ value: 'global', label: 'Global relationship search' },
					{ value: 'naive', label: 'Naive vector baseline' },
					{ value: 'bypass', label: 'Bypass retrieval' }
				]
			),
			selectControl(
				'lightrag_storage_profile',
				'Storage profile',
				sessionString('lightrag_storage_profile', 'eval-local'),
				[
					{ value: 'eval-local', label: 'Eval local workspace' },
					{ value: 'container-postgres', label: 'Container Apps + PostgreSQL' },
					{ value: 'mongo-vcore', label: 'Cosmos DB for MongoDB vCore' }
				]
			),
			numberControl(
				'lightrag_top_k',
				'Entity/relation top K',
				sessionString('lightrag_top_k', '60'),
				1,
				200
			),
			numberControl(
				'lightrag_chunk_top_k',
				'Chunk top K',
				sessionString('lightrag_chunk_top_k', '20'),
				1,
				100
			),
			checkboxControl('lightrag_enable_rerank', 'Enable reranker in mix mode'),
			selectControl(
				'lightrag_response_type',
				'Response style',
				sessionString('lightrag_response_type', 'multiple-paragraphs'),
				[
					{ value: 'multiple-paragraphs', label: 'Multiple paragraphs' },
					{ value: 'bullet-points', label: 'Bullet points' },
					{ value: 'short-answer', label: 'Short answer' }
				]
			),
			numberControl(
				'lightrag_conversation_turns',
				'Conversation history turns',
				sessionString('lightrag_conversation_turns', '0'),
				0,
				20
			),
			selectControl(
				'lightrag_debug_mode',
				'Debug output',
				sessionString('lightrag_debug_mode', 'none'),
				[
					{ value: 'none', label: 'Normal response' },
					{ value: 'context', label: 'Only retrieved context' },
					{ value: 'prompt', label: 'Only generated prompt' }
				]
			),
			checkboxControl('lightrag_stream', 'Stream response from server')
		];
	}
	return [];
}
