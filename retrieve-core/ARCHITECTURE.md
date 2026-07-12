# Retrieve — Architecture Design

> Source of truth for how the system is structured, what calls what,
> and how data flows through the pipeline.
>
> Vision: [Retrieve.md](../docs/vision/Retrieve.md)
> Build plan: [TODO.md](../docs/vision/TODO.md)

---

## System Overview

```mermaid
graph TB
    subgraph UI["Web UI — Primary Interface (web/app.py)"]
        ui_home[Home / Status]
        ui_ingest[Ingest View]
        ui_eval[Eval Set View<br/>Generate + Curate]
        ui_run[Run View<br/>Live Progress via SSE]
        ui_compare[Compare Dashboard<br/>Test Mode + SOTA Mode]
        ui_provision[Provision View]
        ui_history[History / Iteration Timeline]
    end

    subgraph CLI["CLI Layer (cli.py) — Automation Interface"]
        ingest_cmd[retrieve ingest]
        eval_gen[retrieve eval generate]
        eval_run[retrieve eval run]
        eval_cmp[retrieve eval compare]
        info_cmd[retrieve info]
        provision_cmd[retrieve provision]
        index_cmd[retrieve index]
        teardown_cmd[retrieve teardown]
    end

    subgraph Core["Core Services"]
        config[config.py<br/>YAML → RetrieveConfig]
        copilot[copilot.py<br/>Copilot SDK Client]
        db[db.py<br/>SQLite Data Layer]
    end

    subgraph Ingest["Ingestion (ingest/)"]
        plugin[plugin.py<br/>IngestPlugin ABC]
        html[html_plugin.py<br/>RoboHelp → Markdown]
        md[markdown_plugin.py<br/>Passthrough]
        run_ingest[run.py<br/>Orchestrator + Stats]
    end

    subgraph Eval["Evaluation (eval/)"]
        chunks[chunks.py<br/>Corpus → Chunks]
        generate[generate.py<br/>Question Generation]
        metrics[metrics.py<br/>Recall, MRR, nDCG]
        runner[runner.py<br/>Search + Score]
        compare[compare.py<br/>Dashboard + Export]
    end

    subgraph Registry["Registries (registry/)"]
        arch_reg[architectures.py<br/>9 Architectures]
        model_reg[models.py<br/>Embeddings + Rerankers]
    end

    subgraph External["External Systems"]
        copilot_cli[GitHub Copilot CLI<br/>subprocess]
        ai_search[Azure AI Search<br/>REST API]
        azure_res[Azure Resources<br/>Bicep / IaC]
    end

    %% UI → same core modules as CLI (no logic duplication)
    ui_ingest --> run_ingest
    ui_eval --> generate
    ui_run --> runner
    ui_compare --> compare
    ui_home --> db
    ui_history --> db
    ui_provision -.-> azure_res

    %% CLI → Core
    ingest_cmd --> config
    eval_gen --> config
    eval_run --> config
    eval_cmp --> config
    info_cmd --> arch_reg & model_reg

    %% CLI → Modules
    ingest_cmd --> run_ingest
    eval_gen --> generate
    eval_run --> runner
    eval_cmp --> compare

    %% Core dependencies
    copilot --> copilot_cli
    generate --> copilot
    runner --> copilot
    generate --> db
    runner --> db
    compare --> db
    run_ingest --> plugin

    %% Plugin implementations
    plugin -.-> html
    plugin -.-> md

    %% External calls
    runner --> ai_search
    generate --> chunks

    %% Provision (not built)
    provision_cmd -.-> azure_res
    index_cmd -.-> ai_search

    style provision_cmd stroke-dasharray: 5 5
    style index_cmd stroke-dasharray: 5 5
    style teardown_cmd stroke-dasharray: 5 5
    style azure_res stroke-dasharray: 5 5
    style ui_home stroke-dasharray: 5 5
    style ui_ingest stroke-dasharray: 5 5
    style ui_eval stroke-dasharray: 5 5
    style ui_run stroke-dasharray: 5 5
    style ui_compare stroke-dasharray: 5 5
    style ui_provision stroke-dasharray: 5 5
    style ui_history stroke-dasharray: 5 5
```

