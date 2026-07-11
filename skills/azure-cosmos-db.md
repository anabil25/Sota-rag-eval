# Skill: Azure Cosmos DB — Vector + Document Store & GraphRAG Backend

> For: Retrieve solution accelerator — using Cosmos DB for NoSQL as a unified document/vector/text store, and as the GraphRAG artifact backend.

## IMPORTANT: Cosmos DB Has Changed Significantly

Cosmos DB for NoSQL is no longer just a document store. As of 2025, it has:

| Capability | Status | Notes |
|---|---|---|
| **DiskANN vector search** | GA | Production-grade ANN via Microsoft Research's DiskANN. Up to 4,096 dimensions. |
| **Full-text / BM25 search** | GA | Built-in keyword search with BM25 ranking |
| **Hybrid search** | GA | Vector + text + filters in a single query |
| **Document store** | GA | Original capability |
| **Graph traversal** | **NO** | No graph query syntax in NoSQL API. Gremlin API exists but is de-emphasized → Microsoft Fabric Graph |

This means Cosmos DB can now serve as a **unified operational store + vector store + text search engine** — potentially replacing Blob Storage + AI Search for simpler architectures. But it still **cannot do graph traversal** — GraphRAG entity-relationship traversal still requires graph queries at the application layer.

### Gremlin API Status
- Still exists but is de-emphasized
- Microsoft documentation now pushes **Graph in Microsoft Fabric** instead
- **Not used by GraphRAG** — GraphRAG uses the NoSQL API for artifact storage and does graph traversal programmatically

### Cosmos DB for PostgreSQL — RETIRED
- Cosmos DB for PostgreSQL (which could have used Apache AGE for graph) is **being retired**
- **Apache AGE** (openCypher graph) is available on **Azure Database for PostgreSQL Flexible Server** — a separate Azure service
- LightRAG's PostgreSQL adapters should target Azure Database for PostgreSQL Flexible Server, NOT Cosmos DB for PostgreSQL

## When to Use

### Use Case 1: GraphRAG Artifact Storage (current plan)
- Store GraphRAG output artifacts (entities, relationships, communities, community reports, text units)
- GraphRAG v3 has a native Cosmos DB storage adapter (`output_storage: type: cosmosdb`)
- GraphRAG does graph traversal in Python, not via Cosmos queries

### Use Case 2: Unified Vector + Document Store (alternative architecture)
- Store policy documents directly in Cosmos DB with DiskANN vector embeddings alongside the document content
- Hybrid search (vector + BM25 keyword + filters) in a single query
- Could replace Blob Storage + AI Search for simpler deployments
- **Trade-off**: Less control over chunking/skillsets vs AI Search integrated vectorization pipeline

### Use Case 3: LightRAG via MongoDB Wire Protocol
- Cosmos DB for MongoDB vCore can serve as LightRAG's MongoDB backend (KV, Graph, Vector, DocStatus storage)
- Uses `MongoKVStorage`, `MongoGraphStorage`, `MongoVectorDBStorage` adapters
- **Requires vCore tier** (not RU-based) for Atlas-compatible vector search

## Resource Type
`Microsoft.DocumentDB/databaseAccounts` — API version `2024-05-15`

## Vector Search Configuration

### Vector Index Types
| Type | Best For | Max Dimensions | Notes |
|---|---|---|---|
| `flat` | Small datasets, exact kNN | 505 | No ANN, brute-force |
| `quantizedFlat` | Medium datasets | 4,096 | Quantized for storage efficiency |
| `diskANN` | Production (50k+ vectors/partition) | 4,096 | Microsoft Research DiskANN algorithm |

### Container with Vector Index (Bicep)
```bicep
resource vectorContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: database
  name: 'policies'
  properties: {
    resource: {
      id: 'policies'
      partitionKey: { paths: ['/policy_id'], kind: 'Hash' }
      indexingPolicy: {
        automatic: true
        includedPaths: [{ path: '/*' }]
        vectorIndexes: [
          {
            path: '/contentVector'
            type: 'diskANN'   // or 'quantizedFlat', 'flat'
          }
        ]
      }
      vectorEmbeddingPolicy: {
        vectorEmbeddings: [
          {
            path: '/contentVector'
            dataType: 'float32'
            dimensions: 3072   // text-embedding-3-large
            distanceFunction: 'cosine'
          }
        ]
      }
    }
  }
}
```

### Vector Search Query (SQL)
```sql
SELECT TOP 10
  c.policy_id,
  c.title,
  c.content,
  VectorDistance(c.contentVector, @queryVector) AS score
FROM c
ORDER BY VectorDistance(c.contentVector, @queryVector)
```

### Hybrid Query (Vector + Full-Text + Filter)
```sql
SELECT TOP 10
  c.policy_id,
  c.title,
  c.content,
  VectorDistance(c.contentVector, @queryVector) AS vectorScore
FROM c
WHERE c.parent = '100 General Information'
  AND FullTextContains(c.content, 'confidentiality disclosure')
ORDER BY VectorDistance(c.contentVector, @queryVector)
```

