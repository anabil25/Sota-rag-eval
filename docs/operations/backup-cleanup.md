# Backup and Cleanup

## Local state

Before destructive maintenance, retain copies of:

- `retrieve.db` plus WAL/SHM after stopping local processes;
- ignored `retrieve.yaml`;
- canonical corpus manifest and source provenance;
- relevant azd environment values;
- immutable graph run status and evaluation exports.

SQLite backup example:

```powershell
python -c "import sqlite3; source=sqlite3.connect('retrieve.db'); target=sqlite3.connect('retrieve-backup.db'); source.backup(target); target.close(); source.close()"
```

Do not commit backups.

## Corpus cleanup

Blob deletion is manifest-owned. A live mirror that deletes managed Markdown must receive the exact dry-run plan produced against the same remote state. Unmanaged remote Markdown blocks synchronization. The new manifest is uploaded last.

Historical local corpora, GraphRAG/LightRAG state, logs, test results, coverage, builds, and CSV exports are generated artifacts and remain ignored.

## Repository cleanup

The source repository contains no copied upstream repositories or full corpora. Dependency versions and update procedures live in `docs/reference/upstream-dependencies.md`; removal hashes are recorded in `docs/audits/repository-cleanup-2026-07-11.md`.

Validate cleanup with:

```powershell
python -m ruff check retrieve-core/src retrieve-core/tests scripts
python -m pytest retrieve-core/tests -q
npm run lint
npm run check
npm run test:unit -- --run
npm run build
az bicep build --file infra/main.bicep
```

## Azure cleanup

Use app-level teardown to remove unselected indexes/artifacts while retaining a shared experiment environment. Use `azd down --purge --force --no-prompt` to delete the complete isolated environment. Confirm the resource group no longer exists.
