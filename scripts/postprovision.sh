#!/bin/sh
set -eu

case "${RETRIEVE_SKIP_GRAPH_IMAGE_BUILD:-}" in
  1|true|yes) SKIP_BUILD=1 ;;
  *) SKIP_BUILD=0 ;;
esac

if [ "$SKIP_BUILD" -eq 0 ] \
  && [ -n "${AZURE_CONTAINER_REGISTRY_NAME:-}" ] \
  && [ -n "${AZURE_GRAPHRAG_JOB_NAME:-}" ] \
  && [ -n "${AZURE_RESOURCE_GROUP:-}" ] \
  && [ -n "${AZURE_RESOURCE_TOKEN:-}" ]; then
  IMAGE="retrieve-graphrag:${AZURE_RESOURCE_TOKEN}"
  az acr build \
    --registry "$AZURE_CONTAINER_REGISTRY_NAME" \
    --image "$IMAGE" \
    --file "$(dirname "$0")/../retrieve-core/Dockerfile.graphrag-job" \
    --no-logs \
    "$(dirname "$0")/../retrieve-core"
  az containerapp job update \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --name "$AZURE_GRAPHRAG_JOB_NAME" \
    --image "$AZURE_CONTAINER_REGISTRY_ENDPOINT/$IMAGE" \
    --output none
fi

python "$(dirname "$0")/postprovision.py"