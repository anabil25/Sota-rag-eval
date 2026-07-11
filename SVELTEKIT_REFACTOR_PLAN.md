# SvelteKit Refactor Plan

This plan converts Retrieve from a FastAPI-rendered Jinja/HTMX/Alpine UI into a SvelteKit 5 application. The browser-facing app becomes SvelteKit. The Python package remains the retrieval/eval/provisioning engine and, during the migration, FastAPI remains a headless API and job runner.

## Target Decision

Recommended target:

- SvelteKit owns all user-facing routes, SSR, forms, client interactivity, navigation, layout, styling, and E2E UI tests.
- FastAPI stops serving HTML, Jinja templates, HTMX partials, Alpine state, and UI static assets.
- FastAPI remains an internal/headless API around the existing Python core until there is a deliberate separate decision to port backend behavior.
- The CLI continues to call the same Python core modules as it does today.
- The retrieval core is not rewritten in TypeScript as part of this refactor.

Why this shape:

- The Python core already has tests around ingestion, eval generation, scoring, provisioning, indexing, jobs, and SQLite behavior.
- SvelteKit cannot directly import Python modules. Removing FastAPI entirely would require either a Python worker/subprocess bridge or a full backend rewrite.
- The cleanest first win is to make SvelteKit the full app surface while preserving the proven Python service boundary.

## Current Surface Inventory

### Current HTML Routes To Replace

These are rendered from `retrieve-core/src/retrieve/web/app.py` with Jinja templates:

| Route               | Current behavior                                   | SvelteKit replacement                       |
| ------------------- | -------------------------------------------------- | ------------------------------------------- |
| `/`                 | Redirects to `/step/ingest`                        | `/` dashboard or redirect to `/flow/ingest` |
| `/step/{step_name}` | Main wizard route with full or HTMX partial render | `/flow/[step]`                              |
| `/compare`          | Legacy redirect to `/step/compare`                 | `/flow/compare` or `/runs`                  |
| `/history`          | Legacy redirect to `/step/history`                 | `/runs` or `/history`                       |
| `/eval-sets`        | Legacy redirect to `/step/eval`                    | `/eval-sets`                                |
| `/eval-workbench`   | Legacy redirect to `/step/eval`                    | `/eval-sets` or `/flow/eval`                |

### Jinja And Static UI Files To Retire

| Current file                                                           | Replacement                                                                   |
| ---------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| `retrieve-core/src/retrieve/web/templates/base.html`                   | `apps/retrieve-ui/src/routes/+layout.svelte` plus `src/lib/styles/global.css` |
| `retrieve-core/src/retrieve/web/templates/partials/sidebar.html`       | `AppSidebar.svelte` and `StepStatusRail.svelte`                               |
| `retrieve-core/src/retrieve/web/templates/partials/content_shell.html` | SvelteKit route layouts and route headers                                     |
| `retrieve-core/src/retrieve/web/templates/steps/ingest.html`           | `flow/[step]` route plus `IngestStep.svelte`                                  |
| `retrieve-core/src/retrieve/web/templates/steps/eval.html`             | `EvalStep.svelte`, `EvalQuestionBrowser.svelte`, CSV import/export forms      |
| `retrieve-core/src/retrieve/web/templates/steps/mode.html`             | `ModeStep.svelte`, `SotaPathSelector.svelte`                                  |
| `retrieve-core/src/retrieve/web/templates/steps/configure.html`        | `ConfigureStep.svelte`, `ArchitectureSelector.svelte`                         |
| `retrieve-core/src/retrieve/web/templates/steps/provision.html`        | `ProvisionStep.svelte`, `JobProgressStream.svelte`                            |
| `retrieve-core/src/retrieve/web/templates/steps/compare.html`          | `CompareStep.svelte`, `RunsTable.svelte`, `WinnerPicker.svelte`               |
| `retrieve-core/src/retrieve/web/templates/steps/history.html`          | `/runs` and/or `/history` SvelteKit routes                                    |
| `retrieve-core/src/retrieve/web/templates/steps/settings.html`         | `/settings` SvelteKit route                                                   |
| `retrieve-core/src/retrieve/web/static/*`                              | `apps/retrieve-ui/static/` or imported SvelteKit assets                       |

