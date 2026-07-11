"""Tests for registry/sota_paths.py — SOTA path registry and recommendations."""

import pytest
from retrieve.registry.sota_paths import (
    SOTA_PATHS,
    SOTAPath,
    ComponentToggle,
    recommend_sota_path,
    generate_toggle_combinations,
)
from retrieve.registry.architectures import ARCHITECTURES


class TestSOTAPathRegistry:
    def test_all_paths_present(self):
        expected = ["government-policy", "product-docs", "legal-contracts", "knowledge-base-faq"]
        for name in expected:
            assert name in SOTA_PATHS, f"Missing SOTA path: {name}"

    def test_path_count(self):
        assert len(SOTA_PATHS) == 4

    def test_base_architectures_exist(self):
        """Every SOTA path must reference a valid architecture."""
        for name, path in SOTA_PATHS.items():
            assert path.base_architecture in ARCHITECTURES, (
                f"SOTA path '{name}' references unknown architecture '{path.base_architecture}'"
            )

    def test_components_have_defaults_in_options(self):
        """Every component's default must be one of its options."""
        for name, path in SOTA_PATHS.items():
            for comp in path.components:
                assert comp.default in comp.options, (
                    f"SOTA path '{name}', component '{comp.name}': "
                    f"default '{comp.default}' not in options {comp.options}"
                )

    def test_components_have_at_least_two_options(self):
        """Each component must have at least 2 options (otherwise nothing to toggle)."""
        for name, path in SOTA_PATHS.items():
            for comp in path.components:
                assert len(comp.options) >= 2, (
                    f"SOTA path '{name}', component '{comp.name}': "
                    f"only {len(comp.options)} option(s)"
                )


class TestRecommendSOTAPath:
    def test_government_policy_corpus(self):
        """High cross-ref density → government-policy path."""
        path = recommend_sota_path(doc_count=300, avg_doc_length=3000, cross_ref_density=5.0)
        assert path is not None
        assert path.name == "Government Benefits Policy"

    def test_faq_corpus(self):
        """Short docs, low cross-refs → knowledge-base-faq path."""
        path = recommend_sota_path(doc_count=100, avg_doc_length=500, cross_ref_density=0.2)
        assert path is not None
        assert path.name == "Knowledge Base / FAQ"

    def test_product_docs_corpus(self):
        """Medium length, low cross-refs → product-docs path."""
        path = recommend_sota_path(doc_count=200, avg_doc_length=3000, cross_ref_density=0.5)
        assert path is not None
        assert path.name == "Product Documentation"

    def test_legal_corpus(self):
        """Long docs, high cross-refs → legal-contracts path."""
        path = recommend_sota_path(doc_count=50, avg_doc_length=10000, cross_ref_density=8.0)
        assert path is not None
        assert path.name == "Legal & Contract Corpus"


class TestGenerateToggleCombinations:
    def test_first_is_default(self):
        path = SOTA_PATHS["government-policy"]
        combos = generate_toggle_combinations(path)
        defaults = {c.name: c.default for c in path.components}
        assert combos[0] == defaults

    def test_combination_count(self):
        """Number of combos = 1 (defaults) + sum of (options - 1) for each component."""
        path = SOTA_PATHS["government-policy"]
        expected = 1 + sum(len(c.options) - 1 for c in path.components)
        combos = generate_toggle_combinations(path)
        assert len(combos) == expected

    def test_each_variant_differs_by_one(self):
        """Each non-default combo should differ from defaults by exactly one component."""
        path = SOTA_PATHS["knowledge-base-faq"]
        combos = generate_toggle_combinations(path)
        defaults = combos[0]
        for combo in combos[1:]:
            diffs = [k for k in defaults if defaults[k] != combo[k]]
            assert len(diffs) == 1, f"Expected 1 diff, got {len(diffs)}: {diffs}"

    def test_simple_path(self):
        path = SOTAPath(
            name="test",
            description="test",
            base_architecture="hybrid",
            components=[
                ComponentToggle(name="a", options=["on", "off"], default="on"),
                ComponentToggle(name="b", options=["x", "y", "z"], default="x"),
            ],
        )
        combos = generate_toggle_combinations(path)
        # 1 default + 1 (a=off) + 2 (b=y, b=z) = 4
        assert len(combos) == 4
