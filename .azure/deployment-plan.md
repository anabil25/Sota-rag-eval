# Retrieve Azure Modernization Deployment Plan

**Status:** Validated and Authorized — Deployment Execution Pending  
**Approved by:** User (“Start implementation”, 2026-07-10)  
**Live deployment authorized by:** User (“actually deploy and test live”, 2026-07-11)  
**Mode:** Modernize existing application in a parallel Azure environment  
**Deployment path:** Azure Developer CLI (`azd`) + subscription-scoped modular Bicep  
**Current live environment:** protected existing resource group — preserve; no destructive changes during implementation

## 1. Objective

Replace the ad-hoc Python/CLI provisioning path with a deterministic, idempotent `azd` solution-accelerator contract while repairing GraphRAG correctness, securing mutating operations, and preserving rollback. Retrieve remains local-first: its SvelteKit UI, FastAPI control plane, and SQLite history run on localhost and consume the provisioned Azure resource outputs.

## 2. Approved Workstreams

1. GraphRAG end-to-end recovery.
2. Repository cleanup and source/runtime boundary normalization.
3. `azd` and Bicep modernization modeled on the deployment discipline in `abKrazy/ITHelpdesk`.
4. Critical bug and security pass.

Detailed plans will be stored under `docs/plans/`.

## 3. Safety Constraints

- Do not start another full paid GraphRAG run until sample and canary gates pass.
- Do not mutate or delete the protected live resource group during implementation.
- Do not delete corpus generations, databases, or runtime artifacts until they are inventoried and backed up.
- Do not modify upstream GraphRAG or LightRAG source.
- Use a new `azd` environment and resource group for deployment validation.
- Destructive Azure operations require explicit approval.

## 4. Target Architecture

- Localhost SvelteKit UI, FastAPI operation/query API, and SQLite history; none are deployed by the current azd contract.
- Azure Storage, AI Services model deployments, AI Search, ACR, monitoring, and managed identity/RBAC for retrieval experiments.
- Container Apps managed environment dedicated to remote graph workloads.
- Manual Container Apps Job for GraphRAG indexing.
- Azure Storage for canonical corpus and persistent GraphRAG output/cache/reporting.
- Azure AI Search for standard retrieval and GraphRAG vectors.
- Azure AI Services model deployments with managed identity.
- Log Analytics and Application Insights.
- User-assigned managed identities with least-privilege RBAC.
- Cosmos DB removed from the default GraphRAG path unless a tested requirement is approved.
- No `services:` entries or hosted UI/API Container Apps in the current deployment phase.

## 5. Implementation Sequence

- [x] Persist approved plans and baseline evidence.
- [x] Add immediate security/cost containment, operation API authorization, and job admission control.
- [x] Repair canonical corpus generation, manifest validation, and exact Blob mirroring.
- [x] Pin and validate the GraphRAG 3.1 configuration contract.
- [x] Add persistent GraphRAG storage, callbacks, structured query evidence, and reconciliation.
- [x] Scaffold root infrastructure-only `azure.yaml`, subscription Bicep, modules, and hooks.
- [x] Centralize operational writes and durable jobs.
- [x] Validate the narrowed IaC locally: compile Bicep, inspect resource types, and prove no hosted UI/API resources are emitted.
- [x] Run focused and full offline validation for the Plan 03 deployment slice.
- [ ] Run `azd`/Bicep preflight in a new environment.
- [ ] Run Azure sample and 10% canary.
- [ ] Perform final critical-bug sign-off.
- [ ] Clean obsolete repository/runtime/IaC assets after parity.

## 6. Validation Requirements

- Python lint and tests pass.
- Svelte type check, lint, unit tests, and build pass.
- GraphRAG generated config parses under exactly `graphrag==3.1.0` with active retry/rate limiting.
- Canonical corpus has valid YAML and local/Blob manifest parity.
- Mutating operations require authentication/authorization and job admission control.
- Bicep lint/build and subscription-scope what-if pass.
- The compiled template contains no hosted SvelteKit/FastAPI application resource.
- `azd provision` is idempotent in a new environment.
- Localhost UI/API can consume the azd output contract without a deployed application service.
- GraphRAG sample index and structured evidence query pass before canary/full runs.

