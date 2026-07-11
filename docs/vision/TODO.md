# Retrieve — Build TODO

> Design context: [Retrieve.md](Retrieve.md)
> All work items reference phases and concepts defined there.
>
> **Status (April 15, 2026):** Core pipeline works end-to-end for keyword, single-vector, hybrid, hybrid-reranker, and hybrid-llm-enriched architectures via CLI and Web UI. Web UI is a 6-step wizard (Ingest → Eval → Mode → Configure → Provision → Compare) plus History and Settings pages. 42 mock E2E tests passing; live E2E test passing against real 305-doc corpus on Azure. Eval generation uses batched parallel Copilot SDK calls (BATCH_SIZE=20) across 4 category groups. Bicep covers Storage + AI Services + AI Search + roles. GraphRAG/LightRAG/Agentic KB/multi-vector are registered in the architecture registry but not yet provisioned or indexed.
>
> Copilot SDK reference: [copilot-sdk/](copilot-sdk/) — Python SDK at `copilot-sdk/python/`
> Copilot CLI reference: [copilot-cli/](copilot-cli/) — feature set at `copilot-cli/feature-set.md`
>
> Azure skills: [skills/](skills/) — 10 skill files covering all Azure services used by Retrieve
> Service matrix: [service-matrix.md](service-matrix.md) — which architectures spin up which resources, deployment order, role assignments, costs
> Search API spec: [search.json](search.json) — Azure AI Search `2025-11-01-preview` Swagger (includes Knowledge Bases / agentic retrieval)

---

## 0. Project scaffold

> Skills: none (pure Python scaffolding)

- [x] Init Python project: `pyproject.toml`, `src/retrieve/`, `tests/`
- [x] Dependencies: `github-copilot-sdk`, `azure-search-documents`, `azure-storage-blob`, `azure-identity`, `requests`, `typer`, `pydantic`, `graphrag` (optional), `lightrag-hku` (optional)
- [x] CLI entrypoint via `typer` — subcommands: `ingest`, `eval`, `provision`, `index`, `teardown`, `info`
- [x] Config system: YAML config file (`retrieve.yaml`) for corpus path, Azure creds, mode selection, architecture list, Copilot SDK settings (model, BYOK provider config)
- [x] Logging setup: structured logs, verbosity flag
- [x] SQLite module: create/open DB, migrations, shared connection helper (`db.py`)

---

## 1. SQLite schema & data layer

> Skills: none (pure Python/SQLite)
> Backs eval set versioning, run history, and iteration comparisons across both modes.

- [x] `eval_sets` table: id, version label, created_at, question_count, category_counts (JSON), notes
- [x] `eval_questions` table: id, eval_set_id, question_text, category, ground_truth_chunk_ids (JSON), source_doc_id
- [x] `runs` table: id, eval_set_id, mode (test|sota), architecture_config (JSON), created_at, status, aggregate_metrics (JSON)
- [x] `run_results` table: id, run_id, question_id, retrieved_chunk_ids (JSON), scores (JSON: recall@5, recall@10, mrr@10, ndcg@10), latency_ms
- [x] `architectures` table: id, name, config (JSON), resources_provisioned (JSON), status (provisioned|active|torn_down), created_at
- [x] Query helpers: get latest eval set, get all runs for an eval set, compare N runs side-by-side, get failures for a run
- [x] Version migration support (schema_version table)

---

## 2. Corpus ingestion (`retrieve ingest`)

> Skills: none (pure Python, ports logic from `alaska policy eval/ingest.py`)
> See Retrieve.md Phase 1.

