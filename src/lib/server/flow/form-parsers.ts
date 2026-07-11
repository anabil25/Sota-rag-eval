export function getString(form: FormData, key: string, fallback = '') {
	const value = form.get(key);
	return typeof value === 'string' ? value : fallback;
}

export function getBool(form: FormData, key: string) {
	return form.has(key);
}

export function getStrings(form: FormData, key: string): string[] {
	return form.getAll(key).map(String).filter(Boolean);
}

export function collectArgs(form: FormData, skip: string[] = []) {
	const skipped = new Set(skip);
	const args: Record<string, unknown> = {};
	for (const key of new Set(form.keys())) {
		if (skipped.has(key)) continue;
		const values = form.getAll(key).filter((value): value is string => typeof value === 'string');
		args[key] = values.length > 1 ? values : (values[0] ?? '');
	}
	return args;
}

export function collectArchitectureOptions(form: FormData) {
	const options: Record<string, Record<string, string | boolean>> = {};
	for (const key of new Set(form.keys())) {
		if (!key.startsWith('advanced__')) continue;
		const [, architecture, field] = key.split('__');
		if (!architecture || !field) continue;
		const values = form.getAll(key).filter((value): value is string => typeof value === 'string');
		const value = values.at(-1) ?? '';
		options[architecture] ??= {};
		options[architecture][field] = value === 'true' ? true : value === 'false' ? false : value;
	}
	return options;
}
