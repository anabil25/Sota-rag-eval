import { spawn } from 'node:child_process';
import {
	copyFileSync,
	cpSync,
	existsSync,
	mkdtempSync,
	readFileSync,
	rmSync,
	writeFileSync
} from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repoRoot = path.dirname(path.dirname(path.dirname(fileURLToPath(import.meta.url))));
const port = Number(process.env.RETRIEVE_LIVE_PORT ?? 8017);
const baseUrl = `http://127.0.0.1:${port}`;
const tempRoot = mkdtempSync(path.join(tmpdir(), 'retrieve-live-eval-'));
const version = `v-live-sample-${Date.now()}`;
let backend;

function log(message) {
	console.log(`[live-eval] ${message}`);
}

function copyWorkspace() {
	copyFileSync(path.join(repoRoot, 'retrieve.db'), path.join(tempRoot, 'retrieve.db'));
	cpSync(path.join(repoRoot, 'corpus'), path.join(tempRoot, 'corpus'), { recursive: true });
	const sourceConfig = existsSync(path.join(repoRoot, 'retrieve.yaml'))
		? readFileSync(path.join(repoRoot, 'retrieve.yaml'), 'utf8')
		: '';
	const config = `${sourceConfig.trim()}\n\ndb_path: retrieve.db\neval:\n  mode: sample\n`;
	writeFileSync(path.join(tempRoot, 'retrieve.yaml'), config, 'utf8');
}

async function waitForHealth() {
	const deadline = Date.now() + 45_000;
	let lastError;
	while (Date.now() < deadline) {
		try {
			const response = await fetch(`${baseUrl}/api/status`);
			if (response.ok) return;
			lastError = new Error(`status ${response.status}`);
		} catch (error) {
			lastError = error;
		}
		await new Promise((resolve) => setTimeout(resolve, 500));
	}
	throw lastError ?? new Error('Backend did not become healthy');
}

async function waitForJob(jobId) {
	const deadline = Date.now() + Number(process.env.RETRIEVE_LIVE_TIMEOUT_MS ?? 300_000);
	while (Date.now() < deadline) {
		const response = await fetch(`${baseUrl}/api/ui/job/${jobId}/status`);
		if (!response.ok)
			throw new Error(`Job status failed: ${response.status} ${await response.text()}`);
		const status = await response.json();
		if (status.done) {
			if (status.error) throw new Error(`Job failed: ${status.error}`);
			return status;
		}
		await new Promise((resolve) => setTimeout(resolve, 1500));
	}
	throw new Error(`Timed out waiting for job ${jobId}`);
}

async function startSampleEvalJob() {
	const response = await fetch(`${baseUrl}/api/ui/job/start`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({
			kind: 'eval_generate',
			args: {
				mode: 'sample',
				corpus: 'corpus',
				version,
				base_eval_set: 'latest',
				fresh: false,
				operator_context:
					'Live smoke test: generate a small sample eval set from the existing corpus.'
			}
		})
	});
	if (!response.ok)
		throw new Error(`Start job failed: ${response.status} ${await response.text()}`);
	return response.json();
}

function assertGeneratedEvalSet(evalSetId) {
	const db = new DatabaseSync(path.join(tempRoot, 'retrieve.db'));
	try {
		const evalSet = db.prepare('SELECT * FROM eval_sets WHERE id = ?').get(evalSetId);
		if (!evalSet) throw new Error(`Eval set ${evalSetId} not found`);
		if (evalSet.version_label !== version) {
			throw new Error(`Expected version ${version}, got ${evalSet.version_label}`);
		}
		const count = db
			.prepare('SELECT COUNT(*) AS count FROM eval_questions WHERE eval_set_id = ?')
			.get(evalSetId).count;
		if (Number(count) <= 0) throw new Error(`Generated eval set ${evalSetId} has no questions`);
		log(`Generated ${count} sample questions in eval set ${evalSetId} (${version})`);
	} finally {
		db.close();
	}
}

async function main() {
	copyWorkspace();
	log(`Temp workspace: ${tempRoot}`);
	backend = spawn(
		process.platform === 'win32' ? 'python.exe' : 'python',
		[
			'-m',
			'uvicorn',
			'retrieve.web.app:create_app',
			'--factory',
			'--host',
			'127.0.0.1',
			'--port',
			String(port)
		],
		{
			cwd: tempRoot,
			stdio: ['ignore', 'pipe', 'pipe'],
			env: { ...process.env, PYTHONUNBUFFERED: '1' }
		}
	);
	backend.stdout.on('data', (chunk) => process.stdout.write(`[backend] ${chunk}`));
	backend.stderr.on('data', (chunk) => process.stderr.write(`[backend] ${chunk}`));
	await waitForHealth();
	log('Backend healthy');
	const started = await startSampleEvalJob();
	log(`Started job ${started.job_id}`);
	const status = await waitForJob(started.job_id);
	const evalSetId = status.result?.eval_set_id;
	if (!evalSetId) throw new Error(`Job completed without eval_set_id: ${JSON.stringify(status)}`);
	assertGeneratedEvalSet(evalSetId);
}

async function stopBackend() {
	if (!backend || backend.exitCode !== null) return;
	await new Promise((resolve) => {
		backend.once('exit', resolve);
		backend.kill();
		setTimeout(resolve, 5000);
	});
}

async function removeWorkspace() {
	for (let attempt = 0; attempt < 5; attempt += 1) {
		try {
			rmSync(tempRoot, { recursive: true, force: true });
			return;
		} catch (error) {
			if (attempt === 4) throw error;
			await new Promise((resolve) => setTimeout(resolve, 750));
		}
	}
}

main()
	.finally(async () => {
		await stopBackend();
		if (process.env.RETRIEVE_KEEP_LIVE_WORKSPACE !== '1') {
			await removeWorkspace();
		} else {
			log(`Preserved temp workspace: ${tempRoot}`);
		}
	})
	.catch((error) => {
		console.error(error);
		process.exitCode = 1;
	});
