# Upstream Dependencies

Retrieve consumes released packages and documented APIs. Upstream repositories are not copied into this repository.

| Component            | Active contract                                                                                                                  | Upstream                                    |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| GraphRAG             | Exact Python package `graphrag==3.1.0`; generated settings must parse through that installed version                             | <https://github.com/microsoft/graphrag>     |
| LightRAG             | Python package `lightrag-hku==1.5.0` in the validated environment; code uses the 1.5 structured query and storage lifecycle APIs | <https://github.com/HKUDS/LightRAG>         |
| GitHub Copilot SDK   | Python package `github-copilot-sdk==0.2.0` in the validated environment                                                          | <https://github.com/github/copilot-sdk>     |
| GitHub Copilot CLI   | User-installed CLI; Retrieve does not vendor its binaries or source                                                              | <https://github.com/github/copilot-cli>     |
| Azure AI Search REST | Small API map retained in `docs/reference/azure-search-api/`; runtime uses supported Azure SDK/REST versions                     | <https://learn.microsoft.com/azure/search/> |

## Update procedure

1. Update one dependency at a time in `retrieve-core/pyproject.toml`.
2. Inspect the installed public signatures used by Retrieve.
3. Run focused contract tests for settings, indexing, query evidence, retry behavior, and authentication.
4. Run the complete Python and frontend suites.
5. Build and inspect the GraphRAG job image.
6. Run a disposable Azure sample before accepting GraphRAG or Azure SDK changes.

Copied source snapshots removed during Plan 2 are recoverable from Git history. Their pre-removal aggregate hash is recorded in `docs/audits/repository-cleanup-2026-07-11.md`.
