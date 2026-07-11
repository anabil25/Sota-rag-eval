import { expect, test } from '@playwright/test';
import { FlowAudit } from './playwright/audit';

test.describe.configure({ mode: 'serial' });

test('read-only flow inventory uses real SvelteKit data surfaces', async ({ page }, testInfo) => {
	const audit = new FlowAudit(testInfo);
	const workflow = [
		['/flow/ingest', 'Ingest'],
		['/flow/eval', 'Golden Eval Set'],
		['/flow/configure', 'Configure'],
		['/flow/provision', 'Provision & Index'],
		['/flow/run', 'Run Tests'],
		['/flow/compare', 'Evaluate and Select'],
		['/flow/teardown', 'Teardown']
	] as const;

	await audit.goto(page, '/');
	await expect(page.getByRole('heading', { level: 1, name: 'Retrieve' })).toBeVisible();
	await audit.screenshot(page, testInfo, '01-dashboard');

	for (const [path, heading] of workflow) {
		await audit.goto(page, path);
		await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible();
	}

	await audit.goto(page, '/settings');
	await expect(page.getByRole('heading', { level: 1, name: 'Settings' })).toBeVisible();
	await expect(page.getByRole('heading', { level: 2, name: 'Workflow defaults' })).toBeVisible();

	await audit.goto(page, '/pricing');
	await expect(page.getByRole('heading', { level: 1, name: 'Pricing' })).toBeVisible();

	const response = await page.goto('/flow/not-a-step');
	audit.record('boundary-response', { path: '/flow/not-a-step', status: response?.status() });
	expect(response?.status()).toBe(404);
});

test('configure interactions update local component state without submitting operations', async ({
	page
}, testInfo) => {
	const audit = new FlowAudit(testInfo);
	await audit.goto(page, '/flow/configure');

	await expect(page.getByText('Build candidates to measure')).toBeVisible();
	await audit.click(page.getByRole('button', { name: /Cross-paradigm/ }), 'select cross-paradigm');
	await expect(
		page.locator('input[name="selected_architectures"][value="graphrag"]')
	).toBeChecked();
	await expect(
		page.locator('input[name="selected_architectures"][value="lightrag"]')
	).toBeChecked();

	const embeddingSelect = page.getByLabel('Embedding model');
	if (await embeddingSelect.isVisible()) {
		await audit.select(embeddingSelect, 'text-embedding-3-large', 'embedding model');
	}

	await audit.screenshot(page, testInfo, '02-configure-real-data');
});

test('local form actions persist session state without the Python backend', async ({
	page,
	request
}, testInfo) => {
	const audit = new FlowAudit(testInfo);
	await audit.goto(page, '/flow/eval');
	const generateForm = page.locator('form').filter({ hasText: 'Generate Eval Set' });
	await audit.fill(
		generateForm.getByLabel('Operator context'),
		'Real-data E2E operator context.',
		'eval operator context'
	);
	await audit.fill(
		generateForm.getByPlaceholder(/more cross-doc/),
		'more cross-document sample questions',
		'steering note'
	);
	await audit.click(generateForm.getByRole('button', { name: 'Add' }), 'append steering note');
	await audit.click(generateForm.getByRole('button', { name: 'Save Steering' }), 'save steering');
	await expect(page.getByRole('status')).toContainText('Draft saved');

	await audit.goto(page, '/flow/configure');
	await audit.click(page.getByRole('button', { name: /Quick baseline/ }), 'select quick baseline');
	await audit.click(page.getByRole('button', { name: 'Save & Continue' }), 'save configure');
	await page.waitForURL('**/flow/provision');
	await expect(page.getByRole('heading', { level: 1, name: 'Provision & Index' })).toBeVisible();

	await audit.goto(page, '/flow/compare');
	const firstWinner = page.locator('input[name="winners"]').first();
	if ((await firstWinner.count()) > 0) {
		await firstWinner.check();
		await audit.click(page.getByRole('button', { name: /Continue to Teardown/ }), 'save winners');
		await page.waitForURL('**/flow/teardown');
		await expect(page.getByRole('heading', { level: 1, name: 'Teardown' })).toBeVisible();
	}

	await audit.goto(page, '/settings');
	await audit.fill(
		page.getByLabel('Context'),
		'Real-data E2E settings context.',
		'settings context'
	);
	await audit.click(page.getByRole('button', { name: 'Save Settings' }), 'save settings');
	await expect(page.getByRole('status')).toContainText('Settings saved');

	const session = await (await request.get('/api/ui/session')).json();
	expect(session.operator_context).toContain('Real-data E2E settings context.');
});

test('review routes expose real run and eval detail pages', async ({ page, request }, testInfo) => {
	const audit = new FlowAudit(testInfo);
	const runs = (await (await request.get('/api/runs')).json()) as Array<{
		id: number;
		architecture_name: string;
	}>;
	const evalSets = (await (await request.get('/api/eval-sets')).json()) as Array<{
		id: number;
		version_label: string;
	}>;

	await audit.goto(page, '/runs');
	await expect(page.getByRole('heading', { level: 1, name: 'Run Analysis' })).toBeVisible();
	if (runs[0]) {
		await audit.goto(page, `/runs/${runs[0].id}`);
		await expect(
			page.getByRole('heading', { level: 1, name: runs[0].architecture_name })
		).toBeVisible();
		await expect(page.getByText('Category Scores')).toBeVisible();
	}

	await audit.goto(page, '/eval-sets');
	await expect(page.getByRole('heading', { level: 1, name: 'Golden Eval Sets' })).toBeVisible();
	if (evalSets[0]) {
		await audit.goto(page, `/eval-sets/${evalSets[0].id}`);
		await expect(
			page.getByRole('heading', { level: 1, name: evalSets[0].version_label })
		).toBeVisible();
		await expect(page.getByText('Question Browser')).toBeVisible();
	}

	await audit.screenshot(page, testInfo, '03-review-real-data');
});
