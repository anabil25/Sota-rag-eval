import { copyFileSync, mkdirSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = path.dirname(path.dirname(path.dirname(fileURLToPath(import.meta.url))));
const fixtureDir = path.join(repoRoot, 'test-results', 'real-fixture');

rmSync(fixtureDir, { recursive: true, force: true });
mkdirSync(fixtureDir, { recursive: true });
copyFileSync(path.join(repoRoot, 'retrieve.db'), path.join(fixtureDir, 'retrieve.db'));
console.log(`Prepared real DB fixture at ${path.join(fixtureDir, 'retrieve.db')}`);
