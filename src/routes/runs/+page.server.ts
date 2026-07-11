import type { MetricItem } from '$lib/api/types';
import { getRuns } from '$lib/server/retrieve-api';

function metricValue(run: Awaited<ReturnType<typeof getRuns>>[number] | undefined, key: string) {
	if (!run) return undefined;
	const aggregate = run.aggregate_metrics;
	const source = aggregate && typeof aggregate === 'object' ? aggregate : run;
	const value = (source as Record<string, unknown>)[key];
	return typeof value === 'number' ? value : undefined;
}

function metricLabel(value: number | undefined, decimals = 3, suffix = '') {
	return typeof value === 'number' ? `${value.toFixed(decimals)}${suffix}` : 'n/a';
}

function missRate(run: Awaited<ReturnType<typeof getRuns>>[number]) {
	const misses = run.failure_count ?? run.miss_count ?? metricValue(run, 'miss_count');
	if (typeof misses !== 'number' || !run.total_questions) return undefined;
	return misses / run.total_questions;
}

export const load = async () => {
	const runs = await getRuns();
	const completed = runs.filter((run) => run.status === 'completed');
	const sortedByQuality = [...completed].sort(
		(left, right) =>
			(metricValue(right, 'ndcg_at_10') ?? -1) - (metricValue(left, 'ndcg_at_10') ?? -1)
	);
	const leader = sortedByQuality[0];
	const fastest = [...completed].sort(
		(left, right) =>
			(metricValue(left, 'avg_latency_ms') ?? Number.POSITIVE_INFINITY) -
			(metricValue(right, 'avg_latency_ms') ?? Number.POSITIVE_INFINITY)
	)[0];
	const bestScore = metricValue(leader, 'ndcg_at_10');
	const worstScore = metricValue(sortedByQuality.at(-1), 'ndcg_at_10');
	const missRates = completed.flatMap((run) => {
		const rate = missRate(run);
		return typeof rate === 'number' ? [rate] : [];
	});
	const averageMissRate = missRates.length
		? missRates.reduce((sum, rate) => sum + rate, 0) / missRates.length
		: undefined;
	const metrics: MetricItem[] = [
		{ label: 'Runs', value: String(runs.length), note: 'All recorded runs' },
		{
			label: 'Leader',
			value: leader?.architecture_name ?? 'n/a',
			note: leader ? `nDCG@10 ${metricLabel(bestScore)}` : 'No completed run yet',
			tone: 'success'
		},
		{
			label: 'Quality spread',
			value:
				typeof bestScore === 'number' && typeof worstScore === 'number'
					? `+${(bestScore - worstScore).toFixed(3)}`
					: 'n/a',
			note: 'Best minus weakest nDCG@10'
		},
		{
			label: 'Miss pressure',
			value: typeof averageMissRate === 'number' ? `${(averageMissRate * 100).toFixed(0)}%` : 'n/a',
			note: 'Average misses across answered evals',
			tone: typeof averageMissRate === 'number' && averageMissRate > 0.2 ? 'warning' : 'neutral'
		}
	];
	return { runs, metrics, leader, fastest };
};