- [x] Ingestion plugin interface: base class with `discover()`, `fetch()`, `convert()` methods
- [x] HTML/RoboHelp plugin: discover pages from TOC JS, fetch .htm, convert to Markdown (ported from `alaska policy eval/ingest.py`)
- [x] PDF plugin: extract text per page, split by heading structure, convert to Markdown
- [x] Markdown passthrough plugin: accept pre-existing .md files, validate frontmatter
- [x] YAML frontmatter writer: `policy_id`, `title`, `parent`, `source_url`, `last_ingested`, `cross_references`
- [x] Cross-reference extractor: parse internal links, populate `cross_references` in frontmatter
- [x] Corpus stats output after ingest: doc count, avg length, cross-ref density, detected categories — used by SOTA mode to recommend a path
- [x] CLI: `retrieve ingest --source <url|path> --plugin <html|pdf|markdown> --output <dir>`

---

## 3. Golden eval set generation (`retrieve eval generate`)

> Skills: `copilot-sdk/python/README.md`, `copilot-sdk/docs/getting-started.md`, `copilot-sdk/docs/features/custom-agents.md`, `copilot-sdk/docs/auth/byok.md`
> See Retrieve.md Phase 2.

- [x] Chunk loader: read all .md files from corpus dir, split into chunks (heading-based), track chunk→doc mapping
- [x] Copilot SDK session for question generation:
  - Create `CopilotClient()`, start, `create_session()` with model from config
  - System message: instructs the model to generate N questions per chunk with category labels and ground-truth pairing
  - Use `send_and_wait()` per chunk — parse structured JSON output from response
  - BYOK support: provider block passed to `create_session({ "provider": ... })`
  - Model selection: respects `retrieve.yaml` copilot.model setting, default `gpt-4o`
  - Batched generation: BATCH_SIZE=20 chunks per prompt, parallel batches within each category group
  - 4 category groups (single_doc, cross_doc, cross_section, unanswerable) run in parallel via asyncio.gather
  - sample mode (~25 questions) and full mode (~⅔ of docs) with category mix percentages
  - Intent map derivation via LLM (corpus summary → intent families + challenge mix)
- [x] Define `@define_tool` for `get_chunk` and `get_chunks_by_doc` — exposes chunk content to the Copilot session (Pydantic input schema)
- [x] Streaming progress: subscribe to `session.on()` events, show `assistant.message_delta` for real-time progress in terminal
- [x] Category auto-assignment: LLM-based classification into 5 categories via system message
- [x] Ground truth pairing: each question → list of chunk IDs that answer it
- [x] Deduplication: detect near-duplicate questions across chunks (text similarity threshold)
- [x] Output: write eval set to SQLite (`eval_sets` + `eval_questions`) with category counts
- [x] CLI: `retrieve eval generate --corpus <dir> --questions-per-chunk N --output <eval_set_version>`

---

## 4. Eval set curation (`retrieve eval curate`)

> Skills: `copilot-sdk/python/README.md`, `copilot-sdk/docs/features/steering-and-queueing.md`, `copilot-sdk/docs/features/streaming-events.md`
> See Retrieve.md Phase 2 Step 2. Category-level steering, not per-question.

- [x] Curation core (`eval/curate.py`):
  - Show category summary table: category name, count, example questions
  - Category-level steering: "more", "fewer", "remove", "add category"
  - Regeneration via Copilot SDK: builds steered system message, generates targeted questions
  - Versioning: curation creates a new eval set version, preserving the original
- [x] CLI: `retrieve eval curate --eval-set <version> --more cross_document --fewer direct_lookup --output v2`
- [x] REST API: `POST /api/eval/curate` with steering JSON body
- [x] Curation UI page in web app (category-level controls, regenerate button)
- [x] Copilot SDK streaming progress forwarded to UI
- [x] Use `mode: "enqueue"` for queued regeneration

---

## 5. Architecture & model registries

> Skills: `skills/embedding-models.md`, `skills/azure-ai-search.md`, `skills/azure-ai-search-agentic.md`, `skills/graphrag-lightrag.md`, `service-matrix.md`
> See Retrieve.md Phase 3 (both modes).

### Architecture registry

