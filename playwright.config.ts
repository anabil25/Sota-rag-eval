import { defineConfig } from '@playwright/test';

export default defineConfig({
	workers: 1,
	retries: 0,
	outputDir: 'test-results/playwright',
	reporter: [
		['list'],
		['html', { outputFolder: 'test-results/playwright-report', open: 'never' }],
		['json', { outputFile: 'test-results/playwright-results.json' }]
	],
	use: {
		baseURL: 'http://127.0.0.1:4173',
		trace: 'retain-on-failure',
		screenshot: 'only-on-failure',
		video: 'retain-on-failure'
	},
	webServer: {
		command:
			'node tests/playwright/prepare-real-fixture.mjs && npm run build && npm run preview -- --host 127.0.0.1 --port 4173',
		env: {
			PRIVATE_RETRIEVE_DB_PATH: 'test-results/real-fixture/retrieve.db'
		},
		port: 4173
	},
	testMatch: '**/*.e2e.{ts,js}'
});
