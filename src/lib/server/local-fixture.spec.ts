import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DatabaseSync } from 'node:sqlite';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { closeDb } from './db';
import {
	operationAuthHeaders,
	startJob,
	updateOperationUiSession
} from './clients/operation-api-client';
import { getCorpusFiles } from './data/corpus-files';
import { loadFlowStep } from './flow/load-flow-step';
import {
	collectArchitectureOptions,
	collectArgs,
	getBool,
	getString,
	getStrings
} from './flow/form-parsers';
import { startStateForJob } from './flow/progress-rules';
import { getCompareContext } from './services/compare-service';
import { getSotaRecommendation } from './services/sota-service';
import {
	getArchitectureStatus,
	getConfig,
	getStatus,
	selectedArchitectureNames
} from './services/status-service';
import { getUiSession } from './services/workflow-session-service';

describe('local server services with real SQLite/filesystem fixtures', () => {
	let tempDir: string;
	let previousDbPath: string | undefined;
	let previousConfigPath: string | undefined;
	let previousResourceGroup: string | undefined;
	let previousLocation: string | undefined;

	function updateUiSession(patch: Record<string, unknown>): void {
		const database = new DatabaseSync(process.env.PRIVATE_RETRIEVE_DB_PATH!);
		try {
			const row = database
				.prepare("SELECT preferences FROM generation_preferences WHERE scope_key = 'ui_session'")
				.get() as { preferences?: string } | undefined;
			const current = row?.preferences ? JSON.parse(row.preferences) : {};
			database
				.prepare(
					`INSERT INTO generation_preferences (scope_key, preferences, updated_at)
					 VALUES ('ui_session', ?, ?)
					 ON CONFLICT(scope_key) DO UPDATE SET
					 preferences = excluded.preferences, updated_at = excluded.updated_at`
				)
				.run(JSON.stringify({ ...current, ...patch }), new Date().toISOString());
		} finally {
			database.close();
			closeDb();
		}
	}

	beforeEach(() => {
		previousDbPath = process.env.PRIVATE_RETRIEVE_DB_PATH;
		previousConfigPath = process.env.PRIVATE_RETRIEVE_CONFIG_PATH;
		previousResourceGroup = process.env.PRIVATE_RETRIEVE_AZURE_RESOURCE_GROUP;
		previousLocation = process.env.PRIVATE_RETRIEVE_AZURE_LOCATION;
		tempDir = mkdtempSync(path.join(tmpdir(), 'retrieve-local-spec-'));
		const corpusDir = path.join(tempDir, 'corpus');
		mkdirSync(corpusDir);
		writeFileSync(path.join(corpusDir, 'a.md'), '# A', 'utf8');
		writeFileSync(path.join(corpusDir, 'ignore.txt'), 'ignore', 'utf8');
		const dbPath = path.join(tempDir, 'retrieve.db');
		seedDatabase(dbPath);
		writeFileSync(
			path.join(tempDir, 'retrieve.yaml'),
			`
db_path: ${dbPath.replace(/\\/g, '\\\\')}
architectures: [keyword, hybrid]
corpus:
  source: ""
  plugin: html
  output_dir: ${corpusDir.replace(/\\/g, '\\\\')}
azure:
  resource_group: rg-config
  location: eastus2
  name_prefix: ret
eval:
  mode: sample
  categories: [exact_term]
`,
			'utf8'
		);
		process.env.PRIVATE_RETRIEVE_DB_PATH = dbPath;
		process.env.PRIVATE_RETRIEVE_CONFIG_PATH = path.join(tempDir, 'retrieve.yaml');
		process.env.PRIVATE_RETRIEVE_AZURE_RESOURCE_GROUP = 'rg-env';
		process.env.PRIVATE_RETRIEVE_AZURE_LOCATION = 'westus3';
		closeDb();
	});

	afterEach(() => {
		vi.unstubAllGlobals();
		closeDb();
		restoreEnv('PRIVATE_RETRIEVE_DB_PATH', previousDbPath);
		restoreEnv('PRIVATE_RETRIEVE_CONFIG_PATH', previousConfigPath);
		restoreEnv('PRIVATE_RETRIEVE_AZURE_RESOURCE_GROUP', previousResourceGroup);
		restoreEnv('PRIVATE_RETRIEVE_AZURE_LOCATION', previousLocation);
		rmSync(tempDir, { recursive: true, force: true });
	});

	it('parses forms and progress rules', () => {
		const form = new FormData();
		form.set('kind', 'ingest');
		form.set('single', 'one');
		form.set('file', new Blob(['x']));
		form.append('multi', 'a');
		form.append('multi', 'b');
		form.set('advanced__hybrid__vector_exhaustive', 'true');
		form.set('advanced__hybrid__top_k', '20');
		form.set('advanced__bad', 'ignored');
		form.set('advanced__hybrid__flag', 'false');
		expect(getString(form, 'missing', 'fallback')).toBe('fallback');
		expect(getString(form, 'file', 'fallback')).toBe('fallback');
		expect(getBool(form, 'kind')).toBe(true);
		expect(getStrings(form, 'multi')).toEqual(['a', 'b']);
		expect(collectArgs(form, ['kind'])).toMatchObject({ single: 'one', multi: ['a', 'b'] });
		expect(collectArchitectureOptions(form)).toEqual({
			hybrid: { vector_exhaustive: true, top_k: '20', flag: false }
		});
		expect(startStateForJob('ingest')).toMatchObject({
			ingest_done: false,
			eval_done: false
		});
		expect(startStateForJob('eval_generate').eval_done).toBe(false);
		expect(startStateForJob('index').provision_done).toBe(false);
		expect(startStateForJob('provision_index').provision_done).toBe(false);
		expect(startStateForJob('evaluate').run_done).toBe(false);
		expect(startStateForJob('teardown').teardown_done).toBe(false);
		expect(startStateForJob('unknown')).toEqual({});
	});

	it('loads local config, status, corpus, session, architecture status, and SOTA recommendation', async () => {
		const config = getConfig();
		expect(config.architectures).toEqual(['keyword', 'hybrid']);
		expect(getStatus().eval_set?.version_label).toBe('v-fixture');
		expect(getCorpusFiles().files).toEqual([{ name: 'a.md', size: 3 }]);
		expect(getUiSession().selected_architectures).toEqual(['keyword', 'hybrid']);
		updateUiSession({ winners: ['hybrid'] });
		expect(getUiSession().winners).toEqual(['hybrid']);
		expect(getArchitectureStatus().map((row) => row.name)).toEqual(['keyword', 'hybrid']);
		expect(getArchitectureStatus().find((row) => row.name === 'hybrid')?.status).toBe('unverified');
		expect(getArchitectureStatus().find((row) => row.name === 'keyword')?.status).toBe(
			'registered'
		);
		expect(getStatus().provisioned_architectures).toEqual([]);
		updateUiSession({ provision_done: false });
		expect(getArchitectureStatus()).toEqual([]);
		expect(getStatus().provisioned_architectures).toEqual([]);
		updateUiSession({
			provision_done: true,
			active_job_id: 'job-1',
			active_job_kind: 'provision_index'
		});
		expect(getArchitectureStatus()).toEqual([]);
		expect(getStatus().provisioned_architectures).toEqual([]);
		updateUiSession({ active_job_id: '', active_job_kind: '' });
		expect(getSotaRecommendation().recommended_sota?.name).toBe('Legal & Contract Corpus');
		updateUiSession({ ingest_stats: { doc_count: 1, avg_doc_length: 1, cross_ref_density: 1000 } });
		expect(getSotaRecommendation()).toEqual({ recommended_sota: null, rationale: '' });
	});

	it('derives selected architecture names from SOTA, explicit selections, and config defaults', () => {
		expect(
			selectedArchitectureNames(
				{ selected_mode: 'sota', selected_sota_path: 'knowledge-base-faq' },
				getConfig()
			)
		).toEqual(['hybrid']);
		expect(
			selectedArchitectureNames(
				{ selected_mode: 'sota', selected_sota_path: 'missing' },
				getConfig()
			)
		).toEqual(['keyword', 'hybrid']);
		expect(
			selectedArchitectureNames({ selected_architectures: 'keyword, hybrid' } as never, getConfig())
		).toEqual(['keyword', 'hybrid']);
		expect(selectedArchitectureNames({ selected_architectures: ['keyword'] }, getConfig())).toEqual(
			['keyword']
		);
		expect(selectedArchitectureNames({}, getConfig())).toEqual(['keyword', 'hybrid']);
		updateUiSession({ selected_architectures: ['missing'] });
		expect(getArchitectureStatus()).toEqual([]);
	});

	it('builds compare context and flow-step payloads for all read steps', async () => {
		updateUiSession({ winners: ['hybrid'] });
		const compare = getCompareContext();
		expect(compare.runs).toHaveLength(1);
		expect(compare.categories[1].exact_term.ndcg_at_10).toBe(0.75);
		expect(compare.failures[1][0].expected_chunk_id).toBe('chunk-a');
		expect(compare.deployments[0].resource_group).toBe('rg-fixture');
		updateUiSession({ winners: ['keyword', 'missing'], selected_mode: '' });
		const compareWithFallbacks = getCompareContext();
		expect(compareWithFallbacks.deployments[0].resource_group).toBe('');
		expect(compareWithFallbacks.selected_mode).toBe('');

		for (const step of ['ingest', 'eval', 'configure', 'provision', 'run', 'compare', 'teardown']) {
			const payload = await loadFlowStep(step);
			expect(payload.step).toBe(step);
			expect(payload.currentEvalSetId).toBe(1);
		}
		await expect(loadFlowStep('not-real')).rejects.toMatchObject({ status: 404 });
	});

	it('resolves corpus output relative to configured corpus source', () => {
		const sourceDir = path.join(tempDir, 'source');
		const relativeCorpus = path.join(sourceDir, 'relative-corpus');
		mkdirSync(relativeCorpus, { recursive: true });
		writeFileSync(path.join(relativeCorpus, 'relative.md'), '# Relative', 'utf8');
		writeFileSync(
			path.join(tempDir, 'retrieve.yaml'),
			`
db_path: ${process.env.PRIVATE_RETRIEVE_DB_PATH?.replace(/\\/g, '\\\\')}
corpus:
  source: ${path.join(sourceDir, 'index.html').replace(/\\/g, '\\\\')}
  output_dir: relative-corpus
`
		);
		expect(getCorpusFiles().files).toEqual([{ name: 'relative.md', size: 10 }]);
		expect(getCorpusFiles('missing-dir')).toEqual({ output: 'missing-dir', files: [] });
	});

	it('forwards only the Easy Auth principal header', () => {
		const request = new Request('https://retrieve.example/flow', {
			headers: {
				'x-ms-client-principal': 'encoded-principal',
				'x-ms-token-aad-access-token': 'must-not-forward',
				cookie: 'must-not-forward'
			}
		});

		const headers = operationAuthHeaders(request);

		expect(headers.get('x-ms-client-principal')).toBe('encoded-principal');
		expect(headers.has('x-ms-token-aad-access-token')).toBe(false);
		expect(headers.has('cookie')).toBe(false);
	});

	it('adds identity and a stable idempotency key to job admission', async () => {
		const fetchMock = vi.fn().mockResolvedValue(
			new Response(JSON.stringify({ job_id: 'job-1', kind: 'index', operation_id: 'job-1' }), {
				status: 200,
				headers: { 'content-type': 'application/json' }
			})
		);
		vi.stubGlobal('fetch', fetchMock);
		const headers = new Headers({ 'x-ms-client-principal': 'encoded-principal' });

		await startJob('index', { architectures: ['hybrid'] }, headers, 'index-request-001');

		const [target, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
		const sentHeaders = new Headers(init.headers);
		expect(target.pathname).toBe('/api/ui/job/start');
		expect(sentHeaders.get('x-ms-client-principal')).toBe('encoded-principal');
		expect(sentHeaders.get('Idempotency-Key')).toBe('index-request-001');
		expect(JSON.parse(String(init.body))).toEqual({
			kind: 'index',
			args: { architectures: ['hybrid'] }
		});
	});

	it('routes UI-session mutation through the operation API', async () => {
		const fetchMock = vi.fn().mockResolvedValue(
			new Response(JSON.stringify({ status: 'ok', session: { selected_mode: 'test' } }), {
				status: 200,
				headers: { 'content-type': 'application/json' }
			})
		);
		vi.stubGlobal('fetch', fetchMock);

		await updateOperationUiSession(
			{ selected_mode: 'test' },
			{ 'x-ms-client-principal': 'encoded-principal' }
		);

		const [target, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
		expect(target.pathname).toBe('/api/ui/session');
		expect(new Headers(init.headers).get('x-ms-client-principal')).toBe('encoded-principal');
	});
});

function restoreEnv(key: string, value: string | undefined) {
	if (value === undefined) delete process.env[key];
	else process.env[key] = value;
}

function seedDatabase(dbPath: string) {
	const db = new DatabaseSync(dbPath);
	db.exec(`
CREATE TABLE eval_sets (
  id INTEGER PRIMARY KEY,
  version_label TEXT,
  notes TEXT,
  question_count INTEGER,
  category_counts TEXT,
  created_at TEXT
);
CREATE TABLE eval_questions (
  id INTEGER PRIMARY KEY,
  eval_set_id INTEGER,
  question_text TEXT,
  category TEXT,
  question_type TEXT,
  persona TEXT,
  intent_family TEXT,
  ground_truth_chunk_ids TEXT,
  metadata TEXT,
  source_doc_id TEXT
);
CREATE TABLE runs (
  id INTEGER PRIMARY KEY,
  eval_set_id INTEGER,
  architecture_id INTEGER,
  architecture_name TEXT,
  mode TEXT,
  architecture_config TEXT,
  created_at TEXT,
  completed_at TEXT,
  status TEXT,
  aggregate_metrics TEXT
);
CREATE TABLE run_results (
  id INTEGER PRIMARY KEY,
  run_id INTEGER,
  question_id INTEGER,
  retrieved_chunk_ids TEXT,
  scores TEXT,
  latency_ms REAL,
  failure_type TEXT,
  failure_details TEXT
);
CREATE TABLE architectures (
  id INTEGER PRIMARY KEY,
  name TEXT,
  config TEXT,
  resources_provisioned TEXT,
  status TEXT,
  created_at TEXT
);
CREATE TABLE generation_preferences (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope_key TEXT NOT NULL UNIQUE,
  preferences TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
`);
	db.prepare('INSERT INTO eval_sets VALUES (?, ?, ?, ?, ?, ?)').run(
		1,
		'v-fixture',
		'fixture',
		1,
		'{"exact_term":1}',
		'2026-01-01'
	);
	db.prepare('INSERT INTO eval_questions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)').run(
		1,
		1,
		'What is the policy?',
		'exact_term',
		'lookup',
		'worker',
		'policy',
		'["chunk-a"]',
		'{}',
		'doc-a'
	);
	db.prepare('INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)').run(
		1,
		1,
		1,
		'hybrid',
		'test',
		'{"_variant_of":"hybrid","index_name":"idx","experiment_id":"fixture-experiment","corpus_fingerprint":"fixture-corpus"}',
		'2026-01-01',
		'2026-01-01',
		'completed',
		'{"ndcg_at_10":0.75,"recall_at_10":1,"avg_latency_ms":12,"miss_count":1}'
	);
	db.prepare('INSERT INTO run_results VALUES (?, ?, ?, ?, ?, ?, ?, ?)').run(
		1,
		1,
		1,
		'["chunk-b"]',
		'{"ndcg_at_10":0.75,"recall_at_10":1}',
		12,
		'missed_chunk',
		'Expected chunk not retrieved'
	);
	db.prepare('INSERT INTO architectures VALUES (?, ?, ?, ?, ?, ?)').run(
		1,
		'hybrid',
		'{"index_name":"idx"}',
		'{"search_endpoint":"https://search.example","resource_group":"rg-fixture","location":"eastus2"}',
		'active',
		'2026-01-01'
	);
	db.prepare('INSERT INTO architectures VALUES (?, ?, ?, ?, ?, ?)').run(
		2,
		'keyword',
		'{"index_name":"keyword-index"}',
		'{"endpoint":"https://keyword.example"}',
		'registered',
		'2026-01-01'
	);
	db.prepare(
		'INSERT INTO generation_preferences (scope_key, preferences, updated_at) VALUES (?, ?, ?)'
	).run(
		'ui_session',
		JSON.stringify({
			selected_mode: 'test',
			selected_architectures: ['keyword', 'hybrid'],
			active_experiment_id: 'fixture-experiment',
			active_experiment_eval_set_id: 1,
			active_experiment_eval_set_version: 'v-fixture',
			active_experiment_corpus_fingerprint: 'fixture-corpus',
			active_experiment_architectures: ['hybrid'],
			provision_done: true,
			ingest_stats: { doc_count: 500, avg_doc_length: 6000, cross_ref_density: 3 }
		}),
		new Date().toISOString()
	);
	db.close();
}