- [x] Registry data structure: name, description, expected_accuracy (★), cost ($), latency (★), required_azure_resources, supported_toggles
- [x] Built-in architectures:
  - `keyword` — AI Search keyword-only index
  - `single-vector` — AI Search with vector field + embedding model
  - `hybrid` — AI Search keyword + vector, RRF fusion
  - `hybrid-reranker` — hybrid + Azure semantic reranker
  - `hybrid-llm-enriched` — hybrid + reranker + ChatCompletionSkill at index time
  - `multi-vector` — BGE-M3 dense + sparse + ColBERT multi-vector
  - `agentic-kb` — Azure AI Search Knowledge Bases API (preview)
  - `graphrag` — Microsoft GraphRAG
  - `lightrag` — LightRAG graph-augmented retrieval
- [ ] ~~Custom architecture registration~~ — **moved to Future**

### Model registry

- [x] Registry data structure: name, dimensions, mteb_avg, cost_per_1m_tokens, latency_p50, notes, provider
- [x] Built-in models: text-embedding-3-small, text-embedding-3-large, BGE-M3, Cohere embed-v3
- [x] Reranker registry: bge-reranker-v2-m3, Rank1, Azure semantic ranker, Cohere reranker
- [ ] ~~Custom model registration~~ — **moved to Future**

### SOTA path registry

- [x] Data structure: use_case_name, description, architecture, ordered component list with defaults and toggle options
- [x] Ship with initial paths: government-policy, product-docs, legal-contracts, knowledge-base-faq
- [x] Corpus heuristic recommender: given ingestion stats (doc count, avg length, cross-ref density), suggest a SOTA path
- [x] Toggle combination generator: enumerate all meaningful component variants for SOTA eval mode

---

## 6. Azure provisioning (`retrieve provision`)

> Skills: `skills/azure-bicep-iac.md`, `skills/azure-ai-foundry.md`, `skills/azure-blob-storage.md`, `skills/azure-ai-search.md`, `skills/azure-cosmos-db.md`, `skills/azure-functions.md`, `skills/embedding-models.md`, `service-matrix.md`
> See Retrieve.md Phase 4. All resources use managed identity, no keys.

- [x] Bicep templates — modular structure:
  - `modules/storage.bicep` — Storage account + blob container (allowSharedKeyAccess: false)
  - `modules/ai-services.bicep` — AI Foundry account + sequential model deployments
  - `modules/search.bicep` — AI Search service + managed identity + optional semantic search
  - `modules/search-roles.bicep` — Search→Blob Reader, Search→OpenAI User role assignments
  - `main.bicep` — orchestrator: conditionally deploys based on selected architectures
  - `modules/cosmos.bicep` — Cosmos DB for NoSQL (Serverless) for GraphRAG graph artifact store
  - `modules/functions.bicep` — Azure Functions (Flex Consumption, Python) for GraphRAG query endpoint
  - `modules/container-apps.bicep` — Container Apps + managed environment for LightRAG server
- [x] Role assignments per `service-matrix.md` Role Assignment Matrix — managed identity, no keys
- [x] Deployment order enforced: Storage → AI Foundry → AI Search → Role Assignments
- [x] Provision orchestrator (`provision/orchestrator.py`): deploy Bicep, track resources in SQLite
- [x] SOTA mode provisioner: per-variant index provisioning
- [x] Idempotent: re-running provision skips already-provisioned architectures
- [x] CLI: `retrieve provision`

---

## 7. Corpus indexing (`retrieve index`)

> Skills: `skills/azure-blob-storage.md`, `skills/azure-ai-search.md`, `skills/azure-indexer-pipeline.md`, `skills/azure-ai-search-agentic.md`, `skills/embedding-models.md`, `skills/graphrag-lightrag.md`
> Upload corpus to blob, configure search indexes per architecture.

