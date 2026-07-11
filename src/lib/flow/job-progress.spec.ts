import { describe, expect, it } from 'vitest';
import {
	averageStepMs,
	estimateRemainingMs,
	formatDuration,
	parseProgressLine
} from './job-progress';

describe('parseProgressLine', () => {
	it('parses a bare slash fraction', () => {
		expect(parseProgressLine('Evaluating 12/732')).toEqual({ current: 12, total: 732 });
	});

	it('parses a bracketed slash fraction with spaces', () => {
		expect(parseProgressLine('[ 12 / 732 ] question done')).toEqual({ current: 12, total: 732 });
	});

	it('parses an "of" fraction', () => {
		expect(parseProgressLine('Question 5 of 100 complete')).toEqual({ current: 5, total: 100 });
	});

	it('returns null when there is no fraction', () => {
		expect(parseProgressLine('Provisioning Azure AI Search...')).toBeNull();
	});

	it('rejects a zero total', () => {
		expect(parseProgressLine('0/0 nothing yet')).toBeNull();
	});

	it('rejects current greater than total', () => {
		expect(parseProgressLine('900/732 impossible')).toBeNull();
	});
});

describe('averageStepMs', () => {
	it('returns null with fewer than two samples', () => {
		expect(averageStepMs([])).toBeNull();
		expect(averageStepMs([{ t: 0, current: 1 }])).toBeNull();
	});

	it('averages the per-item lapse across the window', () => {
		// 20 items across 2000ms -> 100ms per item.
		expect(
			averageStepMs([
				{ t: 1000, current: 10 },
				{ t: 3000, current: 30 }
			])
		).toBe(100);
	});

	it('uses the full window even with intermediate samples', () => {
		// 30 items across 3000ms -> 100ms per item.
		expect(
			averageStepMs([
				{ t: 0, current: 0 },
				{ t: 1500, current: 12 },
				{ t: 3000, current: 30 }
			])
		).toBe(100);
	});

	it('returns null when no time has elapsed', () => {
		expect(
			averageStepMs([
				{ t: 1000, current: 10 },
				{ t: 1000, current: 20 }
			])
		).toBeNull();
	});

	it('returns null when no items advanced', () => {
		expect(
			averageStepMs([
				{ t: 1000, current: 10 },
				{ t: 3000, current: 10 }
			])
		).toBeNull();
	});
});

describe('estimateRemainingMs', () => {
	it('returns null when total is not positive', () => {
		expect(estimateRemainingMs(1, 0, 100)).toBeNull();
	});

	it('returns 0 when complete', () => {
		expect(estimateRemainingMs(10, 10, 100)).toBe(0);
	});

	it('returns null when there is no usable average yet', () => {
		expect(estimateRemainingMs(5, 10, null)).toBeNull();
		expect(estimateRemainingMs(5, 10, 0)).toBeNull();
	});

	it('multiplies the average per-item lapse by the items remaining', () => {
		// 5 remaining × 1000ms/item -> 5000ms.
		expect(estimateRemainingMs(5, 10, 1000)).toBe(5000);
	});

	it('clamps a non-finite estimate to null', () => {
		expect(estimateRemainingMs(5, 10, Number.POSITIVE_INFINITY)).toBeNull();
	});
});

describe('formatDuration', () => {
	it('formats sub-minute durations in seconds', () => {
		expect(formatDuration(45_000)).toBe('45s');
	});

	it('formats minute-scale durations', () => {
		expect(formatDuration(185_000)).toBe('3m 05s');
	});

	it('formats hour-scale durations', () => {
		expect(formatDuration(3_840_000)).toBe('1h 04m');
	});

	it('renders a dash for invalid input', () => {
		expect(formatDuration(Number.NaN)).toBe('—');
		expect(formatDuration(-1)).toBe('—');
	});
});
