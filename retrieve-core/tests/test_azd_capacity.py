from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from retrieve.config import RetrieveConfig
from retrieve.provision.azd import (
    REGION_CANDIDATES,
    RegionCapacityAssessment,
    RegionUnavailableError,
    _cleanup_temporary_graph_runtime,
    _purge_matching_soft_deleted_ai_account,
    _selected_architectures,
    assess_region_capacity,
    classify_deployment_failure,
    provision_architectures,
)


def test_swedencentral_is_a_provisioning_candidate():
    assert "swedencentral" in REGION_CANDIDATES


def _assessment(region: str) -> RegionCapacityAssessment:
    return RegionCapacityAssessment(
        region=region,
        search_sku="basic",
        search_current=0,
        search_limit=12,
        chat_model="gpt-4.1",
        chat_version="2025-04-14",
        chat_sku="GlobalStandard",
        chat_requested_capacity=10,
        chat_available_capacity=1000,
        embedding_model="text-embedding-3-large",
        embedding_version="1",
        embedding_sku="GlobalStandard",
        embedding_requested_capacity=100,
        embedding_available_capacity=2400,
    )


@patch("retrieve.provision.azd._model_capacity")
@patch("retrieve.provision.azd._search_usage", return_value=(0, 12))
def test_capacity_assessment_requires_exact_model_capacity(mock_search, mock_capacity):
    mock_capacity.side_effect = [1000, 2400]

    assessment = assess_region_capacity("sub-test", "northcentralus")

    assert assessment.search_limit == 12
    assert assessment.chat_available_capacity == 1000
    assert assessment.embedding_available_capacity == 2400
    assert mock_capacity.call_args_list[0].kwargs["model_version"] == "2025-04-14"
    assert mock_capacity.call_args_list[1].kwargs["model_version"] == "1"


@patch("retrieve.provision.azd._search_usage", return_value=(12, 12))
def test_capacity_assessment_rejects_exhausted_search_quota(mock_search):
    with pytest.raises(RegionUnavailableError, match="quota is exhausted"):
        assess_region_capacity("sub-test", "northcentralus")


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("InsufficientCapacity: regional capacity unavailable", "capacity"),
        ("QuotaExceeded: operation exceeds approved quota", "quota"),
        ("AuthorizationFailed", "fatal"),
    ],
)
def test_deployment_failure_classification(message, expected):
    assert classify_deployment_failure(message) == expected


def test_persisted_ui_architectures_override_yaml_defaults(tmp_path):
    from retrieve.db import RetrieveDB

    config_path = tmp_path / "retrieve.yaml"
    config_path.write_text("architectures: [hybrid]\n", encoding="utf-8")
    cfg = RetrieveConfig(db_path="retrieve.db", architectures=["hybrid"])
    db = RetrieveDB(tmp_path / "retrieve.db")
    db.upsert_generation_preferences(
        {"selected_architectures": ["hybrid-reranker", "graphrag"]},
        "ui_session",
    )
    db.close()

    assert _selected_architectures(cfg, config_path) == [
        "hybrid-reranker",
        "graphrag",
    ]


@patch("retrieve.provision.azd.load_config")
@patch("retrieve.provision.azd._private_corpus_is_attested", return_value=True)
@patch("retrieve.provision.azd._purge_matching_soft_deleted_ai_account")
@patch("retrieve.provision.azd._cleanup_failed_attempt")
@patch("retrieve.provision.azd._run")
@patch("retrieve.provision.azd._set_azd_value")
@patch("retrieve.provision.azd.assess_region_capacity")
@patch("retrieve.provision.azd._validate_provider_registrations")
@patch("retrieve.provision.azd._azd_value")
def test_capacity_failure_cleans_then_retries_whole_stack_region(
    mock_value,
    mock_validate,
    mock_assess,
    mock_set,
    mock_run,
    mock_cleanup,
    mock_purge_deleted,
    mock_attested,
    mock_load_config,
    tmp_path,
):
    values = {
        "AZURE_ENV_NAME": "retrieve-test-1234",
        "AZURE_SUBSCRIPTION_ID": "sub-test",
        "RETRIEVE_DEPLOYMENT_REGION": "northcentralus",
        "AZURE_LOCATION": "northcentralus",
        "AZURE_SEARCH_SKU": "basic",
        "AZURE_OPENAI_CHAT_CAPACITY": "10",
        "AZURE_OPENAI_EMBEDDING_CAPACITY": "100",
    }
    mock_value.side_effect = lambda name: values.get(name, "")
    mock_assess.side_effect = lambda _sub, region, **_kwargs: _assessment(region)
    calls = {"provision": 0}

    def run(command, **_kwargs):
        if command[:3] == ["azd", "provision", "--preview"]:
            return SimpleNamespace(returncode=0, stdout="preview", stderr="")
        if command[:2] == ["azd", "provision"]:
            calls["provision"] += 1
            if calls["provision"] == 1:
                return SimpleNamespace(
                    returncode=1,
                    stdout="InsufficientCapacity in northcentralus",
                    stderr="",
                )
            return SimpleNamespace(returncode=0, stdout="success", stderr="")
        raise AssertionError(command)

    mock_run.side_effect = run
    refreshed = RetrieveConfig()
    refreshed.azure.location = "westus3"
    refreshed.azure.resource_group = "rg-retrieve-test-1234"
    refreshed.architectures = ["graphrag"]
    mock_load_config.return_value = refreshed
    cfg = RetrieveConfig()
    cfg.architectures = ["graphrag"]

    result = provision_architectures(cfg, config_path=tmp_path / "retrieve.yaml")

    assert result["region"] == "westus3"
    mock_cleanup.assert_called_once_with("retrieve-test-1234", "sub-test")
    assert ("AZURE_LOCATION", "northcentralus") in [call.args for call in mock_set.call_args_list]
    assert ("AZURE_LOCATION", "westus3") in [call.args for call in mock_set.call_args_list]
    assert cfg.azure.location == "westus3"


