<script lang="ts">
	import { resolve } from '$app/paths';
	import DataEmptyState from '$lib/components/DataEmptyState.svelte';
	import MetricGrid from '$lib/components/MetricGrid.svelte';
	import RouteHeader from '$lib/components/RouteHeader.svelte';

	let { data } = $props();

	type Run = (typeof data.runs)[number];

	const completedRuns = $derived(data.runs.filter((run: Run) => run.status === 'completed'));
	const allRuns = $derived(
		[...data.runs].sort(
			(left, right) => Date.parse(right.created_at ?? '') - Date.parse(left.created_at ?? '')
		)
	);
	const rankedRuns = $derived(
		[...completedRuns].sort((left, right) => qualityScore(right) - qualityScore(left))
	);
	const leader = $derived(data.leader ?? rankedRuns[0]);
	const fastest = $derived(data.fastest ?? fastestRun(completedRuns));
	const highestMissRun = $derived(
		[...completedRuns].sort((left, right) => missCount(right) - missCount(left))[0]
	);
	const baseline = $derived(
		[...completedRuns].sort(
			(left, right) => Date.parse(left.created_at ?? '') - Date.parse(right.created_at ?? '')
		)[0]
	);
	const latencyRange = $derived(range(completedRuns.map((run: Run) => latency(run))));
	const qualityRange = $derived(range(completedRuns.map((run: Run) => qualityScore(run))));

	function runMetric(run: Run | undefined, key: string) {
		if (!run) return undefined;
		const aggregate = run.aggregate_metrics;
		const source = aggregate && typeof aggregate === 'object' ? aggregate : run;
		const value = (source as Record<string, unknown>)[key];
		return typeof value === 'number' ? value : undefined;
	}

	function qualityScore(run: Run | undefined) {
		return runMetric(run, 'ndcg_at_10') ?? 0;
	}

	function latency(run: Run | undefined) {
		return runMetric(run, 'avg_latency_ms') ?? 0;
	}

	function missCount(run: Run | undefined) {
		return run?.failure_count ?? run?.miss_count ?? runMetric(run, 'miss_count') ?? 0;
	}

	function missRate(run: Run | undefined) {
		if (!run?.total_questions) return undefined;
		return missCount(run) / run.total_questions;
	}

	function metricLabel(value: number | undefined, decimals = 3, suffix = '') {
		return typeof value === 'number' ? `${value.toFixed(decimals)}${suffix}` : 'n/a';
	}

	function percentLabel(value: number | undefined) {
		return typeof value === 'number' ? `${(value * 100).toFixed(0)}%` : 'n/a';
	}

	function barWidth(value: number | undefined) {
		return Math.max(0, Math.min(100, (value ?? 0) * 100));
	}

	function range(values: number[]) {
		const finite = values.filter((value) => Number.isFinite(value));
		if (!finite.length) return { min: 0, max: 1 };
		const min = Math.min(...finite);
		const max = Math.max(...finite);
		return min === max ? { min: min - 1, max: max + 1 } : { min, max };
	}

	function scale(value: number, min: number, max: number) {
		return Math.max(8, Math.min(92, ((value - min) / (max - min)) * 84 + 8));
	}

	function scatterX(run: Run) {
		return scale(latency(run), latencyRange.min, latencyRange.max);
	}

	function scatterY(run: Run) {
		return scale(qualityScore(run), qualityRange.min, qualityRange.max);
	}

	function fastestRun(runs: Run[]) {
		return [...runs].sort((left, right) => latency(left) - latency(right))[0];
	}

	function deltaFromBaseline(run: Run) {
		if (!baseline || run.id === baseline.id) return undefined;
		return qualityScore(run) - qualityScore(baseline);
	}

	function deltaLabel(value: number | undefined) {
		if (typeof value !== 'number') return 'baseline';
		return `${value >= 0 ? '+' : ''}${value.toFixed(3)}`;
	}

	function runTitle(run: Run | undefined) {
		return run ? `${run.architecture_name} · Run ${run.id}` : 'n/a';
	}
</script>