### Headless API Surface To Keep

These endpoints are the migration contract for SvelteKit. Keep them green in pytest while the UI moves.

| Method | Path                                            | Purpose                                              |
| ------ | ----------------------------------------------- | ---------------------------------------------------- |
| `GET`  | `/api/status`                                   | Latest eval set, run count, configured architectures |
| `GET`  | `/api/runs`                                     | Completed runs                                       |
| `GET`  | `/api/runs/{run_id}`                            | Run detail, results, category scores, failures       |
| `GET`  | `/api/eval-sets`                                | Eval set inventory                                   |
| `GET`  | `/api/eval-sets/{eval_set_id}/questions`        | Eval questions                                       |
| `GET`  | `/api/eval-sets/{eval_set_id}/questions/browse` | Filtered/paged question browser                      |
| `GET`  | `/api/eval-sets/{eval_set_id}/summary`          | Eval set summary, categories, examples               |
| `GET`  | `/api/architectures`                            | Architecture registry                                |
| `GET`  | `/api/models`                                   | Embedding/reranker model registry                    |
| `GET`  | `/api/sota-paths`                               | SOTA path registry                                   |
| `POST` | `/api/ingest`                                   | Direct ingestion mutation                            |
| `POST` | `/api/eval/generate`                            | Direct eval generation mutation                      |
| `POST` | `/api/eval/export-csv`                          | Export eval set CSV                                  |
| `POST` | `/api/eval/import-csv`                          | Import eval set CSV                                  |
| `GET`  | `/api/eval/preferences`                         | Read scoped generation preferences                   |
| `POST` | `/api/eval/preferences`                         | Update scoped generation preferences                 |
| `GET`  | `/api/ui/session`                               | Read wizard/UI session state                         |
| `POST` | `/api/ui/session`                               | Update wizard/UI session state                       |
| `POST` | `/api/ui/job/start`                             | Start long-running job                               |
| `GET`  | `/api/ui/job/{job_id}/status`                   | Poll job completion/result                           |
| `GET`  | `/api/ui/job/{job_id}/stream`                   | SSE progress stream                                  |

Open contract issue:

- Tests reference `POST /api/eval/curate`, but the route is commented in `app.py`. Decide whether to restore it as API-only or remove/update the tests before the SvelteKit migration begins.

## Target Architecture

```text
Browser
  -> SvelteKit routes, load functions, actions, EventSource components
  -> $lib/server/retrieve-api.ts typed server-side API client
  -> FastAPI headless API on PRIVATE_RETRIEVE_API_BASE
  -> retrieve-core Python modules
  -> SQLite, Azure AI Search, Azure resources, Copilot SDK
```

SvelteKit owns:

- All HTML rendering.
- All route navigation.
- All form UI and progressive enhancement.
- All dashboard, table, evidence, metric, and workflow components.
- All CSS and layout primitives.
- All browser tests.

FastAPI owns:

- API routes.
- Job creation/status/stream endpoints.
- Calling core modules in worker threads.
- Serialization of Python models and DB rows.
- Config loading and persistence until a new config API is added.

Python core owns:

- Ingestion.
- Eval generation/curation.
- Metrics and failure classification.
- Azure provisioning/indexing/teardown.
- Registry definitions.
- SQLite persistence.

## Phase 0: Contract Freeze And Cleanup

Goal: lock the backend contract before changing the UI.

Tasks:

1. Add an API inventory test or snapshot that covers every endpoint in the headless API table.
2. Split HTML route tests from API tests so UI removal does not break backend confidence.
3. Resolve the `POST /api/eval/curate` mismatch.
4. Add explicit response models or documented TypedDict/Pydantic shapes for API responses where practical.
5. Generate or document OpenAPI as the contract SvelteKit will consume.
6. Confirm job kinds accepted by `/api/ui/job/start`: `ingest`, `eval_generate`, `provision`, `index`, `evaluate`, `teardown`.
7. Decide whether `/api/ingest` and `/api/eval/generate` direct mutations remain or whether the UI only uses the job API for long-running work.