@patch("retrieve.provision.azd.load_config")
@patch("retrieve.provision.azd._cleanup_temporary_graph_runtime")
@patch("retrieve.provision.azd._private_corpus_is_attested", return_value=False)
@patch("retrieve.provision.azd._purge_matching_soft_deleted_ai_account")
@patch("retrieve.provision.azd._run")
@patch("retrieve.provision.azd._set_azd_value")
@patch("retrieve.provision.azd.assess_region_capacity")
@patch("retrieve.provision.azd._validate_provider_registrations")
@patch("retrieve.provision.azd._azd_value")
def test_fresh_winner_deployment_uses_temporary_seed_runtime(
    mock_value,
    mock_validate,
    mock_assess,
    mock_set,
    mock_run,
    mock_purge_deleted,
    mock_attested,
    mock_cleanup_runtime,
    mock_load_config,
    tmp_path,
):
    values = {
        "AZURE_ENV_NAME": "retrieve-test-1234",
        "AZURE_SUBSCRIPTION_ID": "sub-test",
        "RETRIEVE_DEPLOYMENT_REGION": "northcentralus",
        "AZURE_LOCATION": "northcentralus",
        "AZURE_SEARCH_SKU": "basic",
        "AZURE_OPENAI_CHAT_CAPACITY": "10",
        "AZURE_OPENAI_EMBEDDING_CAPACITY": "100",
    }
    mock_value.side_effect = lambda name: values.get(name, "")
    mock_assess.return_value = _assessment("northcentralus")
    mock_run.side_effect = [
        SimpleNamespace(returncode=0, stdout="preview", stderr=""),
        SimpleNamespace(returncode=0, stdout="success", stderr=""),
    ]
    refreshed = RetrieveConfig()
    refreshed.azure.location = "northcentralus"
    refreshed.architectures = ["hybrid-reranker"]
    mock_load_config.return_value = refreshed
    cfg = RetrieveConfig(architectures=["hybrid-reranker"])

    result = provision_architectures(cfg, config_path=tmp_path / "retrieve.yaml")

    assert result["status"] == "provisioned"
    assert ("AZURE_DEPLOY_GRAPH_RUNTIME", "true") in [
        call.args for call in mock_set.call_args_list
    ]
    mock_cleanup_runtime.assert_called_once_with(
        cfg,
        environment_name="retrieve-test-1234",
        subscription_id="sub-test",
        region="northcentralus",
    )


@patch("retrieve.provision.azd._set_azd_value")
@patch("retrieve.provision.teardown._delete_graph_runtime")
@patch("retrieve.provision.azd._azd_value")
def test_temporary_seed_runtime_cleanup_uses_exact_outputs(
    mock_value,
    mock_delete,
    mock_set,
):
    values = {
        "AZURE_RESOURCE_TOKEN": "token123",
        "AZURE_GRAPHRAG_JOB_NAME": "azgrjtoken123",
        "AZURE_CONTAINER_APPS_ENVIRONMENT_NAME": "azcaetoken123",
    }
    mock_value.side_effect = lambda name: values.get(name, "")
    cfg = RetrieveConfig()

    _cleanup_temporary_graph_runtime(
        cfg,
        environment_name="retrieve-e2e",
        subscription_id="sub-test",
        region="northcentralus",
    )

    mock_delete.assert_called_once_with(
        {
            "resource_group": "rg-retrieve-e2e",
            "subscription_id": "sub-test",
            "resource_token": "token123",
            "location": "northcentralus",
            "graph_job_name": "azgrjtoken123",
            "graph_worker_environment": "azcaetoken123",
        }
    )
    mock_set.assert_called_once_with("AZURE_DEPLOY_GRAPH_RUNTIME", "false")


@patch("retrieve.provision.azd._run")
@patch("retrieve.provision.azd._azd_value", return_value="azaitoken123")
def test_purges_only_exact_soft_deleted_ai_account(mock_value, mock_run):
    deleted_id = (
        "/subscriptions/sub-test/providers/Microsoft.CognitiveServices/locations/"
        "northcentralus/resourceGroups/rg-retrieve-e2e/deletedAccounts/azaitoken123"
    )
    mock_run.side_effect = [
        SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "id": deleted_id,
                        "name": "azaitoken123",
                        "location": "northcentralus",
                    },
                    {
                        "id": deleted_id.replace("rg-retrieve-e2e", "rg-other"),
                        "name": "azaitoken123",
                        "location": "northcentralus",
                    },
                ]
            ),
            stderr="",
        ),
        SimpleNamespace(returncode=0, stdout="", stderr=""),
    ]

    _purge_matching_soft_deleted_ai_account(
        "retrieve-e2e",
        "sub-test",
        "northcentralus",
    )

    purge = mock_run.call_args_list[1].args[0]
    assert purge[0:4] == ["az", "cognitiveservices", "account", "purge"]
    assert purge[purge.index("--resource-group") + 1] == "rg-retrieve-e2e"
    assert purge[purge.index("--name") + 1] == "azaitoken123"
