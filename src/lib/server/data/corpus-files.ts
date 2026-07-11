import { existsSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import type { CorpusFilesResponse, RetrieveConfigSummary } from '$lib/api/types';
import { loadConfig } from '$lib/server/config';

function resolveCorpusOutput(output: string | undefined, config: RetrieveConfigSummary): string {
	const selected = output || config.corpus.output_dir;
	if (path.isAbsolute(selected)) return selected;
	return config.corpus.source
		? path.resolve(path.dirname(config.corpus.source), selected)
		: path.resolve(process.cwd(), selected);
}

export function getCorpusFiles(output?: string): CorpusFilesResponse {
	const config = loadConfig();
	const target = resolveCorpusOutput(output, config);
	const files = existsSync(target)
		? readdirSync(target)
				.filter((name) => name.endsWith('.md'))
				.sort()
				.map((name) => ({
					name,
					size: statSync(path.join(target, name)).size
				}))
		: [];

	return {
		output: output || config.corpus.output_dir,
		files
	};
}