> **Key design principle:** The Web UI and CLI call the same core Python functions.
> No logic lives in either interface layer — they are thin wrappers over `ingest/run.py`,
> `eval/generate.py`, `eval/runner.py`, `eval/compare.py`, and `db.py`.
> Build order: core modules first (via CLI), then wrap in UI as the final step.

---

## Module Dependency Graph

Shows which modules import from which — no circular dependencies allowed.

```mermaid
graph LR
    cli --> config
    cli --> ingest_run[ingest.run]
    cli --> eval_gen[eval.generate]
    cli --> eval_runner[eval.runner]
    cli --> eval_compare[eval.compare]
    cli --> arch_reg[registry.architectures]
    cli --> model_reg[registry.models]

    ingest_run --> ingest_plugin[ingest.plugin]
    ingest_run --> config
    ingest_plugin -.-> html_plugin[ingest.html_plugin]
    ingest_plugin -.-> md_plugin[ingest.markdown_plugin]

    eval_gen --> copilot
    eval_gen --> db
    eval_gen --> eval_chunks[eval.chunks]
    eval_gen --> config

    eval_runner --> copilot
    eval_runner --> db
    eval_runner --> eval_metrics[eval.metrics]
    eval_runner --> config

    eval_compare --> db
    eval_compare --> config

    copilot --> config

    style html_plugin fill:#e1f5fe
    style md_plugin fill:#e1f5fe
    style arch_reg fill:#f3e5f5
    style model_reg fill:#f3e5f5
```

---

## Data Flow: End-to-End Pipeline

```mermaid
sequenceDiagram
    participant User
    participant CLI as cli.py
    participant Ingest as ingest/run.py
    participant Plugin as IngestPlugin
    participant Chunks as eval/chunks.py
    participant Gen as eval/generate.py
    participant Copilot as copilot.py
    participant CopilotCLI as Copilot CLI (subprocess)
    participant DB as db.py (SQLite)
    participant Runner as eval/runner.py
    participant Search as Azure AI Search
    participant Compare as eval/compare.py

    Note over User,Compare: Phase 1 — Ingest
    User->>CLI: retrieve ingest --source URL --plugin html
    CLI->>Ingest: run_ingest(source, plugin, output_dir)
    Ingest->>Plugin: discover(source)
    Plugin-->>Ingest: list[DiscoveredPage]
    loop Each page
        Ingest->>Plugin: fetch(page, source)
        Plugin-->>Ingest: FetchedPage
        Ingest->>Plugin: convert(page)
        Plugin-->>Ingest: ConvertedDoc
        Ingest->>Ingest: save_doc() → .md with YAML frontmatter
    end
    Ingest->>Ingest: compute_stats()
    Ingest-->>CLI: CorpusStats (doc count, xref density, avg length)

    Note over User,Compare: Phase 2 — Golden Eval Set Generation
    User->>CLI: retrieve eval generate --corpus ./corpus
    CLI->>Gen: generate_eval_set(corpus_dir, version_label)
    Gen->>Chunks: load_corpus_chunks(corpus_dir)
    Chunks-->>Gen: list[Chunk] with chunk_id, doc_id, content
    Gen->>Copilot: get_client(cfg)
    Copilot->>CopilotCLI: start subprocess
    Gen->>Copilot: create_session(model, system_msg, tools=[get_chunk, get_chunks_by_doc])
    loop Each chunk
        Gen->>Copilot: send_and_wait(prompt with chunk content)
        Note right of Copilot: Model may call get_chunk()<br/>or get_chunks_by_doc()<br/>for cross-doc context
        Copilot-->>Gen: JSON {questions: [{question, category, ground_truth_chunk_ids}]}
    end
    Gen->>DB: create_eval_set(version_label)
    Gen->>DB: add_question() × N
    Gen->>DB: update_eval_set_counts()
    Gen->>Copilot: stop_client()

    Note over User,Compare: Phase 5 — Evaluate & Compare
    User->>CLI: retrieve eval run --eval-set v1
    CLI->>Runner: run_evaluation(eval_set_version)
    Runner->>DB: get_eval_set + get_questions
    Runner->>DB: create_run(arch_name, mode=test)
    loop Each question
        Runner->>Search: POST /indexes/{name}/docs/search (direct REST)
        Search-->>Runner: {value: [{id, chunk_id, ...}]}, latency_ms
        Runner->>Runner: compute_scores(retrieved, ground_truth)
        Runner->>DB: add_result(run_id, question_id, scores, latency)
    end
    alt Failures exist (recall@10 == 0)
        Runner->>Copilot: create_session(classification prompt)
        loop Each failure
            Runner->>Copilot: send_and_wait(question + expected + wrong chunk)
            Copilot-->>Runner: {failure_type, explanation}
        end
        Runner->>DB: UPDATE run_results SET failure_type
    end
    Runner->>DB: complete_run(aggregate_metrics)

    User->>CLI: retrieve eval compare --web
    CLI->>Compare: compare_runs()
    Compare->>DB: get_all_completed_runs()
    Compare->>DB: get_per_category_scores(run_id)
    Compare->>DB: get_failures_for_run(run_id)
    Compare-->>User: CLI tables + HTML dashboard
```

