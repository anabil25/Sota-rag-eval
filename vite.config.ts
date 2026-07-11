import { defineConfig } from 'vitest/config';
import { sveltekit } from '@sveltejs/kit/vite';

export default defineConfig({
	plugins: [sveltekit()],
	test: {
		expect: { requireAssertions: true },
		coverage: {
			provider: 'v8',
			reporter: ['text', 'json-summary'],
			include: [
				'src/lib/eval/**/*.ts',
				'src/lib/registry/**/*.ts',
				'src/lib/workflow.ts',
				'src/lib/eval-taxonomy.ts',
				'src/lib/pricing.ts',
				'src/lib/flow/**/*.ts',
				'src/lib/server/config.ts',
				'src/lib/server/data/**/*.ts',
				'src/lib/server/services/**/*.ts',
				'src/lib/server/flow/form-parsers.ts',
				'src/lib/server/flow/progress-rules.ts',
				'src/lib/server/flow/load-flow-step.ts'
			],
			exclude: ['src/**/*.spec.ts', 'src/**/*.test.ts'],
			thresholds: {
				functions: 100,
				lines: 100
			}
		},
		environment: 'node',
		include: ['src/**/*.{test,spec}.{js,ts}'],
		exclude: ['src/**/*.svelte.{test,spec}.{js,ts}']
	}
});