- [x] Blob uploader (`indexing/blob_upload.py`): upload .md files to blob container using managed identity
- [x] Per-architecture index builder (`indexing/search_index.py`):
  - Keyword: text fields, markdown parsing mode, blob data source
  - Hybrid: text + vector fields, AzureOpenAIEmbeddingSkill, SplitSkill, AzureOpenAIVectorizer
  - Hybrid-reranker: hybrid + SemanticConfiguration
  - Multi-vector: BGE-M3 multi-vector with AML skill + AML vectorizer
  - Agentic KB: Knowledge Source + Knowledge Base on existing hybrid index
  - GraphRAG: graphrag package indexer + Cosmos DB store + Functions query
  - LightRAG: lightrag-hku indexer + Container Apps query
- [x] Wait for indexer completion, report document counts
- [x] Indexing orchestrator (`indexing/run.py`): upload → create indexes → wait → update status
- [x] CLI: `retrieve index`
- [x] SOTA mode indexer: per-variant index creation

---

## 8. Evaluation runner (`retrieve eval run`)

> Skills: `skills/azure-ai-search.md` (query API), `skills/azure-ai-search-agentic.md` (KB retrieve endpoint), `skills/graphrag-lightrag.md` (GraphRAG/LightRAG query), `copilot-sdk/python/README.md` (failure classification)
> See Retrieve.md Phase 5.

- [x] Query executor: for each question in the eval set, query the target architecture's search endpoint directly via REST API, collect top-K results with latency
- [x] Copilot SDK for failure classification:
  - For each missed question (ground truth not in top-10), create a Copilot session with a classification prompt
  - Send the question, expected chunk, and top-ranked wrong chunk → model classifies failure type (vocabulary mismatch / semantic gap / cross-ref miss / chunking boundary)
  - Use `send_and_wait()` with structured JSON output parsing
  - Batch failure classification to minimize session overhead
- [x] Metric calculator:
  - Recall@5, Recall@10: fraction of ground-truth chunks in top-K results
  - MRR@10: reciprocal rank of first relevant result
  - nDCG@10: normalized discounted cumulative gain
- [x] Per-question results stored in `run_results` table
- [x] Aggregate metrics stored in `runs` table
- [x] Per-category aggregation: group questions by category, compute metrics per group
- [x] Failure collector: store failure classifications from Copilot SDK session in `run_results`
- [x] Latency tracking: per-query avg and p95
- [x] Cost estimation: compute estimated monthly cost based on provisioned SKUs + query volume assumption
- [x] Run against multiple architectures in parallel (ThreadPoolExecutor with --parallel flag)
- [x] CLI: `retrieve eval run --eval-set <version> --architectures <all|name1,name2> --config <retrieve.yaml>`

---

## 9. Comparison dashboard (`retrieve eval compare`)

> Skills: none (pure Python/HTML — reads from SQLite)
> See Retrieve.md Phase 5 dashboards (Test Mode and SOTA Eval Mode).

- [x] Web dashboard (self-contained HTML/JS):
  - **Test Mode view**: architecture comparison table (Recall@5, Recall@10, MRR@10, nDCG@10, latency, failures)
  - **SOTA Eval Mode view**: component delta table with Δ column
  - **Per-category breakdown**: table showing nDCG@10 per architecture × category
  - **Failure analysis panel**: list of failed queries per architecture, failure type + details
  - Tabbed interface with dark theme
- [x] Export: comparison table as CSV, full results as JSON
- [x] CLI fallback: `retrieve eval compare --runs <id1,id2,...>` — prints table to terminal
- [x] Web dashboard via `--web` flag: opens self-contained HTML in browser

---

## 10. Select & teardown (`retrieve teardown`)

> Skills: `skills/azure-bicep-iac.md` (teardown patterns, az CLI delete commands)
> See Retrieve.md Phase 6.

