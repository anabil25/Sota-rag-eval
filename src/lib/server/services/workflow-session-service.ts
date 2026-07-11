import type { UiSession } from '$lib/api/types';
import * as db from '$lib/server/db';

export function getUiSession(): UiSession {
	return db.getUiSession();
}
