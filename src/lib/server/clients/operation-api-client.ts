import { env } from '$env/dynamic/private';
import { error, isHttpError } from '@sveltejs/kit';
import type {
	CsvExportResponse,
	CsvImportResponse,
	CurateEvalResponse,
	JobKind,
	JobStartResponse,
	JobStatus,
	UiSession
} from '$lib/api/types';

const fallbackBaseUrl = 'http://127.0.0.1:8000';
const timeoutMs = 30_000;
const forwardedIdentityHeaders = ['x-ms-client-principal'] as const;

function configuredBaseUrl() {
	return process.env.PRIVATE_RETRIEVE_API_BASE || env.PRIVATE_RETRIEVE_API_BASE || '';
}

function apiBaseUrl() {
	return configuredBaseUrl() || fallbackBaseUrl;
}

export function operationApiConfigured() {
	return Boolean(configuredBaseUrl());
}

export function operationAuthHeaders(request: Request): Headers {
	const headers = new Headers();
	for (const name of forwardedIdentityHeaders) {
		const value = request.headers.get(name);
		if (value) headers.set(name, value);
	}
	return headers;
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
	const controller = new AbortController();
	const timeout = setTimeout(() => controller.abort(), timeoutMs);
	const headers = new Headers(init.headers);
	if (init.body && !headers.has('content-type')) headers.set('content-type', 'application/json');

	try {
		const response = await fetch(new URL(path, apiBaseUrl()), {
			...init,
			headers,
			signal: controller.signal
		});

		if (!response.ok) {
			error(response.status, (await response.text()) || `Retrieve API returned ${response.status}`);
		}

		return (await response.json()) as T;
	} catch (unknownError) {
		if (isHttpError(unknownError)) throw unknownError;
		const message =
			unknownError instanceof Error ? unknownError.message : 'Retrieve API is unavailable';
		error(503, message);
	} finally {
		clearTimeout(timeout);
	}
}

export function getOperationJson<T>(path: string) {
	return requestJson<T>(path);
}

function postJson<T>(path: string, body: Record<string, unknown>, headers: HeadersInit = {}) {
	return requestJson<T>(path, { method: 'POST', body: JSON.stringify(body), headers });
}

export function exportEvalCsv(eval_set: string, output: string, headers: HeadersInit = {}) {
	return postJson<CsvExportResponse>('/api/eval/export-csv', { eval_set, output }, headers);
}

export function importEvalCsv(
	input: string,
	version: string,
	base_eval_set: string,
	fresh: boolean,
	headers: HeadersInit = {}
) {
	return postJson<CsvImportResponse>(
		'/api/eval/import-csv',
		{
			input,
			version,
			base_eval_set,
			fresh
		},
		headers
	);
}

export function curateEvalSet(
	payload: {
		source_version: string;
		new_version: string;
		corpus: string;
		steering: Record<string, unknown>;
	},
	headers: HeadersInit = {}
) {
	return postJson<CurateEvalResponse>('/api/eval/curate', payload, headers);
}

export function startJob(
	kind: JobKind | string,
	args: Record<string, unknown> = {},
	headers: HeadersInit = {},
	idempotencyKey: string = crypto.randomUUID()
) {
	const requestHeaders = new Headers(headers);
	requestHeaders.set('Idempotency-Key', idempotencyKey);
	return postJson<JobStartResponse>('/api/ui/job/start', { kind, args }, requestHeaders);
}

export function getJobStatus(id: string) {
	return requestJson<JobStatus>(`/api/ui/job/${id}/status`);
}

export function updateOperationUiSession(session: Partial<UiSession>, headers: HeadersInit = {}) {
	return postJson<{ status: string; session: UiSession }>(
		'/api/ui/session',
		session as Record<string, unknown>,
		headers
	);
}
