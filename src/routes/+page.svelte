<script lang="ts">
	import { resolve } from '$app/paths';
	import MetricGrid from '$lib/components/MetricGrid.svelte';
	import RouteHeader from '$lib/components/RouteHeader.svelte';

	let { data } = $props();
</script>

<section class="route-shell">
	<div class="content-wide route-stack">
		<RouteHeader title="Retrieve">
			{#snippet actions()}
				<a class="button primary" href={resolve('/flow/ingest')}>Open Workflow</a>
			{/snippet}
		</RouteHeader>

		<section class="intro-section" aria-label="What Retrieve is for">
			<div class="intro-text">
				<p class="eyebrow">What is Retrieve?</p>
				<h2>Which retrieval architecture works best on your content?</h2>
				<p class="intro-body">
					Retrieve is a measurement workbench for Azure AI Search. You ingest your corpus, write
					golden eval questions, configure a matrix of search architectures — keyword, hybrid,
					hybrid+reranker — then deploy, run, and compare. The answer is a ranked scorecard backed
					by your actual documents and queries, not benchmarks from someone else's dataset.
				</p>
				<p class="intro-questions">
					<strong>Answer questions like:</strong> Is semantic reranking worth the cost on my corpus? Does
					hybrid search outperform keyword-only for short queries? Which embedding model improves recall
					the most?
				</p>
			</div>

			<div class="intro-aside card" aria-label="Result preview">
				{#if data.runs.length > 0}
					<p class="eyebrow">Current results</p>
					<ol class="mini-scorecard" role="list">
						{#each data.runs
							.toSorted((a, b) => (b.recall_at_10 ?? 0) - (a.recall_at_10 ?? 0))
							.slice(0, 4) as run, i (run.id ?? i)}
							<li class="mini-row">
								<span class="mini-rank">#{i + 1}</span>
								<span class="mini-arch">{run.architecture_name}</span>
								<span class="mini-score" class:best={i === 0}>
									{run.recall_at_10 !== undefined ? `${Math.round(run.recall_at_10 * 100)}%` : '—'}
								</span>
							</li>
						{/each}
					</ol>
					<p class="mini-label">Recall@10 · ranked by your corpus</p>
				{:else}
					<p class="eyebrow">What gets measured</p>
					<ul class="metric-explainer" role="list">
						<li>
							<strong>Recall@10</strong>
							<span>Did the right documents appear in the top 10 results?</span>
						</li>
						<li>
							<strong>NDCG</strong>
							<span>Were the most relevant documents ranked highest?</span>
						</li>
						<li>
							<strong>MRR</strong>
							<span>How quickly did the first relevant result appear?</span>
						</li>
					</ul>
					<p class="mini-label">Backed by your own queries, not external benchmarks.</p>
				{/if}
			</div>
		</section>

		<section class="page-section section-stack" aria-labelledby="status-heading">
			<div>
				<p class="eyebrow">Workspace status</p>
				<h2 id="status-heading">Current measurements</h2>
			</div>
			<MetricGrid metrics={data.metrics} />
		</section>

		<section class="page-section section-stack" aria-labelledby="steps-heading">
			<div>
				<p class="eyebrow">The process</p>
				<h2 id="steps-heading">Seven steps, one answer</h2>
			</div>
			<ol class="steps-grid" role="list">
				{#each data.steps as step (step.id)}
					<li>
						<a class="step-card card" href={step.href} data-state={step.state}>
							<span class="step-number">{step.index}</span>
							<div class="step-body">
								<strong>{step.title}</strong>
								<span>{step.subtitle}</span>
							</div>
							{#if step.state === 'done'}
								<span class="step-badge done" aria-label="Complete">✓</span>
							{:else if step.state === 'active'}
								<span class="step-badge active" aria-label="In progress">→</span>
							{/if}
						</a>
					</li>
				{/each}
			</ol>
		</section>
	</div>
</section>

<style>
	.intro-section {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: var(--space-lg, 2rem);
		align-items: start;
		padding-block: var(--space-md, 1.25rem);
		border-block: var(--rule-size, 1px) solid var(--color-border);
	}

	.intro-text {
		display: grid;
		gap: var(--space-sm, 0.75rem);
		max-inline-size: 72ch;
	}

	.intro-text h2 {
		font-size: clamp(1.3rem, 2vw, 1.8rem);
		line-height: 1.2;
	}

	.intro-body {
		color: var(--color-muted);
		line-height: 1.6;
	}

	.intro-questions {
		color: var(--color-muted);
		font-size: 0.92rem;
		line-height: 1.6;
	}

	.intro-aside {
		display: grid;
		gap: var(--space-sm, 0.75rem);
		padding: var(--space-md, 1.25rem);
		border: var(--rule-size, 1px) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		min-inline-size: 22rem;
		align-self: start;
	}

	.mini-scorecard,
	.metric-explainer {
		list-style: none;
		padding: 0;
		margin: 0;
		display: grid;
		gap: var(--space-xs, 0.5rem);
	}

	.mini-row {
		display: grid;
		grid-template-columns: 1.8rem 1fr auto;
		gap: var(--space-xs, 0.5rem);
		align-items: center;
		font-size: 0.9rem;
		padding: 0.3rem 0;
		border-bottom: var(--rule-size, 1px) solid var(--color-border);
	}

	.mini-row:last-child {
		border-bottom: none;
	}

	.mini-rank {
		color: var(--color-muted);
		font-size: 0.8rem;
	}

	.mini-arch {
		font-size: 0.88rem;
	}

	.mini-score {
		font-weight: 700;
		font-size: 0.9rem;
		color: var(--color-muted);
		text-align: right;
	}

	.mini-score.best {
		color: var(--color-success, #4caf50);
	}

	.metric-explainer li {
		display: grid;
		gap: 0.15rem;
		font-size: 0.88rem;
		padding: 0.3rem 0;
		border-bottom: var(--rule-size, 1px) solid var(--color-border);
	}

	.metric-explainer li:last-child {
		border-bottom: none;
	}

	.metric-explainer strong {
		font-size: 0.9rem;
	}

	.metric-explainer span {
		color: var(--color-muted);
		line-height: 1.4;
	}

	.mini-label {
		font-size: 0.8rem;
		color: var(--color-muted);
		margin: 0;
	}

	.steps-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(min(100%, 22rem), 1fr));
		gap: var(--space-sm, 0.75rem);
		list-style: none;
		padding: 0;
		margin: 0;
	}

	.step-card {
		display: grid;
		grid-template-columns: 2rem 1fr auto;
		align-items: start;
		gap: var(--space-sm, 0.75rem);
		padding: var(--space-md, 1.25rem);
		text-decoration: none;
		border: var(--rule-size, 1px) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		transition:
			border-color 0.1s,
			background 0.1s;
	}

	.step-card:hover {
		border-color: var(--color-border-strong);
		background: var(--color-surface-raised);
	}

	.step-card[data-state='done'] {
		border-color: color-mix(in srgb, var(--color-success, #4caf50) 30%, var(--color-border));
	}

	.step-number {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 2rem;
		height: 2rem;
		border-radius: 50%;
		background: var(--color-surface-raised);
		border: var(--rule-size, 1px) solid var(--color-border);
		font-size: 0.85rem;
		font-weight: 700;
		flex-shrink: 0;
		color: var(--color-muted);
	}

	.step-card[data-state='done'] .step-number {
		background: color-mix(in srgb, var(--color-success, #4caf50) 15%, transparent);
		border-color: var(--color-success, #4caf50);
		color: var(--color-success, #4caf50);
	}

	.step-body {
		display: grid;
		gap: var(--space-2xs, 0.3rem);
	}

	.step-body strong {
		font-size: 1rem;
		line-height: 1.2;
	}

	.step-body span {
		color: var(--color-muted);
		font-size: 0.88rem;
		line-height: 1.4;
	}

	.step-badge {
		font-size: 0.85rem;
		font-weight: 700;
		padding: 0.15rem 0.45rem;
		border-radius: var(--radius-sm, 4px);
		line-height: 1;
	}

	.step-badge.done {
		color: var(--color-success, #4caf50);
		background: color-mix(in srgb, var(--color-success, #4caf50) 12%, transparent);
	}

	.step-badge.active {
		color: var(--color-accent);
		background: color-mix(in srgb, var(--color-accent) 12%, transparent);
	}
</style>
