import type { PageServerLoad } from './$types';
import { browseEvalQuestions, getEvalSummary } from '$lib/server/retrieve-api';

export const load: PageServerLoad = async ({ params, url }) => {
	const id = Number(params.id);
	const filters = {
		category: url.searchParams.get('category') || undefined,
		question_type: url.searchParams.get('question_type') || undefined,
		persona: url.searchParams.get('persona') || undefined,
		intent_family: url.searchParams.get('intent_family') || undefined,
		limit: 50
	};
	const [summary, questionBrowse, allQuestionBrowse] = await Promise.all([
		getEvalSummary(id),
		browseEvalQuestions(id, filters),
		browseEvalQuestions(id, { limit: 1000 })
	]);
	return {
		summary,
		questions: questionBrowse.items,
		allQuestions: allQuestionBrowse.items,
		total: questionBrowse.total,
		filters
	};
};
