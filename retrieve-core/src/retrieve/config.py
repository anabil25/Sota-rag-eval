"""Configuration system — loads retrieve.yaml and provides typed access."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    """BYOK provider config — passed directly to CopilotClient.create_session().

    Supports Azure OpenAI, Ollama, or any OpenAI-compatible endpoint.
    When omitted, the Copilot SDK uses the signed-in GitHub Copilot user.
    """

    type: str = Field(
        default="openai",
        description="Provider type: 'openai', 'azure', or 'anthropic'",
    )
    base_url: str | None = None
    api_key: str | None = None
    bearer_token: str | None = None
    wire_api: str | None = None  # 'completions' or 'responses'
    azure: dict[str, str] | None = None  # {"api_version": "2024-10-21"}

    def to_sdk_dict(self) -> dict[str, Any]:
        """Convert to the dict format expected by create_session(provider=...)."""
        d: dict[str, Any] = {"type": self.type}
        if self.base_url:
            d["base_url"] = self.base_url
        if self.api_key:
            d["api_key"] = self.api_key
        if self.bearer_token:
            d["bearer_token"] = self.bearer_token
        if self.wire_api:
            d["wire_api"] = self.wire_api
        if self.azure:
            d["azure"] = self.azure
        return d


class CopilotConfig(BaseModel):
    """Copilot SDK settings."""

    model: str = "gpt-4.1"
    provider: ProviderConfig | None = None
    github_token: str | None = None  # Override for auth
    timeout: float = 120.0  # send_and_wait timeout


class CorpusConfig(BaseModel):
    source: str = ""
    plugin: str = "html"
    output_dir: str = "corpus"


class AzureConfig(BaseModel):
    resource_group: str = ""
    location: str = "southcentralus"
    name_prefix: str = "retrieve"
    subscription_id: str = ""
    deployer_object_id: str = ""


class EvalConfig(BaseModel):
    mode: str = "sample"  # "sample" (testing, ~30 questions) or "full" (~0.5 per doc)
    categories: list[str] = Field(default_factory=lambda: [
        "factual_lookup",
        "procedural",
        "cross_document",
        "cross_policy",
        "edge_case",
        "negation",
        "colloquial_mapping",
        "calculation",
        "unanswerable",
    ])


class RetrieveConfig(BaseModel):
    """Top-level configuration loaded from retrieve.yaml."""

    copilot: CopilotConfig = Field(default_factory=CopilotConfig)
    corpus: CorpusConfig = Field(default_factory=CorpusConfig)
    azure: AzureConfig = Field(default_factory=AzureConfig)
    eval: EvalConfig = Field(default_factory=EvalConfig)
    architectures: list[str] = Field(default_factory=lambda: ["hybrid"])
    db_path: str = "retrieve.db"
    log_level: str = "INFO"
    azure_sdk_logging: bool = False


def load_config(path: str | Path = "retrieve.yaml") -> RetrieveConfig:
    """Load config from YAML file, falling back to defaults."""
    p = Path(path)
    if p.exists():
        raw: dict[str, Any] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return RetrieveConfig.model_validate(raw)
    return RetrieveConfig()
