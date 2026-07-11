import { env } from '$env/dynamic/private';
import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import {
	browseEvalQuestions,
	getArchitectureStatus,
	getArchitectures,
	getCompareContext,
	getConfig,
	getCorpusFiles,
	getEvalSets,
	getEvalSummary,
	getFoundryCatalogEmbeddings,
	getFoundryDeployedEmbeddings,
	getModels,
	getRun,
	getRuns,
	getSotaPaths,
	getSotaRecommendation,
	getStatus,
	getUiSession
} from '$lib/server/retrieve-api';

type LocalReadHandler = (url: URL) => Promise<unknown> | unknown;
type DynamicReadRoute = {
	pattern: RegExp;
	handle: (match: RegExpExecArray, url: URL) => Promise<unknown> | unknown;
};

const hopByHopHeaders = new Set([
	'connection',
	'keep-alive',
	'proxy-authenticate',
	'proxy-authorization',
	'te',
	'trailer',
	'transfer-encoding',
	'upgrade'
]);

const localGetRoutes: Record<string, LocalReadHandler> = {
	status: getStatus,
	config: getConfig,
	'architecture-status': getArchitectureStatus,
	'corpus-files': (url) => getCorpusFiles(url.searchParams.get('output') ?? undefined),
	'sota-recommendation': getSotaRecommendation,
	'compare-context': getCompareContext,
	architectures: getArchitectures,
	models: getModels,
	'sota-paths': getSotaPaths,
	runs: getRuns,
	'eval-sets': getEvalSets,
	'ui/session': getUiSession,
	'foundry/embeddings/deployed': (url) =>
		getFoundryDeployedEmbeddings(
			url.searchParams.get('resource_group') ?? '',
			url.searchParams.get('workspace_name') ?? ''
		),
	'foundry/embeddings/catalog': (url) =>
		getFoundryCatalogEmbeddings(url.searchParams.get('query') ?? '')
};

const dynamicGetRoutes: DynamicReadRoute[] = [
	{
		pattern: /^runs\/([^/]+)$/,
		handle: ([, runId]) => getRun(runId)
	},
	{
		pattern: /^eval-sets\/(\d+)\/summary$/,
		handle: ([, evalSetId]) => getEvalSummary(Number(evalSetId))
	},
	{
		pattern: /^eval-sets\/(\d+)\/questions\/browse$/,
		handle: ([, evalSetId], url) => {
			const filters: Record<string, string | number | undefined> = {};
			for (const key of ['category', 'question_type', 'persona', 'intent_family']) {
				filters[key] = url.searchParams.get(key) ?? undefined;
			}
			const limit = url.searchParams.get('limit');
			const offset = url.searchParams.get('offset');
			if (limit) filters.limit = Number(limit);
			if (offset) filters.offset = Number(offset);
			return browseEvalQuestions(Number(evalSetId), filters);
		}
	}
];

function backendBase() {
	return env.PRIVATE_RETRIEVE_API_BASE ?? 'http://127.0.0.1:8000';
}

function responseHeaders(headers: Headers) {
	const next = new Headers(headers);
	for (const header of hopByHopHeaders) next.delete(header);
	return next;
}

async function localReadResponse(pathname: string, url: URL): Promise<Response | null> {
	const staticHandler = localGetRoutes[pathname];
	if (staticHandler) return json(await staticHandler(url));

	for (const route of dynamicGetRoutes) {
		const match = route.pattern.exec(pathname);
		if (match) return json(await route.handle(match, url));
	}

	return null;
}

async function proxyToOperationBackend(request: Request, pathname: string, url: URL) {
	const target = new URL(`/api/${pathname}${url.search}`, backendBase());
	const headers = new Headers(request.headers);
	headers.delete('host');

	const init: RequestInit & { duplex?: 'half' } = {
		method: request.method,
		headers,
		body: request.method === 'GET' || request.method === 'HEAD' ? undefined : request.body,
		duplex: 'half'
	};

	try {
		const response = await fetch(target, init);
		return new Response(response.body, {
			status: response.status,
			statusText: response.statusText,
			headers: responseHeaders(response.headers)
		});
	} catch (unknownError) {
		const message =
			unknownError instanceof Error ? unknownError.message : 'Retrieve API is unavailable';
		error(503, message);
	}
}

const handler: RequestHandler = async ({ request, params, url }) => {
	if (request.method === 'GET' || request.method === 'HEAD') {
		const response = await localReadResponse(params.path, url);
		if (response) return response;
	}

	return proxyToOperationBackend(request, params.path, url);
};

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const PATCH = handler;
export const DELETE = handler;
