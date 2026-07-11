<script lang="ts">
	import { resolve } from '$app/paths';
	import RouteHeader from '$lib/components/RouteHeader.svelte';
	import {
		PRICING_METERS,
		architectureNeedsVector,
		architectureUsesLlm,
		architectureUsesSearch,
		architectureUsesSemanticRanker,
		estimateArchitectureEvalCost,
		estimateExperimentEvalCost,
		estimateMonthlyProductionCost,
		formatNumber,
		formatUnitPrice,
		formatUsd,
		pricingInputsFromCorpus
	} from '$lib/pricing';

	let { data } = $props();

	function initialPricing() {
		return data.pricingDefaults;
	}

	function initialSelectedArchitecture() {
		return data.selected.architecture;
	}

	function initialAvgTokensPerDoc() {
		const defaults = data.pricingDefaults;
		return Math.max(50, Math.round(defaults.corpusTokens / Math.max(1, defaults.corpusDocuments)));
	}

	let selectedArchitecture = $state(initialSelectedArchitecture());
	let corpusDocuments = $state(initialPricing().corpusDocuments);
	let avgTokensPerDoc = $state(initialAvgTokensPerDoc());
	let evalQuestions = $state(initialPricing().evalQuestions);
	let evalRunsPerMonth = $state(initialPricing().evalRunsPerMonth);
	let searchHours = $state(initialPricing().searchHours);
	let searchUnits = $state(initialPricing().searchUnits);
	let storageGb = $state(initialPricing().storageGb);
	let monthlyQueries = $state(initialPricing().monthlyQueries);
	let llmInputTokensPerQuestion = $state(initialPricing().llmInputTokensPerQuestion);
	let llmOutputTokensPerQuestion = $state(initialPricing().llmOutputTokensPerQuestion);

	const corpusTokens = $derived(Math.max(1, Math.round(corpusDocuments * avgTokensPerDoc)));
	const corpusMb = $derived((corpusTokens * 4) / 1024 ** 2);

	const inputs = $derived(
		pricingInputsFromCorpus({
			corpusDocuments,
			corpusTokens,
			evalQuestions,
			searchHours,
			searchUnits,
			storageGb,
			evalRunsPerMonth,
			monthlyQueries,
			llmInputTokensPerQuestion,
			llmOutputTokensPerQuestion
		})
	);

	const architectureOptions = $derived(Object.entries(data.architectures));
	const configuredArchitectures = $derived(
		data.selectedArchitectures.filter((name: string) => data.architectures[name])
	);
	const candidateCosts = $derived(
		configuredArchitectures.map((name: string) => ({
			name,
			label: architectureName(name),
			cost: estimateArchitectureEvalCost(name, inputs).total,
			tags: capabilityTags(name),
			recommended: name === data.selected.architecture
		}))
	);
	const configuredEvalEstimate = $derived(
		estimateExperimentEvalCost(configuredArchitectures, inputs)
	);
	const evalEstimate = $derived(estimateArchitectureEvalCost(selectedArchitecture, inputs));
	const monthlyEstimate = $derived(estimateMonthlyProductionCost(selectedArchitecture, inputs));

	const passCost = $derived(configuredEvalEstimate.total);
	const monthlyTestingCost = $derived(passCost * Math.max(1, evalRunsPerMonth));
	const candidateCount = $derived(configuredArchitectures.length);

	function architectureName(key: string) {
		const architecture = data.architectures[key];
		return architecture?.display_name ?? architecture?.name ?? key;
	}

	function capabilityTags(name: string) {
		const tags: string[] = [];
		if (architectureUsesSearch(name)) {
			tags.push(architectureNeedsVector(name) ? 'Vector + keyword index' : 'Keyword index');
		}
		if (architectureNeedsVector(name)) tags.push('Embeds corpus once');
		if (architectureUsesSemanticRanker(name)) tags.push('Semantic ranker / question');
		if (architectureUsesLlm(name)) tags.push('LLM calls');
		if (!tags.length) tags.push('Standalone system');
		return tags;
	}
