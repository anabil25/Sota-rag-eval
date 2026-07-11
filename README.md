# Retrieve

**Eval-driven retrieval architecture selection.** Stop guessing which search pipeline works — measure it.

Retrieve is an end-to-end tool for comparing Azure AI Search architectures (keyword, hybrid, hybrid+reranker, hybrid+LLM enrichment, and more) against a golden evaluation set generated from your corpus. It provisions Azure resources, indexes your content, runs evaluations, and shows you which architecture performs best for your domain.

## Prerequisites

| Tool                    | Install                                                         | Required For                         |
| ----------------------- | --------------------------------------------------------------- | ------------------------------------ |
| **Node.js** 22          | [nodejs.org](https://nodejs.org)                                | SvelteKit frontend                   |
| **Python** ≥ 3.11       | [python.org](https://python.org)                                | Backend/CLI                          |
| **Azure CLI**           | `winget install Microsoft.AzureCLI` / `brew install azure-cli`  | Provisioning, indexing               |
| **Azure Developer CLI** | `winget install Microsoft.Azd` / `brew install azd`             | Infrastructure lifecycle             |
| **GitHub Copilot CLI**  | `winget install GitHub.CopilotCLI` / `brew install copilot-cli` | Eval generation, miss classification |

### Sign In

```sh
az login                    # Azure subscription access
azd auth login              # Azure Developer CLI access
copilot login               # GitHub Copilot access (for eval generation)
```

## Quickstart

### 1. Install

```sh
# Frontend
npm ci

# Backend (editable install)
npm run backend:install
# or: pip install -e ./retrieve-core
```

Optional extras:

```sh
pip install -e "./retrieve-core[pdf]"       # PDF ingestion (pdfplumber)
pip install -e "./retrieve-core[graphrag]"   # GraphRAG support
pip install -e "./retrieve-core[lightrag]"   # LightRAG support
```

### 2. Configure

Copy `retrieve.example.yaml` to the ignored local file `retrieve.yaml`, then set corpus and Copilot options. Azure resource fields are written from validated azd outputs after provisioning.

```yaml
copilot:
  model: gpt-4.1 # LLM model for eval generation
  # provider:                  # Uncomment for BYOK (Azure OpenAI, Ollama)
  #   type: openai
  #   base_url: http://localhost:11434/v1
  #   api_key: ollama

corpus:
  source: https://example.com/policies # URL or local path
  plugin: html # html | pdf | markdown
  output_dir: corpus

azure:
  location: northcentralus # initial whole-stack candidate

architectures:
  - hybrid-reranker
  - agentic-kb
  - graphrag
  - lightrag

eval:
  mode: sample # sample (~30 questions) | full (~0.5 per doc)
```

### 3. Run the Pipeline

```sh
# Step 1: Ingest corpus → Markdown
retrieve ingest --source https://example.com --plugin html --output corpus

# Step 2: Generate golden eval set
retrieve eval generate --corpus corpus --output v1

# Step 3: (Optional) Curate eval set
retrieve eval curate --eval-set v1 --more cross_document --fewer direct_lookup --output v2

# One-time: create a unique, disposable azd environment
azd env new retrieve-<unique-suffix> --no-prompt
azd env set AZURE_SUBSCRIPTION_ID <subscription-id>
azd env set AZURE_PRINCIPAL_ID <entra-object-id>

# Step 4: Capacity-check and provision Azure experiment dependencies
retrieve provision

# Step 5: Upload corpus & build indexes
retrieve index

# Step 6: Run evaluation
retrieve eval run --eval-set v1 --architectures keyword,hybrid,hybrid-reranker

# Step 7: Compare results
retrieve eval compare --web

# Step 8: Remove unselected architecture data/indexes
retrieve teardown --keep hybrid-reranker

# Delete the complete experiment environment when finished
azd down --purge --force --no-prompt
```

Or use the **web UI** (recommended):

```sh
npm run dev          # SvelteKit UI on http://127.0.0.1:5173
npm run backend:dev  # Python operation worker on http://127.0.0.1:8000
```

## Development

Start both servers for local development:

```sh
# Terminal 1: FastAPI backend
npm run backend:dev    # http://127.0.0.1:8000

# Terminal 2: SvelteKit frontend
npm run dev            # http://127.0.0.1:5173
```

The SvelteKit app owns browser routes and read-only local data surfaces. FastAPI is the sole operational writer for SQLite/config state and runs long jobs. Azure hosts experiment dependencies plus the manual GraphRAG Job; it does not host the UI or FastAPI in the current topology. Override the local operation worker URL with `PRIVATE_RETRIEVE_API_BASE`.

## Validation

```sh
# Frontend
npm run check           # svelte-check
npm run lint            # ESLint + Prettier
npm run build           # Production build
npm run test:unit -- --run
npm run test:coverage   # Vitest coverage gate
npm run test:e2e        # Playwright
npm run test:live:eval  # Starts real backend in temp workspace and runs sample eval generation

# Backend
npm run backend:test
python -m ruff check retrieve-core/src retrieve-core/tests scripts

# Infrastructure
retrieve validate
azd provision --preview --no-prompt
```

## CLI Reference

| Command                    | Description                                               |
| -------------------------- | --------------------------------------------------------- |
| `retrieve ingest`          | Ingest corpus (HTML/PDF/Markdown → structured Markdown)   |
| `retrieve eval generate`   | Generate golden eval set from corpus via Copilot SDK      |
| `retrieve eval curate`     | Review/steer eval set categories, regenerate with balance |
| `retrieve eval export-csv` | Export eval questions to CSV                              |
| `retrieve eval import-csv` | Import eval questions from CSV                            |
| `retrieve eval run`        | Run eval set against provisioned architectures            |
| `retrieve eval compare`    | Compare evaluation runs side-by-side                      |
| `retrieve provision`       | Capacity-check and provision via azd/Bicep                |
| `retrieve index`           | Upload corpus and build search indexes                    |
| `retrieve teardown`        | Remove unselected architecture data/indexes               |
| `retrieve validate`        | Validate Bicep templates and configuration                |
| `retrieve info`            | Show architecture and model registries                    |
| `retrieve ui`              | Launch web UI (primary interface)                         |

### Key Flags

```sh
retrieve ingest --source <url|path> --plugin <html|pdf|markdown> --output <dir>
retrieve eval generate --corpus <dir> --mode <sample|full> --output <version>
retrieve eval run --architectures <all|name1,name2> --parallel
retrieve eval compare --runs <id1,id2> --export <path.csv> --web
retrieve teardown --keep <arch1,arch2>
retrieve validate --config <path>
retrieve ui --port 8000
```

## `retrieve.yaml` Config Reference

```yaml
copilot:
  model: gpt-4.1 # LLM model (default: gpt-4.1)
  timeout: 120.0 # SDK timeout in seconds
  github_token: null # Override auth with PAT
  provider: # BYOK provider config
    type: openai # openai | azure | anthropic
    base_url: null # Endpoint URL
    api_key: null # API key
    wire_api: null # completions | responses

corpus:
  source: '' # Corpus URL or local path
  plugin: html # Ingestion plugin: html | pdf | markdown
  output_dir: corpus # Output directory for Markdown files

azure:
  location: northcentralus # Initial whole-stack region candidate
  # Remaining fields are populated from azd outputs after provisioning.

eval:
  mode: sample # sample (~30 questions) | full (~0.5 per doc)
  categories: # Question categories for eval generation
    - factual_lookup
    - procedural
    - cross_document
    - cross_policy
    - edge_case
    - negation
    - colloquial_mapping
    - calculation
    - unanswerable

architectures: # Architectures to provision and evaluate
  - keyword
  - hybrid
  - hybrid-reranker

db_path: retrieve.db # SQLite database path
log_level: INFO # Logging level
```

## Architecture Registry

| Architecture            | Accuracy | Cost  | Latency | Best For                               |
| ----------------------- | -------- | ----- | ------- | -------------------------------------- |
| **keyword**             | ★★       | $     | ★★★★★   | Exact term matching, regulation lookup |
| **single-vector**       | ★★★      | $$    | ★★★★    | Semantic similarity, concept search    |
| **hybrid**              | ★★★★     | $$    | ★★★★    | Balanced accuracy/cost                 |
| **hybrid-reranker**     | ★★★★★    | $$$   | ★★★     | High-accuracy retrieval                |
| **hybrid-llm-enriched** | ★★★★★    | $$$$  | ★★★     | Cross-reference dense corpora          |
| **multi-vector**        | ★★★★★    | $$$$  | ★★      | Multi-lingual, fine-grained matching   |
| **agentic-kb**          | ★★★★★    | $$$   | ★★      | Multi-hop reasoning questions          |
| **graphrag**            | ★★★★★    | $$$$$ | ★       | Cross-document relationship queries    |
| **lightrag**            | ★★★★     | $$$$  | ★★      | Lighter graph-augmented retrieval      |

## Copilot SDK Integration

Retrieve uses the GitHub Copilot SDK for:

- **Eval generation**: LLM generates diverse questions from corpus chunks
- **Miss classification**: LLM classifies why retrieval failed (vocabulary mismatch, semantic gap, etc.)
- **Eval curation**: LLM regenerates questions with category steering

### BYOK (Bring Your Own Key)

Use Azure OpenAI, Ollama, or any OpenAI-compatible endpoint:

```yaml
copilot:
  model: gpt-4.1
  provider:
    type: openai
    base_url: http://localhost:11434/v1 # Ollama
    api_key: ollama
```

```yaml
copilot:
  model: gpt-4.1
  provider:
    type: azure
    base_url: https://my-openai.openai.azure.com
    api_key: <key>
    azure:
      api_version: '2024-10-21'
```

## Project Structure

```
retrieve-ui/
├── src/                    # SvelteKit frontend
│   ├── routes/             # Pages: flow wizard, runs, eval-sets, settings
│   └── lib/                # Shared components, API client, types
├── retrieve-core/          # Python backend
│   ├── src/retrieve/
│   │   ├── cli.py          # Typer CLI entrypoint
│   │   ├── copilot.py      # Copilot SDK client manager
│   │   ├── config.py       # YAML config system
│   │   ├── db.py           # SQLite data layer
│   │   ├── observability.py # Event bus, JSONL logging, SSE streaming
│   │   ├── eval/           # Eval generation, curation, runner, metrics
│   │   ├── ingest/         # Corpus ingestion plugins (HTML, PDF, Markdown)
│   │   ├── indexing/       # Blob upload, search index builders
│   │   ├── provision/      # Capacity-aware azd lifecycle
│   │   └── web/            # FastAPI app, job runner, SSE endpoints
│   └── tests/              # 300+ Python tests
├── infra/                  # Subscription-scoped modular Bicep
├── scripts/                # Thin azd lifecycle hooks
├── docs/                   # Vision, plans, operations, references, audits
├── corpus/                 # Ignored local canonical Markdown corpus
└── retrieve.yaml           # Configuration
```

## Current Boundary

SvelteKit owns browser-facing routes. FastAPI remains the headless API/job runner around the tested Python retrieval core. New UI work happens in SvelteKit routes and components.

See [ARCHITECTURE.md](ARCHITECTURE.md), [CONTRIBUTING.md](CONTRIBUTING.md), and [Azure lifecycle operations](docs/operations/azure-lifecycle.md).