- [x] Selection UI: from the web dashboard, mark architecture(s) to keep
- [x] Teardown orchestrator (`provision/teardown.py`):
  - List all provisioned architectures from SQLite
  - Delete search resources (indexes, indexers, skillsets, data sources) for unselected architectures
  - Update `architectures` table: status → `torn_down`
  - Retain selected architecture resources, update status → `active`
- [x] Deployment summary output: shows active architectures with endpoint + index name
- [x] Safety: shows teardown plan table before executing
- [x] CLI: `retrieve teardown --keep <name1,name2>`

---

## 11. Web UI — primary interface

> Skills: `copilot-sdk/docs/setup/backend-services.md` (headless CLI server), `copilot-sdk/docs/features/streaming-events.md` (SSE forwarding), `copilot-cli/feature-set.md` (`--headless` flag)
> The web UI is the primary way users interact with Retrieve. The CLI remains for automation, scripting, and CI/CD.
> Both consume the same core modules — the UI is a FastAPI layer on top of the same Python functions the CLI calls.

### Backend
- [x] FastAPI app (`src/retrieve/web/app.py`) — wraps core modules, exposes REST API
  - All routes call the same functions as the CLI commands (no logic duplication)
  - SQLite-backed: reads/writes the same `retrieve.db` the CLI uses
  - Runnable locally: `retrieve ui` starts FastAPI on `localhost:8000`
  - Job runner with SSE progress streaming for all long-running operations
- [x] Copilot CLI headless server:
  - Start Copilot CLI in headless mode as a managed subprocess
  - SDK connects via `ExternalServerConfig` — single CLI process for all web UI operations
- [x] Real-time progress: SSE streaming from job runner to browser for ingest/generate/provision/index/evaluate/teardown

### Frontend
- [x] Inline HTML templates (no build step) with htmx support
- [x] Pages built:
  - **Ingest**: corpus upload/conversion with SSE progress
  - **Eval**: generate golden eval set with sample/full mode, CSV import/export, question browser
  - **Mode**: Test Mode vs SOTA Eval Mode selection
  - **Configure**: architecture and model selection
  - **Provision**: trigger Azure provisioning with SSE progress
  - **Compare**: full dashboard (architecture table, Δ nDCG, per-category, failure analysis)
  - **History**: iteration timeline with all runs
  - **Settings**: configuration management
- [x] REST API endpoints:
  - `GET /api/status`, `/api/runs`, `/api/runs/{id}`, `/api/eval-sets`, `/api/eval-sets/{id}/questions`
  - `GET /api/eval-sets/{id}/questions/browse` (filtered browsing with pagination)
  - `GET /api/eval-sets/{id}/summary`
  - `GET /api/architectures`, `/api/models`, `/api/sota-paths`
  - `POST /api/ingest`, `/api/eval/generate`
  - `POST /api/eval/export-csv`, `/api/eval/import-csv`
- [x] CLI: `retrieve ui --port 8000`
- [x] Provision/Run/Teardown pages (trigger from web via job runner)
- [x] Live streaming of Copilot SDK events (message_delta, tool calls) to UI

### Deferred UI features (commented out, implement later)
- [x] **Mode selection** (Step 3): Test Mode vs SOTA Mode toggle — drives architecture selection and eval shape downstream.
- [x] **Evaluate from UI** (Step 6): Run Eval button wired — uses latest eval set, runs all configured architectures. Comparison dashboard shows metrics, per-category nDCG@10, and miss analysis.
- [x] **Eval curation** (Step 2): SME curation UI — steer category mix (more/fewer of certain categories), add/remove questions, regenerate with steering.
- [x] **Teardown from UI**: Appears on Provision and Compare pages as a cleanup action with keep-list controls. CLI: `retrieve teardown --keep hybrid`.

### Frontend (legacy — merged above)
- [x] Tech choice: inline HTML templates with htmx — served by FastAPI, no build step
- [x] All 6-step wizard pages built: Ingest, Eval, Mode, Configure, Provision, Compare + History + Settings
- [x] CLI: `retrieve ui` launches the web UI; all `retrieve` subcommands work independently

