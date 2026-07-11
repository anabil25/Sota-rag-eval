import { afterEach, describe, expect, it } from 'vitest';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { loadConfig } from './config';

describe('retrieve config loader', () => {
	let tempDir: string | undefined;
	let previousConfigPath: string | undefined;

	afterEach(() => {
		if (previousConfigPath === undefined) delete process.env.PRIVATE_RETRIEVE_CONFIG_PATH;
		else process.env.PRIVATE_RETRIEVE_CONFIG_PATH = previousConfigPath;
		previousConfigPath = undefined;
		if (tempDir) rmSync(tempDir, { recursive: true, force: true });
		tempDir = undefined;
	});

	function useConfig(text: string) {
		previousConfigPath = process.env.PRIVATE_RETRIEVE_CONFIG_PATH;
		tempDir = mkdtempSync(path.join(tmpdir(), 'retrieve-config-spec-'));
		const configPath = path.join(tempDir, 'retrieve.yaml');
		writeFileSync(configPath, text, 'utf8');
		process.env.PRIVATE_RETRIEVE_CONFIG_PATH = configPath;
		return configPath;
	}

	it('returns Python-compatible defaults when config is absent', () => {
		previousConfigPath = process.env.PRIVATE_RETRIEVE_CONFIG_PATH;
		process.env.PRIVATE_RETRIEVE_CONFIG_PATH = path.join(tmpdir(), 'missing-retrieve.yaml');
		const config = loadConfig();
		expect(config.db_path).toBe('retrieve.db');
		expect(config.azure.location).toBe('eastus2');
		expect(config.architectures).toEqual(['hybrid']);
	});

	it('loads nested YAML values, lists, booleans, numbers, and comments', () => {
		useConfig(`
db_path: custom.db
log_level: DEBUG
azure_sdk_logging: true
architectures:
  - keyword
  - hybrid
corpus:
  source: "/tmp/source/index.html" # comment
  plugin: markdown
  output_dir: out-corpus
azure:
  resource_group: rg-test
  location: westus
  name_prefix: ret
  subscription_id: sub
  deployer_object_id: obj
copilot:
  model: gpt-test
  timeout: 42
  provider:
    type: openai
eval:
  mode: full
  categories: [a, b]
`);
		const config = loadConfig();
		expect(config).toMatchObject({
			db_path: 'custom.db',
			log_level: 'DEBUG',
			azure_sdk_logging: true,
			architectures: ['keyword', 'hybrid'],
			corpus: { source: '/tmp/source/index.html', plugin: 'markdown', output_dir: 'out-corpus' },
			azure: {
				resource_group: 'rg-test',
				location: 'westus',
				name_prefix: 'ret',
				subscription_id: 'sub',
				deployer_object_id: 'obj'
			},
			copilot: { model: 'gpt-test', provider_type: 'openai', timeout: 42 },
			eval: { mode: 'full', categories: ['a', 'b'] }
		});
	});

	it('handles inline comma lists and empty nested sections', () => {
		useConfig(`
architectures: keyword, hybrid
empty_section:
`);
		const config = loadConfig();
		expect(config.architectures).toEqual(['keyword', 'hybrid']);
		expect(config.corpus.output_dir).toBe('corpus');
	});
});
