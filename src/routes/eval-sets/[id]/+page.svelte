<script lang="ts">
	import { resolve } from '$app/paths';
	import MetricGrid from '$lib/components/MetricGrid.svelte';
	import RouteHeader from '$lib/components/RouteHeader.svelte';
	import type { EvalQuestion, MetricItem } from '$lib/api/types';

	let { data } = $props();

	function unique(values: Array<string | null | undefined>) {
		return [...new Set(values.filter((value): value is string => Boolean(value)))].sort();
	}

	function questionCountLabel(count: number) {
		return `${count} question${count === 1 ? '' : 's'}`;
	}

	function groupedCategories(questions: EvalQuestion[]) {
		const groups: Record<string, EvalQuestion[]> = {};
		for (const question of questions) {
			if (!question.category) continue;
			groups[question.category] = [...(groups[question.category] ?? []), question];
		}

		return Object.entries(groups)
			.map(([id, items]) => ({
				id,
				count: items.length,
				questionTypes: unique(items.map((question) => question.question_type)),
				personas: unique(items.map((question) => question.persona)),
				intents: unique(items.map((question) => question.intent_family)),
				examples: items.map((question) => question.question_text).slice(0, 2)
			}))
			.sort((left, right) => right.count - left.count || left.id.localeCompare(right.id));
	}

	const categoryRows = $derived(
		groupedCategories(
			(data.allQuestions.length ? data.allQuestions : data.questions) as EvalQuestion[]
		)
	);
	const filterOptions = $derived({
		categories: categoryRows.map((category) => category.id),
		questionTypes: unique(
			data.allQuestions.map((question: EvalQuestion) => question.question_type)
		),
		personas: unique(data.allQuestions.map((question: EvalQuestion) => question.persona)),
		intents: unique(data.allQuestions.map((question: EvalQuestion) => question.intent_family))
	});
	const metrics = $derived<MetricItem[]>([
		{
			label: 'Questions',
			value: String(data.summary.eval_set.question_count ?? data.questions.length),
			note: 'Measurement prompts'
		},
		{
			label: 'Categories',
			value: String(categoryRows.length),
			note: 'Retrieval failure modes'
		},
		{
			label: 'Question types',
			value: String(filterOptions.questionTypes.length),
			note: 'From question JSON'
		}
	]);
</script>