---

## SQLite Schema (Entity Relationship)

```mermaid
erDiagram
    eval_sets ||--o{ eval_questions : contains
    eval_sets ||--o{ runs : evaluated_by
    runs ||--o{ run_results : produces
    eval_questions ||--o{ run_results : scored_in
    architectures ||--o{ runs : tested_in

    eval_sets {
        int id PK
        text version_label UK
        text created_at
        int question_count
        text category_counts "JSON"
        text notes
    }

    eval_questions {
        int id PK
        int eval_set_id FK
        text question_text
        text category
        text ground_truth_chunk_ids "JSON array"
        text source_doc_id
        text metadata "JSON"
    }

    runs {
        int id PK
        int eval_set_id FK
        int architecture_id FK
        text architecture_name
        text mode "test|sota"
        text architecture_config "JSON"
        text created_at
        text status "running|completed|failed"
        text aggregate_metrics "JSON"
    }

    run_results {
        int id PK
        int run_id FK
        int question_id FK
        text retrieved_chunk_ids "JSON array"
        text scores "JSON: recall@5,10 mrr@10 ndcg@10"
        real latency_ms
        text failure_type "vocab|semantic|xref|chunking"
        text failure_details
    }

    architectures {
        int id PK
        text name
        text config "JSON"
        text resources_provisioned "JSON"
        text status "registered|provisioned|active|torn_down"
        text created_at
    }
```

---

## Copilot SDK Integration Model

Two distinct usage patterns — never mixed:

```mermaid
graph TB
    subgraph "Pattern 1: Eval Generation (eval/generate.py)"
        gen_client[CopilotClient<br/>singleton via copilot.py]
        gen_session[Session<br/>model + system_msg + tools]
        gen_tool1["@define_tool get_chunk(chunk_id)<br/>→ returns chunk content"]
        gen_tool2["@define_tool get_chunks_by_doc(doc_id)<br/>→ returns all chunks for a doc"]
        gen_prompt["send_and_wait(chunk + prompt)<br/>→ JSON {questions: [...]}"]

        gen_client --> gen_session
        gen_session --> gen_tool1 & gen_tool2
        gen_session --> gen_prompt
    end

    subgraph "Pattern 2: Failure Classification (eval/runner.py)"
        fc_client[CopilotClient<br/>same singleton]
        fc_session[Session<br/>model + classification prompt]
        fc_prompt["send_and_wait(question + expected + wrong)<br/>→ JSON {failure_type, explanation}"]
        fc_no_tools["NO tools registered<br/>pure prompt/response"]

        fc_client --> fc_session
        fc_session --> fc_prompt
        fc_session --> fc_no_tools
    end

    subgraph "BYOK Provider (config.py)"
        byok_default["Default: GitHub Copilot<br/>(signed-in user, no config needed)"]
        byok_azure["Azure OpenAI:<br/>type: azure<br/>base_url: https://...openai.azure.com"]
        byok_ollama["Ollama:<br/>type: openai<br/>base_url: http://localhost:11434/v1"]
    end

    byok_default -.-> gen_client
    byok_azure -.-> gen_client
    byok_ollama -.-> gen_client

    style fc_no_tools fill:#fff3e0
```

