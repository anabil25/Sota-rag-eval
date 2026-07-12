/**
 * Native TypeScript port of the read-side SQLite data layer (`retrieve-core`'s
 * `db.py`). Backed by Node's built-in `node:sqlite`, it reads the same
 * `retrieve.db` file the Python engine owns. Only pure read queries are ported — the
 * Azure/OpenAI/config-coupled endpoints still live in the Python backend.
 *
 * Serialization is kept byte-for-byte faithful to the Python contracts:
 * JSON-text columns are parsed exactly where `db.py` parses them and left as
 * raw strings where `db.py` leaves them raw (e.g. `eval_sets.category_counts`
 * on the list endpoint).
 */
import { DatabaseSync } from 'node:sqlite';
import { existsSync } from 'node:fs';
import path from 'node:path';
import type {
	CategoryScore,
	EvalQuestion,
	EvalQuestionBrowseResult,
	EvalSet,
	EvalSummary,
	RunDetail,
	RunResult,
	RunSummary,
	UiSession
} from '$lib/api/types';

type Row = Record<string, unknown>;

let cachedDb: DatabaseSync | null = null;
let cachedPath: string | null = null;

function resolveDbPath(): string {
	const configured = process.env.PRIVATE_RETRIEVE_DB_PATH || 'retrieve.db';
	return path.isAbsolute(configured) ? configured : path.resolve(process.cwd(), configured);
}

/** Lazily open (and cache) a read-only connection to Python-owned state. */
function db(): DatabaseSync | null {
	const target = resolveDbPath();
	if (cachedDb && cachedPath === target) return cachedDb;
	if (cachedDb) cachedDb.close();
	cachedDb = null;
	cachedPath = target;
	if (!existsSync(target)) return null;
	cachedDb = new DatabaseSync(target, { readOnly: true });
	return cachedDb;
}

function dbWithTables(...tableNames: string[]): DatabaseSync | null {
	const database = db();
	if (!database) return null;
	for (const tableName of tableNames) {
		const row = database
			.prepare("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?")
			.get(tableName);
		if (!row) return null;
	}
	return database;
}

/** Close the cached connection (used by tests). */
export function closeDb(): void {
	if (cachedDb) {
		cachedDb.close();
		cachedDb = null;
		cachedPath = null;
	}
}

function parseJson<T>(value: unknown, fallback: T): T {
	if (typeof value !== 'string') return fallback;
	try {
		return JSON.parse(value) as T;
	} catch {
		return fallback;
	}
}

function asNumber(value: unknown): number {
	return typeof value === 'bigint' ? Number(value) : (value as number);
}

// ── Eval sets ────────────────────────────────────────────────────────

/** `SELECT * FROM eval_sets ORDER BY id DESC` — raw rows (matches `/api/eval-sets`). */
export function getEvalSets(): EvalSet[] {
	const database = dbWithTables('eval_sets');
	if (!database) return [];
	const rows = database.prepare('SELECT * FROM eval_sets ORDER BY id DESC').all() as Row[];
	return rows as unknown as EvalSet[];
}

export function getLatestEvalSet(): EvalSet | null {
	const database = dbWithTables('eval_sets');
	if (!database) return null;
	const row = database.prepare('SELECT * FROM eval_sets ORDER BY id DESC LIMIT 1').get() as
		| Row
		| undefined;
	return (row as unknown as EvalSet) ?? null;
}

function questionRow(r: Row): EvalQuestion & Row {
	return {
		...r,
		ground_truth_chunk_ids: parseJson<string[]>(r.ground_truth_chunk_ids, []),
		metadata: parseJson<Record<string, unknown>>(r.metadata, {})
	} as unknown as EvalQuestion & Row;
}

export function getQuestions(evalSetId: number): (EvalQuestion & Row)[] {
	const database = dbWithTables('eval_questions');
	if (!database) return [];
	const rows = database
		.prepare('SELECT * FROM eval_questions WHERE eval_set_id = ? ORDER BY id')
		.all(evalSetId) as Row[];
	return rows.map(questionRow);
}

/** `/api/eval-sets/{id}/summary` — parsed category_counts + per-category examples. */
export function getEvalSummary(evalSetId: number): EvalSummary | null {
	const database = dbWithTables('eval_sets');
	if (!database) return null;
	const row = database.prepare('SELECT * FROM eval_sets WHERE id = ?').get(evalSetId) as
		| Row
		| undefined;
	if (!row) return null;
	const categories = parseJson<Record<string, number>>(row.category_counts, {});
	const examples: Record<string, string[]> = {};
	for (const q of getQuestions(evalSetId)) {
		const cat = q.category as string;
		if (!examples[cat]) examples[cat] = [];
		if (examples[cat].length < 3) examples[cat].push(q.question_text as string);
	}
	return { eval_set: row as unknown as EvalSet, categories, examples };
}

const QUESTION_FILTERS: { key: string; column: string }[] = [
	{ key: 'category', column: 'category' },
	{ key: 'question_type', column: 'question_type' },
	{ key: 'persona', column: 'persona' },
	{ key: 'intent_family', column: 'intent_family' }
];

