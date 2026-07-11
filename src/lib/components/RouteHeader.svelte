<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		eyebrow?: string;
		title: string;
		subtitle?: string;
		actions?: Snippet;
	}

	let { eyebrow = 'Retrieve', title, subtitle, actions }: Props = $props();
</script>

<header class="route-header">
	<div class="copy">
		<p class="eyebrow">{eyebrow}</p>
		<h1>{title}</h1>
		{#if subtitle}
			<p class="muted">{subtitle}</p>
		{/if}
	</div>

	{#if actions}
		<div class="cluster" aria-label="Page actions">
			{@render actions()}
		</div>
	{/if}
</header>

<style>
	.copy {
		display: grid;
		gap: var(--space-xs);
		min-inline-size: 0;
	}

	h1 {
		font-size: clamp(2rem, 4vw, 3.4rem);
		line-height: 1.05;
	}

	.muted {
		max-inline-size: 62rem;
	}
</style>
