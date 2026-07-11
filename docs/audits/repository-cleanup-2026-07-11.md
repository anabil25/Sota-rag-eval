# Repository Cleanup Evidence — 2026-07-11

## Scope

Plan 2 removes copied upstream repositories, generated evaluations, manual validation output, duplicate corpora/runtime state, obsolete images, and superseded planning files while preserving active source, tests, vision, deployment plans, and small reference material.

The initial repository commit remains the rollback source for every tracked deletion. Existing staged removals were preserved and extended; none were reverted.

## Pre-removal inventory

| Path | Files | Aggregate SHA-256 |
|---|---:|---|
| `solution-accelerator/` | 12,133 | `5f5dac5cc91269e855b8ffc6eb59014b4dd8d55913b2a0e87986e2405035aeef` |
| `skills/` | 11 | `a94d21cbabf84a0177d54594cdb2d366306b69ae07f08781a54d1e2e32769b28` |
| `evals/` | 52 | `a2d2bcc9ff789a9377464bd7eb71abf3b36083da0da27d5e85e5a8d79fc8128a` |
| `manual-validation/` | 12 | `bccaf457eb1a53b4537cdf6dac0eda2a4aa0fb8b15f50b8ff4c6ab98aef55e34` |

The aggregate hash is SHA-256 over sorted lines of `<file-sha256><two spaces><workspace-relative-path>`.

## Dispositions

- Move the canonical root skills into `docs/reference/skills/`; delete the byte-duplicate copied skills.
- Preserve the small Search API map under `docs/reference/azure-search-api/`; remove the copied reference tree.
- Move Azure capacity research to `docs/reference/azure-capacity-model.md` and use it in azd preflight/fallback.
- Archive the completed SvelteKit refactor plan under `docs/archive/ui-migration/`.
- Move Svelte conventions to `docs/reference/svelte-conventions.md`.
- Remove copied GraphRAG, LightRAG, Copilot SDK, and Copilot CLI source trees after package/API compatibility tests pass.
- Remove tracked `evals/` and `manual-validation/`; they are generated evidence, not source fixtures.
- Preserve `AGENTS.md` at the workspace root because VS Code loads it as active project configuration.
- Preserve FastAPI templates until the legacy route parity gate is complete; they are still imported by the local operation API.

## Runtime/generated boundary

The following remain local and ignored: corpus generations, GraphRAG/LightRAG state, SQLite/WAL/SHM, local YAML, logs, coverage, test results, build output, Playwright output, and generated CSV exports.

## Canonical corpus recovery

- Corrupt mixed-generation tree: 3,497 files, 14,560,175 bytes, aggregate SHA-256 `a5f76b356c8ee53e1030966e86b51d914b0550ef01c0e3bef339a8578f38e9c0`.
- Disposition: moved outside the repository to `retrieve-ui-corpus-quarantine-20260711`.
- Authoritative candidate: 1,617 pages ingested on 2026-05-09; March and April recursive generations were excluded.
- Canonical tree: 1,617 Markdown files plus manifest, 8,398,958 bytes, aggregate SHA-256 `6f499ab1849eaeb05adcb362ff00ed794868125f0a67852e69df36e8cd77d0a9` at promotion time.
- Corpus fingerprint: `4fff6583bdc9113be4052735f8076c8d4ccfb8294eb6a6d4278fdaeb6f6f10a2`.
- Validation: complete manifest, strict YAML, portable relative source IDs, unique document IDs and basenames, body-hash parity, and zero unmapped references in the active 27-question golden set.
- SQLite was backed up outside the repository as `retrieve-ui-state-backup-20260711.db` before active-set evidence migration. Historical eval sets were preserved unchanged because they describe older corpus generations.

## Validation gate

Cleanup is accepted only after frontend lint/check/tests/build, complete Python tests, Bicep lint/build/topology assertions, GraphRAG image build/non-root inspection, reference scans, privacy/secret scans, and generated-path scans pass.
