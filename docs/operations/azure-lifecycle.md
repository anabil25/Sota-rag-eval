# Azure Lifecycle

## Scope

The default azd environment provisions the shared Retrieve dependencies used by the selected winner. SvelteKit, FastAPI, SQLite, LightRAG state, and workflow control remain on localhost.

GraphRAG experiment compute is opt-in. Set `AZURE_DEPLOY_GRAPH_RUNTIME=true` only while GraphRAG is an active candidate. For a fresh private Storage account, `retrieve provision` automatically creates the same runtime temporarily, seeds the canonical corpus from Azure, and removes the temporary compute before returning.

## Configure an isolated environment

```powershell
az login
azd auth login
azd env new retrieve-<unique-suffix> --no-prompt
azd env set AZURE_SUBSCRIPTION_ID <subscription-id>
azd env set AZURE_PRINCIPAL_ID <entra-object-id>
azd env set AZURE_LOCATION northcentralus
azd env set RETRIEVE_DEPLOYMENT_REGION northcentralus
```

Set `AZURE_DEPLOY_GRAPH_RUNTIME=true` only when GraphRAG is selected as an experiment candidate. After an experiment handoff, run app-level teardown first and set it to `false`; incremental ARM deployment does not delete resources that were deployed previously.

Never select a protected/live environment for validation. Set `RETRIEVE_PROTECTED_RESOURCE_GROUPS` to a comma-separated denylist in operator environments.

## Validation

```powershell
retrieve validate
azd provision --preview --no-prompt
```

`retrieve provision` performs the complete lifecycle:

1. verifies required providers;
2. checks Search SKU usage in each candidate region;
3. checks exact GPT-4.1 and text-embedding-3-large model/version/SKU capacity;
4. runs azd preview;
5. provisions through azd;
6. classifies any failure;
7. on backend capacity only, purges the isolated failed attempt before trying the next whole-stack region;
8. purges a soft-deleted AI Services account only when its name, region, and deleted resource-group ID exactly match the isolated environment contract;
9. checks whether the corpus fingerprint is attested to the current Storage account creation;
10. for an unattested fresh account, deploys temporary Azure-side seed compute;
11. builds a transient seed image, mirrors the canonical corpus through private Blob access, restores the worker image, and deletes the seed tag;
12. removes seed-only compute and resets graph runtime to disabled when GraphRAG is not selected;
13. writes attested azd outputs into the ignored local config and selected architecture rows.

Quota, policy, authorization, validation, and unknown failures stop immediately. They are not blind-retry conditions.

`retrieve index` waits up to 60 minutes for a Search indexer run. The canonical 1,617-document corpus can exceed 30 minutes when Azure OpenAI embedding quota is shared across one-to-many projections.

## Verify outputs

```powershell
azd env get-values
az group show --name "rg-$(azd env get-value AZURE_ENV_NAME)"
az containerapp job show --resource-group "$(azd env get-value AZURE_RESOURCE_GROUP)" --name "$(azd env get-value AZURE_GRAPHRAG_JOB_NAME)"
```

The Container Apps command applies only when `AZURE_DEPLOY_GRAPH_RUNTIME=true`.

Data-plane checks use managed identity/Azure CLI credentials. Shared keys are disabled.

## Re-run

Repeated `retrieve provision` is expected to be idempotent. Corpus reuse requires both the canonical fingerprint and the current Storage account creation attestation, so deleting and recreating Storage cannot silently produce an empty index. Postprovision commits the new manifest last, restores the corpus-free worker image before returning, and treats seed-image deletion failure as a failed hook.

## Remove the environment

The registered `predown` hook removes the Search `storage-blob` shared private link before Storage. This prevents Azure from orphaning Search when group deletion cannot verify locks on an already-deleted Storage account.

```powershell
azd down --purge --force --no-prompt
```

Verify deletion:

```powershell
az group exists --name "rg-$(azd env get-value AZURE_ENV_NAME)"
```

The result must be `false`. App-level teardown removes unselected indexes/artifacts while retaining shared experiment dependencies; `azd down` removes the complete environment.
