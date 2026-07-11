# Plan 3 — Rebuild Azure Deployment as an azd Accelerator

**Status:** Validated; deployment blocked pending explicit approval
**Priority:** P0/P1
**Last updated:** 2026-07-11

## Goal

Replace Python-driven split-brain provisioning with one deterministic `azd` provisioning contract modeled on the best conventions in `abKrazy/ITHelpdesk`: subscription-scoped modular Bicep, stable environment naming, explicit outputs, managed identities/RBAC in IaC, idempotent hooks, reproducible graph-worker images, and validation before deployment.

## Current deployment boundary

- Retrieve remains local-first: SvelteKit, FastAPI, SQLite history, and workflow control run on localhost.
- `azd` provisions only the Azure dependencies used by retrieval experiments and remote graph workloads.
- The current Azure topology has no SvelteKit or FastAPI Container Apps and no `services:` entries in `azure.yaml`.
- The only deployed application workload in this phase is the manual GraphRAG Container Apps Job.
- Any future hosted UI/API is a separate topology decision that requires an explicit plan update and approval.

## Adopted reference conventions

- Root `azure.yaml` is the deployment contract.
- Subscription-scoped `infra/main.bicep` creates one resource group.
- Stable `uniqueString(subscription().id, environmentName, location)` resource token.
- Root `infra/modules/` owns focused resource modules.
- `infra/main.parameters.json` binds azd environment values.
- Contract-locked uppercase outputs feed hooks and localhost application configuration.
- Thin cross-platform hooks call tested Python workers and fail nonzero.
- Model deployment writes are serialized where Azure requires it.
- Managed identity and disabled local auth/shared keys are defaults.
- Docs enumerate prerequisites, quota, region, cost, validation, troubleshooting, and `azd down --purge`.

## Phase 0 — Freeze and plan

1. Use `.azure/deployment-plan.md` as the required source of truth; obtain approval before deployment.
2. Freeze feature additions to current provisioning code.
3. Inventory the protected live resource group; map each resource to keep, migrate, replace, or remove.
4. Define ownership:
   - azd — environment, service deployment, hook order, outputs.
   - Bicep — ARM resources, network, identity, RBAC, security, diagnostics, apps/jobs.
   - Hooks — preflight, image publication gaps, data-plane initialization, smoke tests.
   - App — ingestion/index/query only; no general resource creation.
5. Build a parallel environment; never destructively retrofit the live group.

## Phase 1 — Target topology

1. One resource group per azd environment with deterministic naming.
2. Azure dependencies: Storage, AI Services model deployments, AI Search, ACR, monitoring, and managed identity/RBAC.
3. One manual GraphRAG Container Apps Job in a workload-profile managed environment.
4. SvelteKit and FastAPI remain localhost processes and consume the environment output contract.
5. Blob is persistent corpus/GraphRAG table/cache/report/status storage; AI Search is the retrieval/vector service.
6. Remove Cosmos from the default GraphRAG topology unless a supported tested use is approved.
7. Treat VNet integration, private endpoints, and private DNS as the production network-hardening stage; do not reintroduce hosted UI/API to achieve it.

## Phase 2 — Root azd contract

1. Add `azure.yaml` with schema, metadata, infrastructure, and pre/post provision hooks; do not define azd application services in the current phase.
2. Add `infra/main.parameters.json` binding azd environment, architectures, model names/capacities, SKUs, network mode, and optional graph indexing flags.
3. Add `infra/abbreviations.json`, stable tags, and deterministic resource token.
4. Define contract-locked outputs for resource group/location/token, identities, Storage, Search, AI deployments, ACR, Container Apps environment, GraphRAG Job, monitoring, network, and graph artifact/status contracts.
5. Test output names against hook and localhost application environment/config keys.

## Phase 3 — Modular Bicep

1. Move IaC from the Python package to root `infra/`; stop tracking compiled `main.json`.
2. Add subscription-scoped `main.bicep` creating the resource group and module graph.
3. Modules:
   - monitoring
   - user-assigned identities
   - VNet/subnets/private DNS
   - Storage/containers/lifecycle
   - private endpoints/DNS zone groups
   - AI Services/model deployments
   - AI Search
   - ACR
   - Container Apps environment and GraphRAG manual Job
   - focused RBAC
4. Put all role assignments in Bicep with deterministic GUID names and least privilege.
5. Thread exact deployment-name outputs into service/job environment variables; eliminate hard-coded model/resource names.
6. Parameterize network posture; production policy uses private data planes.
7. Set probes/resources/scaling from measured behavior. GraphRAG Job shape/deadline comes from canary evidence.

## Phase 4 — Idempotent lifecycle hooks

1. Thin PowerShell/POSIX wrappers call shared Python hook modules.
2. Preprovision validates tools, login/subscription, providers, RBAC permissions, region/service/model availability, quota, policy effects, deterministic names, soft-delete conflicts, and cost.
3. Keep UI/API execution local and consume the azd output contract; do not run `azd deploy` for them.
4. Build GraphRAG Job image in ACR with immutable content/commit tag; Bicep remains owner of Job definition.
5. Postprovision verifies RBAC with backoff, initializes/syncs data-plane schemas and standard Search indexes, and runs health probes.
6. Do not start expensive GraphRAG indexing during `azd up` unless an explicit environment flag enables it.
7. Hooks validate resource outputs, graph job definition, managed-identity calls, and data-plane initialization without taking ownership of ARM resources.

