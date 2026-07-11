import {
	getArchitectures,
	getConfig,
	getCorpusFiles,
	getRuns,
	getStatus,
	getUiSession
} from '$lib/server/retrieve-api';
import { bestArchitectureFromRuns, pricingInputsFromCorpus } from '$lib/pricing';

export const load = async () => {
	const [status, session, runs, architectures, config] = await Promise.all([
		getStatus(),
		getUiSession(),
		getRuns(),
		getArchitectures(),
		getConfig()
	]);
	const corpusFiles = await getCorpusFiles(
		typeof session.output === 'string' ? session.output : undefined
	);
	const corpusBytes = corpusFiles.files.reduce((sum, file) => sum + file.size, 0);
	const corpusDocuments = (session.ingest_stats?.doc_count ?? corpusFiles.files.length) || 100;
	const corpusTokens = Math.max(1, Math.round(corpusBytes / 4) || corpusDocuments * 2500);
	const selected = bestArchitectureFromRuns(runs, session, architectures);
	const selectedArchitectures = session.selected_architectures?.length
		? session.selected_architectures
		: [selected.architecture];

	return {
		status,
		session,
		runs,
		architectures,
		config,
		corpusFiles,
		corpusBytes,
		selected,
		selectedArchitectures,
		pricingDefaults: pricingInputsFromCorpus({
			corpusDocuments,
			corpusTokens,
			evalQuestions: status.eval_set?.question_count ?? 25,
			storageGb: Math.max(1, Math.ceil(corpusBytes / 1024 ** 3)),
			searchHours: 4,
			evalRunsPerMonth: 10,
			monthlyQueries: 10_000
		})
	};
};
