import { expect, test, type Page } from '@playwright/test';
import { FlowAudit } from './playwright/audit';

type RouteTarget = {
	path: string;
	name: string;
	heading: string | RegExp;
};

async function expectCleanPage(
	page: Page,
	target: RouteTarget,
	audit: FlowAudit,
	testInfo: Parameters<FlowAudit['screenshot']>[1]
) {
	const consoleErrors: string[] = [];
	page.on('console', (message) => {
		if (message.type() === 'error') consoleErrors.push(message.text());
	});

	const response = await page.goto(target.path);
	audit.record('visual-goto', { path: target.path, status: response?.status() });
	expect(response?.ok(), `${target.path} returned ${response?.status()}`).toBe(true);
	await page.waitForLoadState('networkidle');
	await expect(page.getByRole('heading', { level: 1, name: target.heading })).toBeVisible();
	await audit.screenshot(page, testInfo, target.name);
	expect(consoleErrors, `${target.path} console errors`).toEqual([]);
}

test('visual audit screenshots cover every real-data page', async ({ page, request }, testInfo) => {
	const audit = new FlowAudit(testInfo);
	const routes: RouteTarget[] = [
		{ path: '/', name: 'visual-01-dashboard', heading: 'Retrieve' },
		{ path: '/flow/ingest', name: 'visual-02-flow-ingest', heading: 'Ingest' },
		{ path: '/flow/eval', name: 'visual-03-flow-eval', heading: 'Golden Eval Set' },
		{ path: '/flow/configure', name: 'visual-04-flow-configure', heading: 'Configure' },
		{ path: '/flow/provision', name: 'visual-05-flow-provision', heading: 'Provision & Index' },
		{ path: '/flow/run', name: 'visual-06-flow-run', heading: 'Run Tests' },
		{ path: '/flow/compare', name: 'visual-07-flow-compare', heading: 'Evaluate and Select' },
		{ path: '/flow/teardown', name: 'visual-08-flow-teardown', heading: 'Teardown' },
		{ path: '/runs', name: 'visual-09-runs', heading: 'Run Analysis' },
		{ path: '/eval-sets', name: 'visual-10-eval-sets', heading: 'Golden Eval Sets' },
		{ path: '/pricing', name: 'visual-11-pricing', heading: 'Pricing' },
		{ path: '/settings', name: 'visual-12-settings', heading: 'Settings' }
	];

	const runs = (await (await request.get('/api/runs')).json()) as Array<{
		id: number;
		architecture_name: string;
	}>;
	if (runs[0]) {
		routes.push({
			path: `/runs/${runs[0].id}`,
			name: 'visual-13-run-detail',
			heading: runs[0].architecture_name
		});
	}

	const evalSets = (await (await request.get('/api/eval-sets')).json()) as Array<{
		id: number;
		version_label: string;
	}>;
	if (evalSets[0]) {
		routes.push({
			path: `/eval-sets/${evalSets[0].id}`,
			name: 'visual-14-eval-set-detail',
			heading: evalSets[0].version_label
		});
	}

	for (const route of routes) {
		await expectCleanPage(page, route, audit, testInfo);
	}
});
