<script lang="ts">
	interface Props {
		title: string;
		description?: string;
	}

	let { title, description }: Props = $props();
</script>

<section class="panel empty-state">
	<p class="eyebrow">Empty</p>
	<h2>{title}</h2>
	{#if description}
		<p class="muted">{description}</p>
	{/if}
</section>

<style>
	.empty-state {
		display: grid;
		gap: var(--space-xs);
		place-items: start;
	}
</style>