Exit criteria:

- `pytest retrieve-core/tests/test_web*.py` validates API behavior without depending on Jinja output.
- The current UI still works.
- API responses are stable enough to type in TypeScript.

## Phase 1: Scaffold The SvelteKit App

Goal: add SvelteKit without changing the Python service.

Tasks:

1. Create `apps/retrieve-ui` with SvelteKit 5, TypeScript, ESLint, Prettier, Vitest, Playwright, and adapter-node.
2. Add Svelte MCP support with `npx sv add mcp`.
3. Add `src/lib/styles/global.css` using the token/layout policy in `blog0instruct.md`.
4. Configure Vite dev proxy so `/api/*` points to the local FastAPI service.
5. Add environment variables:
   - `PRIVATE_RETRIEVE_API_BASE=http://127.0.0.1:8000`
   - `PUBLIC_APP_NAME=Retrieve`
6. Add scripts:
   - `dev`
   - `check`
   - `test:unit`
   - `test:e2e`
   - `build`
   - `preview`
7. Add a root README section or command notes for starting FastAPI and SvelteKit together in dev.

Exit criteria:

- `npm run check` and `npm run build` pass in `apps/retrieve-ui`.
- A placeholder SvelteKit shell can call `/api/status` through the dev proxy or server API helper.
- No existing Python tests are broken.

## Phase 2: Build The SvelteKit App Shell

Goal: replace `base.html`, `content_shell.html`, and `sidebar.html` with SvelteKit layout components.

Tasks:

1. Implement `src/routes/+layout.svelte` with the app frame, sidebar, and main content region.
2. Implement `src/routes/+layout.server.ts` to load step states and session summary.
3. Implement shared components:
   - `AppSidebar.svelte`
   - `StepStatusRail.svelte`
   - `RouteHeader.svelte`
   - `JobProgressStream.svelte`
4. Implement route constants for workflow steps:
   - `ingest`
   - `eval`
   - `mode`
   - `configure`
   - `provision`
   - `compare`
5. Remove HTMX and Alpine concepts from the new UI. Use SvelteKit navigation, forms/actions, and Svelte state.
6. Port only the useful visual language from the old CSS. Do not copy inline CSS wholesale.

Exit criteria:

- `/` and `/flow/ingest` render in SvelteKit.
- Sidebar navigation uses regular links and `aria-current`.
- Layout has no raw structural pixel spacing outside tokens.
- Basic Playwright smoke test confirms the app shell renders.

## Phase 3: Add Typed API Client And Types

Goal: make the SvelteKit app consume the backend safely.

Tasks:

1. Create `src/lib/server/retrieve-api.ts`.
2. Create `src/lib/api/types.ts` for response/request types.
3. Add helpers for:
   - `getStatus()`
   - `getRuns()`
   - `getRun(id)`
   - `getEvalSets()`
   - `getEvalSummary(id)`
   - `browseEvalQuestions(id, filters)`
   - `getArchitectures()`
   - `getModels()`
   - `getSotaPaths()`
   - `getUiSession()` / `updateUiSession()`
   - `startJob(kind, args)` / `getJobStatus(id)`
4. Add narrow error handling: failed API responses should become SvelteKit `error(status, message)` in server loads/actions.
5. Keep API base URL private and server-only.

Exit criteria:

- Unit tests cover API helper URL construction, error handling, and representative response parsing.
- No Svelte component imports `PRIVATE_RETRIEVE_API_BASE` or constructs backend URLs directly.

## Phase 4: Convert Read-Only Screens First

Goal: get most of the UI visible before implementing mutations.

Convert routes in this order:

1. `/settings`
   - Config summary, Azure resource group/location, selected architectures.
2. `/eval-sets`
   - Eval set list.
3. `/eval-sets/[id]`
   - Summary, categories, examples, question browser.
