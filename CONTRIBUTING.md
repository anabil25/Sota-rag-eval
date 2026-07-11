# Contributing

## Setup

```sh
npm ci
python -m pip install -e "./retrieve-core[dev,graphrag,lightrag]"
```

Use Node.js 22 and Python 3.11 or 3.12.

## Local development

```sh
npm run backend:dev
npm run dev
```

FastAPI listens on `127.0.0.1:8000`; SvelteKit listens on `127.0.0.1:5173`. Keep mutation routes on FastAPI and keep direct SvelteKit SQLite access read-only.

## Required checks

```sh
python -m ruff check retrieve-core/src retrieve-core/tests scripts
python -m pytest retrieve-core/tests -q
npm run lint
npm run check
npm run test:unit -- --run
npm run build
az bicep lint --file infra/main.bicep
az bicep build --file infra/main.bicep
```

Build the deployed image with:

```sh
docker build -f retrieve-core/Dockerfile.graphrag-job -t retrieve-graphrag:local retrieve-core
```

## Repository boundaries

Commit source, tests, small reviewed fixtures, IaC, and durable documentation. Do not commit:

- corpus generations or duplicate corpora
- SQLite, WAL, SHM, local YAML, or environment files
- GraphRAG/LightRAG state, logs, coverage, test results, builds, or CSV exports
- copied upstream repositories
- compiled Bicep JSON
- credentials, tokens, keys, or tenant-specific local state

Use released, pinned packages and record compatibility in `docs/reference/upstream-dependencies.md`.

## Azure changes

- Keep UI/API localhost-only unless the approved deployment plan explicitly changes.
- Put ARM resources and RBAC in root `infra/`; hooks must remain thin and idempotent.
- Use one region for the complete stack.
- Run `azd provision --preview --no-prompt` before provisioning.
- Never target a protected environment for validation.
- Never start a full GraphRAG run before sample and canary gates pass.

## Tests and risk

Add focused regression tests for the owning boundary. Changes to canonical IDs, corpus mirroring, job admission/reconciliation, authentication, evaluation scoring, or infrastructure require both unit coverage and a disposable live sample before release.
