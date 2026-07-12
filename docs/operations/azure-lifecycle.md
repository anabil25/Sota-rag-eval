# Azure Lifecycle

## Scope

The current azd environment provisions Retrieve experiment dependencies and one manual GraphRAG Job. SvelteKit, FastAPI, SQLite, LightRAG state, and workflow control remain on localhost.

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
8. builds and publishes the corpus-free GraphRAG runtime image;
9. builds a transient seed image containing the canonical corpus;
10. verifies and mirrors the corpus through private Blob access, restores the runtime image, and deletes the seed tag;
11. writes azd outputs into the ignored local config and selected architecture rows.

Quota, policy, authorization, validation, and unknown failures stop immediately. They are not blind-retry conditions.

## Verify outputs

```powershell
azd env get-values
az group show --name "rg-$(azd env get-value AZURE_ENV_NAME)"
az containerapp job show --resource-group "$(azd env get-value AZURE_RESOURCE_GROUP)" --name "$(azd env get-value AZURE_GRAPHRAG_JOB_NAME)"
```

Data-plane checks use managed identity/Azure CLI credentials. Shared keys are disabled.

## Re-run

Repeated `retrieve provision` or `azd provision` is expected to be idempotent. Postprovision skips unchanged corpus blobs, commits the new manifest last, restores the corpus-free worker image before returning, and treats seed-image deletion failure as a failed hook.

## Remove the environment

```powershell
azd down --purge --force --no-prompt
```

Verify deletion:

```powershell
az group exists --name "rg-$(azd env get-value AZURE_ENV_NAME)"
```

The result must be `false`. App-level teardown removes unselected indexes/artifacts while retaining shared experiment dependencies; `azd down` removes the complete environment.
