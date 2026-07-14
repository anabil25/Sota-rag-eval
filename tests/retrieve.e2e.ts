import { expect, test } from '@playwright/test';

test('dashboard, workflow, runs, and eval sets render from real local data', async ({
	page,
	request
}) => {
	await page.goto('/');
	await expect(page.getByRole('heading', { level: 1, name: 'Retrieve' })).toBeVisible();
	await expect(page.getByRole('link', { name: /Continue:|Review outcome/ }).first()).toBeVisible();

	const workflow = [
		['/flow/ingest', 'Ingest'],
		['/flow/eval', 'Golden Eval Set'],
		['/flow/configure', 'Configure'],
		['/flow/provision', 'Provision & Index'],
		['/flow/run', 'Run Tests'],
		['/flow/compare', 'Evaluate and Select'],
		['/flow/teardown', 'Teardown']
	] as const;

	for (const [path, heading] of workflow) {
		await page.goto(path);
		await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible();
		if (path === '/flow/provision') {
			await expect(
				page.getByRole('heading', { level: 2, name: 'Deployed Architectures' })
			).toBeVisible();
			await expect(page.getByText('No architectures are currently deployed.')).toBeVisible();
		}
	}

	const runs = (await (await request.get('/api/runs')).json()) as Array<{
		id: number;
		architecture_name: string;
	}>;
	await page.goto('/runs');
	await expect(page.getByRole('heading', { level: 1, name: 'Run Analysis' })).toBeVisible();
	if (runs[0]) {
		await page.goto(`/runs/${runs[0].id}`);
		await expect(
			page.getByRole('heading', { level: 1, name: runs[0].architecture_name })
		).toBeVisible();
	}

	const evalSets = (await (await request.get('/api/eval-sets')).json()) as Array<{
		id: number;
		version_label: string;
	}>;
	await page.goto('/eval-sets');
	await expect(page.getByRole('heading', { level: 1, name: 'Golden Eval Sets' })).toBeVisible();
	if (evalSets[0]) {
		await page.goto(`/eval-sets/${evalSets[0].id}`);
		await expect(
			page.getByRole('heading', { level: 1, name: evalSets[0].version_label })
		).toBeVisible();
	}
});

test('local read APIs respond without the Python operation backend', async ({ request }) => {
	for (const path of [
		'/api/status',
		'/api/config',
		'/api/runs',
		'/api/eval-sets',
		'/api/ui/session',
		'/api/corpus-files?output=corpus',
		'/api/architecture-status',
		'/api/foundry/embeddings/catalog?query=embedding'
	]) {
		const response = await request.get(path);
		expect(response.ok(), path).toBe(true);
	}
});
