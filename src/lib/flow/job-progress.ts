/**
 * Helpers for turning a raw job log stream into a lightweight progress readout.
 *
 * The job backend streams free-form text lines over SSE with no structured
 * progress field, so we parse a "current of total" fraction out of the log text
 * to show how far the run has got. The time-left estimate is built by tracking
 * the lapse between progress events: we average the per-item gap across the
 * observed events and multiply it by the number of items still to go.
 */

export interface ProgressFraction {
	current: number;
	total: number;
}

/** A single observed progress event: when it arrived and the count it reported. */
export interface ProgressSample {
	t: number;
	current: number;
}

const SLASH_PATTERN = /(?<!\d)(\d{1,9})\s*\/\s*(\d{1,9})(?!\d)/;
const OF_PATTERN = /(\d{1,9})\s+of\s+(\d{1,9})(?!\d)/i;

/**
 * Extract a `current/total` progress fraction from a single log line.
 * Recognises `12/732`, `[12/732]`, `(12 / 732)` and `12 of 732`.
 * Returns `null` when no sane fraction is present.
 */
export function parseProgressLine(line: string): ProgressFraction | null {
	for (const pattern of [SLASH_PATTERN, OF_PATTERN]) {
		const match = pattern.exec(line);
		if (!match) continue;
		const current = Number(match[1]);
		const total = Number(match[2]);
		if (total > 0 && current >= 0 && current <= total) {
			return { current, total };
		}
	}
	return null;
}

/**
 * Average time (ms) elapsed per item across the observed progress events.
 *
 * This is the "lapse between events" the estimate is built on: we take the
 * time and item span between the first and last samples in the window and
 * divide, so events that advance the count by more than one are handled
 * correctly. Returns `null` when there is not enough movement to measure.
 */
export function averageStepMs(samples: ProgressSample[]): number | null {
	if (samples.length < 2) return null;
	const first = samples[0];
	const last = samples[samples.length - 1];
	const deltaT = last.t - first.t;
	const deltaItems = last.current - first.current;
	if (deltaT <= 0 || deltaItems <= 0) return null;
	return deltaT / deltaItems;
}

/**
 * Estimate remaining milliseconds: average per-item lapse × items still to go.
 * Returns `0` once complete and `null` when there is no usable average yet.
 */
export function estimateRemainingMs(
	current: number,
	total: number,
	avgStepMs: number | null
): number | null {
	if (total <= 0) return null;
	if (current >= total) return 0;
	if (avgStepMs == null || avgStepMs <= 0) return null;
	const remaining = (total - current) * avgStepMs;
	return Number.isFinite(remaining) ? Math.max(0, remaining) : null;
}

/** Format a millisecond duration as a compact `45s` / `3m 05s` / `1h 04m` string. */
export function formatDuration(ms: number): string {
	if (!Number.isFinite(ms) || ms < 0) return '—';
	const totalSeconds = Math.round(ms / 1000);
	if (totalSeconds < 60) return `${totalSeconds}s`;

	const minutes = Math.floor(totalSeconds / 60);
	const seconds = totalSeconds % 60;
	if (minutes < 60) return `${minutes}m ${String(seconds).padStart(2, '0')}s`;

	const hours = Math.floor(minutes / 60);
	const remMinutes = minutes % 60;
	return `${hours}h ${String(remMinutes).padStart(2, '0')}m`;
}
