"""Tests for registry/architectures.py and registry/models.py."""

import pytest

from retrieve.registry.architectures import ARCHITECTURES, Architecture, get_architecture
from retrieve.registry.models import EMBEDDING_MODELS, RERANKER_MODELS


class TestArchitectureRegistry:
    def test_all_architectures_present(self):
        expected = [
            "keyword",
            "single-vector",
            "hybrid",
            "hybrid-reranker",
            "hybrid-llm-enriched",
            "multi-vector",
            "agentic-kb",
            "graphrag",
            "lightrag",
        ]
        for name in expected:
            assert name in ARCHITECTURES, f"Missing architecture: {name}"

    def test_architecture_count(self):
        assert len(ARCHITECTURES) == 9

    def test_architecture_fields(self):
        for name, arch in ARCHITECTURES.items():
            assert isinstance(arch, Architecture)
            assert arch.name  # non-empty
            assert arch.accuracy  # has ★ rating
            assert arch.cost  # has $ rating
            assert arch.latency  # has ★ rating
            assert arch.best_for  # has description
            assert len(arch.required_azure_resources) > 0

    def test_get_architecture(self):
        arch = get_architecture("hybrid")
        assert arch.name == "Hybrid (keyword + vector)"

    def test_get_architecture_not_found(self):
        with pytest.raises(ValueError, match="Unknown architecture"):
            get_architecture("nonexistent")

    def test_accuracy_ratings_match_vision_doc(self):
        """Verify ★/$ ratings match the vision doc's Phase 3 table."""
        assert ARCHITECTURES["keyword"].accuracy == "★★"
        assert ARCHITECTURES["keyword"].cost == "$"
        assert ARCHITECTURES["single-vector"].accuracy == "★★★"
        assert ARCHITECTURES["hybrid"].accuracy == "★★★★"
        assert ARCHITECTURES["hybrid-reranker"].accuracy == "★★★★½"
        assert ARCHITECTURES["graphrag"].accuracy == "★★★★★"
        assert ARCHITECTURES["graphrag"].cost == "$$$$$"

    def test_toggleable_components(self):
        # hybrid-reranker should be the most toggleable
        hr = ARCHITECTURES["hybrid-reranker"]
        assert "semantic_reranker" in hr.toggleable_components
        assert hr.toggleable_components == ["semantic_reranker"]
        # keyword should have none
        assert len(ARCHITECTURES["keyword"].toggleable_components) == 0


class TestEmbeddingModelRegistry:
    def test_all_models_present(self):
        expected = ["text-embedding-3-small", "text-embedding-3-large", "bge-m3", "cohere-embed-v3"]
        for name in expected:
            assert name in EMBEDDING_MODELS, f"Missing model: {name}"

    def test_model_count(self):
        assert len(EMBEDDING_MODELS) == 4

    def test_model_fields(self):
        for name, model in EMBEDDING_MODELS.items():
            assert model.name
            assert model.dimensions > 0
            assert model.mteb_avg > 0
            assert model.cost_per_1m
            assert model.provider in ("azure_openai", "self_hosted", "cohere")

    def test_dimensions_match_vision_doc(self):
        assert EMBEDDING_MODELS["text-embedding-3-small"].dimensions == 1536
        assert EMBEDDING_MODELS["text-embedding-3-large"].dimensions == 3072
        assert EMBEDDING_MODELS["bge-m3"].dimensions == 1024


class TestRerankerRegistry:
    def test_all_rerankers_present(self):
        expected = ["azure-semantic-ranker", "bge-reranker-v2-m3", "rank1", "cohere-reranker"]
        for name in expected:
            assert name in RERANKER_MODELS, f"Missing reranker: {name}"

    def test_reranker_count(self):
        assert len(RERANKER_MODELS) == 4

    def test_azure_semantic_ranker_is_native(self):
        asr = RERANKER_MODELS["azure-semantic-ranker"]
        assert asr.provider == "azure_native"
