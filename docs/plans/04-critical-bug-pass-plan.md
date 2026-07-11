# Plan 4 — Critical Bug and Security Pass

**Status:** Local P0/P1 pass complete; disposable live canary pending
**Priority:** P0
**Last updated:** 2026-07-11

## Goal

Run an adversarial, evidence-based audit across the complete Step 1–7 workflow and deployed trust boundaries. Prioritize unauthorized mutation, runaway spend, data loss/corruption, false readiness/success, invalid evaluation, unrecoverable jobs, and outages. Findings require reproduction and evidence; speculation is not marked confirmed.

## Confirmed release blockers

- GraphRAG/corpus/query/persistence failures documented in Plan 1.
- Search/index orchestration can exhaust retries and still mark architectures active.
- Mutating operation jobs are exposed without authentication/authorization in current FastAPI code.
- Jobs are process-memory-only and disappear on backend restart.
- Concurrent mutating jobs share one config, DB, corpus, and Azure environment without admission locking.
- SvelteKit and FastAPI both write the same SQLite session state with no shared cross-runtime write protocol.
- Mutable `retrieve.yaml` writes are non-atomic.
- Async graph status is not automatically reconciled into SQLite.
- CI reports unresolved `azure/cli@v2` action usage.

## Rejected preliminary false positives

- Cosmos SQL role IDs ending in `...0001` and `...0002` are valid built-ins.
- Evaluation calls `db.complete_run()`.
- Provisioning updates architecture status to provisioned.
- `operation()` re-raises exceptions after logging.
- The inspected large Search content field is searchable-only, not currently filterable.

## Implementation progress — batch 1

- [x] Reproduced the false-active defect with six failed indexer attempts.
- [x] Replaced unconditional `active` writes with explicit `failed`, `indexing`, and
	`active` status transitions.
- [x] Added backend and worker cost admission for GraphRAG full/sample/canary runs.
- [x] Kept resource-group creation fail-fast; updated the stale test that expected a
	provisioning error to be swallowed.
- [x] Updated stale REST indexer polling and evaluation-readiness fixtures without
	weakening production gates.
- [x] Full Python result: 343 passed, 2 platform/optional skips; changed files pass Ruff
	and editor diagnostics.
- [x] Authentication/authorization, durable jobs, admission/idempotency, mutual
	exclusion, atomic config, reconciliation, canonical evidence, and durable event
	replay are implemented and tested.

## Current completion checkpoint — 2026-07-11

- [x] Mutation authentication/role enforcement and loopback-only local mode.
- [x] Durable jobs, idempotency, request hashing, one active environment mutation, restart interruption handling, and redaction.
- [x] Durable bounded SSE event journal with sequence IDs and `Last-Event-ID` replay.
- [x] FastAPI single-writer state ownership, WAL, schema-version rejection, locked atomic YAML replacement, and azd output synchronization.
- [x] Canonical manifest aliases unify Search, GraphRAG, LightRAG, and historical eval IDs.
- [x] Evaluation failures mark only the affected run failed and never publish partial success.
- [x] LightRAG 1.5 API compatibility, managed identity, explicit storage lifecycle, bounded sample indexing, failure propagation, and structured evidence.
- [x] Removed the unused unauthenticated OpenAI proxy and all non-deployed application images.
- [x] Pinned CI actions/Bicep; full Ruff, frontend gates, root Bicep, and non-root GraphRAG image are CI contracts.
- [ ] Run the complete workflow against the disposable Azure environment, including RBAC propagation, Search/index/query failures, graph restart/timeout evidence, and cleanup.
- [ ] Publish final P0/P1 disposition and residual-risk recommendation after the live sample/canary.

## Phase 0 — Evidence and safe boundaries

1. Create a bug register with severity, evidence, reproduction, owner, regression test, and disposition.
2. Define P0/P1/P2 criteria.
3. Use isolated local fixtures and a disposable Azure environment; do not mutate the protected live resource group.
4. Capture baseline checks and known failures.

## Phase 1 — Authentication, authorization, and cost control

1. Threat-model UI, SvelteKit routes, FastAPI API, GraphRAG/query, proxy, LightRAG, Jobs, Storage, Search, and AI.
2. Verify deployed endpoint exposure and require Entra identity plus application authorization for mutation.
3. Add permission matrix and CSRF controls where browser cookies apply.
4. Add job kind allowlist, authorization, per-environment mutual exclusion, idempotency key, request validation, cost ceiling, and confirmations for destructive/expensive jobs.
5. Audit SSRF/path traversal on sources, paths, imports/exports, proxy paths, Blob prefixes, and arbitrary endpoints.
6. Audit secrets/tokens across env, logs, DB, azd outputs, SSE, images, Bicep, and proxy headers.

## Phase 2 — Durable jobs and events

