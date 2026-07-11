"""Tests for locked, validated, atomic YAML configuration updates."""

from concurrent.futures import ThreadPoolExecutor

import pytest
import yaml

from retrieve.config import RetrieveConfig
from retrieve.config_io import atomic_update_yaml
from retrieve.web.app import _apply_azure_args


def test_atomic_update_preserves_unrelated_configuration(tmp_path):
    path = tmp_path / "retrieve.yaml"
    path.write_text(
        "architectures: [keyword]\nazure:\n  name_prefix: retrieve\n",
        encoding="utf-8",
    )

    def update(raw):
        raw.setdefault("azure", {})["location"] = "westus3"
        return raw

    result = atomic_update_yaml(path, update)

    assert result["azure"]["location"] == "westus3"
    persisted = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert persisted["architectures"] == ["keyword"]
    assert persisted["azure"] == {
        "name_prefix": "retrieve",
        "location": "westus3",
    }
    assert not list(tmp_path.glob(".retrieve.yaml.*.tmp"))


def test_failed_update_leaves_original_file_unchanged(tmp_path):
    path = tmp_path / "retrieve.yaml"
    original = "architectures: [keyword]\n"
    path.write_text(original, encoding="utf-8")

    def fail(_raw):
        raise RuntimeError("validation failed")

    with pytest.raises(RuntimeError, match="validation failed"):
        atomic_update_yaml(path, fail)

    assert path.read_text(encoding="utf-8") == original


def test_non_mapping_yaml_is_rejected_without_replacement(tmp_path):
    path = tmp_path / "retrieve.yaml"
    original = "- invalid\n- root\n"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="root must be a mapping"):
        atomic_update_yaml(path, lambda raw: raw)

    assert path.read_text(encoding="utf-8") == original


def test_file_lock_prevents_lost_concurrent_updates(tmp_path):
    path = tmp_path / "retrieve.yaml"
    path.write_text("counter: 0\n", encoding="utf-8")

    def increment(_index):
        def update(raw):
            raw["counter"] = int(raw.get("counter", 0)) + 1
            return raw

        atomic_update_yaml(path, update)

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(increment, range(20)))

    assert yaml.safe_load(path.read_text(encoding="utf-8"))["counter"] == 20


def test_apply_azure_args_updates_actual_config_path(tmp_path):
    path = tmp_path / "custom.yaml"
    path.write_text(
        "architectures: [hybrid]\nazure:\n  name_prefix: retrieve\n",
        encoding="utf-8",
    )
    cfg = RetrieveConfig()

    _apply_azure_args(
        {"resource_group": "rg-new", "location": "centralus"},
        cfg,
        path,
    )

    persisted = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert persisted["azure"]["resource_group"] == "rg-new"
    assert persisted["azure"]["location"] == "centralus"
    assert persisted["azure"]["name_prefix"] == "retrieve"
