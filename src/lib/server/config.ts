import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import type { RetrieveConfigSummary } from '$lib/api/types';

type Jsonish = Record<string, unknown> | unknown[];

const DEFAULT_EVAL_CATEGORIES = [
	'factual_lookup',
	'procedural',
	'cross_document',
	'cross_policy',
	'edge_case',
	'negation',
	'colloquial_mapping',
	'calculation',
	'unanswerable'
];

export function defaultConfig(): RetrieveConfigSummary {
	return {
		db_path: 'retrieve.db',
		log_level: 'INFO',
		azure_sdk_logging: false,
		architectures: ['hybrid'],
		corpus: {
			source: '',
			plugin: 'html',
			output_dir: 'corpus'
		},
		azure: {
			resource_group: '',
			location: 'eastus2',
			name_prefix: 'retrieve',
			subscription_id: '',
			deployer_object_id: ''
		},
		copilot: {
			model: 'gpt-4.1',
			provider_type: 'signed-in-user',
			timeout: 120
		},
		eval: {
			mode: 'sample',
			categories: [...DEFAULT_EVAL_CATEGORIES]
		}
	};
}

function parseScalar(value: string): unknown {
	const trimmed = value.trim();
	if (!trimmed) return '';
	if (trimmed === 'true') return true;
	if (trimmed === 'false') return false;
	if (trimmed === 'null') return null;
	if (
		(trimmed.startsWith('"') && trimmed.endsWith('"')) ||
		(trimmed.startsWith("'") && trimmed.endsWith("'"))
	) {
		return trimmed.slice(1, -1);
	}
	if (trimmed.startsWith('[') && trimmed.endsWith(']')) {
		const body = trimmed.slice(1, -1).trim();
		return body ? body.split(',').map((part) => String(parseScalar(part))) : [];
	}
	const asNumber = Number(trimmed);
	return Number.isFinite(asNumber) && /^-?\d+(\.\d+)?$/.test(trimmed) ? asNumber : trimmed;
}

function stripComment(line: string): string {
	let quote: string | null = null;
	for (let i = 0; i < line.length; i++) {
		const char = line[i];
		if ((char === '"' || char === "'") && line[i - 1] !== '\\') {
			quote = quote === char ? null : (quote ?? char);
		}
		if (char === '#' && !quote) return line.slice(0, i);
	}
	return line;
}

function nextSignificant(lines: string[], start: number) {
	for (let i = start; i < lines.length; i++) {
		const text = stripComment(lines[i]).trim();
		if (text) return text;
	}
	return '';
}

function parseYamlSubset(text: string): Record<string, unknown> {
	const root: Record<string, unknown> = {};
	const stack: Array<{ indent: number; value: Jsonish }> = [{ indent: -1, value: root }];
	const lines = text.replace(/\r\n/g, '\n').split('\n');

	for (let i = 0; i < lines.length; i++) {
		const raw = stripComment(lines[i]).replace(/\s+$/, '');
		if (!raw.trim()) continue;
		const indent = raw.match(/^\s*/)?.[0].length ?? 0;
		const trimmed = raw.trim();
		while (stack.length > 1 && indent <= stack[stack.length - 1].indent) stack.pop();
		const parent = stack[stack.length - 1].value;

		if (trimmed.startsWith('- ')) {
			if (!Array.isArray(parent)) continue;
			parent.push(parseScalar(trimmed.slice(2)));
			continue;
		}

		const match = /^([^:]+):(?:\s*(.*))?$/.exec(trimmed);
		if (!match || Array.isArray(parent)) continue;
		const [, key, value = ''] = match;
		if (value === '') {
			const child: Jsonish = nextSignificant(lines, i + 1).startsWith('- ') ? [] : {};
			parent[key.trim()] = child;
			stack.push({ indent, value: child });
		} else {
			parent[key.trim()] = parseScalar(value);
		}
	}

	return root;
}

function asString(value: unknown, fallback: string): string {
	return typeof value === 'string' ? value : fallback;
}

function asBoolean(value: unknown, fallback: boolean): boolean {
	return typeof value === 'boolean' ? value : fallback;
}

function asNumber(value: unknown, fallback: number): number {
	return typeof value === 'number' ? value : fallback;
}

function asStringArray(value: unknown, fallback: string[]): string[] {
	if (Array.isArray(value)) return value.map(String).filter(Boolean);
	if (typeof value === 'string' && value.trim())
		return value
			.split(',')
			.map((item) => item.trim())
			.filter(Boolean);
	return fallback;
}

function record(value: unknown): Record<string, unknown> {
	return value && typeof value === 'object' && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};
}

export function configPath(): string {
	return path.resolve(process.cwd(), process.env.PRIVATE_RETRIEVE_CONFIG_PATH || 'retrieve.yaml');
}

export function loadConfig(): RetrieveConfigSummary {
	const defaults = defaultConfig();
	const target = configPath();
	if (!existsSync(target)) return defaults;

	const raw = parseYamlSubset(readFileSync(target, 'utf8'));
	const corpus = record(raw.corpus);
	const azure = record(raw.azure);
	const copilot = record(raw.copilot);
	const provider = record(copilot.provider);
	const evalConfig = record(raw.eval);

	return {
		db_path: asString(raw.db_path, defaults.db_path),
		log_level: asString(raw.log_level, defaults.log_level ?? 'INFO'),
		azure_sdk_logging: asBoolean(raw.azure_sdk_logging, defaults.azure_sdk_logging ?? false),
		architectures: asStringArray(raw.architectures, defaults.architectures),
		corpus: {
			source: asString(corpus.source, defaults.corpus.source),
			plugin: asString(corpus.plugin, defaults.corpus.plugin),
			output_dir: asString(corpus.output_dir, defaults.corpus.output_dir)
		},
		azure: {
			resource_group: asString(azure.resource_group, defaults.azure.resource_group),
			location: asString(azure.location, defaults.azure.location),
			name_prefix: asString(azure.name_prefix, defaults.azure.name_prefix),
			subscription_id: asString(azure.subscription_id, defaults.azure.subscription_id ?? ''),
			deployer_object_id: asString(
				azure.deployer_object_id,
				defaults.azure.deployer_object_id ?? ''
			)
		},
		copilot: {
			model: asString(copilot.model, defaults.copilot.model),
			provider_type: asString(provider.type, defaults.copilot.provider_type ?? 'signed-in-user'),
			timeout: asNumber(copilot.timeout, defaults.copilot.timeout ?? 120)
		},
		eval: {
			mode: asString(evalConfig.mode, defaults.eval.mode),
			categories: asStringArray(evalConfig.categories, defaults.eval.categories)
		}
	};
}
