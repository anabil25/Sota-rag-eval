# Skill: Azure AI Search — Agentic Retrieval (Knowledge Bases)

> For: Retrieve solution accelerator — using the 2025-preview Knowledge Bases API for agentic, multi-source retrieval with LLM-powered query planning.

## CRITICAL: This Replaces Function-Based Agentic Orchestration

The Knowledge Bases API is a **complete built-in RAG engine** inside the search service. It does everything a custom Function-based orchestrator would do — and more:
- LLM-powered query planning (multi-hop, iterative)
- Automatic source selection across multiple knowledge sources
- Answer synthesis with references
- Agentic reasoning with configurable effort levels
- Security trimming via `x-ms-query-source-authorization` header

**You do NOT need Azure Functions for agentic retrieval.** See `azure-functions.md` for the narrowed scope of when Functions are actually needed (GraphRAG/LightRAG only).

### Knowledge Sources Auto-Ingest
When using a Knowledge Source of kind `azureBlob`, the KB **automatically creates** its own data source, indexer, skillset, and index. You don't need to create any of these manually. The entire indexer pipeline from `azure-indexer-pipeline.md` is **skipped** for this architecture.

## When to Use
- Evaluating agentic retrieval as an architecture option — **this should be the default agentic path**
- Queries that need multi-hop reasoning across sources
- Combining search index data with live web or SharePoint queries
- When you want the search service itself to do query planning + answer synthesis
- Auto-ingesting from blob/SharePoint/OneLake without custom indexer config

## API Version
`2025-11-01-preview` — this is a preview feature, not yet GA.

## Key Concepts

### Three Objects
| Object | API Path | Purpose |
|---|---|---|
| KnowledgeSource | `/knowledgesources` | Points to a data store (search index, blob, SharePoint, web) |
| KnowledgeBase | `/knowledgebases` | Groups sources + LLM model + reasoning config |
| Retrieve | `/knowledgebases('{name}')/retrieve` | POST — executes the agentic retrieval pipeline |

### Knowledge Source Types
| Kind | At Indexing Time? | At Query Time? | Notes |
|---|---|---|---|
| `searchIndex` | Pre-indexed | Queried | Points to an existing AI Search index |
| `azureBlob` | Auto-ingested | Queried | Ingests blob data into a managed index |
| `indexedSharePoint` | Auto-ingested | Queried | Ingests SharePoint content |
| `indexedOneLake` | Auto-ingested | Queried | Ingests Fabric OneLake data |
| `web` | No | Live query | Queries the web at retrieval time (Bing-backed) |
| `remoteSharePoint` | No | Live query | Queries SharePoint directly at retrieval time |

### Reasoning Effort Levels
| Level | Behavior | Cost | Use Case |
|---|---|---|---|
| `minimal` | No query planning, no source selection, direct retrieval | Lowest | Simple lookups, testing |
| `low` | Light query planning | Medium | Standard questions |
| `medium` | Full query planning with iterative search | Highest | Complex cross-doc reasoning |

### Output Modes
| Mode | Behavior |
|---|---|
| `extractiveData` | Returns source passages without LLM alteration |
| `answerSynthesis` | Uses LLM to synthesize an answer from retrieved content |

## Python SDK
```python
from azure.search.documents.agent import KnowledgeAgentRetrievalClient
from azure.search.documents.agent.models import (
    KnowledgeAgentRetrievalRequest,
    KnowledgeAgentMessage,
    KnowledgeAgentMessageTextContent,
    SearchIndexKnowledgeSourceParams
)
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    KnowledgeAgent,
    KnowledgeAgentAzureOpenAIModel,
    KnowledgeSourceReference,
    AzureOpenAIVectorizerParameters
)
```

### Creating a Knowledge Base
```python
agent = KnowledgeAgent(
    name="policy-kb",
    knowledge_sources=[KnowledgeSourceReference(name="policy-source")],
    models=[KnowledgeAgentAzureOpenAIModel(
        azure_open_ai_parameters=AzureOpenAIVectorizerParameters(
            resource_url="https://{oai}.openai.azure.com",
            deployment_name="gpt-4.1",
            model_name="gpt-4.1"
        )
    )],
    retrieval_reasoning_effort="low",
    output_mode="answerSynthesis"
)
index_client.create_or_update_agent(agent)
```

### Querying
```python
agent_client = KnowledgeAgentRetrievalClient(
    endpoint=search_endpoint,
    agent_name="policy-kb",
    credential=credential
)

request = KnowledgeAgentRetrievalRequest(
    messages=[KnowledgeAgentMessage(
        role="user",
        content=[KnowledgeAgentMessageTextContent(text="What are SNAP eligibility rules?")]
    )],
    knowledge_source_params=[SearchIndexKnowledgeSourceParams(
        knowledge_source_name="policy-source",
        kind="searchIndex",
        include_references=True,
        include_reference_source_data=True,
        reranker_threshold=2.5
    )]
)

result = agent_client.retrieve(retrieval_request=request)
```

### Response Structure
```python
# result.response — list of KnowledgeAgentMessage with the answer
# result.references — list of source document references
# result.activity — list of activity records (for debugging/metrics)
for ref in result.references:
    print(ref.id, ref.type, ref.reranker_score)
for activity in result.activity:
    print(activity.type, activity.elapsed_ms)
```

## Activity Record Types
| Type | What It Tracks |
|---|---|
| `searchIndex` | Search index query with arguments (search text, filter, fields) |
| `azureBlob` | Blob source query |
| `web` | Web search query |
| `modelQueryPlanning` | LLM tokens used for query planning |
| `modelAnswerSynthesis` | LLM tokens used for answer generation |
| `agenticReasoning` | Reasoning tokens consumed |

## Requirements
- **Azure OpenAI model deployment** (GPT-4.1 or similar) for query planning + answer synthesis
- **AI Search service** (Standard SKU or higher recommended for KBs)
- The OpenAI resource MUST be deployed BEFORE creating the KB that references it

## REST API
| Operation | Method | Path |
|---|---|---|
| Create knowledge source | POST | `/knowledgesources` |
| Get knowledge source status | GET | `/knowledgesources('{name}')/status` |
| Create knowledge base | POST | `/knowledgebases` |
| Retrieve | POST | `/knowledgebases('{name}')/retrieve` |
