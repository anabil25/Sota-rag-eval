<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';

	const status = $derived(page.status);
	const message = $derived(page.error?.message ?? 'Something went wrong.');

	// A 503 with a network-style message means a Python operation endpoint on
	// 127.0.0.1:8000 is unreachable. Read-only pages use local real data.
	const backendDown = $derived(
		status === 503 || /fetch failed|ECONNREFUSED|actively refused|connect/i.test(message)
	);
</script>

<section class="error-screen" aria-live="polite">
	{#if backendDown}
		<div class="error-card error-card--backend">
			<p class="error-kicker">Backend not running</p>
			<h1 class="error-title">The retrieval service isn’t responding</h1>
			<p class="error-body">
				This operation needs the Python worker, and nothing is answering on <code
					>127.0.0.1:8000</code
				>. Read-only pages use local real data, but jobs and CSV/curation operations still need the
				worker.
			</p>

			<div class="error-steps">
				<p class="error-steps__label">Start it from the project root:</p>
				<pre class="error-cmd"><code>npm run backend:dev</code></pre>
				<p class="error-hint">
					First time? Install deps once with <code>npm run backend:install</code>, then start it.
					Leave that terminal running and reload this page.
				</p>
			</div>

			<div class="error-actions">
				<button
					class="error-btn error-btn--primary"
					type="button"
					onclick={() => location.reload()}
				>
					Reload page
				</button>
				<a class="error-btn" href={resolve('/')}>Back to start</a>
			</div>

			{#if status !== 503}
				<p class="error-detail">{status} · {message}</p>
			{/if}
		</div>
	{:else}
		<div class="error-card">
			<p class="error-kicker">Error {status}</p>
			<h1 class="error-title">{message}</h1>
			<div class="error-actions">
				<button
					class="error-btn error-btn--primary"
					type="button"
					onclick={() => location.reload()}
				>
					Reload page
				</button>
				<a class="error-btn" href={resolve('/')}>Back to start</a>
			</div>
		</div>
	{/if}
</section>

<style>
	.error-screen {
		display: grid;
		place-items: center;
		min-block-size: 70vh;
		padding: var(--space-xl);
	}

	.error-card {
		inline-size: min(40rem, 100%);
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
		padding: var(--space-xl);
		background: var(--color-surface);
		border: var(--rule-size, 1px) solid var(--color-border);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow-panel);
	}

	.error-card--backend {
		border-color: color-mix(in oklab, var(--color-warning) 45%, var(--color-border));
	}

	.error-kicker {
		margin: 0;
		font-size: 0.8rem;
		font-weight: 600;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--color-warning);
	}

	.error-card:not(.error-card--backend) .error-kicker {
		color: var(--color-danger);
	}

	.error-title {
		margin: 0;
		font-size: clamp(1.35rem, 2.5vw, 1.75rem);
		line-height: 1.2;
		color: var(--color-text);
	}

	.error-body {
		margin: 0;
		color: var(--color-muted);
		line-height: 1.6;
	}

	.error-steps {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
		padding: var(--space-md);
		background: var(--color-bg-soft);
		border: var(--rule-size, 1px) solid var(--color-border);
		border-radius: var(--radius-sm);
	}

	.error-steps__label {
		margin: 0;
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--color-text);
	}

	.error-cmd {
		margin: 0;
		padding: var(--space-sm) var(--space-md);
		background: var(--color-bg);
		border: var(--rule-size, 1px) solid var(--color-border-strong);
		border-radius: var(--radius-sm);
		overflow-x: auto;
	}

	.error-cmd code,
	.error-hint code,
	.error-body code {
		font-family: var(--font-mono);
		font-size: 0.9em;
	}

	.error-hint {
		margin: 0;
		font-size: 0.85rem;
		color: var(--color-subtle);
		line-height: 1.55;
	}

	.error-actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-sm);
		margin-block-start: var(--space-2xs);
	}

	.error-btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: var(--space-xs) var(--space-md);
		font: inherit;
		font-weight: 600;
		text-decoration: none;
		color: var(--color-text);
		background: var(--color-surface-raised);
		border: var(--rule-size, 1px) solid var(--color-border);
		border-radius: var(--radius-sm);
		cursor: pointer;
	}

	.error-btn:hover {
		background: var(--color-surface-strong);
	}

	.error-btn--primary {
		color: var(--color-bg);
		background: var(--color-accent-strong);
		border-color: transparent;
	}

	.error-btn--primary:hover {
		background: var(--color-accent);
	}

	.error-btn:focus-visible {
		outline: 0.18rem solid var(--color-focus);
		outline-offset: 0.1rem;
	}

	.error-detail {
		margin: 0;
		font-family: var(--font-mono);
		font-size: 0.78rem;
		color: var(--color-subtle);
	}
</style>