<section class="route-shell">
	<div class="content-wide route-stack">
		<RouteHeader
			title="Run Analysis"
			subtitle="Evaluation history should explain what changed, what won, where quality moved, and what still fails."
		>
			{#snippet actions()}
				<details class="run-menu">
					<summary class="button primary">All Runs</summary>
					<div class="run-menu-popover" aria-label="All evaluation runs">
						{#each allRuns as run (run.id)}
							<a
								class="run-menu-row"
								class:is-leader={leader?.id === run.id}
								href={resolve(`/runs/${run.id}`)}
							>
								<span class="run-menu-main">
									<strong>{run.architecture_name}</strong>
									<span class="muted">
										Run {run.id} · {run.eval_set_version ?? `Eval set ${run.eval_set_id ?? 'n/a'}`} ·
										{run.created_at ?? 'created time unknown'}
									</span>
								</span>
								<span class="run-menu-metrics">
									<span>nDCG {metricLabel(runMetric(run, 'ndcg_at_10'))}</span>
									<span>Recall {metricLabel(runMetric(run, 'recall_at_10'))}</span>
									<span>{metricLabel(latency(run), 0, ' ms')}</span>
									<span>{missCount(run)} misses</span>
								</span>
								<span class="zoom-label">Zoom in →</span>
							</a>
						{/each}
					</div>
				</details>
			{/snippet}
		</RouteHeader>

		<MetricGrid metrics={data.metrics} />

		{#if data.runs.length > 0}
			<section class="analysis-grid" aria-label="Run insights">
				<article class="panel insight-card winner-card">
					<p class="eyebrow">Winner</p>
					<h2>{runTitle(leader)}</h2>
					<p>
						Best observed quality by nDCG@10. Use this as the current reference point, not as a
						permanent winner if the eval set or architecture matrix changes.
					</p>
					<div class="score-row">
						<span>nDCG@10</span>
						<strong>{metricLabel(runMetric(leader, 'ndcg_at_10'))}</strong>
					</div>
					<div class="score-row">
						<span>Recall@10</span>
						<strong>{metricLabel(runMetric(leader, 'recall_at_10'))}</strong>
					</div>
				</article>

				<article class="panel insight-card">
					<p class="eyebrow">Fastest</p>
					<h2>{runTitle(fastest)}</h2>
					<p>
						Lowest average latency. Compare it against the leader to decide whether quality gain is
						worth the response-time cost.
					</p>
					<div class="score-row">
						<span>Latency</span>
						<strong>{metricLabel(latency(fastest), 0, ' ms')}</strong>
					</div>
					<div class="score-row">
						<span>Quality delta</span>
						<strong
							>{deltaLabel(
								fastest ? qualityScore(fastest) - qualityScore(leader) : undefined
							)}</strong
						>
					</div>
				</article>

				<article class="panel insight-card">
					<p class="eyebrow">Weakest spot</p>
					<h2>{runTitle(highestMissRun)}</h2>
					<p>
						Highest known miss pressure among completed runs. Drill into the run detail for category
						scores, per-question misses, and failure notes.
					</p>
					<div class="score-row">
						<span>Misses</span>
						<strong>{missCount(highestMissRun)}</strong>
					</div>
					<div class="score-row">
						<span>Miss rate</span>
						<strong>{percentLabel(missRate(highestMissRun))}</strong>
					</div>
				</article>
			</section>

			<section class="page-section section-stack" aria-labelledby="chart-heading">
				<div>
					<p class="eyebrow">Tradeoff chart</p>
					<h2 id="chart-heading">Quality vs latency</h2>
					<p class="muted">
						This mirrors the useful artifact charts: put the architecture score against an
						operational cost so the tradeoff is visible before opening details.
					</p>
				</div>

				<div class="scatter-wrap">
					<div class="scatter-plot" aria-label="Quality versus latency chart">
						<span class="axis-label y-axis">Higher nDCG@10</span>
						<span class="axis-label x-axis">Higher latency</span>
						{#each completedRuns as run (run.id)}
							<a
								class="scatter-point"
								class:is-leader={leader?.id === run.id}
								href={resolve(`/runs/${run.id}`)}
								style={`--x: ${scatterX(run)}%; --y: ${scatterY(run)}%;`}
								aria-label={`${run.architecture_name}: nDCG ${metricLabel(qualityScore(run))}, latency ${metricLabel(latency(run), 0, ' ms')}`}
							>
								<span>{run.architecture_name}</span>
							</a>
						{/each}
					</div>
				</div>
			</section>

			<section class="page-section section-stack" aria-labelledby="leaderboard-heading">
				<div>
					<p class="eyebrow">Leaderboard</p>
					<h2 id="leaderboard-heading">Architecture scorecards</h2>
					<p class="muted">
						Each card keeps the same eval workload fixed and shows quality, speed, and miss pressure
						for one candidate.
					</p>
				</div>

				<div class="run-card-grid">
					{#each rankedRuns as run, index (run.id)}
						<article class="run-card" class:is-leader={index === 0}>
							<header>
								<div>
									<span class="rank">#{index + 1}</span>
									<h3>{run.architecture_name}</h3>
									<p>{run.eval_set_version ?? `Eval set ${run.eval_set_id ?? 'n/a'}`}</p>
								</div>
								<span class="status-pill">{run.status}</span>
							</header>

							<div class="bar-stack">
								<div class="bar-row">
									<span>nDCG@10</span>
									<div class="bar-track">
										<span style={`inline-size: ${barWidth(runMetric(run, 'ndcg_at_10'))}%`}></span>
									</div>
									<strong>{metricLabel(runMetric(run, 'ndcg_at_10'))}</strong>
								</div>
								<div class="bar-row">
									<span>Recall@10</span>
									<div class="bar-track">
										<span style={`inline-size: ${barWidth(runMetric(run, 'recall_at_10'))}%`}
										></span>
									</div>
									<strong>{metricLabel(runMetric(run, 'recall_at_10'))}</strong>
								</div>
								<div class="bar-row">
									<span>MRR@10</span>
									<div class="bar-track">
										<span style={`inline-size: ${barWidth(runMetric(run, 'mrr_at_10'))}%`}></span>
									</div>
									<strong>{metricLabel(runMetric(run, 'mrr_at_10'))}</strong>
								</div>
							</div>

							<dl class="run-facts">
								<div>
									<dt>Latency</dt>
									<dd>{metricLabel(latency(run), 0, ' ms')}</dd>
								</div>
								<div>
									<dt>Misses</dt>
									<dd>{missCount(run)}</dd>
								</div>
								<div>
									<dt>Delta</dt>
									<dd>{deltaLabel(deltaFromBaseline(run))}</dd>
								</div>
							</dl>

							<a class="button" href={resolve(`/runs/${run.id}`)}>Open run analysis</a>
						</article>
					{/each}
				</div>
			</section>

			<section class="page-section section-stack" aria-labelledby="matrix-heading">
				<div>
					<p class="eyebrow">Experiment matrix</p>
					<h2 id="matrix-heading">Comparable run table</h2>
				</div>

				<div class="table-scroll">
					<table>
						<thead>
							<tr>
								<th>Run</th>
								<th>Eval set</th>
								<th>Status</th>
								<th>nDCG@10</th>
								<th>Δ vs baseline</th>
								<th>Recall@10</th>
								<th>MRR@10</th>
								<th>Latency</th>
								<th>Miss rate</th>
							</tr>
						</thead>
						<tbody>
							{#each rankedRuns as run (run.id)}
								<tr>
									<td>
										<a href={resolve(`/runs/${run.id}`)}>{run.architecture_name}</a>
										<span class="muted">Run {run.id}</span>
									</td>
									<td>{run.eval_set_version ?? run.eval_set_id ?? 'n/a'}</td>
									<td><span class="status-pill">{run.status}</span></td>
									<td>{metricLabel(runMetric(run, 'ndcg_at_10'))}</td>
									<td>{deltaLabel(deltaFromBaseline(run))}</td>
									<td>{metricLabel(runMetric(run, 'recall_at_10'))}</td>
									<td>{metricLabel(runMetric(run, 'mrr_at_10'))}</td>
									<td>{metricLabel(latency(run), 0, ' ms')}</td>
									<td>{percentLabel(missRate(run))}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</section>
		{:else}
			<section class="page-section">
				<DataEmptyState
					title="No completed run analysis yet"
					description="Start an evaluation run from the workflow to populate scorecards, tradeoffs, and failure analysis."
				/>
			</section>
		{/if}
	</div>
</section>

<style>
	h2 {
		font-size: clamp(1.3rem, 2vw, 1.8rem);
	}

	.run-menu {
		position: relative;
	}

	.run-menu summary {
		cursor: pointer;
		list-style: none;
	}

	.run-menu summary::-webkit-details-marker {
		display: none;
	}

	.run-menu-popover {
		position: absolute;
		z-index: 20;
		inset-block-start: calc(100% + var(--space-xs));
		inset-inline-end: 0;
		display: grid;
		gap: var(--space-xs);
		inline-size: min(52rem, calc(100vw - 2rem));
		max-block-size: min(70vh, 36rem);
		overflow: auto;
		padding: var(--space-sm);
		border: var(--rule-size) solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		box-shadow: 0 1rem 2.5rem color-mix(in oklab, black 38%, transparent);
	}

	.run-menu-row {
		display: grid;
		grid-template-columns: minmax(12rem, 1.2fr) minmax(17rem, 1.6fr) auto;
		align-items: center;
		gap: var(--space-md);
		padding: var(--space-sm);
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface);
		color: inherit;
	}

	.run-menu-row:hover {
		border-color: var(--color-border-strong);
		text-decoration: none;
	}

	.run-menu-row.is-leader {
		border-color: color-mix(in oklab, var(--color-success) 45%, var(--color-border));
	}

	.run-menu-main {
		display: grid;
		gap: var(--space-2xs);
		min-inline-size: 0;
	}

	.run-menu-metrics {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2xs);
		color: var(--color-muted);
		font-size: 0.82rem;
	}

	.run-menu-metrics span {
		padding: 0.2rem 0.45rem;
		border: var(--rule-size) solid var(--color-border);
		border-radius: 999rem;
		background: var(--color-surface-raised);
	}

	.zoom-label {
		color: var(--color-muted);
		font-size: 0.72rem;
		font-weight: 800;
		text-transform: uppercase;
		white-space: nowrap;
	}

	.analysis-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 18rem), 1fr));
		gap: var(--space-md);
	}

	.insight-card {
		display: grid;
		gap: var(--space-sm);
	}

	.insight-card h2 {
		font-size: clamp(1.2rem, 2vw, 1.6rem);
	}

	.insight-card p:not(.eyebrow) {
		color: var(--color-muted);
	}

	.winner-card {
		border-color: color-mix(in oklab, var(--color-success) 45%, var(--color-border));
	}

	.score-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-sm);
		padding-block-start: var(--space-xs);
		border-block-start: var(--rule-size) solid var(--color-border);
	}

	.score-row span {
		color: var(--color-muted);
	}

	.scatter-wrap {
		overflow-x: auto;
	}

	.scatter-plot {
		position: relative;
		min-inline-size: 36rem;
		block-size: 22rem;
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-md);
		background:
			linear-gradient(var(--color-border) 1px, transparent 1px) 0 0 / 100% 25%,
			linear-gradient(90deg, var(--color-border) 1px, transparent 1px) 0 0 / 25% 100%,
			var(--color-surface);
	}

	.axis-label {
		position: absolute;
		color: var(--color-muted);
		font-size: 0.78rem;
		font-weight: 800;
		text-transform: uppercase;
	}

	.y-axis {
		inset-block-start: var(--space-sm);
		inset-inline-start: var(--space-sm);
	}

	.x-axis {
		inset-block-end: var(--space-sm);
		inset-inline-end: var(--space-sm);
	}

	.scatter-point {
		position: absolute;
		inset-inline-start: var(--x);
		inset-block-end: var(--y);
		transform: translate(-50%, 50%);
		display: grid;
		place-items: center;
		min-inline-size: 2.4rem;
		min-block-size: 2.4rem;
		padding: var(--space-2xs) var(--space-xs);
		border: var(--rule-size) solid var(--color-accent);
		border-radius: 999rem;
		background: color-mix(in oklab, var(--color-accent) 18%, var(--color-surface));
		color: var(--color-text);
		font-size: 0.78rem;
		font-weight: 800;
		text-align: center;
	}

	.scatter-point.is-leader {
		border-color: var(--color-success);
		background: color-mix(in oklab, var(--color-success) 18%, var(--color-surface));
	}

	.scatter-point:hover {
		text-decoration: none;
		filter: brightness(1.15);
	}

	.run-card-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 24rem), 1fr));
		gap: var(--space-md);
	}

	.run-card {
		display: grid;
		gap: var(--space-md);
		padding: var(--space-md);
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}

	.run-card.is-leader {
		border-color: color-mix(in oklab, var(--color-success) 50%, var(--color-border));
	}

	.run-card header {
		display: flex;
		align-items: start;
		justify-content: space-between;
		gap: var(--space-sm);
	}

	.run-card h3 {
		font-size: 1.25rem;
	}

	.run-card header p,
	.rank {
		color: var(--color-muted);
	}

	.rank {
		display: block;
		font-weight: 900;
	}

	.bar-stack {
		display: grid;
		gap: var(--space-xs);
	}

	.bar-row {
		display: grid;
		grid-template-columns: 5rem minmax(6rem, 1fr) 4rem;
		align-items: center;
		gap: var(--space-xs);
		color: var(--color-muted);
		font-size: 0.82rem;
	}

	.bar-row strong {
		color: var(--color-text);
		text-align: end;
	}

	.bar-track {
		overflow: hidden;
		block-size: 0.55rem;
		border-radius: 999rem;
		background: var(--color-surface-raised);
	}

	.bar-track span {
		display: block;
		block-size: 100%;
		border-radius: inherit;
		background: linear-gradient(90deg, var(--color-accent), var(--color-success));
	}

	.run-facts {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: var(--space-xs);
		margin: 0;
	}

	.run-facts div {
		padding: var(--space-xs);
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface-raised);
	}

	.run-facts dt {
		color: var(--color-muted);
		font-size: 0.72rem;
		font-weight: 800;
		text-transform: uppercase;
	}

	.run-facts dd {
		margin: 0;
		font-weight: 900;
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

	td:first-child {
		display: grid;
		gap: var(--space-2xs);
	}

	@media (max-width: 42rem) {
		.run-menu-row,
		.bar-row,
		.run-facts {
			grid-template-columns: 1fr;
		}

		.run-menu {
			inline-size: 100%;
		}

		.run-menu summary {
			justify-content: center;
		}

		.run-menu-popover {
			position: static;
			inline-size: 100%;
			margin-block-start: var(--space-xs);
		}
	}
</style>
