# Graph Rollout

GraphRAG is cost-gated. Full-corpus execution remains locked until representative sample and canary evidence pass.

## Preconditions

- canonical corpus manifest validates locally and matches Blob;
- GraphRAG package is exactly `3.1.0`;
- GraphRAG image runs non-root;
- job identity can read/write Blob, query/manage Search indexes, and call Azure AI models;
- architecture config contains the job name, immutable corpus fingerprint, and selected run controls;
- no other environment mutation owns admission.

## Representative sample

Use `graphrag_run_scope=sample` and `graphrag_max_documents<=50`. Start three immutable runs with chunk sizes `100`, `300`, and `600`. Use an overlap below each chunk size.

Document IDs are generated from the active corpus manifest; the accelerator does not require a predefined ID scheme or corpus-specific configuration. When a selected eval set has grounded questions, its canonical evidence IDs may be pinned into the bounded sample so the quality benchmark covers those questions. The remaining slots are selected deterministically across the corpus. With no grounded eval evidence, the same sampler works with no pinned IDs and selects the entire bounded sample across the corpus.

For every run, retain:

- Azure execution name and terminal state;
- immutable `runs/<fingerprint>/<job-id>` prefix;
- workflow results, heartbeat, duration, and errors;
- model request/token/throttle metrics;
- output table/report counts and graph density;
- at least one structured local query with canonical document IDs and citations;
- evaluation metrics against the same representative question subset.

Select a chunk size from measured retrieval quality, graph usefulness, duration, and cost. Do not select solely by speed.

## Canary

Use `graphrag_run_scope=canary` and `graphrag_max_documents<=500`. Abort when:

- any workflow fails;
- the Azure execution and durable Blob status disagree;
- 429 rate is at least 5%;
- projected duration/cost exceeds the approved tolerance;
- structured query evidence is missing or cannot map to the canonical manifest.

## Full run

A full run requires all sample/canary gates and `RETRIEVE_GRAPHRAG_FULL_RUN_APPROVED=true`. It cannot set a document cap. The timeout must be based on measured canary throughput plus a documented safety margin.

## Failure handling

- Never mutate a successful immutable run.
- Never write directly to `indexes/current`.
- Container Apps execution failure overrides stale running Blob status.
- A successful execution without a successful durable status is a failure.
- Preserve partial artifacts and diagnostics; retry with a new job ID.
- Capacity failure may trigger the next whole-stack region only during environment provisioning, not while an index run is active.