## Phase 5 — Security, observability, and costs

1. Keep the local UI/API bound to localhost and authenticated for mutation; do not expose either through this Azure deployment.
2. Disable local auth/shared keys for Storage, Search, and AI services where supported.
3. Add diagnostic settings and correlated App Insights dimensions for services and jobs.
4. Add budgets/alerts, model-capacity limits, graph job concurrency one, explicit full-index start, retention, and scaling controls.
5. Replace whole-stack custom teardown with `azd down --purge`; keep app-level data cleanup explicit and confirmed.

## Phase 6 — Validation and CI

1. Bicep lint/build, output-contract tests, subscription what-if, and `azd provision --preview` where supported.
2. Static policy tests: HTTPS/TLS, local auth disabled, public access, secret handling, identities, RBAC, private DNS, diagnostics, tags, and architecture conditions.
3. Build and inspect the GraphRAG job image; run local frontend/API checks independently of Azure provisioning.
4. Repair and pin CI actions, including current unresolved `azure/cli@v2` usage.
5. Ephemeral integration deployment: `azd provision`, Search initialization, localhost UI/API smoke against azd outputs, GraphRAG sample, query/citations, then `azd down --purge` with proof.

## Phase 7 — Parallel migration and cutover

1. Deploy a new azd environment beside the protected live resource group.
2. Copy only approved canonical data; rebuild indexes from manifests.
3. Validate Steps 1–7 from the local application against the new environment, including auth, status, errors, evidence, and teardown.
4. Switch the local environment output/configuration only after health/data parity and rollback tests.
5. Delete the old environment only after explicit approval and backup/cost inventory.
6. Retire old Python ARM polling, random naming, `az containerapp up`, old Bicep, role shell-outs, and whole-stack teardown after parity.

## Current implementation checkpoint

- [x] Root infrastructure-only `azure.yaml` with cross-platform pre/post provision hooks.
- [x] Subscription-scoped `infra/main.bicep` and focused resource modules.
- [x] Managed identity, deterministic RBAC, Storage, AI Services, Search, ACR, monitoring, and GraphRAG Job definitions.
- [x] Removed SvelteKit/FastAPI azd services and Azure Container Apps from the current topology.
- [x] Hook behavior tests cover region persistence, protected environments, and canonical corpus handling.
- [x] Rebuild Bicep and inspect the emitted ARM resource types after the infrastructure-only pivot.
- [x] Rerun focused frontend/API tests and full local validation.
- [x] Run `azd provision --preview` and subscription-scope ARM validation against a new environment only.
- [ ] Obtain explicit approval before provisioning the validated isolated environment.
- [ ] Run an approved GraphRAG sample before any canary or full-corpus execution.

## Local validation evidence — 2026-07-11

- Bicep build passed; compiled topology contains 0 hosted Container Apps, 1 manual Container Apps Job, and 1 managed environment.
- `azure.yaml`, deployment-plan Markdown, and Bicep editor diagnostics report no errors.
- Svelte check: 0 errors and 0 warnings.
- Vitest: 11 files and 88 tests passed; focused deployed-read routing: 8 tests passed.
- SvelteKit adapter-node production build passed.
- Frontend Prettier and ESLint checks passed.
- Python: 391 tests passed and 2 platform-capability tests skipped.
- azd hook regression suite: 5 tests passed.
- Ruff passed for the Plan 03 hook implementation and tests. Repository-wide Ruff still reports legacy findings in untouched files and remains a separate cleanup gate.
- Official `azure.yaml` schema validation, regional availability, quota checks, assigned-policy review, azd what-if, and subscription-scope ARM validation passed for the isolated validation environment in `northcentralus`.
- Static RBAC review removed a redundant Search reader assignment and replaced deployer `AcrPush` with Container Registry Tasks Contributor, which grants the quick-build operations used by `az acr build`.
- Non-mutation proof: the preview succeeded while the isolated validation resource group remained absent.
- No Azure deployment, paid GraphRAG execution, or mutation of the protected live resource group occurred.

## Key files

- `.azure/deployment-plan.md`
- New `azure.yaml`, `infra/`, `scripts/`
- `retrieve-core/src/retrieve/provision/orchestrator.py`
- `retrieve-core/src/retrieve/provision/naming.py`
- `retrieve-core/src/retrieve/provision/teardown.py`
- `retrieve-core/src/retrieve/provision/bicep/`
- `retrieve-core/Dockerfile.graphrag-job`
- `.github/workflows/ci.yml`
- `README.md`, future `ARCHITECTURE.md`, operations docs

## Acceptance criteria

- Repeated `azd provision` is idempotent.
- The compiled ARM template contains no hosted SvelteKit/FastAPI application resource.
- Outputs match hook and localhost application contracts exactly.
- Managed identities have only required access; local key auth fails.
- Private service names resolve correctly from workloads.
- Ephemeral deployment passes local UI/API-to-Azure, Search, and GraphRAG sample/query tests and cleans up fully.
- Migration has tested rollback and does not mutate the protected live resource group before cutover approval.
