# Retrieve Recovery Program Plans

These four plans are separate ownership tracks but share release gates.

1. [GraphRAG recovery](01-graphrag-recovery-plan.md)
2. [Repository cleanup](02-repository-cleanup-plan.md)
3. [azd/Bicep modernization](03-azd-bicep-modernization-plan.md)
4. [Critical bug and security pass](04-critical-bug-pass-plan.md)

## Execution order

1. Contain unauthenticated/expensive operations and freeze full GraphRAG starts.
2. Establish a safe repository backup/quarantine baseline.
3. Repair canonical corpus and GraphRAG 3.1 contracts.
4. Scaffold a parallel azd environment after `.azure/deployment-plan.md` approval.
5. Fix durable jobs, status reconciliation, SQLite write ownership, readiness, and evidence IDs.
6. Validate/deploy only to a disposable or parallel environment.
7. Run representative GraphRAG sample and 10% canary.
8. Complete the adversarial Step 1–7 bug pass.
9. Perform destructive repository/old-environment cleanup last.

## Global release gates

- No unauthenticated mutation or unrestricted expensive job start.
- One reviewed canonical corpus with valid YAML and Blob manifest parity.
- Pinned GraphRAG config with recognized retry/rate-limit settings.
- Persistent graph output/cache/reporting and verified query evidence.
- Durable job/status/event state that survives restarts.
- No architecture marked active before query smoke validation.
- Bicep/azd validation proof and idempotent repeated deployment.
- Zero open P0 and no unmitigated P1 in auth, data integrity, readiness, query, or cost.
- Clean clone passes documented offline setup, tests, builds, and image checks.
