# Skill: Azure Blob Storage — Corpus Storage & Search Integration

> For: Retrieve solution accelerator — storing policy corpus files, connecting to AI Search indexers, managing uploads via managed identity.

## When to Use
- Uploading ingested Markdown corpus to Azure for indexing
- Connecting blob storage as an AI Search data source (indexer input)
- Configuring managed identity access (no keys)
- Organizing blobs by architecture variant for SOTA eval mode

## Resource Type
`Microsoft.Storage/storageAccounts` — API version `2023-05-01`

## Container Layout
```
policies/                    # shared across all architectures
  100/
    100-1_prudent_person.md
    100-2_prohibition.md
  101/
    101_the_application.md
  addenda/
  transmittals/
```
All architectures index from the same blob container. Different chunking/embedding happens at the indexer/skillset level, not at storage level.

## Bicep

### Storage Account (HTTPS-only, no public blob access, TLS 1.2)
```bicep
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowSharedKeyAccess: false  // force Azure AD only
  }
}
```

### Blob Container
```bicep
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'policies'
  properties: { publicAccess: 'None' }
}
```

## Role Assignments

| Role | Role ID | Assigned To | Purpose |
|---|---|---|---|
| Storage Blob Data Reader | `2a2b9908-6ea1-4ae2-8e65-a410df84e7d1` | AI Search managed identity | Indexer reads blobs |
| Storage Blob Data Contributor | `ba92f5b4-2d11-453d-a403-e96b0029c9fe` | Deployer user / upload script | Write/overwrite blobs |

```bicep
var blobDataReaderRoleId = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'

resource searchBlobReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, searchService.id, blobDataReaderRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataReaderRoleId)
    principalId: searchService.identity.principalId
    principalType: 'ServicePrincipal'
  }
}
```

## Python SDK — Upload

```python
from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.identity import DefaultAzureCredential

credential = DefaultAzureCredential()
blob_service = BlobServiceClient(
    account_url=f"https://{account_name}.blob.core.windows.net",
    credential=credential
)
container = blob_service.get_container_client("policies")

# Upload a single file
md_settings = ContentSettings(content_type="text/markdown; charset=utf-8")
container.upload_blob(
    name="100/100-3_confidentiality.md",
    data=file_bytes,
    content_settings=md_settings,
    overwrite=True
)
```

### Bulk Upload Pattern (used by Retrieve)
```python
from pathlib import Path

def upload_corpus(account_url: str, corpus_dir: Path, container_name: str = "policies"):
    credential = DefaultAzureCredential()
    blob_service = BlobServiceClient(account_url=account_url, credential=credential)
    container = blob_service.get_container_client(container_name)
    
    md_settings = ContentSettings(content_type="text/markdown; charset=utf-8")
    files = sorted(corpus_dir.rglob("*.md"))
    
    for i, filepath in enumerate(files, 1):
        blob_name = filepath.relative_to(corpus_dir).as_posix()
        container.upload_blob(
            name=blob_name,
            data=filepath.read_bytes(),
            content_settings=md_settings,
            overwrite=True
        )
```

## Data Source Connection (for AI Search Indexer)

### Managed Identity (ResourceId format — no keys)
```python
from azure.search.documents.indexes.models import (
    SearchIndexerDataSourceConnection,
    SearchIndexerDataContainer
)

# Get storage resource ID
# e.g., /subscriptions/.../resourceGroups/.../providers/Microsoft.Storage/storageAccounts/akpolicystore
data_source = SearchIndexerDataSourceConnection(
    name="policies-blob",
    type="azureblob",
    connection_string=f"ResourceId={storage_resource_id};",
    container=SearchIndexerDataContainer(name="policies")
)
```

### REST API Equivalent
```json
PUT /datasources/policies-blob?api-version=2024-07-01
{
  "name": "policies-blob",
  "type": "azureblob",
  "credentials": {
    "connectionString": "ResourceId=/subscriptions/.../storageAccounts/akpolicystore;"
  },
  "container": { "name": "policies" }
}
```

## Key Gotchas

1. **`allowSharedKeyAccess: false`** — If your subscription policy blocks key-based auth, you MUST use managed identity everywhere. The indexer connection string uses `ResourceId=...;` format, not a key.
2. **Role assignment propagation** — After creating a role assignment, wait ~30 seconds before the indexer can read blobs. Bicep `dependsOn` won't help — it's an Azure AD propagation delay.
3. **Container must exist before indexer runs** — Create the container in Bicep, not in Python.
4. **Markdown parsing mode** — AI Search has native Markdown parsing (`parsingMode: 'markdown'`). With `markdownParsingSubmode: 'oneToMany'` each heading section becomes a separate search document. This is how different chunking strategies start.
5. **Blob metadata** — YAML frontmatter in Markdown files is NOT automatically extracted. You need fieldMappings or a skillset to extract `policy_id`, `title`, etc.
