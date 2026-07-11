import type { Locator, Page, TestInfo } from '@playwright/test';
import { mkdirSync, appendFileSync } from 'node:fs';
import { join } from 'node:path';

export class FlowAudit {
	private readonly logPath: string;
	private sequence = 0;

	constructor(testInfo: TestInfo) {
		const auditDir = join(testInfo.project.outputDir, '..', 'audit');
		mkdirSync(auditDir, { recursive: true });
		this.logPath = join(auditDir, 'ui-flow-audit.jsonl');
		this.record('test-start', { title: testInfo.title, file: testInfo.file });
	}

	record(action: string, details: Record<string, unknown> = {}) {
		appendFileSync(
			this.logPath,
			`${JSON.stringify({
				timestamp: new Date().toISOString(),
				sequence: ++this.sequence,
				action,
				...details
			})}\n`,
			'utf8'
		);
	}

	async goto(page: Page, path: string) {
		this.record('goto', { path });
		await page.goto(path);
		await page.waitForLoadState('networkidle');
		this.record('goto-complete', { path, url: page.url() });
	}

	async fill(locator: Locator, value: string, label: string) {
		this.record('fill', { label, value });
		await locator.fill(value);
	}

	async select(locator: Locator, value: string, label: string) {
		this.record('select', { label, value });
		await locator.selectOption(value);
	}

	async check(locator: Locator, label: string) {
		this.record('check', { label });
		await locator.check();
	}

	async uncheck(locator: Locator, label: string) {
		this.record('uncheck', { label });
		await locator.uncheck();
	}

	async click(locator: Locator, label: string) {
		this.record('click', { label });
		await locator.click();
	}

	async screenshot(page: Page, testInfo: TestInfo, name: string) {
		const path = testInfo.outputPath(`${name}.png`);
		await page.screenshot({ path, fullPage: true });
		this.record('screenshot', { name, path });
	}
}
