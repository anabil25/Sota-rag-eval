import { describe, expect, it } from 'vitest';
import { ARCHITECTURES } from './registry/architectures';
import {
	DEFAULT_PRICING_INPUTS,
	PRICING_METERS,
	architectureNeedsVector,
	architectureUsesLlm,
	architectureUsesSearch,
	architectureUsesSemanticRanker,
	bestArchitectureFromRuns,
	estimateArchitectureEvalCost,
	estimateExperimentEvalCost,
	estimateMonthlyProductionCost,
	formatNumber,
	formatUnitPrice,
	formatUsd,
	pricingInputsFromCorpus
} from './pricing';

describe('pricing model', () => {
	it('classifies architecture capabilities', () => {
		expect(architectureUsesSearch('keyword')).toBe(true);
		expect(architectureUsesSearch('graphrag')).toBe(false);
		expect(architectureNeedsVector('hybrid')).toBe(true);
		expect(architectureNeedsVector('keyword')).toBe(false);
		expect(architectureUsesSemanticRanker('hybrid-reranker')).toBe(true);
		expect(architectureUsesSemanticRanker('hybrid')).toBe(false);
		expect(architectureUsesLlm('lightrag')).toBe(true);
		expect(architectureUsesLlm('keyword')).toBe(false);
	});

	it('estimates each architecture cost path', () => {
		for (const architecture of Object.keys(ARCHITECTURES)) {
			const estimate = estimateArchitectureEvalCost(architecture, DEFAULT_PRICING_INPUTS);
			expect(estimate.total).toBeGreaterThanOrEqual(0);
			expect(Array.isArray(estimate.lines)).toBe(true);
		}
		expect(estimateArchitectureEvalCost('unknown').total).toBe(0);
		expect(() =>
			estimateArchitectureEvalCost('keyword', {
				...DEFAULT_PRICING_INPUTS,
				searchHours: 1,
				searchUnits: 1
			})
		).not.toThrow();
		expect(
			estimateArchitectureEvalCost('keyword', { ...DEFAULT_PRICING_INPUTS, searchHours: 0 }).lines
		).toEqual([]);
	});

	it('estimates experiment and production totals', () => {
		const inputs = pricingInputsFromCorpus({ corpusDocuments: 2, corpusTokens: 1000 });
		expect(inputs.corpusDocuments).toBe(2);
		expect(inputs.corpusTokens).toBe(1000);
		expect(estimateExperimentEvalCost(['keyword', 'hybrid'], inputs).lines.length).toBeGreaterThan(
			1
		);
		expect(estimateMonthlyProductionCost('agentic-kb', inputs).total).toBeGreaterThan(0);
		expect(estimateMonthlyProductionCost('graphrag', inputs).total).toBeGreaterThan(0);
		expect(
			estimateMonthlyProductionCost('hybrid-reranker', inputs).lines.some(
				(line) => line.label === 'Semantic ranker queries'
			)
		).toBe(true);
	});

	it('selects a pricing architecture by winner, run, selected candidate, then default', () => {
		const architectures = { keyword: ARCHITECTURES.keyword, hybrid: ARCHITECTURES.hybrid };
		expect(bestArchitectureFromRuns([], { winners: ['hybrid'] }, architectures).reason).toBe(
			'Selected winner from Compare'
		);
		expect(
			bestArchitectureFromRuns(
				[
					{
						id: 1,
						architecture_name: 'keyword',
						status: 'completed',
						aggregate_metrics: { ndcg_at_10: 0.1 }
					},
					{
						id: 2,
						architecture_name: 'hybrid',
						status: 'completed',
						aggregate_metrics: { ndcg_at_10: 0.9 }
					}
				],
				{},
				architectures
			)
		).toEqual({ architecture: 'hybrid', reason: 'Highest nDCG@10 run' });
		expect(
			bestArchitectureFromRuns([], { selected_architectures: ['keyword'] }, architectures).reason
		).toBe('First configured candidate');
		expect(bestArchitectureFromRuns([], {}, architectures).reason).toBe('Default architecture');
		expect(
			bestArchitectureFromRuns(
				[{ id: 3, architecture_name: 'keyword', status: 'completed', ndcg_at_10: 0.4 }],
				{},
				architectures
			).architecture
		).toBe('keyword');
		expect(
			bestArchitectureFromRuns(
				[{ id: 4, architecture_name: 'keyword', status: 'completed', aggregate_metrics: {} }],
				{},
				architectures
			).architecture
		).toBe('keyword');
		expect(bestArchitectureFromRuns([], {}, {}).architecture).toBe('hybrid');
	});

	it('formats prices, numbers, and exposes retail source metadata', () => {
		expect(PRICING_METERS.length).toBeGreaterThan(0);
		expect(formatUsd(Number.NaN)).toBe('$0.00');
		expect(formatUsd(0.001)).toBe('<$0.01');
		expect(formatUsd(12)).toBe('$12.00');
		expect(formatUnitPrice(Number.NaN)).toBe('$0.00');
		expect(formatUnitPrice(0.000022)).toBe('$0.000022');
		expect(formatUnitPrice(1)).toBe('$1.00');
		expect(formatNumber(12345)).toBe('12,345');
	});
});