1. Reproduce backend restart during every long operation.
2. Add durable job records: state, owner, kind, idempotency, args hash, external execution, result/error, heartbeat, timestamps.
3. Reconcile external Azure jobs on startup and refresh.
4. Test/fix SSE completion-subscription race, reconnect, replay, multiple subscribers, disconnect, restart, ordering, bounds, and retention.
5. Reject or queue conflicting environment mutations.
6. Add authorized cancellation with external stop, terminal state, retained partial artifacts, unchanged current alias, and safe retry.

## Phase 3 — SQLite/config integrity

1. Stress Python and Node SQLite together; measure locks and lost updates.
2. Make FastAPI the sole operational write owner; SvelteKit proxies writes and remains read-only if direct DB access is retained.
3. Use version/CAS semantics for session patches.
4. Configure compatible read-only/busy-timeout/schema behavior for any Node read connection.
5. Replace YAML writes with atomic validated replace under lock or move runtime mutation to azd/DB state.
6. Add transactional migration, backup, newer-version rejection, and integrity tests.
7. Scope architecture history by environment/resource token and test latest-row semantics.

## Phase 4 — Retrieval/evaluation correctness

1. Define and test canonical IDs across ingestion, Search modes, GraphRAG, LightRAG, and scoring.
2. Use controlled questions and assert recall/MRR/nDCG for every architecture.
3. Verify Search projections include every queried identity field.
4. Fault-inject permission, schema, vector, quota, malformed document, and network failures.
5. Ensure exhausted index retries persist failure and never mark active.
6. Label or remove unimplemented/no-op SOTA toggles.
7. Mark failed/partial evaluation runs correctly and never present partial aggregates as complete.
8. Validate cost estimates against measured Azure usage and deployed SKUs.

## Phase 5 — Graph, LightRAG, proxy, and model failures

1. Execute all Plan 1 GraphRAG gates.
2. Test LightRAG auth, duplicate ingestion, partial batch failure, backoff, restart, query, and evidence.
3. Require inbound auth and path/method restrictions for the OpenAI proxy; test streaming, limits, timeout, token renewal, sovereign cloud, and redaction.
4. Verify model names, versions, dimensions, quota, and RBAC match deployment outputs.
5. Add circuit breakers for sustained 429s and runaway token generation.

## Phase 6 — Containers, CI, and supply chain

1. Build each service image from a clean checkout and inspect health, user, packages, layers, secrets, shutdown, and context.
2. Retire the combined image if it cannot satisfy split SvelteKit/FastAPI deployment cleanly.
3. Run npm/Python vulnerability and license checks, critical package review, SBOM, and image scans.
4. Repair/pin Actions and split CI jobs.
5. Validate Bicep security/policy and generated-artifact drift.

## Phase 7 — Disposable Azure canary and sign-off

1. Deploy through Plan 3 to a disposable environment.
2. Test quota/name/policy/RBAC/DNS/Search/image/job/restart failures and rollback.
3. Verify correlated observability and spend signals without content leakage.
4. Run complete Step 1–7 tiny-fixture canary with refresh/restart at each step.
5. Fix all P0; fix or explicitly mitigate every P1.
6. Publish final report with confirmed/rejected findings, residual risk, and production recommendation.

## Priority queue

1. Unauthenticated mutation and missing job admission.
2. Plan 1 GraphRAG/corpus/query defects.
3. False active status after index failure.
4. Non-durable job state and missing reconciliation.
5. Concurrent mutating jobs.
6. SSE race/replay.
7. Cross-runtime SQLite writes.
8. Non-atomic YAML writes.
9. Canonical evidence IDs.
10. Proxy/LightRAG auth and inference protection.
11. Container context/layer correctness.
12. CI/dependency/supply-chain failures.

## Key files

- `retrieve-core/src/retrieve/web/app.py`
- `retrieve-core/src/retrieve/observability.py`
- `src/routes/api/[...path]/+server.ts`
- `src/lib/server/db.ts`
- `retrieve-core/src/retrieve/db.py`
- `src/lib/server/clients/operation-api-client.ts`
- `retrieve-core/src/retrieve/indexing/run.py`
- `retrieve-core/src/retrieve/indexing/search_index.py`
- `retrieve-core/src/retrieve/indexing/advanced.py`
- `retrieve-core/src/retrieve/eval/runner.py`
- GraphRAG, LightRAG, and proxy modules
- Dockerfiles, `.dockerignore`, `.github/workflows/ci.yml`

## Acceptance criteria

- No public unauthenticated mutation endpoints.
- Durable restart-safe jobs with correct reconciliation/cancellation.
- One authoritative state writer and no lost session updates.
- Architectures become active only after real query validation.
- Controlled retrieval fixtures produce correct evidence and metrics.
- Zero open P0 and no unmitigated P1 in auth, data integrity, readiness, query, or cost.