---

## Ingestion Plugin Architecture

```mermaid
classDiagram
    class IngestPlugin {
        <<abstract>>
        +name: str
        +discover(source: str) list~DiscoveredPage~
        +fetch(page: DiscoveredPage, source: str) FetchedPage
        +convert(page: FetchedPage) ConvertedDoc
    }

    class HtmlPlugin {
        +name = "html"
        +delay: float
        +max_retries: int
        -_session: requests.Session
        -_get(url) Response
        -_parse_toc_js(text) list~dict~
        -_extract_content(html) str
        -_extract_cross_references(html) list~str~
        -_convert_to_markdown(html) str
        -_derive_policy_id(href, title) str
    }

    class MarkdownPlugin {
        +name = "markdown"
        -_parse_frontmatter(text) dict
        -_strip_frontmatter(text) str
    }

    class DiscoveredPage {
        +href: str
        +title: str
        +parent: str
        +metadata: dict
    }

    class FetchedPage {
        +href: str
        +title: str
        +parent: str
        +raw_content: str
        +source_url: str
    }

    class ConvertedDoc {
        +policy_id: str
        +title: str
        +parent: str
        +source_url: str
        +markdown: str
        +cross_references: list~str~
    }

    class CorpusStats {
        +doc_count: int
        +total_chars: int
        +avg_doc_length: float
        +cross_ref_count: int
        +cross_ref_density: float
        +categories: dict
    }

    IngestPlugin <|-- HtmlPlugin
    IngestPlugin <|-- MarkdownPlugin
    IngestPlugin ..> DiscoveredPage : produces
    IngestPlugin ..> FetchedPage : produces
    IngestPlugin ..> ConvertedDoc : produces
```

---

## Evaluation Metrics Pipeline

```mermaid
graph LR
    subgraph "Per Question"
        Q[Question + Ground Truth chunk IDs]
        Search[Azure AI Search<br/>POST /docs/search]
        Retrieved[Retrieved chunk IDs<br/>ordered by score]
        Scores["compute_scores()<br/>recall@5, recall@10<br/>mrr@10, ndcg@10"]
        Result[run_results row]
    end

    subgraph "Per Run"
        Agg["aggregate_scores()<br/>mean of all per-question scores"]
        CatAgg["get_per_category_scores()<br/>mean grouped by category"]
        RunRecord[runs.aggregate_metrics]
    end

    subgraph "Failure Path"
        Miss{"recall@10 == 0?"}
        Classify["Copilot SDK session<br/>classify failure type"]
        FType["vocabulary_mismatch<br/>semantic_gap<br/>cross_ref_miss<br/>chunking_boundary"]
    end

    Q --> Search --> Retrieved --> Scores --> Result
    Result --> Agg --> RunRecord
    Result --> CatAgg
    Scores --> Miss
    Miss -->|yes| Classify --> FType --> Result
    Miss -->|no| Result
```

---

## Dashboard Output Model

Two views, determined by `run.mode`:

```mermaid
graph TB
    subgraph TestMode["Test Mode (mode='test')"]
        TTable["Architecture Comparison Table<br/>Arch | Recall@5 | Recall@10 | MRR@10 | nDCG@10 | Latency | Cost | Failures"]
        TCat["Per-Category Breakdown<br/>nDCG@10 per arch × category"]
        TFail["Failure Analysis<br/>per arch: question, failure_type, details"]
    end

    subgraph SOTAMode["SOTA Eval Mode (mode='sota')"]
        STable["Component Delta Table<br/>Config | MRR@10 | nDCG@10 | Δ nDCG | Latency"]
        SCat["Per-Category Breakdown"]
        SFail["Failure Analysis"]
    end

    subgraph Outputs["Output Formats"]
        Terminal["CLI: Rich tables"]
        HTML["HTML: self-contained dashboard<br/>tabbed: Metrics | Per-Category | Failures"]
        CSV["CSV export"]
        JSON["JSON export"]
    end

    TestMode --> Terminal & HTML
    SOTAMode --> Terminal & HTML
    Terminal --> CSV & JSON
```

