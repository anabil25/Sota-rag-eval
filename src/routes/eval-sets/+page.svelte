<script lang="ts">
	import { resolve } from '$app/paths';
	import DataEmptyState from '$lib/components/DataEmptyState.svelte';
	import MetricGrid from '$lib/components/MetricGrid.svelte';
	import RouteHeader from '$lib/components/RouteHeader.svelte';
	import { parseEvalCategoryCounts } from '$lib/eval-taxonomy';
	import type { EvalSet, MetricItem } from '$lib/api/types';

	let { data } = $props();

	function questionTotal(evalSet: EvalSet) {
		return evalSet.question_count ?? 0;
	}

	function categorySummary(count: number) {
		return count === 1 ? '1 retrieval category covered' : `${count} retrieval categories covered`;
	}

	function categoryEntries(evalSet: EvalSet) {
		return Object.entries(parseEvalCategoryCounts(evalSet.category_counts))
			.sort(([, left], [, right]) => right - left)
			.map(([id, count]) => ({ id, count }));
	}

	const totalQuestions = $derived(
		data.evalSets.reduce((total: number, evalSet: EvalSet) => total + questionTotal(evalSet), 0)
	);
	const distinctCategories = $derived(
		new Set(
			data.evalSets.flatMap((evalSet: EvalSet) =>
				Object.keys(parseEvalCategoryCounts(evalSet.category_counts))
			)
		)
	);
	const metrics = $derived<MetricItem[]>([
		{ label: 'Eval sets', value: String(data.evalSets.length), note: 'Reusable golden versions' },
		{ label: 'Questions', value: String(totalQuestions), note: 'Across saved sets' },
		{ label: 'Categories', value: String(distinctCategories.size), note: 'Retrieval failure modes' }
	]);
</script>

<section class="route-shell">
	<div class="content-wide route-stack">
		<RouteHeader
			title="Golden Eval Sets"
			subtitle="Versioned measurement sets that keep the corpus questions stable while you compare retrieval architectures."
		>
			{#snippet actions()}
				<a class="button primary" href={resolve('/flow/eval')}>Build, Import, or Curate</a>
			{/snippet}
		</RouteHeader>

		<MetricGrid {metrics} />

		<section class="page-section section-stack" aria-labelledby="eval-heading">
			<div>
				<p class="eyebrow">Measurement library</p>
				<h2 id="eval-heading">Available golden sets</h2>
				<p class="muted">
					Each set should represent the retrieval behaviors you want to stress: exact terms,
					paraphrase, multi-hop reasoning, graph/global questions, exceptions, temporal rules, and
					operator-defined categories.
				</p>
			</div>

			{#if data.evalSets.length > 0}
				<div class="eval-grid">
					{#each data.evalSets as evalSet (evalSet.id)}
						{@const categories = categoryEntries(evalSet)}
						<a class="card eval-card" href={resolve(`/eval-sets/${evalSet.id}`)}>
							<div class="eval-card-head">
								<strong>{evalSet.version_label}</strong>
								<span class="status-pill">{questionTotal(evalSet)} questions</span>
							</div>
							<p>
								{categories.length
									? categorySummary(categories.length)
									: 'No category coverage reported yet'}
							</p>
							{#if categories.length}
								<div class="category-preview" aria-label="Category coverage preview">
									{#each categories.slice(0, 4) as category (category.id)}
										<span class="taxonomy-pill">
											{category.id}
											<small>{category.count}</small>
										</span>
									{/each}
									{#if categories.length > 4}
										<span class="taxonomy-pill muted">+{categories.length - 4} more</span>
									{/if}
								</div>
							{/if}
							<span class="created-at">{evalSet.created_at ?? 'Created locally'}</span>
						</a>
					{/each}
				</div>
			{:else}
				<DataEmptyState
					title="No golden eval sets yet"
					description="Generate, import, or curate one from the Eval workflow step."
				/>
			{/if}
		</section>
	</div>
</section>

<style>
	h2 {
		font-size: clamp(1.3rem, 2vw, 1.8rem);
	}

	.eval-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 20rem), 1fr));
		gap: var(--space-md);
	}

	.eval-card {
		display: grid;
		gap: var(--space-sm);
	}

	.eval-card:hover {
		border-color: var(--color-border-strong);
		background: var(--color-surface-raised);
		text-decoration: none;
	}

	.eval-card-head {
		display: flex;
		align-items: start;
		justify-content: space-between;
		gap: var(--space-sm);
	}

	.eval-card p,
	.created-at {
		color: var(--color-muted);
	}

	.category-preview {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2xs);
	}

	.taxonomy-pill {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2xs);
		padding: 0.2rem 0.55rem;
		border: var(--rule-size) solid var(--color-border);
		border-radius: 999rem;
		background: var(--color-surface-raised);
		color: var(--color-text);
		font-size: 0.82rem;
		font-weight: 700;
	}

	.taxonomy-pill small {
		color: var(--color-muted);
		font-size: 0.72rem;
	}
</style>
