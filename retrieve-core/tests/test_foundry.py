"""Tests for optional Foundry embedding discovery."""

from retrieve import foundry


def test_empty_catalog_query_uses_curated_presets_without_azure(monkeypatch):
    def unexpected_azure_call(*_args, **_kwargs):
        raise AssertionError("Empty catalog discovery must not call Azure CLI")

    monkeypatch.setattr(foundry, "_az_json", unexpected_azure_call)

    result = foundry.search_foundry_embedding_catalog()

    assert result["errors"] == []
    assert {item["name"] for item in result["items"]} >= {
        "text-embedding-3-large",
        "Cohere-embed-v3-english",
        "bge-m3",
    }