---

## 12. Copilot SDK/CLI integration layer

> Skills: `copilot-sdk/python/README.md` (CopilotClient, create_session, define_tool, hooks, streaming), `copilot-sdk/docs/auth/byok.md` (BYOK provider config)
> Shared module used by §3, §4, §8, §11. Centralizes all Copilot SDK usage.

- [x] `src/retrieve/copilot.py` — Copilot client manager:
  - `get_client()` — singleton `CopilotClient` with lazy `start()`. Reads config from `retrieve.yaml`
  - Auto-detects auth: signed-in CLI user (default), or `github_token` from config
  - BYOK config mapping: translate `retrieve.yaml` provider block → SDK `provider` dict (type, base_url, api_key, wire_api)
  - Session factory: `_session_config()` → pre-configured session with permission handler, model, provider
  - `send_and_wait()` / `send_and_wait_session()` convenience wrappers
  - Cleanup: `stop_client()` for graceful shutdown
  - `run_sync()` — bridge async SDK to sync CLI commands
- [x] Custom tools defined inline per use case:
  - `@define_tool get_chunk(chunk_id)` — in `eval/generate.py` for question generation
  - `@define_tool get_chunks_by_doc(doc_id)` — in `eval/generate.py` for cross-doc context
  - All tools use Pydantic models for input schemas (auto JSON schema generation)
- [x] Hooks integration:
  - `onPreToolUse` hook: log all tool calls to observability for audit trail
  - `onPostToolUse` hook: capture tool execution timing for latency tracking
  - `onSessionEnd` hook: record session metrics (token usage, cost)
- [x] Streaming event handler:
  - Subscribe to session events via `session.on(handler)`
  - Route `assistant.message_delta` → terminal progress / web UI SSE
  - Route `tool.execution_start` / `tool.execution_complete` → progress indicators
  - Route `session.idle` → signal completion to callers
- [ ] ~~OpenTelemetry integration~~ — **deferred post-v1** (premature; add when token/cost tracking becomes a priority)
- [ ] ~~Skills packaging~~ — **deferred post-v1** (meta-concern, not user-facing)

---

## 13. Testing

> Skills: all skills (Bicep validation), `copilot-sdk/python/README.md` (SDK lifecycle tests)

- [x] Unit tests (42 mock E2E tests passing):
  - Config parsing, SQLite CRUD, metric calculators, registry lookups
  - Copilot client manager (mocked CopilotClient lifecycle)
  - Ingestion plugins (HTML with mocked HTTP, Markdown passthrough)
  - Eval generation (mocked Copilot SDK, JSON parsing edge cases, batching)
  - Eval runner (mocked search API + failure classification)
  - Comparison dashboard (CLI tables, HTML generation, CSV/JSON export)
  - Web UI (FastAPI TestClient, all HTML pages + REST API endpoints)
  - Provisioning, indexing, teardown (mocked az CLI + search API)
  - SOTA path registry (recommendations, toggle combinations)
  - Curation (steering, regeneration, versioning)
- [x] E2E smoke test: ingest (5 docs) → generate (mocked) → run (mocked search) → compare → export
- [x] Bicep validation: `retrieve validate` command runs `az bicep build` on all templates
- [x] Live integration test with real Azure resources (`test_web_live_e2e.py` — 305-doc corpus, 8 steps: ingest → generate → provision → index → evaluate → read APIs → teardown → cleanup)

---

## 14. Docs & packaging

> Skills: all skills (architecture registry docs), `copilot-cli/README.md` (prerequisites), `copilot-sdk/docs/getting-started.md` (SDK integration doc)