export interface QuestionFilters {
	category?: string;
	question_type?: string;
	persona?: string;
	intent_family?: string;
	limit?: number;
	offset?: number;
}

/** `/api/eval-sets/{id}/questions/browse` — filtered page + total count. */
export function browseQuestions(
	evalSetId: number,
	filters: QuestionFilters = {}
): EvalQuestionBrowseResult {
	const database = dbWithTables('eval_questions');
	if (!database) return { total: 0, items: [] };
	const where = ['eval_set_id = ?'];
	const params: (string | number)[] = [evalSetId];
	for (const { key, column } of QUESTION_FILTERS) {
		const value = filters[key as keyof QuestionFilters];
		if (value !== undefined && value !== '') {
			where.push(`${column} = ?`);
			params.push(value as string);
		}
	}
	const whereSql = where.join(' AND ');

	const limit = filters.limit ?? 100;
	const offset = filters.offset ?? 0;
	const items = database
		.prepare(`SELECT * FROM eval_questions WHERE ${whereSql} ORDER BY id LIMIT ? OFFSET ?`)
		.all(...params, limit, offset) as Row[];

	const countRow = database
		.prepare(`SELECT COUNT(*) AS cnt FROM eval_questions WHERE ${whereSql}`)
		.get(...params) as Row;

	return {
		total: asNumber(countRow.cnt),
		items: items.map(questionRow) as unknown as EvalQuestion[]
	};
}

// ── Runs ─────────────────────────────────────────────────────────────

function runRow(r: Row): RunSummary & Row {
	return {
		...r,
		architecture_config: parseJson<Record<string, unknown>>(r.architecture_config, {}),
		aggregate_metrics: parseJson<Record<string, number>>(r.aggregate_metrics, {})
	} as RunSummary & Row;
}

/** Latest completed run per architecture name (matches `get_all_completed_runs`). */
export function getAllCompletedRuns(): (RunSummary & Row)[] {
	const database = dbWithTables('runs', 'eval_sets');
	if (!database) return [];
	const rows = database
		.prepare(
			`SELECT r.*, es.version_label AS eval_set_version
			   FROM runs r
			   LEFT JOIN eval_sets es ON es.id = r.eval_set_id
			   INNER JOIN (
			       SELECT architecture_name, MAX(id) AS max_id
			       FROM runs WHERE status = 'completed'
			       GROUP BY architecture_name
			   ) latest ON r.id = latest.max_id
			   ORDER BY r.id`
		)
		.all() as Row[];
	return rows.map(runRow);
}

export function getCompletedRunsForExperiment(scope: {
	experimentId: string;
	evalSetId: number;
	architectureNames: string[];
	corpusFingerprint: string;
}): (RunSummary & Row)[] {
	if (
		!scope.experimentId ||
		!scope.corpusFingerprint ||
		scope.architectureNames.length === 0
	)
		return [];
	const database = dbWithTables('runs', 'eval_sets');
	if (!database) return [];
	const rows = database
		.prepare(
			`SELECT r.*, es.version_label AS eval_set_version
			   FROM runs r
			   LEFT JOIN eval_sets es ON es.id = r.eval_set_id
			   WHERE r.status = 'completed' AND r.eval_set_id = ?
			   ORDER BY r.id`
		)
		.all(scope.evalSetId) as Row[];
	const allowed = new Set(scope.architectureNames);
	const latestByName = new Map<string, RunSummary & Row>();
	for (const row of rows) {
		const run = runRow(row);
		const config = run.architecture_config ?? {};
		const baseName = String(
			config._variant_of || config.candidate_base || run.architecture_name
		).split('[', 1)[0];
		if (
			config.experiment_id !== scope.experimentId ||
			config.corpus_fingerprint !== scope.corpusFingerprint ||
			!allowed.has(baseName)
		)
			continue;
		latestByName.set(run.architecture_name, run);
	}
	return [...latestByName.values()].sort((left, right) => left.id - right.id);
}

export function getRun(runId: number): (RunSummary & Row) | null {
	const database = dbWithTables('runs');
	if (!database) return null;
	const row = database.prepare('SELECT * FROM runs WHERE id = ?').get(runId) as Row | undefined;
	return row ? runRow(row) : null;
}

function resultRow(r: Row): RunResult & Row {
	return {
		...r,
		retrieved_chunk_ids: parseJson<string[]>(r.retrieved_chunk_ids, []),
		scores: parseJson<Record<string, number>>(r.scores, {}),
		ground_truth_chunk_ids: parseJson<string[]>(r.ground_truth_chunk_ids, [])
	} as RunResult & Row;
}

export function getResultsForRun(runId: number): (RunResult & Row)[] {
	const database = dbWithTables('run_results', 'eval_questions');
	if (!database) return [];
	const rows = database
		.prepare(
			`SELECT rr.*, eq.question_text, eq.category, eq.ground_truth_chunk_ids
			   FROM run_results rr
			   LEFT JOIN eval_questions eq ON eq.id = rr.question_id
			   WHERE rr.run_id = ?
			   ORDER BY rr.id`
		)
		.all(runId) as Row[];
	return rows.map(resultRow);
}