4. `/runs`
   - Completed run table and high-level comparison.
5. `/runs/[id]`
   - Metrics, categories, failures, retrieved chunks.
6. `/flow/compare`
   - Read-only comparison using existing run data.

Components to build:

- `MetricGrid.svelte`
- `RunsTable.svelte`
- `RunFailureList.svelte`
- `EvalQuestionBrowser.svelte`
- `PolicySnippet.svelte`
- `EmptyState.svelte`
- `DataTable.svelte` or route-specific semantic tables

Exit criteria:

- Read-only SvelteKit pages cover the information currently shown by Jinja compare/history/eval/settings pages.
- Dense tables are wrapped in `.table-scroll` and remain usable on narrow viewports.
- Playwright covers navigation and at least one seeded run detail page.

## Phase 5: Convert Workflow Mutations

Goal: replace all Alpine/HTMX/fetch behavior with SvelteKit forms/actions and focused client components.

### Ingest

- Route: `/flow/ingest`
- Inputs: source, plugin, output, delay.
- Behavior: start `ingest` job and stream progress.
- Session updates: backend already stores `ingest_done` and `ingest_stats`.

### Eval

- Route: `/flow/eval`
- Inputs: version, mode, fresh/base eval set, operator context.
- Behavior: start `eval_generate` job and stream progress.
- Additional forms: CSV export/import.

### Mode

- Route: `/flow/mode`
- Inputs: selected mode, SOTA path.
- Behavior: update `/api/ui/session`.
- UI: show recommendation from API-provided SOTA paths and ingest stats.

### Configure

- Route: `/flow/configure`
- Inputs: selected architectures, embedding model, SOTA toggles.
- Behavior: update `/api/ui/session`.

### Provision

- Route: `/flow/provision`
- Inputs: resource group, location.
- Behavior: start `provision` and `index` jobs, stream each distinctly.

### Compare

- Route: `/flow/compare`
- Inputs: eval version, selected winners.
- Behavior: start `evaluate` job, stream progress, refresh runs after completion, update winners in session.

Exit criteria:

- Every current wizard step has SvelteKit parity.
- No new UI code uses HTMX or Alpine.
- SSE stream reconnect/cleanup is handled in `JobProgressStream.svelte`.
- Playwright covers one happy path through the wizard using mocked or seeded API responses where appropriate.

## Phase 6: Cut Over Browser Routes

Goal: make SvelteKit the user-facing app.

Tasks:

1. Stop linking users to FastAPI `/step/*` routes.
2. Add redirects from old paths to SvelteKit paths at the edge/proxy layer:
   - `/step/ingest` -> `/flow/ingest`
   - `/step/eval` -> `/flow/eval`
   - `/step/mode` -> `/flow/mode`
   - `/step/configure` -> `/flow/configure`
   - `/step/provision` -> `/flow/provision`
   - `/step/compare` -> `/flow/compare`
   - `/history` -> `/runs`
   - `/eval-sets` remains `/eval-sets`
3. Update docs and CLI output to point at the SvelteKit app URL.
4. Decide the dev launcher shape:
   - `retrieve api` starts FastAPI headless API.
   - `npm run dev` starts SvelteKit.
   - Optional `retrieve ui` starts both, or prints both commands.
5. Decide the production process shape:
   - two services behind one reverse proxy, or
   - one container with Node adapter and FastAPI API process supervised together.

Exit criteria:

- Normal users only see SvelteKit pages.
- FastAPI `/api/*` remains reachable from SvelteKit.
- Old Jinja routes are not the primary navigation path.

## Phase 7: Remove Jinja/HTMX/Alpine From FastAPI

Goal: delete retired UI code once SvelteKit parity is proven.

Tasks:

