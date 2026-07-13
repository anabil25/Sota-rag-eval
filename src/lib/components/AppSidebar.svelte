<script lang="ts">
	import { resolve } from '$app/paths';
	import type { StepNavItem } from '$lib/api/types';

	interface Props {
		steps: StepNavItem[];
		currentPath: string;
	}

	let { steps, currentPath }: Props = $props();

	const utilityLinks = [
		{ href: resolve('/runs'), match: '/runs', label: 'Runs' },
		{ href: resolve('/eval-sets'), match: '/eval-sets', label: 'Eval Sets' },
		{ href: resolve('/pricing'), match: '/pricing', label: 'Pricing' },
		{ href: resolve('/settings'), match: '/settings', label: 'Settings' }
	];

	function stepStatus(state: StepNavItem['state']) {
		if (state === 'done') return 'Complete';
		if (state === 'active') return 'Up next';
		if (state === 'error') return 'Needs attention';
		if (state === 'locked') return 'Locked';
		return 'Not started';
	}
</script>

<nav class="sidebar" aria-label="Retrieve navigation">
	<a class="brand" href={resolve('/')} aria-label="Retrieve dashboard">
		<span class="brand-mark" aria-hidden="true">R</span>
		<span>
			<strong>Retrieve</strong>
			<span>Policy retrieval workbench</span>
		</span>
	</a>

	<section class="nav-section" aria-labelledby="workflow-heading">
		<h2 id="workflow-heading">Workflow</h2>
		<ol class="step-list">
			{#each steps as step (step.id)}
				<li>
					{#if step.state === 'locked'}
						<span class="step-link locked" aria-disabled="true">
							<span class="step-index" data-state={step.state}>{step.index}</span>
							<span>
								<strong>{step.shortTitle}</strong>
								<small>{stepStatus(step.state)}</small>
							</span>
						</span>
					{:else}
						<a
							class="step-link"
							class:active={currentPath === step.href}
							href={resolve('/flow/[step]', { step: step.id })}
							aria-current={currentPath === step.href ? 'step' : undefined}
						>
							<span class="step-index" data-state={step.state}>{step.index}</span>
							<span>
								<strong>{step.shortTitle}</strong>
								<small>{stepStatus(step.state)}</small>
							</span>
						</a>
					{/if}
				</li>
			{/each}
		</ol>
	</section>

	<section class="nav-section utility" aria-labelledby="utility-heading">
		<h2 id="utility-heading">Review</h2>
		{#each utilityLinks as link (link.href)}
			<a
				class="utility-link"
				class:active={currentPath === link.match || currentPath.startsWith(`${link.match}/`)}
				href={link.href}>{link.label}</a
			>
		{/each}
	</section>
</nav>

<style>
	.sidebar {
		position: sticky;
		inset-block-start: 0;
		display: grid;
		align-content: start;
		gap: var(--space-lg);
		block-size: 100vh;
		overflow-y: auto;
		padding: var(--space-md);
		border-inline-end: var(--rule-size) solid var(--color-border);
		background: color-mix(in oklab, var(--color-surface) 86%, black);
	}

	.brand {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding-block-end: var(--space-md);
		border-block-end: var(--rule-size) solid var(--color-border);
	}

	.brand:hover {
		text-decoration: none;
	}

	.brand-mark {
		display: grid;
		place-items: center;
		inline-size: 2.4rem;
		block-size: 2.4rem;
		border-radius: var(--radius-md);
		background: color-mix(in oklab, var(--color-accent) 24%, var(--color-surface));
		color: var(--color-accent-strong);
		font-weight: 900;
	}

	.brand span span {
		display: block;
		color: var(--color-muted);
		font-size: 0.82rem;
	}

	.nav-section {
		display: grid;
		gap: var(--space-sm);
	}

	h2 {
		color: var(--color-subtle);
		font-size: 0.78rem;
		font-weight: 900;
		text-transform: uppercase;
	}

	.step-list {
		display: grid;
		gap: var(--space-xs);
		padding: 0;
		margin: 0;
		list-style: none;
	}

	.step-link,
	.utility-link {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		min-block-size: var(--tap-target);
		padding: var(--space-xs);
		border: var(--rule-size) solid transparent;
		border-radius: var(--radius-md);
		color: var(--color-muted);
	}

	.step-link:hover,
	.utility-link:hover,
	.step-link.active,
	.utility-link.active {
		border-color: var(--color-border-strong);
		background: var(--color-surface-raised);
		color: var(--color-text);
		text-decoration: none;
	}

	.step-link.locked {
		color: var(--color-subtle);
		cursor: not-allowed;
		opacity: 0.58;
	}

	.step-link.locked:hover {
		border-color: transparent;
		background: transparent;
	}

	.step-index {
		display: grid;
		place-items: center;
		inline-size: 2rem;
		block-size: 2rem;
		border: var(--rule-size) solid var(--color-border);
		border-radius: 999rem;
		font-weight: 900;
		font-size: 0.82rem;
	}

	.step-index[data-state='done'] {
		border-color: color-mix(in oklab, var(--color-success) 70%, transparent);
		color: var(--color-success);
	}

	.step-index[data-state='active'] {
		border-color: color-mix(in oklab, var(--color-accent) 70%, transparent);
		background: color-mix(in oklab, var(--color-accent) 22%, transparent);
		color: var(--color-accent-strong);
	}

	.step-index[data-state='locked'] {
		border-style: dashed;
	}

	.step-link strong {
		display: block;
	}

	.step-link small {
		display: block;
		color: var(--color-subtle);
		font-size: 0.78rem;
	}

	.utility {
		margin-block-start: auto;
	}

	@media (max-width: 52rem) {
		.sidebar {
			position: static;
			block-size: auto;
			border-inline-end: 0;
			border-block-end: var(--rule-size) solid var(--color-border);
		}

		.step-list {
			grid-template-columns: repeat(auto-fit, minmax(min(100%, 8rem), 1fr));
		}

		.step-link small {
			display: none;
		}
	}
</style>
