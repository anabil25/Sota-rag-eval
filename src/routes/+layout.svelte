<script lang="ts">
	import AppSidebar from '$lib/components/AppSidebar.svelte';
	import '$lib/styles/global.css';
	import favicon from '$lib/assets/favicon.svg';

	let { data, children } = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>Retrieve</title>
</svelte:head>

<div class="app-shell">
	<AppSidebar steps={data.steps} currentPath={data.currentPath} />
	<main class="app-main" id="main-content">
		{@render children()}
	</main>
</div>