export function getFailuresForRun(runId: number): (RunResult & Row)[] {
	const database = dbWithTables('run_results', 'eval_questions');
	if (!database) return [];
	const rows = database
		.prepare(
			`SELECT rr.*, eq.question_text, eq.category, eq.ground_truth_chunk_ids
			   FROM run_results rr
			   LEFT JOIN eval_questions eq ON eq.id = rr.question_id
			   WHERE rr.run_id = ? AND rr.failure_type IS NOT NULL
			   ORDER BY rr.id`
		)
		.all(runId) as Row[];
	return rows.map((r) => {
		const result = resultRow(r);
		const gt = result.ground_truth_chunk_ids ?? [];
		const retrieved = result.retrieved_chunk_ids ?? [];
		return {
			...result,
			expected_chunk_id: gt.length ? gt[0] : undefined,
			top_retrieved_id: retrieved.length ? retrieved[0] : undefined
		} as RunResult & Row;
	});
}

/** Average scores per question category for a run (matches `get_per_category_scores`). */
export function getPerCategoryScores(runId: number): Record<string, Record<string, number>> {
	const database = dbWithTables('run_results', 'eval_questions');
	if (!database) return {};
	const rows = database
		.prepare(
			`SELECT eq.category, rr.scores
			   FROM run_results rr
			   JOIN eval_questions eq ON eq.id = rr.question_id
			   WHERE rr.run_id = ?`
		)
		.all(runId) as Row[];

	const byCategory = new Map<string, Record<string, number>[]>();
	for (const r of rows) {
		const cat = r.category as string;
		const scores = parseJson<Record<string, number>>(r.scores, {});
		const list = byCategory.get(cat) ?? [];
		list.push(scores);
		byCategory.set(cat, list);
	}

	const averages: Record<string, Record<string, number>> = {};
	for (const [cat, scoreList] of byCategory) {
		if (!scoreList.length) continue;
		const keys = Object.keys(scoreList[0]);
		const avg: Record<string, number> = {};
		for (const k of keys) {
			avg[k] = scoreList.reduce((sum, s) => sum + (s[k] ?? 0), 0) / scoreList.length;
		}
		averages[cat] = avg;
	}
	return averages;
}

/** Full `/api/runs/{id}` payload: run + results + per-category rows + failures. */
export function getRunDetail(runId: number): RunDetail | null {
	const run = getRun(runId);
	if (!run) return null;
	const results = getResultsForRun(runId);
	const categoryScores = getPerCategoryScores(runId);
	const categories: CategoryScore[] = Object.entries(categoryScores).map(([category, scores]) => {
		const totalQuestions = results.filter((r) => r.category === category).length;
		const failureCount = results.filter((r) => r.category === category && r.failure_type).length;
		return {
			category,
			...scores,
			total_questions: totalQuestions,
			failure_count: failureCount
		} as CategoryScore;
	});
	const failures = getFailuresForRun(runId);
	return {
		run: run as RunSummary,
		results: results as RunResult[],
		categories,
		failures: failures as RunResult[]
	};
}

// ── UI session (generation_preferences scope) ────────────────────────

export function getGenerationPreferences(scopeKey = 'default'): Record<string, unknown> {
	const database = dbWithTables('generation_preferences');
	if (!database) return {};
	const row = database
		.prepare('SELECT preferences FROM generation_preferences WHERE scope_key = ?')
		.get(scopeKey) as Row | undefined;
	if (!row) return {};
	return parseJson<Record<string, unknown>>(row.preferences, {});
}

function stringList(value: unknown): string[] {
	if (Array.isArray(value)) return value.map(String).filter(Boolean);
	if (typeof value === 'string') {
		return value
			.split(',')
			.map((item) => item.trim())
			.filter(Boolean);
	}
	return [];
}

function normalizeUiSession(raw: Record<string, unknown>): UiSession {
	const session = { ...raw } as UiSession;
	if ('selected_architectures' in raw) {
		session.selected_architectures = stringList(raw.selected_architectures);
	}
	if ('winners' in raw) {
		session.winners = stringList(raw.winners);
	}
	return session;
}

export function getUiSession(): UiSession {
	return normalizeUiSession(getGenerationPreferences('ui_session'));
}

export interface ArchitectureRecord extends Row {
	name: string;
	status: string;
	config: Record<string, unknown>;
	resources_provisioned: Record<string, unknown>;
}

/** Latest architecture row for a name, with JSON columns parsed (matches `get_architecture`). */
export function getArchitecture(name: string): ArchitectureRecord | null {
	const database = dbWithTables('architectures');
	if (!database) return null;
	const row = database
		.prepare('SELECT * FROM architectures WHERE name = ? ORDER BY id DESC LIMIT 1')
		.get(name) as Row | undefined;
	if (!row) return null;
	return {
		...row,
		config: parseJson<Record<string, unknown>>(row.config, {}),
		resources_provisioned: parseJson<Record<string, unknown>>(row.resources_provisioned, {})
	} as ArchitectureRecord;
}