## Bicep — Serverless Account (Eval)

```bicep
resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: cosmosName
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    capabilities: [
      { name: 'EnableServerless' }
      { name: 'EnableNoSQLVectorSearch' }  // enable vector search
      { name: 'EnableNoSQLFullTextSearch' }  // enable full-text search
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      { locationName: location, failoverPriority: 0 }
    ]
    disableLocalAuth: true  // force Azure AD, no keys
  }
  identity: { type: 'SystemAssigned' }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmosAccount
  name: 'graphrag'
  properties: {
    resource: { id: 'graphrag' }
  }
}
```

## Role Assignments

| Role | Role ID | Assigned To | Purpose |
|---|---|---|---|
| Cosmos DB Built-in Data Contributor | `00000000-0000-0000-0000-000000000002` | App / Function managed identity | Read/write data |
| Cosmos DB Built-in Data Reader | `00000000-0000-0000-0000-000000000001` | AI Search (if reading from Cosmos) | Query data |

```bicep
// Cosmos DB uses custom role definitions, not ARM role assignments
resource cosmosDataContributor 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmosAccount
  name: guid(cosmosAccount.id, principalId, 'data-contributor')
  properties: {
    roleDefinitionId: '${cosmosAccount.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    principalId: principalId
    scope: cosmosAccount.id
  }
}
```

## Python SDK

```python
from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential

credential = DefaultAzureCredential()
client = CosmosClient(
    url=f"https://{cosmos_name}.documents.azure.com:443/",
    credential=credential
)

database = client.get_database_client("graphrag")
container = database.get_container_client("entities")

# Query entities by type
items = container.query_items(
    query="SELECT * FROM c WHERE c.type = @type",
    parameters=[{"name": "@type", "value": "POLICY"}],
    enable_cross_partition_query=True
)

# Vector search
query_vector = [0.1, 0.2, ...]  # your embedding
items = container.query_items(
    query="""
        SELECT TOP 10 c.policy_id, c.title,
               VectorDistance(c.contentVector, @qv) AS score
        FROM c
        ORDER BY VectorDistance(c.contentVector, @qv)
    """,
    parameters=[{"name": "@qv", "value": query_vector}],
    enable_cross_partition_query=True
)
```

## GraphRAG v3 Configuration (Cosmos DB as artifact store)
```yaml
# In graphrag settings.yaml (v3 syntax)
output_storage:
  type: cosmosdb
  connection_string: ${COSMOS_CONNECTION_STRING}
  container_name: graphrag-output
  database_name: graphrag

# Cosmos DB can also be used as the vector store
vector_store:
  type: cosmosdb
  connection_string: ${COSMOS_CONNECTION_STRING}
  database_name: graphrag

# But AI Search is recommended as the vector store instead:
vector_store:
  type: azure_ai_search
  url: https://<search>.search.windows.net
  audience: https://cognitiveservices.azure.com/.default
```

## Three Architecture Paths Using Cosmos DB

| Path | What Cosmos Does | Other Services Needed | Graph? |
|---|---|---|---|
| **GraphRAG backend** | Stores entities, relationships, communities, text units | AI Foundry + AI Search (vector store) + Functions (query API) | Yes (app-layer traversal) |
| **Unified store** | Documents + vectors + full-text search (replaces Blob + AI Search) | AI Foundry (embeddings) + Functions (query API) | No |
| **LightRAG (MongoDB vCore)** | KV + graph + vector + doc status storage via MongoDB adapters | AI Foundry | Yes (LightRAG graph traversal) |

## Key Gotchas

1. **Serverless vs Provisioned** — Use Serverless for eval (pay per request). Switch to provisioned throughput in production. Serverless has a 1 GB max container size.
2. **DiskANN requires `EnableNoSQLVectorSearch` capability** — Must be enabled at account creation or added via account update. Won't work without it.
3. **Vector dimensions mismatch** — The `vectorEmbeddingPolicy` dimensions must match your embedding model output. Changing models means recreating the container.
4. **Role assignments are different** — Cosmos DB uses `sqlRoleAssignments`, not `Microsoft.Authorization/roleAssignments`. The syntax is unique to Cosmos DB.
5. **No graph traversal in NoSQL API** — DiskANN + BM25 + hybrid is powerful but it's still document-level search. Cross-document relationship traversal is NOT supported. GraphRAG handles this in Python, not via Cosmos queries.
6. **Cosmos DB for PostgreSQL is retired** — If you need PostgreSQL for LightRAG (Apache AGE graph extension), use **Azure Database for PostgreSQL Flexible Server** — a separate service.
7. **Teardown** — Deleting the Cosmos DB account deletes all data. No additional cleanup needed.
8. **Cosmos DB for MongoDB vCore** — Required for LightRAG MongoDB adapters. The RU-based MongoDB API does NOT support Atlas-compatible vector search. Must use vCore tier.
