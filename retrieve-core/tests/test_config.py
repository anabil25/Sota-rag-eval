"""Tests for config.py — YAML loading and typed config access."""

import tempfile
from pathlib import Path

from retrieve.config import (
    ProviderConfig,
    RetrieveConfig,
    load_config,
)


def test_default_config():
    cfg = RetrieveConfig()
    assert cfg.copilot.model == "gpt-4.1"
    assert cfg.copilot.provider is None
    assert cfg.copilot.timeout == 120.0
    assert cfg.db_path == "retrieve.db"
    assert cfg.architectures == ["hybrid"]
    assert cfg.azure.location == "southcentralus"
    assert len(cfg.eval.categories) == 9


def test_load_config_missing_file():
    cfg = load_config("nonexistent.yaml")
    assert cfg.copilot.model == "gpt-4.1"


def test_load_config_from_yaml():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(
            "copilot:\n"
            "  model: gpt-5\n"
            "  timeout: 60\n"
            "azure:\n"
            "  resource_group: test-rg\n"
            "  location: westus2\n"
            "architectures:\n"
            "  - keyword\n"
            "  - hybrid\n"
            "db_path: custom.db\n"
        )
        f.flush()
        cfg = load_config(f.name)

    assert cfg.copilot.model == "gpt-5"
    assert cfg.copilot.timeout == 60.0
    assert cfg.azure.resource_group == "test-rg"
    assert cfg.azure.location == "westus2"
    assert cfg.architectures == ["keyword", "hybrid"]
    assert cfg.db_path == "custom.db"
    Path(f.name).unlink()


def test_load_config_byok_provider():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(
            "copilot:\n"
            "  model: gpt-4\n"
            "  provider:\n"
            "    type: azure\n"
            "    base_url: https://my-resource.openai.azure.com\n"
            "    api_key: test-key\n"
            "    azure:\n"
            "      api_version: '2024-10-21'\n"
        )
        f.flush()
        cfg = load_config(f.name)

    assert cfg.copilot.provider is not None
    assert cfg.copilot.provider.type == "azure"
    assert cfg.copilot.provider.base_url == "https://my-resource.openai.azure.com"
    assert cfg.copilot.provider.api_key == "test-key"

    sdk_dict = cfg.copilot.provider.to_sdk_dict()
    assert sdk_dict["type"] == "azure"
    assert sdk_dict["base_url"] == "https://my-resource.openai.azure.com"
    assert sdk_dict["api_key"] == "test-key"
    assert sdk_dict["azure"] == {"api_version": "2024-10-21"}
    Path(f.name).unlink()


def test_provider_to_sdk_dict_minimal():
    p = ProviderConfig(type="openai", base_url="http://localhost:11434/v1")
    d = p.to_sdk_dict()
    assert d == {"type": "openai", "base_url": "http://localhost:11434/v1"}
    assert "api_key" not in d
    assert "azure" not in d


def test_eval_config_categories():
    cfg = RetrieveConfig()
    expected = [
        "factual_lookup",
        "procedural",
        "cross_document",
        "cross_policy",
        "edge_case",
        "negation",
        "colloquial_mapping",
        "calculation",
        "unanswerable",
    ]
    assert cfg.eval.categories == expected


def test_load_config_empty_yaml():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("")
        f.flush()
        cfg = load_config(f.name)
    assert cfg.copilot.model == "gpt-4.1"
    Path(f.name).unlink()