1. Remove `Jinja2Templates`, `HTMLResponse`, `StaticFiles`, and template/static path constants from `web/app.py` if no longer needed.
2. Remove HTML route handlers or leave thin redirects only if needed for compatibility.
3. Delete `retrieve-core/src/retrieve/web/templates/`.
4. Delete retired UI static assets from `retrieve-core/src/retrieve/web/static/` after moving any needed assets to SvelteKit.
5. Update pytest tests that asserted HTML content.
6. Keep API tests and job/SSE tests.
7. Update `ARCHITECTURE.md` built/planned status to say SvelteKit UI is built and FastAPI is headless API.

Exit criteria:

- FastAPI app is API-only or redirect-only.
- No dependency on Jinja, HTMX, or Alpine remains in the Python web layer.
- Python tests and SvelteKit tests pass.

## Phase 8: Optional Full Backend Consolidation

Only do this if the project truly wants to remove FastAPI, not just Jinja.

Options:

1. Keep Python as a worker process and let SvelteKit endpoints call it through subprocess or a local RPC protocol.
2. Keep Python as a package but expose stable CLI commands for every mutation, then have SvelteKit call the CLI.
3. Port backend behavior to TypeScript.

Recommendation:

- Do not pick option 3 unless there is a strong reason. It duplicates a tested Python retrieval system and creates high regression risk.
- If FastAPI removal is required, option 1 is usually cleaner than shelling out for long-running interactive work.

## Test Plan

Python side:

```powershell
cd retrieve-core
pytest tests/test_web.py tests/test_web_wizard.py tests/test_web_e2e.py
pytest
```

SvelteKit side:

```powershell
cd apps/retrieve-ui
npm run check
npm run test:unit
npm run test:e2e
npm run build
```

Contract tests:

- Add API schema fixtures or generated TypeScript type checks for representative endpoint payloads.
- Add a seeded backend test mode so Playwright can run without live Azure resources.
- Keep live Azure tests opt-in only.

Browser/layout checks:

- `/flow/ingest`
- `/flow/eval`
- `/flow/mode`
- `/flow/configure`
- `/flow/provision`
- `/flow/compare`
- `/runs`
- `/runs/[id]`
- `/eval-sets/[id]`
- `/settings`

Check mobile, tablet, and desktop for:

- no horizontal page overflow outside intentional table scroll areas,
- visible keyboard focus,
- usable sidebar/step navigation,
- readable tables,
- non-overlapping metric cards,
- `aria-live` job progress updates,
- EventSource cleanup on navigation,
- touch/coarse-pointer access to all content.

## Risk Register

| Risk                                                           | Mitigation                                                                                   |
| -------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| API shape drifts while UI is being ported                      | Freeze contract with tests and typed SvelteKit API client                                    |
| SSE proxying fails through SvelteKit or deployment proxy       | Test EventSource directly against FastAPI first, then through proxy; keep headers unbuffered |
| Long-running jobs outlive page navigation                      | Store job id in route/session state and let `JobProgressStream` reconnect by id              |
| UI session keys diverge from Python expectations               | Centralize session type in TypeScript and document keys in API tests                         |
| SvelteKit accidentally exposes private API base or credentials | Keep backend calls in `$lib/server`, use `PRIVATE_` env vars only                            |
| Layout regressions return during port                          | Use tokenized `global.css`, no raw structural spacing, Playwright viewport checks            |
| Removing Jinja breaks CLI `retrieve ui` workflow               | Change CLI in a separate phase with tests and clear dev/prod command behavior                |
| Tests require live Azure unintentionally                       | Keep live tests explicitly named/marked and use seeded DB/mock API for UI tests              |

## Done Definition

The refactor is complete when:

- SvelteKit owns every browser-facing route.
- FastAPI serves no Jinja templates and includes no HTMX/Alpine UI code.
- The Python core and CLI behavior are preserved.
- The job/SSE flow works from SvelteKit for ingest, eval generation, provision, index, evaluate, and teardown.
- Read-only pages cover runs, run detail, eval sets, question browsing, compare, history, and settings.
- Python API tests, SvelteKit unit tests, Playwright tests, `npm run check`, and `npm run build` pass.
- `ARCHITECTURE.md` and the CLI launch/docs reflect the new SvelteKit app boundary.
