---
name: azure-search-api-reference
description: "Azure AI Search REST API reference navigation — progressive-disclosure docs from 167-line cheat sheet to 800-line overview to full JSON schema to raw swagger. WHEN: search API property, search type definition, search REST endpoint, search field type, search enum values, search request/response schema, index projection schema, skillset schema, knowledge base API, vector query type, scoring profile schema, analyzer/tokenizer details."
---

# Skill: Azure AI Search REST API Reference

> Navigate the Azure AI Search REST API (v2025-11-01-preview) using a 4-tier progressive-disclosure reference.
> 38 endpoints, 421 type definitions — distilled from the raw swagger into increasingly detailed formats.

## Reference Files (use in this order)

All files live in `retrieve-solution-accelerator/search-api-reference/`.

### Tier 1 — Quick Reference (start here)
**File:** `search-api-quick-ref.md` (167 lines)

Use when you need:
- All 38 API paths at a glance
- Core concepts: 5 query modes, indexer pipeline diagram, skill categories
- Index projections cheat sheet (creation order, key rules)
- Knowledge base / agentic retrieval summary
- Vector search config stack
- Key enum values (field types, parsing modes, data sources, etc.)

This file is enough for **most code generation tasks**. Read it first. Only escalate to Tier 2 if the property or type you need isn't covered.

### Tier 2 — Comprehensive Overview (property-level detail)
**File:** `search-api-overview.md` (809 lines)

Use when you need:
- Every property on a type (e.g., all 30+ fields on `SearchRequest`, all fields on `SearchField`)
- Full skill catalog with per-skill parameters
- ChatCompletionSkill detailed breakdown (model params, response format, schema)
- Knowledge Store projections (table/object/file selectors)
- Indexer execution result structure (errors, warnings, tracking state)
- Scoring function parameters and interpolation types
- All 35+ token filters with their specific parameters
- All tokenizer types and their configs
- Facet result structure, suggest/autocomplete request/response shapes
- Security model details (CMK encryption, managed identity, permission filters)

### Tier 3 — Structured JSON Map (machine-readable schemas)
**File:** `search-api-map.json` (168 KB)

Use when you need:
- Exact property names, types, and enum values for code generation
- Discriminator hierarchies (which types inherit from which base)
- Required vs optional fields on any type
- Complete enum value lists (not summarized)
- Cross-references between types (e.g., what `SearchIndexerSkillset.indexProjection` actually contains)

Structure:
```json
{
  "paths": { "/indexes": { "get": {...}, "post": {...} }, ... },
  "definitions": { "SearchIndex": { "properties": {...} }, ... }
}
```

### Tier 4 — Raw Swagger (full OpenAPI spec)
**File:** `search.json` (793 KB)

Use when you need:
- Complete request/response examples
- HTTP status codes per operation
- Full parameter descriptions with defaults
- `x-ms-*` extension metadata
- Anything not captured in the distilled files

## Usage Pattern

```
1. Read search-api-quick-ref.md
   ↓ (need more detail on a specific type?)
2. Read the relevant section of search-api-overview.md
   ↓ (need exact schema / enum values / discriminator?)
3. Search search-api-map.json for the type name
   ↓ (need raw OpenAPI metadata?)
4. Search search.json
```

## Common Lookup Scenarios

| I need to... | Start at |
|--------------|----------|
| Know what endpoints exist | Tier 1 — "All 38 API Paths" |
| Write a search query | Tier 1 — "5 query modes" table |
| Set up an indexer pipeline | Tier 1 — pipeline diagram + Tier 2 "Indexer Pipeline" |
| Configure index projections for chunking | Tier 1 — "Index Projections" section |
| Get all properties on `SearchRequest` | Tier 2 — "Search Request" table |
| Get all properties on `SearchField` | Tier 2 — "Field Definition" table |
| List all skill types and their params | Tier 2 — "Skills" section |
| Get ChatCompletionSkill full config | Tier 2 — "ChatCompletionSkill — Full Detail" |
| Get exact enum values for code gen | Tier 1 "Key Enums" → Tier 3 if incomplete |
| Understand Knowledge Base retrieval | Tier 1 summary → Tier 2 "Knowledge Bases" |
| Find a token filter's parameters | Tier 2 — "Token Filters" section |
| Check discriminator inheritance | Tier 3 — look at `x-ms-discriminator-value` in definitions |
| Get HTTP status codes for an endpoint | Tier 4 — raw swagger |

## Key Gotchas (from debugging experience)

1. **Index projections vs output field mappings**: For SplitSkill + EmbeddingSkill pipelines, use `skillset.indexProjection` — NOT `indexer.outputFieldMappings`. The latter causes `Collection(Edm.Double)` vs `Collection(Edm.Single)` type mismatches.

2. **Python SDK naming**: The attribute is `index_projection` (singular), not `index_projections` (plural).

3. **Creation order for projection pipelines**: DataSource → Index → Skillset (with projection) → Indexer (no field/output mappings). The target index MUST exist before the skillset.

4. **Key field for projections**: Must have `analyzer_name="keyword"` — projections generate composite keys that standard analyzers would tokenize and break.

5. **POST search path**: The POST endpoint is at `/docs/search.post.search`, NOT `/docs`. Same pattern for suggest (`.post.suggest`) and autocomplete (`.post.autocomplete`).

6. **`retrievable` in Python SDK**: The Python SDK uses `hidden` (inverted boolean) instead of `retrievable`. Don't set `retrievable=True` in Python — it's not a valid parameter.
