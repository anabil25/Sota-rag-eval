<script lang="ts">
	import { resolve } from '$app/paths';
	import MetricGrid from '$lib/components/MetricGrid.svelte';
	import RouteHeader from '$lib/components/RouteHeader.svelte';
	import type { MetricItem } from '$lib/api/types';

	let { data } = $props();

	const metrics = $derived<MetricItem[]>([
		{ label: 'Recall@10', value: metricLabel(data.run.run, 'recall_at_10'), tone: 'success' },
		{ label: 'MRR', value: metricLabel(data.run.run, 'mrr_at_10') },
		{
			label: 'Average latency',
			value: metricLabel(data.run.run, 'avg_latency_ms', 0, ' ms')
		},
		{
			label: 'Failures',
			value: String(data.run.run.failure_count ?? 0),
			tone: data.run.run.failure_count ? 'warning' : 'success'
		}
	]);

	function runMetric(source: unknown, key: string) {
		const sourceRecord = source as Record<string, unknown>;
		const aggregate = sourceRecord.aggregate_metrics;
		const record = aggregate && typeof aggregate === 'object' ? aggregate : sourceRecord;
		return (record as Record<string, unknown>)[key];
	}

	function metricLabel(source: unknown, key: string, decimals = 3, suffix = '') {
		const value = runMetric(source, key);
		return typeof value === 'number' ? `${value.toFixed(decimals)}${suffix}` : 'n/a';
	}

	function scoreLabel(scores: Record<string, number> | undefined, key: string) {
		const value = scores?.[key];
		return typeof value === 'number' ? value.toFixed(3) : 'n/a';
	}
</script>

<section class="route-shell">
	<div class="content-wide route-stack">
		<RouteHeader title={data.run.run.architecture_name} subtitle={`Run ${data.run.run.id}`}>
			{#snippet actions()}
				<a class="button" href={resolve('/runs')}>Back to Runs</a>
			{/snippet}
		</RouteHeader>

		<MetricGrid {metrics} />

		<section class="page-section section-stack" aria-labelledby="category-heading">
			<div>
				<p class="eyebrow">Breakdown</p>
				<h2 id="category-heading">Category Scores</h2>
			</div>
			<div class="table-scroll">
				<table>
					<thead
						><tr
							><th>Category</th><th>Recall@10</th><th>MRR@10</th><th>nDCG@10</th><th>Failures</th
							><th>Questions</th></tr
						></thead
					>
					<tbody>
						{#each data.run.categories as category (category.category)}
							<tr>
								<td>{category.category}</td>
								<td>{category.recall_at_10?.toFixed(3) ?? 'n/a'}</td>
								<td>{category.mrr_at_10?.toFixed(3) ?? 'n/a'}</td>
								<td>{category.ndcg_at_10?.toFixed(3) ?? 'n/a'}</td>
								<td>{category.failure_count ?? 0}</td>
								<td>{category.total_questions ?? 0}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</section>

		<section class="page-section section-stack" aria-labelledby="results-heading">
			<div>
				<p class="eyebrow">Questions</p>
				<h2 id="results-heading">Per-Question Results</h2>
			</div>
			<div class="table-scroll">
				<table>
					<thead
						><tr
							><th>Question</th><th>Category</th><th>Recall@10</th><th>MRR@10</th><th>nDCG@10</th
							><th>Latency</th><th>Retrieved</th></tr
						></thead
					>
					<tbody>
						{#each data.run.results as result (result.id ?? result.question_id)}
							<tr>
								<td>{result.question_text ?? `Question ${result.question_id}`}</td>
								<td>{result.category ?? 'n/a'}</td>
								<td>{scoreLabel(result.scores, 'recall_at_10')}</td>
								<td>{scoreLabel(result.scores, 'mrr_at_10')}</td>
								<td>{scoreLabel(result.scores, 'ndcg_at_10')}</td>
								<td>{result.latency_ms ? `${result.latency_ms.toFixed(0)} ms` : 'n/a'}</td>
								<td>
									{#if result.retrieved_chunk_ids?.length}
										<details>
											<summary>{result.retrieved_chunk_ids.length} chunks</summary>
											{#each result.retrieved_chunk_ids as chunkId (chunkId)}<div class="mono-cell">
													{chunkId}
												</div>{/each}
										</details>
									{:else}
										n/a
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</section>

		<section class="page-section section-stack" aria-labelledby="failure-heading">
			<div>
				<p class="eyebrow">Miss analysis</p>
				<h2 id="failure-heading">Failures</h2>
			</div>
			{#if data.run.failures.length > 0}
				<div class="table-scroll">
					<table>
						<thead
							><tr
								><th>Question</th><th>Type</th><th>Expected</th><th>Top retrieved</th><th
									>Details</th
								></tr
							></thead
						>
						<tbody>
							{#each data.run.failures as failure (failure.id ?? failure.question_id)}
								<tr>
									<td>{failure.question_text ?? `Question ${failure.question_id}`}</td>
									<td><span class="status-pill">{failure.failure_type ?? 'miss'}</span></td>
									<td class="mono-cell"
										>{failure.expected_chunk_id ?? failure.ground_truth_chunk_ids?.[0] ?? 'n/a'}</td
									>
									<td class="mono-cell"
										>{failure.top_retrieved_id ?? failure.retrieved_chunk_ids?.[0] ?? 'n/a'}</td
									>
									<td>{failure.failure_details ?? 'n/a'}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{:else}
				<p class="muted">No misses recorded for this run.</p>
			{/if}
		</section>
	</div>
</section>

<style>
	h2 {
		font-size: clamp(1.3rem, 2vw, 1.8rem);
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

	.mono-cell {
		max-inline-size: 18rem;
		overflow-wrap: anywhere;
		font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
		font-size: 0.82rem;
	}
</style>
