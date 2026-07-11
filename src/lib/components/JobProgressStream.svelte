<script lang="ts">
	import { onMount } from 'svelte';
	import {
		averageStepMs,
		estimateRemainingMs,
		formatDuration,
		parseProgressLine,
		type ProgressFraction,
		type ProgressSample
	} from '$lib/flow/job-progress';
	import type { JobStatus } from '$lib/api/types';

	interface Props {
		jobId?: string | null;
		label?: string;
		pending?: boolean;
		onDone?: () => void | Promise<void>;
	}

	let { jobId = null, label = 'Job progress', pending = false, onDone }: Props = $props();

	let lines = $state<string[]>([]);
	let status = $state<'idle' | 'starting' | 'running' | 'done' | 'error'>('idle');
	let progress = $state<ProgressFraction | null>(null);
	let samples = $state<ProgressSample[]>([]);
	let startedAt = $state<number | null>(null);
	let now = $state<number>(Date.now());

	const elapsedMs = $derived(startedAt != null ? Math.max(0, now - startedAt) : 0);
	// Average lapse between progress events (ms per item), used for the estimate.
	const stepMs = $derived(averageStepMs(samples));
	const remainingMs = $derived(
		progress && status === 'running'
			? estimateRemainingMs(progress.current, progress.total, stepMs)
			: null
	);
	const showProgress = $derived(status === 'starting' || status === 'running' || status === 'done');

	function field(record: Record<string, unknown>, key: string): string {
		const value = record[key];
		return typeof value === 'string' ? value : '';
	}

	function asyncIndexingLines(result: Record<string, unknown>): string[] {
		const raw = result.async_indexing;
		if (!Array.isArray(raw)) return [];
		return raw
			.filter((item): item is Record<string, unknown> => item != null && typeof item === 'object')
			.map((item) => {
				const architecture = field(item, 'architecture') || 'Graph index';
				const estimate =
					field(item, 'graph_worker_estimate') ||
					field(item, 'lightrag_estimate') ||
					'background indexing may take a while';
				const graphJob = field(item, 'graph_worker_job_id');
				const lightTrackCount = item.lightrag_track_count;
				const handle = graphJob
					? `job ${graphJob.slice(0, 8)}`
					: typeof lightTrackCount === 'number'
						? `${lightTrackCount} LightRAG batches`
						: 'cloud job';
				return `${architecture}: background indexing started (${handle}). Estimate: ${estimate}.`;
			});
	}

	async function settleJob(activeJobId: string) {
		now = Date.now();
		const response = await fetch(`/api/ui/job/${activeJobId}/status`);
		if (!response.ok) {
			status = 'error';
			lines = [...lines, `Unable to read final job status (${response.status})`];
			await onDone?.();
			return;
		}

		const finalStatus = (await response.json()) as JobStatus;
		if (finalStatus.error) {
			status = 'error';
			lines = [...lines, `Job failed: ${finalStatus.error}`];
		} else {
			status = 'done';
			const asyncLines = asyncIndexingLines(finalStatus.result);
			if (asyncLines.length) lines = [...lines, ...asyncLines];
			if (progress) progress = { current: progress.total, total: progress.total };
		}
		await onDone?.();
	}

	onMount(() => {
		const activeJobId = jobId ?? '';
		lines = [];
		progress = null;
		samples = [];
		const start = Date.now();
		now = start;
		startedAt = activeJobId || pending ? start : null;
		status = activeJobId ? 'running' : pending ? 'starting' : 'idle';

		if (!activeJobId) return;

		const ticker = setInterval(() => {
			if (status === 'running') now = Date.now();
		}, 1000);

		const source = new EventSource(`/api/ui/job/${activeJobId}/stream`);
		let stopped = false;

		function stop() {
			if (stopped) return;
			stopped = true;
			source.close();
			clearInterval(ticker);
		}

		source.onmessage = (event) => {
			lines = [...lines, event.data];
			const parsed = parseProgressLine(event.data);
			if (parsed) {
				progress = parsed;
				samples = [...samples, { t: Date.now(), current: parsed.current }].slice(-12);
			}
		};

		source.addEventListener('done', () => {
			stop();
			void settleJob(activeJobId);
		});

		source.onerror = () => {
			status = 'error';
			now = Date.now();
			stop();
		};

		return stop;
	});
</script>

<section
	class="panel stream"
	aria-live="polite"
	aria-busy={status === 'starting' || status === 'running'}
>
	<header>
		<div>
			<p class="eyebrow">{label}</p>
			<h2>{jobId ? jobId : pending ? 'Starting new job...' : 'No active job'}</h2>
		</div>
		<span class="status-pill" data-status={status}>{status}</span>
	</header>

	{#if showProgress}
		<dl class="progress">
			<div class="progress-item">
				<dt>Progress</dt>
				<dd>
					{#if progress}
						{progress.current} of {progress.total}
					{:else}
						{lines.length} update{lines.length === 1 ? '' : 's'}
					{/if}
				</dd>
			</div>
			<div class="progress-item">
				<dt>Elapsed</dt>
				<dd>{formatDuration(elapsedMs)}</dd>
			</div>
			<div class="progress-item">
				<dt>Est. left</dt>
				<dd>
					{#if status === 'done'}
						done
					{:else if remainingMs != null}
						~{formatDuration(remainingMs)}
					{:else}
						—
					{/if}
				</dd>
			</div>
		</dl>
	{/if}

	{#if lines.length > 0}
		<ol class="log">
			{#each lines as line, index (`${index}-${line}`)}
				<li>{line}</li>
			{/each}
		</ol>
	{:else}
		<p class="muted">
			{pending
				? 'Starting new workflow run...'
				: 'Submit a workflow action to stream progress here.'}
		</p>
	{/if}
</section>

<style>
	.stream {
		display: grid;
		gap: var(--space-md);
	}

	header {
		display: flex;
		align-items: start;
		justify-content: space-between;
		gap: var(--gap-normal);
	}

	h2 {
		font-size: 1rem;
		overflow-wrap: anywhere;
	}

	.status-pill[data-status='running'] {
		color: var(--color-accent-strong);
	}

	.status-pill[data-status='starting'] {
		color: var(--color-accent-strong);
	}

	.status-pill[data-status='done'] {
		color: var(--color-success);
	}

	.status-pill[data-status='error'] {
		color: var(--color-danger);
	}

	.progress {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-sm) var(--space-lg);
		margin: 0;
	}

	.progress-item {
		display: grid;
		gap: 0.1rem;
	}

	.progress-item dt {
		font-size: 0.72rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-muted, inherit);
	}

	.progress-item dd {
		margin: 0;
		font-size: 0.95rem;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	.log {
		display: grid;
		gap: var(--space-2xs);
		max-block-size: 18rem;
		overflow: auto;
		padding: var(--space-sm);
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-sm);
		background: color-mix(in oklab, black 28%, var(--color-surface));
		font-family: var(--font-mono);
		font-size: 0.82rem;
	}

	li {
		overflow-wrap: anywhere;
	}
</style>
