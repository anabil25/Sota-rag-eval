<script lang="ts">
	import { resolve } from '$app/paths';
	import MetricGrid from '$lib/components/MetricGrid.svelte';
	import RouteHeader from '$lib/components/RouteHeader.svelte';

	let { data } = $props();

	function currentStepNote(stepId: string | undefined) {
		if (stepId === 'ingest') return 'Add the corpus that every candidate will be measured against.';
		if (stepId === 'eval') return 'Choose the grounded questions that define retrieval quality.';
		if (stepId === 'configure') return 'Select the architectures and controls for this experiment.';
		if (stepId === 'provision') return 'Azure resources and candidate indexes are not ready yet.';
		if (stepId === 'run') return 'The candidates are ready for the shared evaluation set.';
		if (stepId === 'compare') return 'Review measured quality, latency, and cost before promotion.';
		if (stepId === 'teardown') return 'Keep the winner and remove experiment-only resources.';
		return 'This experiment has a durable winner and a completed cleanup record.';
	}

	function recallAt10(run: (typeof data.runs)[number]) {
		return run.recall_at_10 ?? run.aggregate_metrics?.recall_at_10;
	}
</script>

<section class="route-shell">
	<div class="content-wide route-stack">
		<RouteHeader title="Retrieve">
			{#snippet actions()}
				<a class="button primary" href={data.currentStep?.href ?? resolve('/flow/teardown')}>
					{data.workflowComplete ? 'Review outcome' : `Continue: ${data.currentStep?.shortTitle}`}
				</a>
			{/snippet}
		</RouteHeader>

		<section
			class="journey-band"
			data-complete={data.workflowComplete}
			aria-labelledby="journey-heading"
		>
			<div class="journey-copy">
				<p class="eyebrow">{data.workflowComplete ? 'Experiment complete' : 'Active experiment'}</p>
				<h2 id="journey-heading">
					{data.workflowComplete
						? 'Winner selected and cleanup recorded'
						: `Up next: ${data.currentStep?.title ?? 'Ingest'}`}
				</h2>
				<p>{currentStepNote(data.currentStep?.id)}</p>
			</div>
			<div class="journey-actions">
				<a class="button primary" href={data.currentStep?.href ?? resolve('/flow/teardown')}>
					{data.workflowComplete ? 'Review outcome' : 'Continue'}
				</a>
				<details class="experiment-menu">
					<summary class="button">New experiment</summary>
					<form method="POST" action="?/startExperiment" class="experiment-options">
						<button class="option-button" type="submit" name="mode" value="reuse">
							<strong>Reuse local inputs</strong>
							<span>Resume at Configure with the stored corpus and eval set.</span>
						</button>
						<button class="option-button" type="submit" name="mode" value="fresh">
							<strong>Begin at Ingest</strong>
							<span>Ignore stored inputs for the new workflow; Review history stays available.</span
							>
						</button>
					</form>
				</details>
			</div>
		</section>

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
					<p class="eyebrow">Latest completed results</p>
					<ol class="mini-scorecard" role="list">
						{#each data.runs
							.toSorted((a, b) => (recallAt10(b) ?? 0) - (recallAt10(a) ?? 0))
							.slice(0, 4) as run, i (run.id ?? i)}
							<li class="mini-row">
								<span class="mini-rank">#{i + 1}</span>
								<span class="mini-arch">{run.architecture_name}</span>
								<span class="mini-score" class:best={i === 0}>
									{recallAt10(run) !== undefined
										? `${Math.round((recallAt10(run) ?? 0) * 100)}%`
										: '—'}
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
				<h2 id="status-heading">Stored workspace evidence</h2>
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
						{#if step.state === 'locked'}
							<div class="step-card card locked" data-state={step.state} aria-disabled="true">
								<span class="step-number">{step.index}</span>
								<div class="step-body">
									<strong>{step.title}</strong>
									<span>{step.subtitle}</span>
								</div>
								<span class="step-badge locked">Locked</span>
							</div>
						{:else}
							<a class="step-card card" href={step.href} data-state={step.state}>
								<span class="step-number">{step.index}</span>
								<div class="step-body">
									<strong>{step.title}</strong>
									<span>{step.subtitle}</span>
								</div>
								{#if step.state === 'done'}
									<span class="step-badge done">Complete</span>
								{:else if step.state === 'active'}
									<span class="step-badge active">Up next</span>
								{/if}
							</a>
						{/if}
					</li>
				{/each}
			</ol>
		</section>
	</div>
</section>

<style>
	.journey-band {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-lg);
		padding-block: var(--space-lg);
		border-block: var(--rule-size) solid var(--color-border-strong);
	}

	.journey-band[data-complete='true'] {
		border-color: color-mix(in oklab, var(--color-success) 55%, var(--color-border));
	}

	.journey-copy {
		display: grid;
		gap: var(--space-xs);
		max-inline-size: 68ch;
	}

	.journey-copy h2 {
		font-size: 1.35rem;
	}

	.journey-copy p:last-child {
		color: var(--color-muted);
	}

	.journey-actions {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		flex: 0 0 auto;
	}

	.experiment-menu {
		position: relative;
	}

	.experiment-menu summary {
		list-style: none;
		cursor: pointer;
	}

	.experiment-menu summary::-webkit-details-marker {
		display: none;
	}

	.experiment-options {
		position: absolute;
		z-index: 10;
		inset-block-start: calc(100% + var(--space-xs));
		inset-inline-end: 0;
		display: grid;
		inline-size: min(24rem, 80vw);
		padding: var(--space-xs);
		border: var(--rule-size) solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		box-shadow: 0 1rem 2rem rgb(0 0 0 / 24%);
	}

	.option-button {
		display: grid;
		gap: var(--space-2xs);
		padding: var(--space-sm);
		border: 0;
		border-radius: var(--radius-sm);
		background: transparent;
		color: var(--color-text);
		text-align: start;
		cursor: pointer;
	}

	.option-button:hover,
	.option-button:focus-visible {
		background: var(--color-surface);
	}

	.option-button span {
		color: var(--color-muted);
		font-size: 0.84rem;
		line-height: 1.4;
	}

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

	.step-card[data-state='locked'] {
		opacity: 0.56;
		border-style: dashed;
	}

	.step-card.locked:hover {
		border-color: var(--color-border);
		background: var(--color-surface);
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

	.step-badge.locked {
		color: var(--color-subtle);
		background: var(--color-surface-raised);
	}

	@media (max-width: 48rem) {
		.journey-band,
		.journey-actions {
			align-items: stretch;
			flex-direction: column;
		}

		.experiment-options {
			inset-inline: 0 auto;
			inline-size: min(24rem, calc(100vw - 3rem));
		}

		.intro-section {
			grid-template-columns: minmax(0, 1fr);
		}

		.intro-aside {
			min-inline-size: 0;
		}
	}
</style>