</script>

<section class="route-shell">
	<div class="content-wide route-stack">
		<RouteHeader
			title="Pricing"
			subtitle="Real Azure retail rates, turned into one honest number: what it costs to measure your candidates."
		>
			{#snippet actions()}
				<a class="button" href={resolve('/flow/provision')}>Deploy plan</a>
				<a class="button primary" href={resolve('/flow/compare')}>Compare results</a>
			{/snippet}
		</RouteHeader>

		<!-- HERO: the primary "cost to test" answer -->
		<section class="hero" aria-labelledby="hero-heading">
			<div class="hero-main">
				<p class="eyebrow">Cost to run one eval pass</p>
				<p id="hero-heading" class="hero-amount">{formatUsd(passCost)}</p>
				<p class="hero-formula">
					{candidateCount}
					candidate{candidateCount === 1 ? '' : 's'} × {formatNumber(evalQuestions)} questions over a
					{formatNumber(corpusDocuments)}-doc corpus
					<span class="formula-tokens"
						>({formatNumber(corpusDocuments)} docs × ~{formatNumber(avgTokensPerDoc)} tok ≈ {formatNumber(
							corpusTokens
						)} tokens · {corpusMb.toFixed(1)} MB)</span
					>
				</p>
			</div>
			<dl class="hero-stats">
				<div>
					<dt>Repeat monthly</dt>
					<dd>{formatUsd(monthlyTestingCost)}</dd>
					<p>{evalRunsPerMonth} passes / month</p>
				</div>
				<div>
					<dt>Winner in production</dt>
					<dd>{formatUsd(monthlyEstimate.total)}</dd>
					<p>{architectureName(selectedArchitecture)} · run-rate / month</p>
				</div>
			</dl>
		</section>

		<!-- DRIVERS: the three inputs that actually move the number -->
		<section class="page-section section-stack" aria-labelledby="drivers-heading">
			<div>
				<p class="eyebrow">What drives it</p>
				<h2 id="drivers-heading">Size your corpus and eval set</h2>
				<p class="muted">
					Prefilled from the current session. Every candidate re-embeds and re-queries this corpus,
					so these two numbers set the floor.
				</p>
			</div>
			<div class="drivers">
				<label class="driver">
					<span>Corpus documents</span>
					<input type="number" min="1" step="1" bind:value={corpusDocuments} />
					<small>≈ {formatNumber(corpusTokens)} tokens · {corpusMb.toFixed(1)} MB</small>
				</label>
				<label class="driver">
					<span>Eval questions / pass</span>
					<input type="number" min="1" step="1" bind:value={evalQuestions} />
					<small>Scales ranker, agentic & LLM query costs</small>
				</label>
				<div class="driver">
					<span>Candidates ({candidateCount})</span>
					<div class="candidate-chips">
						{#each configuredArchitectures as name (name)}
							<span class="chip" class:chip-recommended={name === data.selected.architecture}>
								{architectureName(name)}
							</span>
						{:else}
							<span class="chip chip-empty">None configured yet</span>
						{/each}
					</div>
					<small>Set in <a href={resolve('/flow/configure')}>Configure</a></small>
				</div>
			</div>
		</section>

		<!-- PER-CANDIDATE: makes "across architectures" concrete -->
		<section class="page-section section-stack" aria-labelledby="candidates-heading">
			<div>
				<p class="eyebrow">Per candidate</p>
				<h2 id="candidates-heading">What each architecture costs to test once</h2>
			</div>
			<ul class="candidate-list">
				{#each candidateCosts as candidate (candidate.name)}
					<li class="candidate" class:candidate-recommended={candidate.recommended}>
						<div class="candidate-id">
							<span class="candidate-name">
								{candidate.label}
								{#if candidate.recommended}<span class="badge">Recommended</span>{/if}
							</span>
							<div class="tag-row">
								{#each candidate.tags as tag (tag)}
									<span class="tag">{tag}</span>
								{/each}
							</div>
						</div>
						<strong class="candidate-cost">{formatUsd(candidate.cost)}</strong>
					</li>
				{:else}
					<li class="candidate candidate-empty">
						No candidates configured. Pick experiments in
						<a href={resolve('/flow/configure')}>Configure</a> to populate this list.
					</li>
				{/each}
			</ul>
			{#if candidateCount > 1}
				<p class="candidate-total">
					<span>All {candidateCount} candidates, one pass</span>
					<strong>{formatUsd(passCost)}</strong>
				</p>
			{/if}
		</section>

		<!-- PRODUCTION: secondary, query-driven -->
		<section class="page-section production" aria-labelledby="production-heading">
			<div class="production-copy">
				<p class="eyebrow">Production run-rate</p>
				<h2 id="production-heading">If you ship the winner</h2>
				<p class="muted">
					A separate, ongoing cost driven by live query volume — not by your eval set.
				</p>
				<div class="production-inputs">
					<label class="driver">
						<span>Architecture</span>
						<select bind:value={selectedArchitecture}>
							{#each architectureOptions as [key, architecture] (key)}
								<option value={key}>{architecture.display_name ?? architecture.name ?? key}</option>
							{/each}
						</select>
						<small>{data.selected.reason}</small>
					</label>
					<label class="driver">
						<span>Production queries / month</span>
						<input type="number" min="0" step="1000" bind:value={monthlyQueries} />
						<small>{formatNumber(monthlyQueries)} live queries</small>
					</label>
				</div>
			</div>
			<div class="production-figure">
				<p class="eyebrow">Estimated monthly</p>
				<p class="production-amount">{formatUsd(monthlyEstimate.total)}</p>
				<ul class="mini-lines">
					{#each monthlyEstimate.lines as line (line.label)}
						<li>
							<span>{line.label}</span>
							<span>{formatUsd(line.cost)}</span>
						</li>
					{/each}
				</ul>
			</div>
		</section>

		<!-- ADVANCED LEVERS -->
		<details class="disclosure">
			<summary>
				<span>Advanced assumptions</span>
				<small>Embedding density, search capacity, LLM tokens, storage</small>
			</summary>
			<div class="advanced-grid">
				<label class="driver">
					<span>Avg tokens / document</span>
					<input type="number" min="50" step="50" bind:value={avgTokensPerDoc} />
					<small>Used to estimate corpus tokens from doc count</small>
				</label>
				<label class="driver">
					<span>Eval passes / month</span>
					<input type="number" min="1" step="1" bind:value={evalRunsPerMonth} />
				</label>
				<label class="driver">
					<span>Temporary search hours / pass</span>
					<input type="number" min="0.25" step="0.25" bind:value={searchHours} />
				</label>
				<label class="driver">
					<span>Search units</span>
					<input type="number" min="1" step="1" bind:value={searchUnits} />
				</label>
				<label class="driver">
					<span>Storage GB</span>
					<input type="number" min="1" step="1" bind:value={storageGb} />
				</label>
				<label class="driver">
					<span>LLM input tokens / query</span>
					<input type="number" min="0" step="100" bind:value={llmInputTokensPerQuestion} />
				</label>
				<label class="driver">
					<span>LLM output tokens / query</span>
					<input type="number" min="0" step="50" bind:value={llmOutputTokensPerQuestion} />
				</label>
			</div>
		</details>

		<!-- COST BREAKDOWN -->
		<details class="disclosure">
			<summary>
				<span>Cost breakdown</span>
				<small>{architectureName(selectedArchitecture)} — eval pass & monthly lines</small>
			</summary>
			<div class="table-scroll">
				<table>
					<thead>
						<tr>
							<th>Scenario</th>
							<th>Service</th>
							<th>Line item</th>
							<th>Estimate</th>
							<th>Assumption</th>
						</tr>
					</thead>
					<tbody>
						{#each evalEstimate.lines as line (line.label)}
							<tr>
								<td>Eval pass</td>
								<td>{line.service}</td>
								<td>{line.label}</td>
								<td>{formatUsd(line.cost)}</td>
								<td>{line.note}</td>
							</tr>
						{/each}
						{#each monthlyEstimate.lines as line (line.label)}
							<tr>
								<td>Monthly</td>
								<td>{line.service}</td>
								<td>{line.label}</td>
								<td>{formatUsd(line.cost)}</td>
								<td>{line.note}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</details>

		<!-- AZURE RATE SOURCE -->
		<details class="disclosure">
			<summary>
				<span>Azure retail unit prices</span>
				<small>East US · fetched {PRICING_METERS[0].fetchedAt}</small>
			</summary>
			<div class="table-scroll">
				<table>
					<thead>
						<tr>
							<th>Service</th>
							<th>SKU</th>
							<th>Meter</th>
							<th>Unit price</th>
							<th>Unit</th>
							<th>Source</th>
						</tr>
					</thead>
					<tbody>
						{#each PRICING_METERS as meter (meter.id)}
							<tr>
								<td>{meter.service}</td>
								<td>{meter.sku}</td>
								<td>
									{meter.meter}
									{#if meter.note}<small>{meter.note}</small>{/if}
								</td>
								<td>{formatUnitPrice(meter.unitPrice)}</td>
								<td>{meter.unit}</td>
								<td>
									<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
									<a href={meter.sourceUrl} target="_blank" rel="noreferrer">{meter.source}</a>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</details>
	</div>
</section>

<style>
	h2 {
		font-size: clamp(1.2rem, 1.8vw, 1.6rem);
	}

	/* Hero */
	.hero {
		display: grid;
		grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
		gap: var(--space-lg);
		align-items: center;
		padding: var(--space-lg) var(--space-xl);
		border: var(--rule-size) solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background:
			radial-gradient(
				120% 140% at 0% 0%,
				color-mix(in oklab, var(--color-accent) 18%, transparent),
				transparent 60%
			),
			var(--color-surface);
	}

	.hero-amount {
		font-size: clamp(2.8rem, 6vw, 4.5rem);
		font-weight: 900;
		line-height: 0.95;
		letter-spacing: -0.02em;
	}

	.hero-formula {
		margin-block-start: var(--space-xs);
		max-inline-size: 38ch;
		color: var(--color-muted);
		font-size: 0.95rem;
		line-height: 1.5;
	}

	.formula-tokens {
		display: block;
		margin-block-start: var(--space-2xs);
		color: var(--color-subtle);
		font-size: 0.82rem;
	}

	.hero-stats {
		display: grid;
		gap: var(--space-sm);
		padding-inline-start: var(--space-lg);
		border-inline-start: var(--rule-size) solid var(--color-border);
	}

	.hero-stats dt {
		color: var(--color-muted);
		font-size: 0.72rem;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.hero-stats dd {
		font-size: 1.6rem;
		font-weight: 800;
		line-height: 1.1;
	}

	.hero-stats p {
		color: var(--color-subtle);
		font-size: 0.8rem;
	}

	/* Drivers */
	.drivers {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 16rem), 1fr));
		gap: var(--space-md);
	}

	.driver {
		display: grid;
		gap: var(--space-2xs);
		align-content: start;
		color: var(--color-muted);
		font-size: 0.85rem;
		font-weight: 800;
	}

	.driver > span {
		text-transform: uppercase;
		letter-spacing: 0.03em;
		font-size: 0.72rem;
		color: var(--color-muted);
	}

	.driver small {
		color: var(--color-subtle);
		font-weight: 500;
		font-size: 0.78rem;
	}

	.driver small a {
		color: var(--color-accent);
	}

	input,
	select {
		min-block-size: var(--tap-target);
		padding-inline: var(--space-sm);
		border: var(--rule-size) solid var(--color-border-strong);
		border-radius: var(--radius-sm);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-weight: 600;
	}

	.candidate-chips {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2xs);
		min-block-size: var(--tap-target);
		align-content: center;
	}

	.chip {
		padding: 0.2rem var(--space-xs);
		border: var(--rule-size) solid var(--color-border);
		border-radius: 999px;
		background: var(--color-surface-raised);
		color: var(--color-text);
		font-size: 0.78rem;
		font-weight: 700;
	}

	.chip-recommended {
		border-color: var(--color-accent);
		color: var(--color-accent-strong);
	}

	.chip-empty {
		color: var(--color-subtle);
		font-weight: 500;
	}

	/* Candidate list */
	.candidate-list {
		display: grid;
		gap: var(--space-2xs);
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.candidate {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-md);
		padding: var(--space-sm) var(--space-md);
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}

	.candidate-recommended {
		border-color: var(--color-accent);
		background: color-mix(in oklab, var(--color-accent) 8%, var(--color-surface));
	}

	.candidate-id {
		display: grid;
		gap: var(--space-2xs);
	}

	.candidate-name {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		font-weight: 800;
	}

	.badge {
		padding: 0.1rem 0.45rem;
		border-radius: 999px;
		background: var(--color-accent);
		color: var(--color-bg);
		font-size: 0.66rem;
		font-weight: 900;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.tag-row {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2xs);
	}

	.tag {
		color: var(--color-subtle);
		font-size: 0.74rem;
		font-weight: 600;
	}

	.tag:not(:last-child)::after {
		content: '·';
		margin-inline-start: var(--space-2xs);
	}

	.candidate-cost {
		font-size: 1.4rem;
		font-weight: 800;
		white-space: nowrap;
	}

	.candidate-empty {
		display: block;
		color: var(--color-subtle);
		font-weight: 500;
	}

	.candidate-empty a {
		color: var(--color-accent);
	}

	.candidate-total {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-md);
		padding-block-start: var(--space-sm);
		border-block-start: var(--rule-size) solid var(--color-border-strong);
		font-weight: 800;
	}

	.candidate-total strong {
		font-size: 1.4rem;
	}

	/* Production */
	.production {
		display: grid;
		grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr);
		gap: var(--space-lg);
		align-items: stretch;
		padding: var(--space-lg);
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}

	.production-copy {
		display: grid;
		gap: var(--space-sm);
		align-content: start;
	}

	.production-inputs {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 13rem), 1fr));
		gap: var(--space-md);
		margin-block-start: var(--space-2xs);
	}

	.production-figure {
		display: grid;
		gap: var(--space-sm);
		align-content: start;
		padding: var(--space-md);
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-bg-soft);
	}

	.production-amount {
		font-size: clamp(2rem, 4vw, 2.8rem);
		font-weight: 900;
		line-height: 1;
	}

	.mini-lines {
		display: grid;
		gap: var(--space-2xs);
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.mini-lines li {
		display: flex;
		justify-content: space-between;
		gap: var(--space-sm);
		padding-block-start: var(--space-2xs);
		border-block-start: var(--rule-size) solid var(--color-border);
		color: var(--color-muted);
		font-size: 0.84rem;
	}

	/* Disclosures */
	.disclosure {
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}

	.disclosure summary {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: var(--space-sm);
		padding: var(--space-sm) var(--space-md);
		cursor: pointer;
		font-weight: 800;
	}

	.disclosure summary small {
		color: var(--color-subtle);
		font-weight: 500;
		font-size: 0.82rem;
	}

	.disclosure[open] summary {
		border-block-end: var(--rule-size) solid var(--color-border);
	}

	.advanced-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 14rem), 1fr));
		gap: var(--space-md);
		padding: var(--space-md);
	}

	/* Tables */
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
		font-size: 0.74rem;
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}

	td small {
		display: block;
		margin-block-start: var(--space-2xs);
		color: var(--color-subtle);
	}

	td a {
		color: var(--color-accent);
	}

	@media (max-width: 60rem) {
		.hero,
		.production {
			grid-template-columns: 1fr;
		}

		.hero-stats {
			padding-inline-start: 0;
			border-inline-start: 0;
			padding-block-start: var(--space-sm);
			border-block-start: var(--rule-size) solid var(--color-border);
			grid-template-columns: 1fr 1fr;
		}
	}
</style>