- [x] README.md: quickstart (ingest → eval → provision → run → compare), install, config reference
- [x] Prerequisites doc: Copilot CLI installation (`winget install GitHub.Copilot` / `brew install copilot-cli`), `copilot login`, `az login`
- [x] `retrieve.yaml` reference: all config fields including `model`, `provider` (BYOK), `otel`, architecture list, SOTA path toggles
- [x] CLI reference: all subcommands with flags and examples
- [x] Copilot SDK integration doc: how Retrieve uses the SDK, which tools are registered, how to configure BYOK, how to use Ollama locally
- [x] Architecture registry docs: what each built-in architecture is, what it provisions
- [x] SOTA path docs: each pre-defined path, what it includes, when to use it (docs/sota-paths.md)
- [x] `pip install retrieve` packaging — `pyproject.toml` with entry points, optional deps (`[all]`, `[graphrag]`, `[lightrag]`, `[domain]`)
- [x] Docker image: multi-stage build (frontend + backend) with health check

---

## 15. Advanced architectures (v0.5)

> Skills: `skills/azure-ai-search-agentic.md`, `skills/graphrag-lightrag.md`, `skills/azure-cosmos-db.md`, `skills/azure-functions.md`, `skills/embedding-models.md`
> See Retrieve.md roadmap v0.5.

- [x] **Multi-vector (BGE-M3)**: AML skill + AML vectorizer for Foundry model catalog integration, index builder with dense + semantic fields, query adapter with multi-vector fusion
- [x] **Agentic retrieval (Knowledge Bases)**: Knowledge Source + Knowledge Base creation via Python SDK, KnowledgeBaseRetrievalClient query adapter, extractive data output mode
- [x] **GraphRAG**: Bicep for Cosmos DB + Azure Functions, `graphrag` indexer integration (entity extraction, community detection), local + remote query modes via Functions endpoint
- [x] **LightRAG**: Bicep for Container Apps, `lightrag-hku` indexer integration, mix-mode query (graph + vector), local + remote query via Container Apps endpoint
- [x] **SOTA eval runner**: Toggle combination iterator, per-variant eval execution, per-component marginal delta computation, recommended configuration output

---

## 16. Domain adaptation (v0.6)

> See Retrieve.md roadmap v0.6.

- [x] Eval-triggered fine-tuning recommendation: domain analysis via corpus vocabulary stats, acronym density, jargon density
- [x] Automated training data generation: synthetic query-document pairs via LLM for contrastive learning
- [x] Azure OpenAI fine-tuning job management: submit, monitor, retrieve fine-tuned model
- [x] Before/after eval comparison on same golden set with delta table
- [x] Fine-tuned model versioning via job IDs and model registry

---

## Future (post-v1, per roadmap)

- [x] OpenTelemetry integration: opt-in OTLP HTTP trace export via `otel_endpoint` config, auto-spans for operations
- [ ] Skills packaging: prompt skills for eval-generate, failure-classify, eval-curate
- [x] Docker image: multi-stage Dockerfile (Node.js frontend build + Python runtime), .dockerignore, health check
- [ ] Custom architecture registration: user provides name + config + Bicep template
- [ ] Custom model registration: user provides name + endpoint + config
- [x] CI/CD pipeline: GitHub Actions for lint + test + Bicep validation + Docker build
- [ ] Query expansion evaluation: add toggle for LLM-assisted query rewriting in SOTA mode
- [ ] Custom architecture plugin SDK: bring your own Bicep + indexer + query adapter
- [ ] Multi-corpus support: manage multiple corpora in one Retrieve instance
- [ ] CI/CD integration: run eval as a GitHub Action on corpus or config changes — use `copilot -p` programmatic mode in CI
- [ ] Custom agents: define Retrieve-specific sub-agents (researcher for corpus analysis, evaluator for scoring) via SDK `custom_agents` — auto-delegate between them
- [ ] MCP server for Azure provisioning: integrate Azure MCP server (`mcp_servers` config in SDK session) so the Copilot agent can directly provision/query Azure resources during interactive sessions
- [ ] Fleet mode: use Copilot CLI `/fleet` for parallel eval generation across corpus partitions
