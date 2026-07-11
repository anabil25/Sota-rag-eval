import type { UiSession } from '$lib/api/types';
import * as db from '$lib/server/db';

export function getUiSession(): UiSession {
	return db.getUiSession();
}

export function updateUiSession(session: Partial<UiSession>): {
	status: string;
	session: UiSession;
} {
	const merged = db.updateUiSession(session);
	return { status: 'ok', session: merged };
}
