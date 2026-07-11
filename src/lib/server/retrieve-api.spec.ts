import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	getArchitectureStatus,
	getConfig,
	getCorpusFiles,
	getFoundryCatalogEmbeddings,
	getFoundryDeployedEmbeddings,
	getRuns,
	getSotaRecommendation,
	getStatus,
	getUiSession
} from './retrieve-api';

const originalApiBase = process.env.PRIVATE_RETRIEVE_API_BASE;

afterEach(() => {
	vi.unstubAllGlobals();
	if (originalApiBase === undefined) delete process.env.PRIVATE_RETRIEVE_API_BASE;
	else process.env.PRIVATE_RETRIEVE_API_BASE = originalApiBase;
});

describe('retrieve-api local read surfaces', () => {
	it('builds status from local db/config without the Python backend', async () => {
		const status = await getStatus();
		expect(status.eval_set).not.toBeNull();
		expect(status.run_count).toBeGreaterThanOrEqual(0);
		expect(status.architectures.length).toBeGreaterThan(0);
	});

	it('loads retrieve.yaml with Python-compatible defaults', async () => {
		const config = await getConfig();
		expect(config.db_path).toBe('retrieve.db');
		expect(config.azure.location).toBeTruthy();
		expect(config.corpus.output_dir).toBe('corpus');
		expect(config.eval.categories.length).toBeGreaterThan(0);
	});

	it('normalizes the persisted UI session architecture selection', async () => {
		const session = await getUiSession();
		expect(Array.isArray(session.selected_architectures ?? [])).toBe(true);
	});

	it('returns current architecture status rows when a provision cycle has state', async () => {
		const rows = await getArchitectureStatus();
		expect(Array.isArray(rows)).toBe(true);
		for (const row of rows) {
			expect(row.name).toBeTruthy();
			expect(row.status).toBeTruthy();
		}
	});

	it('reads corpus files from the real filesystem path', async () => {
		const corpus = await getCorpusFiles('corpus');
		expect(corpus.output).toBe('corpus');
		expect(Array.isArray(corpus.files)).toBe(true);
		for (const file of corpus.files.slice(0, 3)) {
			expect(file.name.endsWith('.md')).toBe(true);
			expect(file.size).toBeGreaterThan(0);
		}
	});

	it('computes SOTA recommendation from persisted ingest stats', async () => {
		const recommendation = await getSotaRecommendation();
		expect(recommendation).toHaveProperty('recommended_sota');
		expect(recommendation).toHaveProperty('rationale');
	});

	it('keeps Foundry reads local and empty while Foundry is disabled', async () => {
		await expect(getFoundryCatalogEmbeddings('embedding')).resolves.toEqual({
			items: [],
			errors: []
		});
		await expect(getFoundryDeployedEmbeddings('rg', 'ws')).resolves.toEqual({
			items: [],
			errors: []
		});
	});
});

describe('retrieve-api deployed read surfaces', () => {
	it('routes server reads through the configured operation API', async () => {
		process.env.PRIVATE_RETRIEVE_API_BASE = 'https://api.example.test';
		const payloads = new Map<string, unknown>([
			[
				'/api/status',
				{ eval_set: null, run_count: 2, architectures: ['hybrid'], provisioned_architectures: [] }
			],
			['/api/runs', []],
			['/api/ui/session', { selected_architectures: ['hybrid'] }]
		]);
		const fetchMock = vi.fn(async (input: URL | RequestInfo) => {
			const url = new URL(String(input));
			return new Response(JSON.stringify(payloads.get(url.pathname)), {
				status: 200,
				headers: { 'content-type': 'application/json' }
			});
		});
		vi.stubGlobal('fetch', fetchMock);

		const [status, runs, session] = await Promise.all([getStatus(), getRuns(), getUiSession()]);

		expect(status.run_count).toBe(2);
		expect(runs).toEqual([]);
		expect(session.selected_architectures).toEqual(['hybrid']);
		expect(fetchMock).toHaveBeenCalledTimes(3);
		for (const [input] of fetchMock.mock.calls) {
			expect(String(input)).toMatch(/^https:\/\/api\.example\.test\/api\//);
		}
	});
});