### 6.1 Azure Validation Checklist

- [x] All validation checks pass.
	- [x] Azure Developer CLI 1.27.1 and Azure CLI 2.84.0 are installed.
	- [x] `azure.yaml` passes the official stable-schema validator.
	- [x] Disposable local azd environment targets an isolated validation resource group, not the protected live resource group.
	- [x] azd authentication and the selected subscription context are valid.
	- [x] `northcentralus` supports every declared resource type and has Search, Container Apps, Storage, AI Services, and required model quota.
	- [x] This is not an Aspire project; Aspire checks do not apply.
	- [x] `azd provision --preview --no-prompt` completes without errors.
	- [x] Local SvelteKit and Python build/test verification passes.
	- [x] The GraphRAG Docker build context is valid; no azd application service package step applies.
	- [x] Assigned Azure Policy permits ARM validation and what-if for the previewed resource topology.
	- [x] Bicep compiles and lints without diagnostics.
	- [x] Subscription-scope template validation and what-if complete without errors.

### 6.2 Static Role Assignment Verification

- **GraphRAG job identity:** ACR Pull, Storage Blob Data Contributor, Cognitive Services OpenAI User, Search Service Contributor, and Search Index Data Contributor at individual resource scope.
- **Search service identity:** Storage Blob Data Reader and Cognitive Services OpenAI User at individual resource scope for indexers and embedding skills.
- **Local deployer:** Storage Blob Data Contributor, Cognitive Services OpenAI User, Search Service Contributor, Search Index Data Contributor, and Container Registry Tasks Contributor at individual resource scope.
- **Least privilege fixes:** removed the redundant Search Index Data Reader assignment; replaced insufficient `AcrPush` with Container Registry Tasks Contributor for `az acr build`.
- **Remaining live check:** preview must prove the signed-in principal can create deterministic role assignments; postprovision must later prove ACR role propagation and job update authorization.

## 7. Validation Proof

The current implementation is locally validated; Azure preview and deployment are not
yet validated.

- Compiled Bicep topology: 0 hosted Container Apps, 1 manual Container Apps Job, and
	1 managed environment.
- Svelte check: 0 errors and 0 warnings.
- Vitest: 11 files and 88 tests passed; focused local/deployed read routing: 8 passed.
- SvelteKit adapter-node production build passed.
- Frontend Prettier and ESLint checks passed.
- Full Python suite: 391 passed, 2 platform-capability skips.
- azd hook tests: 5 passed.
- Ruff passes for the Plan 03 Python hook implementation and tests. Existing
	repository-wide Ruff findings in untouched legacy files remain tracked separately.
- Installed package proof: `graphrag=3.1.0`.
- Generated-config proof: `GraphRagConfig` parses the shared settings with active
	`rate_limit` and `retry.max_retries=12`; unexpected Pydantic extras are rejected.
- Azure safety: no deployment, paid GraphRAG execution, or mutation of the protected live resource group
	occurred in this batch.
- azd preview: succeeded in 22 seconds for the isolated validation environment in `northcentralus`; the
	preview contains only the resource group, retrieval dependencies, and one GraphRAG Job.
- Subscription-scope ARM validation: `Succeeded` with no error.
- Non-mutation proof: `az group exists` returned `false` for the isolated validation resource group after
	preview and validation.
- Policy/quota proof: assigned policies were retrieved; ARM accepted the topology;
	Search Basic has 12 available services, and the requested GPT-4.1 and embedding
	capacities are within regional quota.
- RBAC proof: redundant Search reader access was removed, and the deployer now receives
	Container Registry Tasks Contributor for the `az acr build` hook instead of the
	insufficient `AcrPush` role.

## 8. Rollback

- Keep the protected live resource group unchanged and available during parallel validation.
- Use immutable data/index prefixes and atomic current-index promotion.
- Keep corpus and SQLite backups until post-cutover approval.
- Cut back to the existing endpoint/environment if any acceptance gate fails.
