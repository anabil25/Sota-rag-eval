# Plan 2 — Clean and Normalize the Repository

**Status:** Planned
**Priority:** P1
**Last updated:** 2026-07-10

## Goal

Create a maintainable monorepo with explicit source, generated, runtime, fixture, documentation, and deployment boundaries. Preserve behavior and evidence first; quarantine before deletion; keep functional rewrites out of cleanup commits.

## Phase 0 — Safe baseline

1. Restore or establish the authoritative version-control root. This workspace currently lacks `.git`; do not run history rewrites here.
2. Inventory every path with size, count, owner/source, runtime references, secret-scan result, and proposed disposition.
3. Hash all removal candidates and store the manifest outside cleanup targets.
4. Capture baseline Python, Svelte, Playwright, Docker, Bicep, and docs checks with known failures noted.
5. Quarantine in small batches outside build/deploy contexts; delete only after repeated parity checks and approval.

## Phase 1 — Target monorepo boundary

1. Keep root Node/SvelteKit plus nested `retrieve-core/` Python package.
2. Establish sources of truth:
   - `README.md` — deploy/run/operator guide.
   - `ARCHITECTURE.md` — components, data flows, trust/state boundaries, contracts.
   - `CONTRIBUTING.md` — development and generated-file policy.
   - `docs/audits`, `docs/plans`, `docs/design`, `docs/operations`, `docs/reference`, `docs/archive`.
3. Move root planning/instruction documents into reviewed docs locations with status/replacement links.
4. Create a parity matrix for legacy FastAPI Jinja/static UI versus SvelteKit; retire legacy UI only after route/action parity.

## Phase 2 — Data, fixtures, and runtime state

1. Treat the full corpus as managed external/local data, not application source.
2. Keep only small, curated, license-reviewed fixtures under test fixture directories.
3. Archive historical corpus generations externally with manifests; remove duplicate corpus copies after references migrate.
4. Ignore local DB/WAL/SHM, local YAML variants, `.graphrag`, logs, eval outputs, manual validation, test/coverage/build/cache outputs, and local environment files.
5. Keep only sanitized root `.env.example` and `retrieve.example.yaml`.
6. Classify CSVs and eval outputs as generated artifacts or named golden fixtures with provenance.

## Phase 3 — Remove copied upstream repositories

1. Search active code/tests/scripts for `solution-accelerator/` references.
2. Record upstream URL, commit/version, license, and exact required artifacts.
3. Remove copied GraphRAG, LightRAG, and Copilot SDK repositories after replacing references with pinned packages or links.
4. Preserve only small consumed schemas/assets with provenance.
5. Consolidate `skills/` and duplicated solution-accelerator guidance into one authoritative docs/customization location.
6. Create `docs/reference/upstream-dependencies.md` with compatibility/update procedures.

## Phase 4 — Configuration, dependencies, and builds

1. Keep `package-lock.json`; add reproducible Python constraints/locks per runtime image.
2. Align Node/Python versions across README, package metadata, CI, and Docker. Current Node docs and CI disagree.
3. Normalize one image per deployable unit: UI, operation API, GraphRAG Job, and proxy only if retained.
4. Retire the combined root image after split-service deployment reaches parity.
5. Ensure Docker contexts exclude corpora, DBs, configs, logs, tests, copied repos, and secrets.
6. Remove compiled Bicep `main.json` and other generated IaC from source control.
7. Standardize path/test naming while preserving public APIs/imports.

## Phase 5 — Data ownership and duplicate implementations

1. Make FastAPI the sole write owner for operational state; SvelteKit proxies writes and may keep a read-only local read model.
2. Remove duplicate persistence/config logic only after cross-runtime contract tests pass.
3. If Node keeps direct SQLite reads, enforce query-only mode, busy timeout, and schema-version compatibility.
4. Replace duplicate config parsers with one API-provided runtime contract for deployed environments.

## Phase 6 — CI and documentation

1. Split CI into Python, frontend, integration, IaC, container, security, and docs jobs.
2. Repair and pin GitHub Actions; current `azure/cli@v2` resolution is failing.
3. Add checks for forbidden generated paths, secrets, vulnerabilities, licenses, lock drift, duplicate large files, invalid frontmatter, broken links, IaC drift, image layers, and fixture size budgets.
4. Keep live Azure tests opt-in and non-destructive; publish artifacts instead of committing them.
5. Update README structure/commands and add operations guides for state, corpus, azd, graph indexing, backup/restore, and cleanup.

## Phase 7 — Batch cleanup and sign-off

1. Execute batches: runtime ignore rules; docs moves; corpus externalization; copied repo removal; image/build normalization; legacy UI retirement.
2. For every batch, run reference scans, baseline tests, size comparison, and rollback verification.
3. Verify a clean clone reaches a passing offline state using only documented commands.
4. Publish a cleanup report and delete quarantine only after approval.

## Key paths

- `.gitignore`, `.dockerignore`, `.prettierignore`
- `README.md`, root legacy docs, `docs/`
- `package.json`, `package-lock.json`, `.npmrc`, `retrieve-core/pyproject.toml`
- `Dockerfile`, `retrieve-core/Dockerfile*`
- `corpus/`, `retrieve-core/corpus/`, `evals/`, `logs/`, `manual-validation/`, `test-results/`, `coverage/`
- `solution-accelerator/`, `skills/`
- `retrieve-core/src/retrieve/web/templates/`, `retrieve-core/src/retrieve/web/static/`
- `.github/workflows/ci.yml`
- `src/lib/server/db.ts`, `retrieve-core/src/retrieve/db.py`

## Acceptance criteria

- Clean clone installs/builds/tests without local hidden state.
- Full corpora, DBs, logs, generated files, and secrets are absent from source and images.
- Copied upstream repositories are removed with provenance retained.
- Documentation has clear current/archive status and one source of truth.
- Cleanup introduces no functional regression and is reversible until final approval.
