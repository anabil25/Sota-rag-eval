$ErrorActionPreference = 'Stop'

$skipBuild = $env:RETRIEVE_SKIP_GRAPH_IMAGE_BUILD -match '^(1|true|yes)$'
if (-not $skipBuild) {
  $registry = $env:AZURE_CONTAINER_REGISTRY_NAME
  $job = $env:AZURE_GRAPHRAG_JOB_NAME
  $resourceGroup = $env:AZURE_RESOURCE_GROUP
  $tag = $env:AZURE_RESOURCE_TOKEN
  if ($registry -and $job -and $resourceGroup -and $tag) {
    $image = "retrieve-graphrag:$tag"
    az acr build --registry $registry --image $image --file "$PSScriptRoot/../retrieve-core/Dockerfile.graphrag-job" --no-logs "$PSScriptRoot/../retrieve-core"
    if ($LASTEXITCODE -ne 0) { throw "GraphRAG ACR build failed" }
    $server = $env:AZURE_CONTAINER_REGISTRY_ENDPOINT
    az containerapp job update --resource-group $resourceGroup --name $job --image "$server/$image" --output none
    if ($LASTEXITCODE -ne 0) { throw "GraphRAG job image update failed" }
  }
}

python "$PSScriptRoot/postprovision.py"
if ($LASTEXITCODE -ne 0) {
  throw "postprovision.py failed with exit code $LASTEXITCODE"
}