<section class="route-shell">
	<div class="content-wide route-stack">
		<RouteHeader
			title={data.summary.eval_set.version_label}
			subtitle="Golden eval set coverage, taxonomy, and inspectable questions."
		>
			{#snippet actions()}
				<a class="button" href={resolve('/eval-sets')}>Back to Eval Sets</a>
				<a class="button primary" href={resolve('/flow/eval')}>Refine in Eval Flow</a>
			{/snippet}
		</RouteHeader>

		<MetricGrid {metrics} />

		<section class="page-section eval-purpose section-stack" aria-labelledby="purpose-heading">
			<div>
				<p class="eyebrow">Measurement intent</p>
				<h2 id="purpose-heading">What this set is meant to stress</h2>
				<p class="muted">
					A golden eval set should hold the workload still while Configure changes retrieval
					architectures. The useful question is not only how many prompts it has, but whether it
					covers the failure modes that separate keyword, vector, hybrid, reranked, graph, and
					agentic retrieval.
				</p>
			</div>
		</section>

		<section class="page-section section-stack" aria-labelledby="coverage-heading">
			<div>
				<p class="eyebrow">Coverage</p>
				<h2 id="coverage-heading">Retrieval categories</h2>
				<p class="muted">
					Categories, types, personas, and intents are read from the eval questions themselves so
					generated or imported JSON stays visible without maintaining a separate hardcoded list.
				</p>
			</div>

			{#if categoryRows.length}
				<div class="category-grid">
					{#each categoryRows as category (category.id)}
						<article class="category-card">
							<header>
								<div>
									<strong>{category.id}</strong>
								</div>
								<span class="status-pill">{questionCountLabel(category.count)}</span>
							</header>
							<div class="category-facets" aria-label={`${category.id} facets`}>
								{#if category.questionTypes.length}
									<span>Types: {category.questionTypes.join(', ')}</span>
								{/if}
								{#if category.personas.length}
									<span>Personas: {category.personas.join(', ')}</span>
								{/if}
								{#if category.intents.length}
									<span>Intents: {category.intents.join(', ')}</span>
								{/if}
							</div>
							{#if category.examples.length}
								<ul class="example-list" aria-label={`${category.id} examples`}>
									{#each category.examples.slice(0, 2) as example (example)}
										<li>{example}</li>
									{/each}
								</ul>
							{/if}
						</article>
					{/each}
				</div>
			{:else}
				<p class="muted">No category coverage reported for this eval set.</p>
			{/if}
		</section>

		<section class="page-section section-stack" aria-labelledby="questions-heading">
			<div>
				<p class="eyebrow">Inspect</p>
				<h2 id="questions-heading">Question browser</h2>
				<p class="muted">Showing {data.questions.length} of {data.total} questions.</p>
			</div>
			<form class="toolbar" method="GET">
				<label>
					<span>Category</span>
					<select name="category">
						<option value="">All categories</option>
						{#each filterOptions.categories as category (category)}
							<option value={category} selected={category === data.filters.category}
								>{category}</option
							>
						{/each}
					</select>
				</label>
				<label>
					<span>Type</span>
					<select name="question_type">
						<option value="">All types</option>
						{#each filterOptions.questionTypes as type (type)}
							<option value={type} selected={type === data.filters.question_type}>{type}</option>
						{/each}
					</select>
				</label>
				<label>
					<span>Persona</span>
					<select name="persona">
						<option value="">All personas</option>
						{#each filterOptions.personas as persona (persona)}
							<option value={persona} selected={persona === data.filters.persona}>{persona}</option>
						{/each}
					</select>
				</label>
				<label>
					<span>Intent</span>
					<select name="intent_family">
						<option value="">All intents</option>
						{#each filterOptions.intents as intent (intent)}
							<option value={intent} selected={intent === data.filters.intent_family}
								>{intent}</option
							>
						{/each}
					</select>
				</label>
				<button class="button" type="submit">Apply Filters</button>
			</form>
			<div class="table-scroll">
				<table>
					<thead>
						<tr>
							<th>ID</th>
							<th>Question</th>
							<th>Policy</th>
							<th>Category</th>
							<th>Type</th>
							<th>Persona</th>
							<th>Intent</th>
						</tr>
					</thead>
					<tbody>
						{#each data.questions as question (question.id)}
							<tr>
								<td>{question.id}</td>
								<td>{question.question_text}</td>
								<td>{question.source_doc_id}</td>
								<td>
									<span class="taxonomy-mini">{question.category}</span>
								</td>
								<td>{question.question_type ?? 'n/a'}</td>
								<td>{question.persona ?? 'n/a'}</td>
								<td>{question.intent_family ?? 'n/a'}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</section>
	</div>
</section>

<style>
	h2 {
		font-size: clamp(1.3rem, 2vw, 1.8rem);
	}

	.category-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 22rem), 1fr));
		gap: var(--space-md);
	}

	.category-card {
		display: grid;
		gap: var(--space-sm);
		padding: var(--space-md);
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}

	.category-card header {
		display: flex;
		align-items: start;
		justify-content: space-between;
		gap: var(--space-sm);
	}

	.category-card header div {
		display: grid;
		gap: var(--space-2xs);
	}

	.category-card header span,
	.category-facets,
	.example-list {
		color: var(--color-muted);
	}

	.category-facets {
		display: grid;
		gap: var(--space-2xs);
		font-size: 0.86rem;
	}

	.example-list {
		display: grid;
		gap: var(--space-2xs);
		margin: 0;
		padding-inline-start: var(--space-md);
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
		vertical-align: top;
	}

	th {
		color: var(--color-muted);
		font-size: 0.78rem;
		text-transform: uppercase;
	}

	.toolbar {
		display: grid;
		grid-template-columns: repeat(4, minmax(min(100%, 12rem), 1fr)) auto;
		align-items: end;
		gap: var(--space-sm);
	}

	.toolbar label {
		display: grid;
		gap: var(--space-2xs);
		min-inline-size: min(100%, 12rem);
		color: var(--color-muted);
		font-size: 0.82rem;
		font-weight: 800;
	}

	.toolbar .button {
		align-self: end;
		justify-content: center;
		min-block-size: var(--tap-target);
	}

	select {
		min-block-size: var(--tap-target);
		padding-inline: var(--space-sm);
		border: var(--rule-size) solid var(--color-border-strong);
		border-radius: var(--radius-sm);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
	}

	.taxonomy-mini {
		display: inline-flex;
		padding: 0.1rem 0.45rem;
		border: var(--rule-size) solid var(--color-border);
		border-radius: 999rem;
		background: var(--color-surface-raised);
		font-size: 0.82rem;
	}

	@media (max-width: 62rem) {
		.toolbar {
			grid-template-columns: repeat(auto-fit, minmax(min(100%, 12rem), 1fr));
		}
	}
</style>