---

## Config → Session Mapping

How `retrieve.yaml` fields translate to Copilot SDK calls:

```
retrieve.yaml                    SDK Call
─────────────                    ────────
copilot:
  model: gpt-4.1         →      create_session({ model: "gpt-4.1" })
  timeout: 120            →      send_and_wait(timeout=120)
  github_token: ghp_...  →      SubprocessConfig(github_token=...)
  provider:               →      create_session({ provider: {
    type: azure                    type: "azure",
    base_url: https://...          base_url: "https://...",
    api_key: $KEY                  api_key: "...",
    azure:                         azure: { api_version: "2024-10-21" }
      api_version: ...           }})
```

---

## What's Built vs Planned

## Search Schema Guardrails

- Large text body fields in Azure AI Search must stay searchable-only unless they are chunked or projected into smaller units.
- Setting `filterable`, `facetable`, or `sortable` on long text can force whole-field term indexing and hit the 32 KB (`32766` byte UTF-8) term limit.
- If field-level schema controls are added later, the config/UI layer should reject unsafe combinations for body fields or automatically route them through chunking/projection logic.

| Component | Status | Module |
|---|---|---|
| CLI entrypoint (all commands) | ✅ Built | `cli.py` |
| Config system (YAML + BYOK) | ✅ Built | `config.py` |
| Copilot SDK client | ✅ Built | `copilot.py` |
| SQLite data layer | ✅ Built | `db.py` |
| HTML ingestion | ✅ Built | `ingest/html_plugin.py` |
| Markdown ingestion | ✅ Built | `ingest/markdown_plugin.py` |
| Ingestion orchestrator + stats | ✅ Built | `ingest/run.py` |
| Corpus chunking | ✅ Built | `eval/chunks.py` |
| Eval generation (Copilot SDK) | ✅ Built | `eval/generate.py` |
| Eval curation (category steering) | ✅ Built | `eval/curate.py` |
| Retrieval metrics | ✅ Built | `eval/metrics.py` |
| Eval runner + failure classification | ✅ Built | `eval/runner.py` |
| Comparison dashboard (CLI + HTML) | ✅ Built | `eval/compare.py` |
| Architecture registry (9 archs) | ✅ Built | `registry/architectures.py` |
| Model registry (4 embed + 4 rerank) | ✅ Built | `registry/models.py` |
| SOTA path registry (4 paths) | ✅ Built | `registry/sota_paths.py` |
| Azure provisioning (Bicep + orchestrator) | ✅ Built | `provision/` |
| Corpus indexing (blob + search) | ✅ Built | `indexing/` |
| Teardown (search resource deletion) | ✅ Built | `provision/teardown.py` |
| Web UI — FastAPI + REST API | ✅ Built | `web/app.py` |
| Tests (222 passing, 88% coverage) | ✅ Built | `tests/` |
| PDF ingestion plugin | ⬜ Not built | — |
| Streaming progress (SSE) | ⬜ Not built | — |
| Deduplication | ⬜ Not built | — |
| Cost estimation | ⬜ Not built | — |
| Cosmos/Functions Bicep (GraphRAG) | ⬜ Not built | — |
| Multi-vector/agentic/GraphRAG/LightRAG indexers | ⬜ Not built | — |
| Hooks / OTel | ⬜ Not built | — |
| Web UI pages: Ingest, Provision, Run, Teardown | ⬜ Not built | — |
| Curation UI (within web UI) | ⬜ Not built | — |
| Teardown | ⬜ Not built | — |
| Hooks / OTel | ⬜ Not built | — |
| SOTA path registry | ⬜ Not built | — |
