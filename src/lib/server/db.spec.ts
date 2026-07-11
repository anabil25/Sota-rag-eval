import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { DatabaseSync } from 'node:sqlite';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import {
	browseQuestions,
	closeDb,
	getAllCompletedRuns,
	getArchitecture,
	getEvalSets,
	getEvalSummary,
	getLatestEvalSet,
	getRunDetail,
	getUiSession,
	updateUiSession
} from './db';

// These tests read the real retrieve.db at the repo root (the same file the
// Python engine uses). They assert the ported TS query layer returns the
// documented shapes against real data.
describe('db read layer (real retrieve.db)', () => {
	afterAll(() => closeDb());

	it('lists eval sets newest-first with raw columns', () => {
		const sets = getEvalSets();
		expect(Array.isArray(sets)).toBe(true);
		expect(sets.length).toBeGreaterThan(0);
		// Ordered by id DESC.
		for (let i = 1; i < sets.length; i++) {
			expect(sets[i - 1].id).toBeGreaterThan(sets[i].id);
		}
	});

	it('returns the latest eval set', () => {
		const latest = getLatestEvalSet();
		const sets = getEvalSets();
		expect(latest?.id).toBe(sets[0].id);
	});

	it('summarizes an eval set with parsed categories and examples', () => {
		const latest = getLatestEvalSet();
		expect(latest).not.toBeNull();
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
		const latest = getLatestEvalSet()!;
		const page = browseQuestions(latest.id, { limit: 5 });
		expect(page.total).toBeGreaterThan(0);
		expect(page.items.length).toBeLessThanOrEqual(5);
		expect(page.items.length).toBeGreaterThan(0);
		expect(Array.isArray(page.items[0].ground_truth_chunk_ids)).toBe(true);
	});

	it('applies category filters in browse', () => {
		const latest = getLatestEvalSet()!;
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

// The write path (UI session upsert) is verified against an isolated temp DB so
// it never mutates the real retrieve.db.
describe('updateUiSession (isolated temp db)', () => {
	let tempDir: string;
	let previousPath: string | undefined;

	beforeAll(() => {
		previousPath = process.env.PRIVATE_RETRIEVE_DB_PATH;
		tempDir = mkdtempSync(path.join(tmpdir(), 'retrieve-db-spec-'));
		const dbPath = path.join(tempDir, 'temp.db');
		const seed = new DatabaseSync(dbPath);
		seed.exec(
			`CREATE TABLE generation_preferences (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				scope_key TEXT NOT NULL UNIQUE,
				preferences TEXT NOT NULL DEFAULT '{}',
				updated_at TEXT NOT NULL DEFAULT (datetime('now'))
			);`
		);
		seed.close();
		process.env.PRIVATE_RETRIEVE_DB_PATH = dbPath;
		closeDb(); // force the module to reopen against the temp db
	});

	afterAll(() => {
		closeDb();
		if (previousPath === undefined) delete process.env.PRIVATE_RETRIEVE_DB_PATH;
		else process.env.PRIVATE_RETRIEVE_DB_PATH = previousPath;
		rmSync(tempDir, { recursive: true, force: true });
	});

	it('inserts then shallow-merges patches, preserving prior keys', () => {
		expect(getUiSession()).toEqual({});

		const first = updateUiSession({ selected_mode: 'sota', winners: ['hybrid'] });
		expect(first.selected_mode).toBe('sota');
		expect(first.winners).toEqual(['hybrid']);

		// Second patch must merge, not replace.
		const second = updateUiSession({ configure_done: true });
		expect(second.selected_mode).toBe('sota');
		expect(second.configure_done).toBe(true);
		expect(second.winners).toEqual(['hybrid']);

		// Persisted across reads.
		const persisted = getUiSession();
		expect(persisted.selected_mode).toBe('sota');
		expect(persisted.configure_done).toBe(true);
	});
});
