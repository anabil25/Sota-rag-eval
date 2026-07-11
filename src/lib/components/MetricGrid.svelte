<script lang="ts">
	import type { MetricItem } from '$lib/api/types';

	interface Props {
		metrics: MetricItem[];
	}

	let { metrics }: Props = $props();
</script>

<dl class="metric-grid" aria-label="Metrics">
	{#each metrics as metric (metric.label)}
		{#if metric.href}
			<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
			<a class="metric-card" href={metric.href} data-tone={metric.tone ?? 'neutral'}>
				<dt>{metric.label}</dt>
				<dd>{metric.value}</dd>
				{#if metric.note}
					<p>{metric.note}</p>
				{/if}
			</a>
		{:else}
			<div class="metric-card" data-tone={metric.tone ?? 'neutral'}>
				<dt>{metric.label}</dt>
				<dd>{metric.value}</dd>
				{#if metric.note}
					<p>{metric.note}</p>
				{/if}
			</div>
		{/if}
	{/each}
</dl>

<style>
	.metric-card {
		display: grid;
		gap: var(--space-2xs);
		padding: var(--space-md);
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		text-decoration: none;
		color: inherit;
	}

	a.metric-card {
		transition: border-color 0.15s ease;
	}

	a.metric-card:hover {
		border-color: var(--color-accent, var(--color-muted));
	}

	dt {
		color: var(--color-muted);
		font-size: 0.8rem;
		font-weight: 800;
		text-transform: uppercase;
	}

	dd {
		font-size: clamp(1.7rem, 3vw, 2.4rem);
		font-weight: 900;
		line-height: 1;
	}

	p {
		color: var(--color-subtle);
		font-size: 0.88rem;
	}

	.metric-card[data-tone='success'] dd {
		color: var(--color-success);
	}

	.metric-card[data-tone='warning'] dd {
		color: var(--color-warning);
	}

	.metric-card[data-tone='danger'] dd {
		color: var(--color-danger);
	}
</style>
