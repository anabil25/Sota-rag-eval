import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import {
	browseQuestions,
	closeDb,
	getAllCompletedRuns,
	getArchitecture,
	getEvalSets,
	getEvalSummary,
	getLatestEvalSet,
	getRunDetail,
	getUiSession
} from './db';

// The read layer must support both an initialized Python database and a clean
// clone where retrieve.db does not exist yet.
describe('db read layer (real retrieve.db)', () => {
	afterAll(() => closeDb());

	it('lists eval sets newest-first with raw columns', () => {
		const sets = getEvalSets();
		expect(Array.isArray(sets)).toBe(true);
		// Ordered by id DESC.
		for (let i = 1; i < sets.length; i++) {
			expect(sets[i - 1].id).toBeGreaterThan(sets[i].id);
		}
	});

	it('returns the latest eval set', () => {
		const latest = getLatestEvalSet();
		const sets = getEvalSets();
		expect(latest?.id ?? null).toBe(sets[0]?.id ?? null);
	});

	it('summarizes an eval set with parsed categories and examples', () => {
		const latest = getLatestEvalSet();
		if (!latest) return expect(getEvalSummary(-1)).toBeNull();
		const summary = getEvalSummary(latest!.id);
		expect(summary).not.toBeNull();
		expect(typeof summary!.categories).toBe('object');
		expect(Object.keys(summary!.categories).length).toBeGreaterThan(0);
		// Examples cap at 3 per category.
		for (const examples of Object.values(summary!.examples)) {
			expect(examples.length).toBeLessThanOrEqual(3);
		}
	});

	it('browses questions with a total and parsed JSON fields', () => {
		const latest = getLatestEvalSet();
		if (!latest) return expect(browseQuestions(-1)).toEqual({ total: 0, items: [] });
		const page = browseQuestions(latest.id, { limit: 5 });
		expect(page.items.length).toBeLessThanOrEqual(5);
		if (page.items.length) {
			expect(Array.isArray(page.items[0].ground_truth_chunk_ids)).toBe(true);
		}
	});

	it('applies category filters in browse', () => {
		const latest = getLatestEvalSet();
		if (!latest) return expect(browseQuestions(-1)).toEqual({ total: 0, items: [] });
		const summary = getEvalSummary(latest.id)!;
		const category = Object.keys(summary.categories)[0];
		const page = browseQuestions(latest.id, { category, limit: 50 });
		expect(page.items.every((q) => q.category === category)).toBe(true);
	});

	it('returns completed runs with parsed metrics, one per architecture', () => {
		const runs = getAllCompletedRuns();
		expect(Array.isArray(runs)).toBe(true);
		const names = runs.map((r) => r.architecture_name);
		expect(new Set(names).size).toBe(names.length); // unique per architecture
		for (const run of runs) {
			expect(run.status).toBe('completed');
			expect(typeof run.aggregate_metrics).toBe('object');
			expect(typeof run.architecture_config).toBe('object');
		}
	});

	it('builds full run detail with per-category rows', () => {
		const runs = getAllCompletedRuns();
		if (!runs.length) return expect(runs.length).toBe(0);
		const detail = getRunDetail(runs[0].id);
		expect(detail).not.toBeNull();
		expect(detail!.run.id).toBe(runs[0].id);
		expect(Array.isArray(detail!.results)).toBe(true);
		expect(Array.isArray(detail!.failures)).toBe(true);
		for (const cat of detail!.categories) {
			expect(typeof cat.category).toBe('string');
			expect(typeof cat.total_questions).toBe('number');
		}
	});

	it('reads the persisted UI session object', () => {
		const session = getUiSession();
		expect(typeof session).toBe('object');
	});

	it('returns null for an unknown architecture', () => {
		expect(getArchitecture('__definitely_not_a_real_arch__')).toBeNull();
	});
});
