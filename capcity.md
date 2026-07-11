# Determining Azure Regional Quota and Deployable Capacity Programmatically

## Executive Summary

> **Key Finding:** Azure does not provide one universal API that guarantees a resource can be deployed now. Azure explicitly says, “An assigned Quota does not reserve or guarantee capacity for Customer use,” while quota is only the subscription-side allowance. [Quotas overview](https://learn.microsoft.com/en-us/azure/quotas/quotas-overview)  
> **Confidence:** HIGH  
> **Action:** Automate a layered check—authorization/policy, provider and SKU/model availability, quota/usage, service-specific capacity—and use a controlled create/deploy probe when no authoritative capacity API exists.

The decisive distinction is quota versus backend capacity. Microsoft defines the difference directly: “Quota is your subscription's permission to deploy resources, while capacity is the underlying infrastructure available in a specific region or zone.” [On-demand capacity reservation](https://learn.microsoft.com/en-us/azure/virtual-machines/capacity-reservation-overview) Quota can therefore be sufficient while deployment still fails because the service has no backend capacity.

Azure OpenAI and Microsoft Foundry have the strongest public model-capacity mechanism: the management-plane model-capacity APIs return `availableCapacity`, defined as “The available capacity for deployment with this model and sku.” [Model Capacities - List](https://learn.microsoft.com/en-us/rest/api/aiservices/accountmanagement/model-capacities/list?view=rest-aiservices-accountmanagement-2024-10-01) For provisioned throughput, Microsoft explicitly instructs customers to “Use the model capacities API to programmatically query the maximum deployable PTU count for a given model and region.” [Provisioned throughput for Foundry Models](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/provisioned-throughput)

Azure AI Search exposes quota and regional-offering metadata but not a documented real-time backend-capacity value. Its usage API returns “quota usages,” its preview Offerings API lists “features and SKUs offered,” and Microsoft’s current capacity guidance recommends deploying to another region or retrying, adding that retry “isn't guaranteed.” [Usages - List by Subscription](https://learn.microsoft.com/en-us/rest/api/searchmanagement/usages/list-by-subscription?view=rest-searchmanagement-2025-05-01) [Offerings - List](https://learn.microsoft.com/en-us/rest/api/searchmanagement/offerings/list?view=rest-searchmanagement-2026-03-01-preview) [Handle regional capacity constraints](https://learn.microsoft.com/en-us/azure/search/search-region-capacity) The reliable public Search capacity probe is consequently the actual service create/scale operation, followed by immediate cleanup if the probe succeeds.

## Key Findings

- **[HIGH] Quota is not capacity.** “An assigned Quota does not reserve or guarantee capacity for Customer use.” [Quotas overview](https://learn.microsoft.com/en-us/azure/quotas/quotas-overview)
- **[HIGH] Azure AI Search exposes quota and offerings, but its documented capacity workflow is deploy elsewhere or retry.** “When a preferred Azure region is unavailable due to capacity constraints, you have two options: Deploy to an alternative region. Retry deployment during off-peak hours.” [Handle regional capacity constraints](https://learn.microsoft.com/en-us/azure/search/search-region-capacity)
- **[HIGH] Microsoft Foundry exposes model/SKU capacity programmatically.** `availableCapacity` is “The available capacity for deployment with this model and sku.” [Model Capacities - List](https://learn.microsoft.com/en-us/rest/api/aiservices/accountmanagement/model-capacities/list?view=rest-aiservices-accountmanagement-2024-10-01)
- **[HIGH] PTU quota does not guarantee PTU capacity.** “Having PTU quota doesn't guarantee that capacity is available.” [Provisioned throughput for Foundry Models](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/provisioned-throughput)
- **[HIGH] Compute Capacity Reservation is an actual capacity-bearing operation.** “If Azure doesn't have capacity available that meets the request, the reservation deployment fails.” [On-demand capacity reservation](https://learn.microsoft.com/en-us/azure/virtual-machines/capacity-reservation-overview)
- **[MODERATE] Where no capacity API or reservation exists, a minimal actual create is the strongest available test.** ARM preflight remains non-authoritative because it “is a best-effort process and does not catch all deployment-time errors.” [Preflight validation](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/deploy-preflight)

## Conclusion Up Front

1. **Quota and usage:** Use `Microsoft.Quota` only for onboarded providers, and use product-specific usage APIs for Search and Cognitive Services. Microsoft describes the generic API as supporting selected providers, not all Azure services. [Azure Quota Service REST API](https://learn.microsoft.com/en-us/rest/api/quota/)
2. **Region/SKU/model catalog:** Use subscription locations, provider metadata, resource-SKU APIs, Search Offerings, and model-list APIs as filters. The subscription-locations API warns that “each resource provider may support a subset of this list.” [Subscriptions - List Locations](https://learn.microsoft.com/en-us/rest/api/resources/subscriptions/list-locations?view=rest-resources-2022-12-01)
3. **Real deployable capacity:** Use a service-specific capacity endpoint where Microsoft documents one—Foundry model capacities—or a capacity-reserving create operation such as Compute Capacity Reservation. “Having PTU quota doesn't guarantee that capacity is available.” [Provisioned throughput for Foundry Models](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/provisioned-throughput)
4. **No capacity endpoint:** Use a minimal, isolated, actual create/deploy probe. ARM preflight helps but “is a best-effort process and does not catch all deployment-time errors.” [Preflight validation](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/deploy-preflight)

## 1. The Four Different Questions Automation Must Ask

### 1.1 Is the subscription allowed to deploy?

This layer covers RBAC, provider registration, policy, offer restrictions, and regional access. ARM preflight checks “whether the caller has sufficient permissions,” “required resource providers not registered,” and whether “the specified API versions are valid and supported.” [Preflight validation](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/deploy-preflight)

This layer is not quota or capacity. A deployment rejected by authorization, policy, provider registration, or offer eligibility should not be retried as though capacity were temporarily unavailable.

### 1.2 Is the service/resource type/SKU/model offered in the location?

`GET /subscriptions/{subscriptionId}/locations` is only a broad subscription region list. Microsoft says it “provides all the locations that are available for resource providers; however, each resource provider may support a subset of this list.” [Subscriptions - List Locations](https://learn.microsoft.com/en-us/rest/api/resources/subscriptions/list-locations?view=rest-resources-2022-12-01)

Provider metadata narrows that list by resource type. The `ProviderResourceType.locations` field is defined as “The collection of locations where this resource type can be created,” and the same response exposes API versions, capabilities, location mappings, and zone mappings. [Providers - Get](https://learn.microsoft.com/en-us/rest/api/resources/providers/get?view=rest-resources-2021-04-01)

These are catalog/contract signals, not a promise of immediate allocation. Compute illustrates why: the SKU API can list a size, while a create request can still return “Allocation failed. We do not have sufficient capacity for the requested VM size in this region.” [Troubleshooting VM allocation failures](https://learn.microsoft.com/en-us/troubleshoot/azure/virtual-machines/windows/allocation-failure)

### 1.3 Does the subscription have enough quota?

Quota is an assigned allowance: “Many Azure services have quotas, which are the assigned number of resources for your Azure subscription.” [Quotas overview](https://learn.microsoft.com/en-us/azure/quotas/quotas-overview)

Quota is not a reservation: “An assigned Quota does not reserve or guarantee capacity for Customer use, and capacity may not be available at the time of request.” [Quotas overview](https://learn.microsoft.com/en-us/azure/quotas/quotas-overview)

### 1.4 Does the backend have capacity now?

This is the time-sensitive allocation question. For Compute Capacity Reservations, Azure treats creation as a real capacity request: “If Azure doesn't have capacity available that meets the request, the reservation deployment fails.” [On-demand capacity reservation](https://learn.microsoft.com/en-us/azure/virtual-machines/capacity-reservation-overview)

For Foundry provisioned throughput, Microsoft says capacity is “the actual amount of PTUs per model version that's available to be deployed” and that it is “allocated at deployment time.” [Provisioned throughput for Foundry Models](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/provisioned-throughput)

For Search, Microsoft documents temporary regional constraints and recommends either an alternative region or a retry; it does not document a pre-allocation capacity number. “This option isn't guaranteed and isn't a substitute for evaluating an alternative region.” [Handle regional capacity constraints](https://learn.microsoft.com/en-us/azure/search/search-region-capacity)

## 2. Cross-Azure Programmatic Surfaces

## 2.1 Azure Quota REST API: selected providers only

The current generic read patterns are:

```http
GET https://management.azure.com/{scope}/providers/Microsoft.Quota/usages?api-version=2025-09-01
GET https://management.azure.com/{scope}/providers/Microsoft.Quota/quotas?api-version=2025-09-01
```

The first operation is documented as “Get a list of current usage for all resources for the scope specified.” [Quota Usages - List](https://learn.microsoft.com/en-us/rest/api/quota/usages/list?view=rest-quota-2025-09-01) The second is documented as “Get a list of current quota limits of all resources for the specified scope.” [Quota - List](https://learn.microsoft.com/en-us/rest/api/quota/quota/list?view=rest-quota-2025-09-01)

Typical scopes are nested under a provider and region:

```text
/subscriptions/{subscriptionId}/providers/Microsoft.Compute/locations/eastus
/subscriptions/{subscriptionId}/providers/Microsoft.Network/locations/eastus
/subscriptions/{subscriptionId}/providers/Microsoft.MachineLearningServices/locations/eastus
```

Microsoft’s Quota REST overview says the API supports “Azure virtual machines (cores/vCPU), Azure Machine Learning (dedicated/vCPUs), Networking, Azure HPC Cache, Storage and Azure Purview services.” [Azure Quota Service REST API](https://learn.microsoft.com/en-us/rest/api/quota/) A newer Quotas overview table says only “Compute, Machine Learning,” so the official documentation is internally inconsistent. [Quotas overview](https://learn.microsoft.com/en-us/azure/quotas/quotas-overview) The safe implementation rule is to treat `Microsoft.Quota` as provider-onboarded, verify support, and fall back to the target resource provider’s own usage API.

### Azure CLI

```bash
az quota list --scope "/subscriptions/$SUB/providers/Microsoft.Compute/locations/eastus"
az quota usage list --scope "/subscriptions/$SUB/providers/Microsoft.Compute/locations/eastus"
az quota show --resource-name standardFSv2Family --scope "$SCOPE"
az quota usage show --resource-name standardFSv2Family --scope "$SCOPE"
az quota update --resource-name standardFSv2Family --scope "$SCOPE" \
  --limit-object value=100 --resource-type dedicated
```

The CLI reference labels these commands “Extension GA” and says the extension automatically installs on Azure CLI 2.54.0 or higher. [az quota](https://learn.microsoft.com/en-us/cli/azure/quota?view=azure-cli-latest)

### Azure PowerShell

```powershell
Get-AzQuota -Scope $scope
Get-AzQuotaUsage -Scope $scope
```

The PowerShell module is not GA: “This cmdlet is part of a Preview module. Preview versions aren't recommended for use in production environments.” [Get-AzQuotaUsage](https://learn.microsoft.com/en-us/powershell/module/az.quota/get-azquotausage?view=azps-16.0.0)

## 2.2 Subscription locations and provider metadata

```bash
az account list-locations
az provider show --namespace Microsoft.Search
az provider show --namespace Microsoft.CognitiveServices
```

`az account list-locations` is documented as “List supported regions for the current subscription.” [az account](https://learn.microsoft.com/en-us/cli/azure/account?view=azure-cli-latest) The REST contract qualifies that result as a provider superset, not service availability. [Subscriptions - List Locations](https://learn.microsoft.com/en-us/rest/api/resources/subscriptions/list-locations?view=rest-resources-2022-12-01)

`az provider show` is documented as “Gets the specified resource provider,” while `az provider list` can return resource types and expanded metadata. [az provider](https://learn.microsoft.com/en-us/cli/azure/provider?view=azure-cli-latest)

PowerShell exposes the same metadata:

```powershell
Get-AzResourceProvider -ProviderNamespace Microsoft.Search
Get-AzResourceProvider -ProviderNamespace Microsoft.CognitiveServices
```

The cmdlet output includes `ResourceTypes`, `Locations`, `ApiVersions`, and `DefaultApiVersion`. [Get-AzResourceProvider](https://learn.microsoft.com/en-us/powershell/module/az.resources/get-azresourceprovider?view=azps-16.0.0)

**Interpretation:** Use provider metadata to discover supported resource types, regions, API versions, and zones. Do not treat registration state or a listed location as proof of current backend capacity.

## 2.3 Resource SKU APIs

Compute’s resource-SKU endpoint is:

```http
GET https://management.azure.com/subscriptions/{subscriptionId}/providers/Microsoft.Compute/skus?api-version=2021-07-01
```

It “Gets the list of Microsoft.Compute SKUs available for your Subscription.” [Compute Resource SKUs - List](https://learn.microsoft.com/en-us/rest/api/compute/resource-skus/list?view=rest-compute-2026-03-02)

Useful fields include:

- `locations` and `locationInfo.zones`, described as “A list of locations and availability zones in those locations where the SKU is available.” [Compute Resource SKUs - List](https://learn.microsoft.com/en-us/rest/api/compute/resource-skus/list?view=rest-compute-2026-03-02)
- `restrictions`, described as “The restrictions because of which SKU cannot be used. This is empty if there are no restrictions.” [Compute Resource SKUs - List](https://learn.microsoft.com/en-us/rest/api/compute/resource-skus/list?view=rest-compute-2026-03-02)
- `reasonCode`, whose documented values include `QuotaId` and `NotAvailableForSubscription`. [Compute Resource SKUs - List](https://learn.microsoft.com/en-us/rest/api/compute/resource-skus/list?view=rest-compute-2026-03-02)

CLI and PowerShell equivalents include:

```bash
az vm list-skus --location eastus --all --zone --output table
az vm list-usage --location eastus --output table
```

```powershell
Get-AzComputeResourceSku
Get-AzVMUsage -Location "East US"
```

`az vm list-skus` is “Get details for compute-related resource SKUs,” while `az vm list-usage` is “List available usage resources for VMs.” [az vm](https://learn.microsoft.com/en-us/cli/azure/vm?view=azure-cli-latest) `Get-AzVMUsage` “gets the virtual machine core count usage for a location.” [Get-AzVMUsage](https://learn.microsoft.com/en-us/powershell/module/az.compute/get-azvmusage?view=azps-16.0.0)

**Limitation:** SKU metadata is not host-allocation telemetry. Microsoft separately documents `AllocationFailed` and `ZonalAllocationFailed` when there is insufficient backend capacity. [Troubleshooting VM allocation failures](https://learn.microsoft.com/en-us/troubleshoot/azure/virtual-machines/windows/allocation-failure)

## 2.4 Azure Resource Graph

Resource Graph is useful for inventory, existing configuration, tags, region distribution, and health-event joins. Microsoft says it provides “efficient and performant resource exploration” and accesses “properties the resource providers return.” [Overview of Azure Resource Graph](https://learn.microsoft.com/en-us/azure/governance/resource-graph/overview)

It is not a generic live capacity feed. Its database is updated after ARM notifications and by “a regular full scan,” and it gathers data with “a GET to the latest non-preview” provider API. [Overview of Azure Resource Graph](https://learn.microsoft.com/en-us/azure/governance/resource-graph/overview)

Use Resource Graph for questions such as:

```kusto
resources
| where type =~ 'microsoft.search/searchservices'
| summarize count() by location, tostring(sku.name)
```

Use it to find existing resource placement or likely cleanup targets, not to certify that another instance can be allocated.

## 2.5 Service Health, Resource Health, and pricing are ancillary signals

Service Health provides “service-impacting communications about outages, planned maintenance, and health advisories.” [What is Azure Service Health?](https://learn.microsoft.com/en-us/azure/service-health/overview) Its `ServiceHealthResources` Resource Graph table contains “Service Health events such as outages, planned maintenance, or other incidents.” [Azure Resource Graph overview for Service Health](https://learn.microsoft.com/en-us/azure/service-health/azure-resource-graph-overview)

Resource Health APIs describe existing resources: `Availability Statuses - List By Subscription Id` “Lists the current availability status for all the resources in the subscription.” [Availability Statuses REST API](https://learn.microsoft.com/en-us/rest/api/resourcehealth/availability-statuses?view=rest-resourcehealth-2025-05-01)

The Retail Prices API is also not a capacity source. It is for “retail prices for all Azure services” and “price comparison across SKUs and regions.” [Azure Retail Prices REST API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)

## 3. Azure AI Search

## 3.1 Subscription quota and usage

The official management-plane endpoint is:

```http
GET https://management.azure.com/subscriptions/{subscriptionId}/providers/Microsoft.Search/locations/{location}/usages?api-version=2025-05-01
```

Microsoft describes it as “Get a list of all Azure AI Search quota usages across the subscription.” [Usages - List by Subscription](https://learn.microsoft.com/en-us/rest/api/searchmanagement/usages/list-by-subscription?view=rest-searchmanagement-2025-05-01)

Each result has:

- `currentValue`: “The currently used up value for the particular search SKU.” [Usages - List by Subscription](https://learn.microsoft.com/en-us/rest/api/searchmanagement/usages/list-by-subscription?view=rest-searchmanagement-2025-05-01)
- `limit`: “The quota limit for the particular search SKU.” [Usages - List by Subscription](https://learn.microsoft.com/en-us/rest/api/searchmanagement/usages/list-by-subscription?view=rest-searchmanagement-2025-05-01)

CLI:

```bash
az search usage list --location eastus
az search usage show --location eastus --name standard
```

The CLI labels both commands Core GA. [az search usage](https://learn.microsoft.com/en-us/cli/azure/search/usage?view=azure-cli-latest)

Search quota is tier- and region-specific. Microsoft says, “You can create multiple billable search services (Basic and higher), up to the maximum number of services allowed at each tier, per region.” [Azure AI Search service limits](https://learn.microsoft.com/en-us/azure/search/search-limits-quotas-capacity)

Quota increases are not exposed as a Search quota PUT in the documented Search management API. Microsoft’s guidance is, “You can raise maximum service limits by request. If you need more services within the same subscription, file a support request.” [Azure AI Search service limits](https://learn.microsoft.com/en-us/azure/search/search-limits-quotas-capacity)

## 3.2 Regional SKU and feature offerings

The documented preview endpoint is:

```http
GET https://management.azure.com/providers/Microsoft.Search/offerings?api-version=2026-03-01-preview
```

It “Lists all of the features and SKUs offered by the Azure AI Search service in each region.” [Offerings - List](https://learn.microsoft.com/en-us/rest/api/searchmanagement/offerings/list?view=rest-searchmanagement-2026-03-01-preview)

It returns region-level `features`, `skus`, and limits such as indexes, indexers, partition storage, vector storage, search units, replicas, and partitions. [Offerings - List](https://learn.microsoft.com/en-us/rest/api/searchmanagement/offerings/list?view=rest-searchmanagement-2026-03-01-preview)

CLI:

```bash
az search offering list
```

The command is labeled “Core GA.” [az search offering](https://learn.microsoft.com/en-us/cli/azure/search/offering?view=azure-cli-latest)

**Status warning:** The corresponding documented REST operation is preview and explicitly unstable: “It will be replaced with an action-style API in the next preview as a breaking change. Customers should avoid taking new dependencies on the current shape.” [Offerings - List](https://learn.microsoft.com/en-us/rest/api/searchmanagement/offerings/list?view=rest-searchmanagement-2026-03-01-preview) Treat the CLI command as convenient discovery, but do not persist or tightly couple to the current response schema.

## 3.3 Current regional constraints

The current region page says, “In some regions, insufficient capacity prevents you from creating search services on certain tiers.” [Azure AI Search supported regions](https://learn.microsoft.com/en-us/azure/search/search-region-support)

The page can identify explicit restrictions, including regions where constraints “prevent the creation of new search services and scaling operations.” [Azure AI Search supported regions](https://learn.microsoft.com/en-us/azure/search/search-region-support)

This page is current but is documentation, not an API contract. It should be used as a planning/circuit-breaker input, not the sole automated truth.

## 3.4 Name validation does not test capacity

```http
POST https://management.azure.com/subscriptions/{subscriptionId}/providers/Microsoft.Search/checkNameAvailability?api-version=2025-05-01
```

The operation only “Checks whether or not the given search service name is available for use.” [Check Name Availability](https://learn.microsoft.com/en-us/rest/api/searchmanagement/services/check-name-availability?view=rest-searchmanagement-2025-05-01)

Its documented failure reasons are `Invalid` and `AlreadyExists`, which are naming outcomes, not quota or regional-capacity outcomes. [Check Name Availability](https://learn.microsoft.com/en-us/rest/api/searchmanagement/services/check-name-availability?view=rest-searchmanagement-2025-05-01)

## 3.5 Reliable Search deployment probe

The actual management operation is:

```http
PUT https://management.azure.com/subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}/providers/Microsoft.Search/searchServices/{searchServiceName}?api-version=2025-05-01
Content-Type: application/json

{
  "location": "eastus",
  "sku": { "name": "basic" },
  "properties": {
    "replicaCount": 1,
    "partitionCount": 1,
    "hostingMode": "Default"
  },
  "tags": {
    "purpose": "capacity-probe",
    "expiresAt": "2026-07-11T08:00:00Z"
  }
}
```

The operation “Creates or updates a search service in the given resource group,” and a create response can return `201 Created` with `Location` and `Retry-After` headers. [Services - Create or Update](https://learn.microsoft.com/en-us/rest/api/searchmanagement/services/create-or-update?view=rest-searchmanagement-2025-05-01)

The result exposes `provisioningState`, `status`, and `statusDetails`. [Services - Create or Update](https://learn.microsoft.com/en-us/rest/api/searchmanagement/services/create-or-update?view=rest-searchmanagement-2025-05-01)

**Recommended interpretation:**

- A terminal `Succeeded` proves the requested SKU/region/configuration was deployable at that operation time.
- A quota error should be handled by quota/support workflow, not blind retry.
- A capacity/availability failure should trigger bounded retry or an alternate region because Search guidance says constraints can be temporary but retry “isn't guaranteed.” [Handle regional capacity constraints](https://learn.microsoft.com/en-us/azure/search/search-region-capacity)
- A validation, policy, provider-registration, or authorization failure should be corrected rather than retried.

Cleanup:

```http
DELETE https://management.azure.com/subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}/providers/Microsoft.Search/searchServices/{searchServiceName}?api-version=2025-05-01
```

The operation “Deletes a search service in the given resource group, along with its associated resources.” [Services - Delete](https://learn.microsoft.com/en-us/rest/api/searchmanagement/services/delete?view=rest-searchmanagement-2025-05-01)

CLI and PowerShell equivalents:

```bash
az search service create --name "$NAME" --resource-group "$RG" \
  --location eastus --sku basic --replica-count 1 --partition-count 1 --no-wait
az search service wait --name "$NAME" --resource-group "$RG" --created
az search service delete --name "$NAME" --resource-group "$RG" --yes
```

```powershell
New-AzSearchService -ResourceGroupName $rg -Name $name `
  -Sku Basic -Location "East US" -PartitionCount 1 -ReplicaCount 1
Remove-AzSearchService -ResourceGroupName $rg -Name $name
```

The Search PowerShell guidance says `New-AzSearchService` creates a service and `Remove-AzSearchService` deletes a service and its data. [Manage Azure AI Search using PowerShell](https://learn.microsoft.com/en-us/azure/search/search-manage-powershell)

## 3.6 Search PowerShell and preview limitations

The Az.Search guidance says, “Preview administration features are typically not available in the Az.Search module. If you want to use a preview feature, use the Management REST API and a preview API version.” [Manage Azure AI Search using PowerShell](https://learn.microsoft.com/en-us/azure/search/search-manage-powershell)

It also says, “The Az.Search module extends Azure PowerShell with full parity to the stable versions of the Search Management REST APIs.” [Manage Azure AI Search using PowerShell](https://learn.microsoft.com/en-us/azure/search/search-manage-powershell)

Therefore:

- Use Az.Search for stable create/show/update/delete operations.
- Use `Invoke-AzRestMethod` for Search quota/offerings operations when no dedicated cmdlet exists.
- Treat Offerings as preview even if the CLI wrapper is labeled Core GA.

## 4. Azure OpenAI and Microsoft Foundry Models

## 4.1 Subscription/provider usage and quota

The provider-specific usage endpoint is:

```http
GET https://management.azure.com/subscriptions/{subscriptionId}/providers/Microsoft.CognitiveServices/locations/{location}/usages?api-version=2024-10-01
```

It is documented as “Get usages for the requested subscription.” [Azure AI Services Usages - List](https://learn.microsoft.com/en-us/rest/api/aiservices/accountmanagement/usages/list?view=rest-aiservices-accountmanagement-2024-10-01)

The response has `currentValue`, “Current value for this metric,” and `limit`, “Maximum value for this metric.” [Azure AI Services Usages - List](https://learn.microsoft.com/en-us/rest/api/aiservices/accountmanagement/usages/list?view=rest-aiservices-accountmanagement-2024-10-01)

CLI:

```bash
az cognitiveservices usage list --location eastus
```

The command is Core GA and is documented as “Show all usages for Azure Cognitive Services.” [az cognitiveservices usage](https://learn.microsoft.com/en-us/cli/azure/cognitiveservices/usage?view=azure-cli-latest)

Azure OpenAI quota allocation is more specific than the generic account count. Microsoft says, “Quota is assigned to your subscription on a per-region, per-model, per-deployment-type basis in units of Tokens-per-Minute (TPM).” [Manage Azure OpenAI quota](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/quota)

Deployment creation consumes that quota: “You assign TPM to each deployment as it is created, and the available quota for that model is reduced by that amount.” [Manage Azure OpenAI quota](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/quota)

## 4.2 Foundry quota scope is model-family dependent in 2026

For Azure OpenAI, the current limits page says TPM and RPM are “defined per region, per subscription, and per model or deployment type.” [Azure OpenAI quotas and limits](https://learn.microsoft.com/en-us/azure/foundry/openai/quotas-limits)

For other Foundry Models being onboarded to the newer system after 2026-05-07, Microsoft says quota is tracked at subscription scope, with Global Standard sharing “one quota pool across all regions in a subscription” and Data Zone Standard sharing “one quota pool per data zone.” [Microsoft Foundry Models quotas and limits](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/quotas-limits)

Automation must therefore use model/deployment-type-specific scope rather than assuming every Foundry model has Azure OpenAI’s regional quota semantics.

## 4.3 Account SKU availability is not model deployment capacity

Provider-level account SKUs:

```http
GET https://management.azure.com/subscriptions/{subscriptionId}/providers/Microsoft.CognitiveServices/skus?api-version=2024-10-01
```

This operation “Gets the list of Microsoft.CognitiveServices SKUs available for your Subscription.” [Resource SKUs - List](https://learn.microsoft.com/en-us/rest/api/aiservices/accountmanagement/resource-skus/list?view=rest-aiservices-accountmanagement-2024-10-01)

Account-level SKUs:

```http
GET https://management.azure.com/subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}/providers/Microsoft.CognitiveServices/accounts/{accountName}/skus?api-version=2024-10-01
```

This operation “List[s] available SKUs for the requested Cognitive Services account.” [Accounts - List SKUs](https://learn.microsoft.com/en-us/rest/api/aiservices/accountmanagement/accounts/list-skus?view=rest-aiservices-accountmanagement-2024-10-01)

SKU check:

```http
POST https://management.azure.com/subscriptions/{subscriptionId}/providers/Microsoft.CognitiveServices/locations/{location}/checkSkuAvailability?api-version=2025-06-01

{
  "skus": ["S0"],
  "kind": "OpenAI",
  "type": "Microsoft.CognitiveServices/accounts"
}
```

The request body is defined by account `kind`, account `skus`, and resource `type`; the sample uses `"type": "Microsoft.CognitiveServices/accounts"`. [Check SKU Availability](https://learn.microsoft.com/en-us/rest/api/microsoftfoundry/accountmanagement/check-sku-availability/check-sku-availability?view=rest-microsoftfoundry-accountmanagement-2025-06-01)

**Interpretation:** These surfaces answer whether an account SKU is offered/allowed. They do not answer whether a particular model version and deployment SKU has deployable inference capacity.

## 4.4 Model availability

For an existing account:

```http
GET https://management.azure.com/subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}/providers/Microsoft.CognitiveServices/accounts/{accountName}/models?api-version=2024-10-01
```

This operation “List[s] available Models for the requested Cognitive Services account.” [Accounts - List Models](https://learn.microsoft.com/en-us/rest/api/aiservices/accountmanagement/accounts/list-models?view=rest-aiservices-accountmanagement-2024-10-01)

The response can include:

- `capabilities`
- `deprecation`
- `lifecycleStatus`
- `maxCapacity`
- model `skus`

Those fields are part of the documented `AccountModel` schema. [Accounts - List Models](https://learn.microsoft.com/en-us/rest/api/aiservices/accountmanagement/accounts/list-models?view=rest-aiservices-accountmanagement-2024-10-01)

CLI:

```bash
az cognitiveservices model list --location eastus
az cognitiveservices account list-models --resource-group "$RG" --name "$ACCOUNT"
```

The location command is Core GA and is documented as “Show all models for Azure Cognitive Services.” [az cognitiveservices model](https://learn.microsoft.com/en-us/cli/azure/cognitiveservices/model?view=azure-cli-latest)

For planning, the current region matrix identifies model version, region, and deployment category. Microsoft says it provides “region availability, capabilities, and deployments types available for Microsoft Foundry Models sold by Azure.” [Foundry model region availability](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability)

## 4.5 Model deployment capacity APIs

Subscription-wide, returning per-location rows:

```http
GET https://management.azure.com/subscriptions/{subscriptionId}/providers/Microsoft.CognitiveServices/modelCapacities
  ?api-version=2024-10-01
  &modelFormat=OpenAI
  &modelName={modelName}
  &modelVersion={modelVersion}
```

Location-scoped:

```http
GET https://management.azure.com/subscriptions/{subscriptionId}/providers/Microsoft.CognitiveServices/locations/{location}/modelCapacities
  ?api-version=2024-10-01
  &modelFormat=OpenAI
  &modelName={modelName}
  &modelVersion={modelVersion}
```

The response field is explicit: `availableCapacity` is “The available capacity for deployment with this model and sku.” [Model Capacities - List](https://learn.microsoft.com/en-us/rest/api/aiservices/accountmanagement/model-capacities/list?view=rest-aiservices-accountmanagement-2024-10-01)

The location endpoint also returns `availableFinetuneCapacity`, defined as “The available capacity for deployment with a fine-tune version of this model and sku.” [Location Based Model Capacities - List](https://learn.microsoft.com/en-us/rest/api/aiservices/accountmanagement/location-based-model-capacities/list?view=rest-aiservices-accountmanagement-2024-10-01)

PowerShell has a direct cmdlet:

```powershell
Get-AzCognitiveServicesModelCapacity `
  -Format OpenAI `
  -Name gpt-4.1 `
  -Version 2025-04-14 `
  -Location "East US"
```

The cmdlet’s description is “Get Cognitive Services Model Capacity in all the regions or single region.” [Get-AzCognitiveServicesModelCapacity](https://learn.microsoft.com/en-us/powershell/module/az.cognitiveservices/get-azcognitiveservicesmodelcapacity?view=azps-16.0.0)

The current `az cognitiveservices model` reference lists only `az cognitiveservices model list`, so use `az rest` for model-capacity REST calls when working in Azure CLI. [az cognitiveservices model](https://learn.microsoft.com/en-us/cli/azure/cognitiveservices/model?view=azure-cli-latest) Microsoft says, “The az rest command should only be used when an existing Azure CLI command isn't available.” [Use Azure REST API with Azure CLI](https://learn.microsoft.com/en-us/cli/azure/use-azure-cli-rest-command?view=azure-cli-latest)

Example:

```bash
az rest --method get --url \
"https://management.azure.com/subscriptions/$SUB/providers/Microsoft.CognitiveServices/locations/eastus/modelCapacities?api-version=2024-10-01&modelFormat=OpenAI&modelName=gpt-4.1&modelVersion=2025-04-14"
```

## 4.6 PTU quota versus capacity

Microsoft’s current provisioned-throughput guidance is definitive:

- “PTU quota and capacity are related but distinct concepts that both affect whether you can create a deployment.” [Provisioned throughput for Foundry Models](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/provisioned-throughput)
- “Having PTU quota doesn't guarantee that capacity is available.” [Provisioned throughput for Foundry Models](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/provisioned-throughput)
- “Capacity availability changes throughout the day based on customer demand across all regions and models.” [Provisioned throughput for Foundry Models](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/provisioned-throughput)
- “Use the model capacities API to programmatically query the maximum deployable PTU count for a given model and region.” [Provisioned throughput for Foundry Models](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/provisioned-throughput)

The capacity result is a snapshot, not a reservation. Microsoft warns, “There's no guarantee the same capacity is available if you re-create or scale the deployment up later.” [Provisioned throughput for Foundry Models](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/provisioned-throughput)

## 4.7 Standard versus provisioned capacity

Standard deployments use shared capacity. Microsoft says, “Unlike standard deployments, where inference capacity is shared across customers and throughput can vary with demand, a provisioned deployment holds a fixed amount of processing capacity exclusively for your deployment's use.” [Provisioned throughput for Foundry Models](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/provisioned-throughput)

The deployment-type guidance summarizes the service level: “Provisioned types provide guaranteed throughput and lower latency variance. Standard types offer best-effort service.” [Foundry deployment types](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/deployment-types)

For Standard, Global Standard, and Data Zone Standard, quota and model availability are necessary, but a successful deployment PUT remains the strongest proof that Azure accepted that model/SKU/capacity request.

## 4.8 Actual model deployment probe

REST:

```http
PUT https://management.azure.com/subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}/providers/Microsoft.CognitiveServices/accounts/{accountName}/deployments/{deploymentName}?api-version=2024-10-01
Content-Type: application/json

{
  "sku": {
    "name": "GlobalStandard",
    "capacity": 1
  },
  "properties": {
    "model": {
      "format": "OpenAI",
      "name": "gpt-4.1",
      "version": "2025-04-14"
    }
  }
}
```

The operation returns `200` or `201`; its response includes `provisioningState`, whose documented terminal and transitional values include `Accepted`, `Creating`, `Failed`, and `Succeeded`. [Deployments - Create or Update](https://learn.microsoft.com/en-us/rest/api/aiservices/accountmanagement/deployments/create-or-update?view=rest-aiservices-accountmanagement-2024-10-01)

CLI:

```bash
az cognitiveservices account deployment create \
  --resource-group "$RG" \
  --name "$ACCOUNT" \
  --deployment-name "$DEPLOYMENT" \
  --model-format OpenAI \
  --model-name gpt-4.1 \
  --model-version 2025-04-14 \
  --sku-name GlobalStandard \
  --sku-capacity 1
```

The CLI operation is Core GA and accepts model format/name/version plus SKU capacity. [az cognitiveservices account deployment](https://learn.microsoft.com/en-us/cli/azure/cognitiveservices/account/deployment?view=azure-cli-latest)

Cleanup:

```bash
az cognitiveservices account deployment delete \
  --resource-group "$RG" \
  --name "$ACCOUNT" \
  --deployment-name "$DEPLOYMENT"
```

The REST DELETE can return `202 Accepted`, meaning “the operation was successfully started and will complete asynchronously.” [Deployments - Delete](https://learn.microsoft.com/en-us/rest/api/aiservices/accountmanagement/deployments/delete?view=rest-aiservices-accountmanagement-2024-10-01)

## 4.9 Capacity calculator is a sizing tool

The REST calculator is:

```http
POST https://management.azure.com/subscriptions/{subscriptionId}/providers/Microsoft.CognitiveServices/calculateModelCapacity?api-version=2024-10-01
```

Microsoft describes it only as “Model capacity calculator.” [calculate Model Capacity](https://learn.microsoft.com/en-us/rest/api/aiservices/accountmanagement/calculate-model-capacity/calculate-model-capacity?view=rest-aiservices-accountmanagement-2024-10-01)

The PTU sizing guidance says the formulas and calculator “generate estimates” and advises: “For the most accurate results, benchmark a deployment against representative traffic rather than relying solely on estimated inputs.” [Determine PTU sizing](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/provisioned-throughput-sizing)

Use `calculateModelCapacity` to estimate PTUs for a workload shape. Use `modelCapacities` to query deployable capacity. Use deployment PUT to allocate it.

## 4.10 Reservations do not create model capacity

Foundry reservations are financial discounts, not capacity reservations. Microsoft says, “Reservations don't guarantee capacity. First create deployments to confirm that capacity is available, then purchase the reservation.” [Provisioned throughput for Foundry Models](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/provisioned-throughput)

The production workflow repeats this: “Use Foundry to deploy your model in a region with available quota. This step confirms capacity is available.” [Operate provisioned deployments](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/provisioned-get-started)

## 4.11 Preview, classic, and deprecated mechanisms

### Quota tiers API — preview

The Azure OpenAI quota page exposes:

```http
GET /subscriptions/{subscriptionId}/providers/Microsoft.CognitiveServices/quotaTiers?api-version=2025-10-01-preview
PATCH /subscriptions/{subscriptionId}/providers/Microsoft.CognitiveServices/quotaTiers/default?api-version=2025-10-01-preview
```

Microsoft explicitly warns, “The opt out feature is preview and may be subject to change/removal in the future.” [Azure OpenAI quotas and limits](https://learn.microsoft.com/en-us/azure/foundry/openai/quotas-limits)

The ARM resource itself is `Microsoft.CognitiveServices/quotaTiers@2025-10-01-preview`, with `tierUpgradePolicy` values `NoAutoUpgrade` and `OnceUpgradeIsAvailable`. [quotaTiers ARM reference](https://learn.microsoft.com/en-us/azure/templates/microsoft.cognitiveservices/2025-10-01-preview/quotatiers)

### Dynamic quota — preview and classic-only

The page is labeled “Dynamic quota (Preview) (classic)” and says it “Applies only to: Foundry (classic) portal. This article isn't available for the new Foundry portal.” [Azure OpenAI dynamic quota](https://learn.microsoft.com/en-us/azure/foundry-classic/openai/how-to/dynamic-quota)

It is not predictable capacity: “The Azure OpenAI backend decides if, when, and how much extra dynamic quota is added or removed … It isn't forecasted or announced in advance, and isn't predictable.” [Azure OpenAI dynamic quota](https://learn.microsoft.com/en-us/azure/foundry-classic/openai/how-to/dynamic-quota)

### Deprecated deployment scale settings

The deployment REST schema labels `scaleSettings` as “Deprecated, please use Deployment.sku instead.” [Deployments - Create or Update](https://learn.microsoft.com/en-us/rest/api/aiservices/accountmanagement/deployments/create-or-update?view=rest-aiservices-accountmanagement-2024-10-01)

New automation should set `sku.name` and `sku.capacity`, not build around deprecated `scaleSettings`.

## 5. Compute and Other Resource Types

## 5.1 Compute quota

REST:

```http
GET https://management.azure.com/subscriptions/{subscriptionId}/providers/Microsoft.Compute/locations/{location}/usages?api-version=2026-03-01
```

The operation returns “the current compute resource usage information as well as the limits for compute resources under the subscription.” [Compute Usage - List](https://learn.microsoft.com/en-us/rest/api/compute/usage/list?view=rest-compute-2026-03-02)

## 5.2 Compute SKU/location/zone eligibility

Use Resource SKUs, `az vm list-skus --all --zone`, or `Get-AzComputeResourceSku`. The SKU error guidance specifically recommends `az vm list-skus`, `Get-AzComputeResourceSku`, or the Resource SKUs REST operation. [SKU not available errors](https://learn.microsoft.com/en-us/azure/azure-resource-manager/troubleshooting/error-sku-not-available)

## 5.3 Compute real capacity

An ordinary VM create is a deployment probe but does not reserve future capacity. Microsoft says allocation can fail because “Azure currently lacks sufficient capacity to fulfill your request in the specified region or zone.” [Troubleshooting VM allocation failures](https://learn.microsoft.com/en-us/troubleshoot/azure/virtual-machines/windows/allocation-failure)

On-demand Capacity Reservation is the authoritative capacity-reserving mechanism for supported VM SKUs:

```http
PUT https://management.azure.com/subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}/providers/Microsoft.Compute/capacityReservationGroups/{group}/capacityReservations/{name}?api-version=2024-07-01
```

The body requires `location` and an SKU whose “name and capacity is required to be set.” [Capacity Reservations - Create or Update](https://learn.microsoft.com/en-us/rest/api/compute/capacity-reservations/create-or-update?view=rest-compute-2024-11-04)

After success, the instance view exposes runtime utilization, including `currentCapacity`, “the current capacity of the VM size which was reserved successfully and for which the customer is getting billed.” [Capacity Reservations - Create or Update](https://learn.microsoft.com/en-us/rest/api/compute/capacity-reservations/create-or-update?view=rest-compute-2024-11-04)

CLI:

```bash
az capacity reservation create \
  --capacity-reservation-group "$GROUP" \
  --capacity-reservation-name "$NAME" \
  --resource-group "$RG" \
  --location eastus \
  --sku Standard_D4s_v5 \
  --capacity 1 \
  --zone 1
```

The command is Core GA. [az capacity reservation](https://learn.microsoft.com/en-us/cli/azure/capacity/reservation?view=azure-cli-latest)

**Cost warning:** “Capacity reservations are priced at the same rate as the underlying VM size,” including unused reserved capacity. [On-demand capacity reservation](https://learn.microsoft.com/en-us/azure/virtual-machines/capacity-reservation-overview)

## 5.4 Other providers

Other resource types generally fall into one of four patterns:

1. **Onboarded to Microsoft.Quota:** use the nested `Microsoft.Quota/quotas` and `usages` endpoints. [Azure Quota Service REST API](https://learn.microsoft.com/en-us/rest/api/quota/)
2. **Provider-specific usage endpoint:** use the target RP’s `/locations/{location}/usages`, as Search and Cognitive Services do. [Usages - List by Subscription](https://learn.microsoft.com/en-us/rest/api/searchmanagement/usages/list-by-subscription?view=rest-searchmanagement-2025-05-01) [Azure AI Services Usages - List](https://learn.microsoft.com/en-us/rest/api/aiservices/accountmanagement/usages/list?view=rest-aiservices-accountmanagement-2024-10-01)
3. **Resource-SKU or offerings endpoint:** use provider-specific SKU catalog and restrictions, then treat the result as eligibility rather than a capacity guarantee.
4. **No capacity endpoint:** use ARM preflight and an actual minimal create probe, then delete.

## 6. What Validation and “Check” APIs Actually Prove

## 6.1 ARM what-if

What-if is change prediction: “The what-if operation doesn't make any changes to existing resources. Instead, it predicts the changes if the specified template is deployed.” [Template deployment what-if](https://learn.microsoft.com/en-us/azure/azure-resource-manager/templates/deploy-what-if)

It is useful for configuration drift and destructive-change review. It is not an allocation reservation.

## 6.2 ARM validate and provider preflight

REST:

```http
POST https://management.azure.com/subscriptions/{subscriptionId}/resourcegroups/{resourceGroupName}/providers/Microsoft.Resources/deployments/{deploymentName}/validate?api-version=2025-04-01
```

The operation “Validates whether the specified template is syntactically correct and will be accepted by Azure Resource Manager.” [Deployments - Validate](https://learn.microsoft.com/en-us/rest/api/resources/deployments/validate?view=rest-resources-2025-04-01)

Current CLI:

```bash
az deployment group validate \
  --resource-group "$RG" \
  --template-file main.bicep \
  --validation-level Provider
```

Validation levels are:

- `Provider`: “full validation” plus permission checks.
- `ProviderNoRbac`: “full validation” but only read-permission checks.
- `Template`: “only static validation”; preflight and permission checks are skipped.  
  [az deployment group](https://learn.microsoft.com/en-us/cli/azure/deployment/group?view=azure-cli-latest)

PowerShell:

```powershell
Test-AzResourceGroupDeployment `
  -ResourceGroupName $rg `
  -TemplateFile ./main.bicep `
  -ValidationLevel Provider
```

The cmdlet “determines whether an Azure resource group deployment template and its parameter values are valid.” [Test-AzResourceGroupDeployment](https://learn.microsoft.com/en-us/powershell/module/az.resources/test-azresourcegroupdeployment?view=azps-16.0.0)

**Blocking limitation:** “Preflight validation is a best-effort process and does not catch all deployment-time errors.” [Preflight validation](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/deploy-preflight)

## 6.3 Check-name endpoints

Check-name operations answer uniqueness and syntax. Search’s endpoint says it “Checks whether or not the given search service name is available for use.” [Check Name Availability](https://learn.microsoft.com/en-us/rest/api/searchmanagement/services/check-name-availability?view=rest-searchmanagement-2025-05-01)

Do not interpret `nameAvailable: true` as region, SKU, quota, or backend-capacity approval.

## 6.4 SKU-check endpoints

SKU-check operations are service-specific. Cognitive Services’ `checkSkuAvailability` returns `skuAvailable`, `reason`, and `message` for an account `kind` and account SKU. [Check SKU Availability](https://learn.microsoft.com/en-us/rest/api/microsoftfoundry/accountmanagement/check-sku-availability/check-sku-availability?view=rest-microsoftfoundry-accountmanagement-2025-06-01)

Use it before creating a Cognitive Services/Foundry account. Use model list/capacity/deployment APIs for a model deployment.

## 7. Reliable Deployment-Probe Pattern

## 7.1 Recommended sequence

1. **Check authorization, policy, provider registration, and API version.** ARM preflight validates permissions, registration, API compatibility, naming, and scope. [Preflight validation](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/deploy-preflight)
2. **Check region/resource-type catalog.** Subscription locations are only a superset, so intersect them with provider metadata or a service-specific regional source. [Subscriptions - List Locations](https://learn.microsoft.com/en-us/rest/api/resources/subscriptions/list-locations?view=rest-resources-2022-12-01)
3. **Check SKU/model/deployment-type availability.** Use provider SKU APIs, Search Offerings/region support, or Foundry model-list/region matrices.
4. **Check quota and usage.** Use `Microsoft.Quota` where supported or the product-specific usage endpoint.
5. **Check service-specific capacity.** Use Foundry model capacities or Compute Capacity Reservation where applicable.
6. **Run ARM validate/what-if.** Use them to catch known-invalid requests, not to reserve capacity.
7. **Create/deploy a minimal probe if required.** Use the exact SKU/model/zone/network constraints that matter; capacity is constraint-specific.
8. **Poll to a terminal state.** Do not treat the initial `201` or `202` as success.
9. **Capture error code, nested details, request IDs, and correlation ID.**
10. **Delete the probe and verify deletion.**

## 7.2 Isolation and cleanup

Use a dedicated resource group per probe batch. Resource-group deletion is comprehensive: “When you delete a resource group, all of its resources are also deleted.” [Resource Groups - Delete](https://learn.microsoft.com/en-us/rest/api/resources/resource-groups/delete?view=rest-resources-2021-04-01)

Remove locks before cleanup because “To delete a resource group, you must first remove any underlying resource locks and backup data.” [Delete resource groups and resources](https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/delete-resource-group)

Delete:

```bash
az group delete --name "$PROBE_RG" --yes --no-wait
```

or:

```powershell
Remove-AzResourceGroup -Name $ProbeResourceGroup
```

Resource-group deletion is irreversible. [Delete resource groups and resources](https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/delete-resource-group)

For Foundry provisioned deployments, delete deployments before deleting/purging the account because “Charges for deployments on a deleted resource continue until the resource is purged.” [Operate provisioned deployments](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/provisioned-get-started)

## 7.3 Long-running operation protocol

An initial `201` or `202` is not a terminal success. Microsoft says, “An asynchronous operation initially returns an HTTP status code of either: 201 (Created) 202 (Accepted).” [Track asynchronous Azure operations](https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/async-operations)

Polling order:

1. Use `Azure-AsyncOperation` if returned: it is the “URL for checking the ongoing status of the operation.” [Track asynchronous Azure operations](https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/async-operations)
2. Otherwise use `Location`.
3. Honor `Retry-After`, “The number of seconds to wait before checking the status.” [Track asynchronous Azure operations](https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/async-operations)
4. Continue until `Succeeded`, `Failed`, or `Canceled`.

PowerShell can handle this directly:

```powershell
Invoke-AzRestMethod -Method PUT -Uri $uri -Payload $json -WaitForCompletion
```

`Invoke-AzRestMethod` is documented to “Construct and perform HTTP request to Azure resource management endpoint” and supports `-WaitForCompletion`, polling source, final-result source, and pagination. [Invoke-AzRestMethod](https://learn.microsoft.com/en-us/powershell/module/az.accounts/invoke-azrestmethod?view=azps-16.0.0)

## 7.4 Error classification

### Quota exhausted

Evidence is a usage/limit comparison or a provider error explicitly identifying quota. Do not infer quota from any failure that merely contains “capacity.”

### SKU or subscription restriction

Compute Resource SKUs distinguishes `QuotaId` from `NotAvailableForSubscription`. [Compute Resource SKUs - List](https://learn.microsoft.com/en-us/rest/api/compute/resource-skus/list?view=rest-compute-2026-03-02)

The ARM troubleshooting page documents `SkuNotAvailable` when a requested size is not available in a location or zone for the subscription. [SKU not available errors](https://learn.microsoft.com/en-us/azure/azure-resource-manager/troubleshooting/error-sku-not-available)

### Backend capacity

Compute uses allocation errors such as `AllocationFailed` and `ZonalAllocationFailed`, with the message that sufficient capacity is unavailable. [Troubleshooting VM allocation failures](https://learn.microsoft.com/en-us/troubleshoot/azure/virtual-machines/windows/allocation-failure)

Foundry documents “Provisioned capacity unavailable — No PTU capacity in region.” [Foundry deployment types](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/deployment-types)

Search documents region-level insufficient capacity and recommends alternate-region deployment or later retry. [Azure AI Search supported regions](https://learn.microsoft.com/en-us/azure/search/search-region-support) [Handle regional capacity constraints](https://learn.microsoft.com/en-us/azure/search/search-region-capacity)

### Throttling versus capacity

ARM says, “Some resource providers return 429 to report a temporary problem. The problem could be an overload condition that your request didn't cause.” [Understand ARM throttling](https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/request-limits-and-throttling)

Azure OpenAI distinguishes:

- “Rate limit exceeded” when TPM/RPM quota allocated to the deployment is exceeded.
- “System capacity throttling” when “Backend capacity is constrained.”  
  [Manage Azure OpenAI quota](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/quota)

## 7.5 Retry policy

Honor `Retry-After` for ARM 429 responses. Microsoft says a 429 response “includes a Retry-After value, which specifies the number of seconds your application should wait.” [Understand ARM throttling](https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/request-limits-and-throttling)

Retry only transient failures: “Perform retry operations only when the faults are transient … and when there's at least some likelihood that the operation will succeed when retried.” [Transient-fault handling](https://learn.microsoft.com/en-us/azure/well-architected/design-guides/handle-transient-faults)

Use bounded exponential backoff with jitter for background probes. Microsoft recommends “an exponential back-off with jitter strategy for background operations.” [Transient-fault handling](https://learn.microsoft.com/en-us/azure/well-architected/design-guides/handle-transient-faults)

Do not stack multiple uncontrolled retry layers. The guidance says to “avoid implementations that include duplicated layers of retry code” and “Never implement an endless retry mechanism.” [Transient-fault handling](https://learn.microsoft.com/en-us/azure/well-architected/design-guides/handle-transient-faults)

## 7.6 Diagnostics

Deployment history “contains information about any errors,” and each deployment has a correlation ID used to track related events. [Deployment history](https://learn.microsoft.com/en-us/azure/azure-resource-manager/templates/deployment-history)

REST:

```http
GET https://management.azure.com/subscriptions/{subscriptionId}/resourcegroups/{resourceGroupName}/deployments/{deploymentName}/operations?api-version=2025-04-01
```

The response includes `provisioningState`, `statusCode`, `serviceRequestId`, and `statusMessage`; `statusMessage` is provided when “an error was received from the resource provider.” [Deployment Operations - List](https://learn.microsoft.com/en-us/rest/api/resources/deployment-operations/list?view=rest-resources-2025-04-01)

Activity Log can be filtered by resource, provider, resource group, or correlation ID. The REST API explicitly allows a filter with `correlationId eq 'correlationID'`. [Activity Logs - List](https://learn.microsoft.com/en-us/rest/api/monitor/activity-logs/list?view=rest-monitor-2015-04-01)

## 8. Recommended Product-by-Product Decision Matrix

| Product / question | Official programmatic signal | Status | What to do |
|---|---|---|---|
| Generic onboarded-provider quota | `Microsoft.Quota/quotas` and `/usages` | REST GA; CLI extension GA; PowerShell module Preview | Compare usage with limit, but remember quota “does not reserve or guarantee capacity.” [Quotas overview](https://learn.microsoft.com/en-us/azure/quotas/quotas-overview) |
| Subscription regions | `GET /subscriptions/{id}/locations`, `az account list-locations` | GA | Intersect with provider metadata because “each resource provider may support a subset.” [Subscriptions - List Locations](https://learn.microsoft.com/en-us/rest/api/resources/subscriptions/list-locations?view=rest-resources-2022-12-01) |
| Resource provider region/API metadata | `Providers - Get`, `az provider show`, `Get-AzResourceProvider` | GA | Use for resource type, location, zone, and API-version discovery; then continue to quota/capacity checks. |
| Compute SKU eligibility | `Microsoft.Compute/skus`, `az vm list-skus`, `Get-AzComputeResourceSku` | GA | Read `restrictions` and `reasonCode`; do not infer live allocation capacity. |
| Compute quota | Compute usages or Microsoft.Quota | GA | Compare current usage and limit. |
| Compute guaranteed capacity | Capacity Reservation PUT | GA for supported VM SKUs | A successful reservation allocates capacity; creation fails if quota or capacity is unavailable. [On-demand capacity reservation](https://learn.microsoft.com/en-us/azure/virtual-machines/capacity-reservation-overview) |
| Azure AI Search quota | `Microsoft.Search/locations/{location}/usages`, `az search usage` | GA | Compare per-SKU `currentValue` and `limit`. |
| Azure AI Search regional offerings | Search Offerings REST, `az search offering list` | REST Preview and breaking; CLI labeled Core GA | Use as catalog metadata only; pin/tests are required because Microsoft says to avoid new dependencies on the current shape. [Offerings - List](https://learn.microsoft.com/en-us/rest/api/searchmanagement/offerings/list?view=rest-searchmanagement-2026-03-01-preview) |
| Azure AI Search backend capacity | Region-support guidance plus actual service PUT | No documented real-time capacity value | Use a minimal create/scale probe; if constrained, try another region or bounded retry. |
| Cognitive/Foundry account quota | `Microsoft.CognitiveServices/locations/{location}/usages`, `az cognitiveservices usage list` | GA | Use for provider metrics/account quotas, not model backend capacity. |
| Foundry account SKU | Cognitive Resource SKUs and `checkSkuAvailability` | GA | Confirms account kind/SKU eligibility, not model deployment capacity. |
| Foundry model availability | Account/location model list and current region matrix | GA/current docs | Validate exact model version and deployment type. |
| Foundry model deployable capacity | Model Capacities REST or `Get-AzCognitiveServicesModelCapacity` | Stable REST/PowerShell | Read per-SKU `availableCapacity`; deploy promptly because capacity changes dynamically. |
| Foundry Standard deployment | Actual deployment PUT/CLI | GA | A successful deployment is the definitive allocation result at that time. |
| Foundry Provisioned deployment | Model-capacity API plus actual deployment PUT | GA | Check PTU quota, query capacity, deploy, then purchase a reservation; reservations do not guarantee capacity. |
| Foundry quota tiers | `Microsoft.CognitiveServices/quotaTiers` | Preview | Do not make it a hard production dependency without version monitoring and fallback. |
| Dynamic quota | `dynamicThrottlingEnabled` classic flow | Preview; classic-only | Opportunistic and unpredictable; not a capacity guarantee. |
| ARM what-if | REST/CLI/PowerShell | GA | Change preview only; no resource change or reservation. |
| ARM validate/preflight | REST/CLI/PowerShell | GA | Catch known-invalid requests, but preflight is best-effort. |
| Name availability | RP-specific `checkNameAvailability` | GA where offered | Name/syntax only. |
| Service Health/Resource Health | Resource Health REST and Resource Graph health tables | GA/current | Use to suppress probes during incidents or diagnose existing resources, not to predict deployability. |

## 9. Reference Automation Skeleton

```text
function assess(region, resourceSpec):
    assert_authorized_and_policy_compliant(resourceSpec)
    assert_provider_registered(resourceSpec.provider)

    providerMetadata = get_provider_metadata(resourceSpec.provider)
    assert region in providerMetadata.locations_for(resourceSpec.type)

    skuOrModel = get_service_specific_catalog(resourceSpec, region)
    assert requested sku/model/version/deploymentType is offered

    quota = get_quota_and_usage(resourceSpec, region)
    assert requested amount <= quota.limit - quota.currentUsage

    if service_has_capacity_api(resourceSpec):
        capacitySnapshot = query_capacity(resourceSpec, region)
        assert requested amount <= capacitySnapshot.availableCapacity

    run_arm_validate_with_provider_preflight(resourceSpec)

    if service_has_no_authoritative_capacity_reservation:
        result = create_minimal_isolated_probe(resourceSpec)
        poll_long_running_operation(result)
        classify_terminal_result(result)
        delete_probe_and_verify_404()

    return assessment_with_timestamp_and_evidence()
```

The timestamp matters because Foundry says capacity “changes throughout the day,” Search says constraints can be temporary, and Compute says a later retry may succeed after resources are freed. [Provisioned throughput for Foundry Models](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/provisioned-throughput) [Handle regional capacity constraints](https://learn.microsoft.com/en-us/azure/search/search-region-capacity) [Troubleshooting VM allocation failures](https://learn.microsoft.com/en-us/troubleshoot/azure/virtual-machines/windows/allocation-failure)

## 10. Preview, Private, Undocumented, and Deprecated Assessment

### Generally available and documented

- Microsoft.Quota REST API for supported/onboarded providers. [Azure Quota Service REST API](https://learn.microsoft.com/en-us/rest/api/quota/)
- Search usage, service create/delete, and name availability using API `2025-05-01`. [Search Management REST](https://learn.microsoft.com/en-us/rest/api/searchmanagement/)
- Cognitive Services usages, model lists, model capacities, and deployments using stable documented management APIs such as `2024-10-01`. [Azure AI Services REST](https://learn.microsoft.com/en-us/rest/api/aiservices/)
- Compute Resource SKUs, usage, and Capacity Reservations. [Compute REST](https://learn.microsoft.com/en-us/rest/api/compute/)
- ARM validate, what-if, LRO polling, and Activity Log/deployment operations. [Resource Management REST](https://learn.microsoft.com/en-us/rest/api/resources/)

### Documented preview / not stable

- Search Offerings `2026-03-01-preview`; Microsoft says the current shape will be replaced and customers should avoid new dependencies. [Offerings - List](https://learn.microsoft.com/en-us/rest/api/searchmanagement/offerings/list?view=rest-searchmanagement-2026-03-01-preview)
- `Microsoft.CognitiveServices/quotaTiers@2025-10-01-preview`. [quotaTiers ARM reference](https://learn.microsoft.com/en-us/azure/templates/microsoft.cognitiveservices/2025-10-01-preview/quotatiers)
- Dynamic quota; the page is Preview and classic-only. [Azure OpenAI dynamic quota](https://learn.microsoft.com/en-us/azure/foundry-classic/openai/how-to/dynamic-quota)
- Azure AI Search Serverless Developer; Microsoft says it is “currently in preview,” “without a service-level agreement,” and “isn't recommended for production workloads.” [Azure AI Search service limits](https://learn.microsoft.com/en-us/azure/search/search-limits-quotas-capacity)

### Deprecated

- Cognitive deployment `scaleSettings`; “Deprecated, please use Deployment.sku instead.” [Deployments - Create or Update](https://learn.microsoft.com/en-us/rest/api/aiservices/accountmanagement/deployments/create-or-update?view=rest-aiservices-accountmanagement-2024-10-01)
- Azure AI Search data-plane `2023-07-01-preview`; Microsoft says, “Do not use this API version. It's now deprecated.” [Upgrade Search REST API versions](https://learn.microsoft.com/en-us/azure/search/search-api-migration)

### Private or undocumented

No private or undocumented portal endpoint is recommended in this report. Azure publishes supported REST contracts, CLI/PowerShell commands, and SDK operations; automation should not depend on captured portal network calls when a documented contract is absent.

Preview contracts require active maintenance. Microsoft’s versioning policy says previews “aren't intended for long-term use” and may become unavailable “as early as 90 days” after a newer version appears. [Azure service versioning policy](https://learn.microsoft.com/en-us/azure/developer/intro/azure-service-sdk-tool-versioning)

## 11. Limitations and Residual Risks

- **Pre-mortem:** Six months from now, this report would be wrong if Microsoft changed preview contracts, shifted model quota scopes, or regional capacity conditions changed faster than automation refreshed its evidence. Microsoft says previews “aren't intended for long-term use,” Foundry says capacity “changes throughout the day,” and Search says retries are not guaranteed. [Azure service versioning policy](https://learn.microsoft.com/en-us/azure/developer/intro/azure-service-sdk-tool-versioning) [Provisioned throughput for Foundry Models](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/provisioned-throughput) [Handle regional capacity constraints](https://learn.microsoft.com/en-us/azure/search/search-region-capacity)
- **Capacity is a moving target.** “Capacity availability changes throughout the day based on customer demand across all regions and models.” [Provisioned throughput for Foundry Models](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/provisioned-throughput)
- **Search region constraints can change between documentation updates and deployment.** Microsoft says retry can work because constraints are sometimes temporary, but “This option isn't guaranteed.” [Handle regional capacity constraints](https://learn.microsoft.com/en-us/azure/search/search-region-capacity)
- **Preflight is not definitive.** “Preflight validation is a best-effort process and does not catch all deployment-time errors.” [Preflight validation](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/deploy-preflight)
- **Official quota-provider support documentation is inconsistent.** Verify the provider’s current operations instead of assuming all quotas are under `Microsoft.Quota`.
- **API versions evolve.** Provider metadata exposes supported API versions, while Microsoft warns preview versions can break or be retired quickly. [Providers - Get](https://learn.microsoft.com/en-us/rest/api/resources/providers/get?view=rest-resources-2021-04-01) [Azure service versioning policy](https://learn.microsoft.com/en-us/azure/developer/intro/azure-service-sdk-tool-versioning)
- **Probe operations can create billable or stateful resources.** Use minimal sizes, dedicated resource groups, explicit expiry tags, bounded retries, and verified cleanup.

## Verification Summary

| Metric | Result |
|---|---|
| Core registered sources | 56 |
| Primary Microsoft sources | 56 |
| Retained atomic claims | 41 |
| Supported or directly verified | 41/41 |
| Unsupported claims retained | 0 |
| Contradictions explicitly resolved | 4 |
| Methods | Source tracing, direct re-fetch verification, provider-contract comparison, contradiction analysis, adversarial review |

## Conclusion

There is no single “can I deploy this Azure resource in this region right now?” API because the answer depends on separate control planes: subscription authorization and policy, provider/SKU/model catalog, subscription quota, and backend allocation. Azure’s own wording explains the causal boundary: quota is permission, while capacity is infrastructure. [On-demand capacity reservation](https://learn.microsoft.com/en-us/azure/virtual-machines/capacity-reservation-overview)

For Azure OpenAI and Microsoft Foundry, use the model-capacity API as the best official pre-deployment capacity signal, especially for PTUs, but deploy promptly and treat the result as a snapshot because capacity changes dynamically. A successful deployment remains the definitive allocation event, and an Azure Reservation should be purchased only afterward because reservations do not guarantee capacity. [Provisioned throughput for Foundry Models](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/provisioned-throughput) [Operate provisioned deployments](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/provisioned-get-started)

For Azure AI Search, use the usage API for quota, the preview Offerings API and region-support page for catalog/current constraint filtering, and a minimal actual create/scale probe for deployability. This is necessary because the documented Search APIs expose quota and offerings, while Microsoft’s backend-capacity guidance still reduces to alternate-region deployment or retry. [Usages - List by Subscription](https://learn.microsoft.com/en-us/rest/api/searchmanagement/usages/list-by-subscription?view=rest-searchmanagement-2025-05-01) [Offerings - List](https://learn.microsoft.com/en-us/rest/api/searchmanagement/offerings/list?view=rest-searchmanagement-2026-03-01-preview) [Handle regional capacity constraints](https://learn.microsoft.com/en-us/azure/search/search-region-capacity)

For other Azure resources, apply the same hierarchy. Compute is the model case: quota/usage, Resource SKUs and restrictions, then either an actual allocation or Capacity Reservation. Validation and what-if reduce false starts but cannot replace the capacity-bearing operation.
