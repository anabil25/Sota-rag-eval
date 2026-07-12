"""Teardown orchestrator — tears down unselected Azure resources.

Reference: docs/reference/skills/azure-bicep-iac.md (app-level teardown patterns)
See Retrieve.md Phase 6.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote

import requests
from rich.console import Console
from rich.table import Table

from retrieve.cli_process import resolve_cli_command
from retrieve.config import RetrieveConfig
from retrieve.db import RetrieveDB
from retrieve.observability import emit_error, emit_progress, step

log = logging.getLogger(__name__)
console = Console()

PROTECTED_RESOURCE_GROUPS = {"rg-ret-test2"}


def _az_cmd(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        resolve_cli_command(["az", *args]),
        capture_output=True,
        text=True,
    )


def teardown(
    keep: list[str] | None,
    cfg: RetrieveConfig,
):
    """Tear down Azure resources for architectures not in the keep list.

    Retains selected architecture indexes and updates their status to 'active'.
    Tears down rejected architecture indexes and updates their status to 'torn_down'.
    Shared resources (Storage, AI Foundry, Search Service) are NEVER deleted
    — only individual indexes/indexers are removed.
    """
    db = RetrieveDB(cfg.db_path)
    try:
        # Get all provisioned/active architectures
        all_archs = [
            architecture
            for architecture in db.get_latest_architectures()
            if architecture["status"] in ("provisioned", "active")
        ]

        if not all_archs:
            console.print("[yellow]No provisioned architectures to tear down.[/yellow]")
            return

        keep_set = set(keep) if keep else set()
        to_keep = [a for a in all_archs if a["name"] in keep_set]
        to_teardown = [a for a in all_archs if a["name"] not in keep_set]

        if not to_teardown:
            console.print(
                "[green]Nothing to tear down — all architectures are in the keep list.[/green]"
            )

        # Show what will happen
        console.print("\n[bold]Teardown Plan[/bold]\n")
        t = Table()
        t.add_column("Architecture")
        t.add_column("Action", style="bold")
        for a in to_keep:
            t.add_row(a["name"], "[green]KEEP[/green]")
        for a in to_teardown:
            t.add_row(a["name"], "[red]TEAR DOWN[/red]")
        console.print(t)
        console.print()

        # Delete all loser-owned artifacts before committing any status changes.
        for arch in to_teardown:
            console.print(f"  Removing [red]{arch['name']}[/red] owned artifacts...")
            with step("teardown.delete_architecture_resources", architecture=arch["name"]):
                try:
                    _delete_architecture_resources(arch)
                    emit_progress(
                        f"Removed owned artifacts for {arch['name']}",
                        stage="teardown.delete",
                        architecture=arch["name"],
                    )
                except Exception as exc:
                    emit_error(
                        f"Failed to delete owned artifacts for {arch['name']}",
                        exc,
                        stage="teardown.delete",
                        architecture=arch["name"],
                    )
                    raise

        graph_runtime_kept = any(
            arch["name"] in {"graphrag", "lightrag", "multi-vector"} for arch in to_keep
        )
        graphrag_loser = next(
            (arch for arch in to_teardown if arch["name"] == "graphrag"),
            None,
        )
        if graphrag_loser and not graph_runtime_kept:
            _delete_graph_runtime(graphrag_loser["config"])

        session = db.get_generation_preferences("ui_session") or {}
        for arch in to_teardown:
            db.conn.execute(
                "UPDATE architectures SET status = 'torn_down' WHERE id = ?",
                (arch["id"],),
            )

        # Mark keepers as active
        for arch in to_keep:
            promoted_config = _promoted_architecture_config(db, arch, session)
            db.conn.execute(
                "UPDATE architectures SET status = 'active', config = ? WHERE id = ?",
                (json.dumps(promoted_config), arch["id"]),
            )

        db.conn.commit()

        # Deployment summary
        console.print("\n[bold green]Teardown complete![/bold green]\n")
        emit_progress(
            f"Teardown complete: kept {len(to_keep)}, removed {len(to_teardown)}",
            stage="teardown.summary",
            kept=len(to_keep),
            removed=len(to_teardown),
        )
        if to_keep:
            console.print("[bold]Active architectures:[/bold]")
            for a in to_keep:
                cfg_data = a["config"]
                console.print(f"  [green]✓ {a['name']}[/green]")
                console.print(f"    Endpoint: [cyan]{cfg_data.get('search_endpoint', '')}[/cyan]")
                console.print(f"    Index:    [cyan]{cfg_data.get('index_name', '')}[/cyan]")

    finally:
        db.close()


def _delete_architecture_resources(architecture: dict) -> None:
    name = str(architecture["name"])
    config = architecture.get("config") or {}
    endpoint = str(config.get("search_endpoint") or "")
    index_name = str(config.get("index_name") or "")
    if name == "agentic-kb":
        _delete_agentic_resources(endpoint, index_name)
    elif name == "graphrag":
        _delete_graphrag_search_resources(endpoint, config)
        _verify_graphrag_blob_retention(config)
    elif name == "lightrag":
        _delete_lightrag_state(config)
    elif endpoint and index_name:
        _delete_search_resources(endpoint, index_name)


def _promoted_architecture_config(db: RetrieveDB, architecture: dict, session: dict) -> dict:
    selected_run_id = session.get("selected_run_id")
    if not selected_run_id or session.get("final_winner") != architecture["name"]:
        return dict(architecture.get("config") or {})
    run = db.get_run(int(selected_run_id))
    if not run or run.get("status") != "completed":
        raise ValueError("Selected winner run is not completed")
    run_config = dict(run.get("architecture_config") or {})
    candidate = str(run_config.get("candidate_base") or run["architecture_name"]).split("[", 1)[0]
    if candidate != architecture["name"]:
        raise ValueError("Selected winner run does not belong to the kept architecture")
    expected_eval_set = session.get("final_eval_set_id")
    expected_fingerprint = session.get("final_corpus_fingerprint")
    if expected_eval_set and int(run["eval_set_id"]) != int(expected_eval_set):
        raise ValueError("Selected winner run does not match the final eval set")
    if expected_fingerprint and run_config.get("corpus_fingerprint") != expected_fingerprint:
        raise ValueError("Selected winner run does not match the final corpus")
    return {
        **dict(architecture.get("config") or {}),
        **run_config,
        "selected_run_id": int(run["id"]),
        "selected_experiment_id": str(run_config.get("experiment_id") or ""),
        "selected_eval_set_id": int(run["eval_set_id"]),
        "selected_metrics": dict(run.get("aggregate_metrics") or {}),
    }


def _delete_search_resources(endpoint: str, index_name: str):
    """Delete index, indexer, skillset, and data source for an architecture.

    Uses DefaultAzureCredential via the Python SDK.
    """
    from azure.identity import DefaultAzureCredential
    from azure.search.documents.indexes import SearchIndexClient, SearchIndexerClient

    credential = DefaultAzureCredential()
    index_client = SearchIndexClient(endpoint, credential)
    indexer_client = SearchIndexerClient(endpoint, credential)

    # Delete in order: indexer → skillset → data source → index
    failures: list[str] = []
    for name, delete_fn in [
        (f"{index_name}-indexer", lambda n: indexer_client.delete_indexer(n)),
        (f"{index_name}-skillset", lambda n: indexer_client.delete_skillset(n)),
        (f"{index_name}-ds", lambda n: indexer_client.delete_data_source_connection(n)),
        (index_name, lambda n: index_client.delete_index(n)),
    ]:
        try:
            delete_fn(name)
            log.debug("Deleted %s", name)
        except Exception as e:
            if "404" in str(e) or "not found" in str(e).lower():
                log.debug("Already gone: %s", name)
            else:
                failures.append(f"{name}: {e}")

    if failures:
        raise RuntimeError("Search resource deletion failed: " + "; ".join(failures))

    console.print("    [dim]Search resources removed[/dim]")


def _delete_agentic_resources(endpoint: str, kb_name: str) -> None:
    if not endpoint or not kb_name:
        raise ValueError("Agentic KB teardown requires its Search endpoint and KB name")
    from azure.identity import DefaultAzureCredential

    from retrieve.indexing.search_index import _search_rest_headers

    credential = DefaultAzureCredential()
    base_index = f"{kb_name}-base"
    resources = [
        f"knowledgebases('{quote(kb_name, safe='')}')",
        f"knowledgesources('{quote(f'{base_index}-ks', safe='')}')",
    ]
    for resource in resources:
        response = requests.delete(
            f"{endpoint.rstrip('/')}/{resource}?api-version=2025-11-01-preview",
            headers=_search_rest_headers(credential),
            timeout=(10, 60),
        )
        if response.status_code not in {200, 202, 204, 404}:
            raise RuntimeError(
                f"Agentic Search resource deletion failed for {resource}: "
                f"{response.status_code} {response.text.strip()}"
            )
    _delete_search_resources(endpoint, base_index)


def _delete_graphrag_search_resources(endpoint: str, config: dict) -> None:
    fingerprint = str(config.get("corpus_fingerprint") or "")
    if not endpoint or len(fingerprint) != 64:
        raise ValueError("GraphRAG teardown requires its Search endpoint and corpus fingerprint")
    from azure.identity import DefaultAzureCredential
    from azure.search.documents.indexes import SearchIndexClient

    client = SearchIndexClient(endpoint, DefaultAzureCredential())
    prefix = f"gr-{fingerprint[:8]}-"
    names = [
        str(index.name)
        for index in client.list_indexes()
        if str(index.name).startswith(prefix)
    ]
    for name in names:
        client.delete_index(name)
    remaining = [
        str(index.name) for index in client.list_indexes() if str(index.name).startswith(prefix)
    ]
    if remaining:
        raise RuntimeError("GraphRAG Search indexes remain after deletion: " + ", ".join(remaining))


def _verify_graphrag_blob_retention(config: dict) -> None:
    storage_account = str(config.get("storage_account") or "")
    container_name = str(config.get("graph_output_container") or "graphrag")
    corpus_container = str(config.get("corpus_container") or "corpus")
    resource_group = str(config.get("resource_group") or "")
    subscription_id = str(config.get("subscription_id") or "")
    if not storage_account or not resource_group or not subscription_id:
        raise ValueError("GraphRAG Blob retention requires its Azure resource context")
    if container_name == corpus_container:
        raise ValueError("GraphRAG output container must not be the canonical corpus container")
    result = _az_cmd(
        [
            "storage",
            "account",
            "management-policy",
            "show",
            "--account-name",
            storage_account,
            "--resource-group",
            resource_group,
            "--subscription",
            subscription_id,
            "--output",
            "json",
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Storage lifecycle policy lookup failed")
    policy = json.loads(result.stdout)
    expected_prefixes = {
        f"{container_name}/runs/",
        f"{container_name}/cache/",
        f"{container_name}/jobs/",
    }
    for rule in ((policy.get("policy") or {}).get("rules") or []):
        definition = rule.get("definition") or {}
        delete = (((definition.get("actions") or {}).get("baseBlob") or {}).get("delete") or {})
        prefixes = set((definition.get("filters") or {}).get("prefixMatch") or [])
        if (
            rule.get("name") == "retrieve-delete-graphrag-artifacts"
            and rule.get("enabled") is True
            and expected_prefixes.issubset(prefixes)
            and 0 < float(delete.get("daysAfterModificationGreaterThan") or 0) <= 30
        ):
            return
    raise RuntimeError("GraphRAG Azure-side Blob retention policy is missing or invalid")


def _delete_lightrag_state(config: dict) -> None:
    working_dir = str(config.get("lightrag_working_dir") or "")
    if not working_dir:
        return
    active_path = Path(working_dir).resolve()
    root = Path(str(config.get("lightrag_working_root") or ".lightrag")).resolve()
    runs_root = root / "runs"
    if not active_path.is_relative_to(runs_root) or active_path.parent != runs_root:
        raise ValueError("LightRAG working directory is outside its configured runs root")
    marker = active_path / "retrieve-index.json"
    if not marker.is_file():
        raise ValueError("LightRAG teardown requires an attested completed index")
    identity = json.loads(marker.read_text(encoding="utf-8"))
    if identity.get("corpus_fingerprint") != config.get("representative_corpus_fingerprint"):
        raise ValueError("LightRAG teardown marker does not match the selected corpus")
    shutil.rmtree(root)
    if root.exists():
        raise RuntimeError("LightRAG working root remains after deletion")


def _delete_graph_runtime(config: dict) -> None:
    resource_group = str(config.get("resource_group") or "")
    subscription_id = str(config.get("subscription_id") or "")
    resource_token = str(config.get("resource_token") or "")
    job_name = str(config.get("graph_job_name") or "")
    environment_name = str(config.get("graph_worker_environment") or "")
    if resource_group.lower() in PROTECTED_RESOURCE_GROUPS:
        raise RuntimeError(f"Protected resource group teardown is blocked: {resource_group}")
    expected = {
        "job": f"azgrj{resource_token}",
        "environment": f"azcae{resource_token}",
        "registry": f"azcr{resource_token}",
    }
    if (
        not subscription_id
        or not resource_group
        or not resource_token
        or job_name != expected["job"]
        or environment_name != expected["environment"]
    ):
        raise ValueError("Graph runtime teardown target does not match its deployment contract")
    executions = _az_json(
        [
            "containerapp",
            "job",
            "execution",
            "list",
            "--name",
            job_name,
            "--resource-group",
            resource_group,
            "--subscription",
            subscription_id,
            "--output",
            "json",
        ]
    )
    if any(
        str((execution.get("properties") or {}).get("status") or "").lower() == "running"
        for execution in executions
    ):
        raise RuntimeError("Graph runtime teardown is blocked by an active execution")
    for args in (
        ["containerapp", "job", "delete", "--name", job_name],
        ["containerapp", "env", "delete", "--name", environment_name],
        ["acr", "delete", "--name", expected["registry"]],
    ):
        result = _az_cmd(
            [
                *args,
                "--resource-group",
                resource_group,
                "--subscription",
                subscription_id,
                "--yes",
            ]
        )
        if result.returncode != 0 and "not found" not in result.stderr.lower():
            raise RuntimeError(result.stderr.strip() or f"Azure deletion failed: {' '.join(args)}")
    _delete_graph_support_resources(config)


def _delete_graph_support_resources(config: dict) -> None:
    resource_group = str(config.get("resource_group") or "")
    subscription_id = str(config.get("subscription_id") or "")
    resource_token = str(config.get("resource_token") or "")
    location = str(config.get("location") or "").replace(" ", "").lower()
    if resource_group.lower() in PROTECTED_RESOURCE_GROUPS:
        raise RuntimeError(f"Protected resource group teardown is blocked: {resource_group}")
    if not resource_group or not subscription_id or not resource_token or not location:
        raise ValueError("Graph support teardown requires its deployment contract")
    identity_name = f"azid{resource_token}"
    virtual_network_name = f"azvnet{resource_token}"
    network_security_group_name = f"{virtual_network_name}-container-apps-nsg-{location}"

    identity_result = _az_cmd(
        [
            "identity",
            "show",
            "--name",
            identity_name,
            "--resource-group",
            resource_group,
            "--subscription",
            subscription_id,
            "--output",
            "json",
        ]
    )
    if identity_result.returncode == 0:
        principal_id = str(json.loads(identity_result.stdout).get("principalId") or "")
        if principal_id:
            assignments = _az_json(
                [
                    "role",
                    "assignment",
                    "list",
                    "--assignee",
                    principal_id,
                    "--subscription",
                    subscription_id,
                    "--output",
                    "json",
                ]
            )
            for assignment in assignments:
                assignment_id = str(assignment.get("id") or "")
                if assignment_id:
                    result = _az_cmd(
                        [
                            "role",
                            "assignment",
                            "delete",
                            "--ids",
                            assignment_id,
                            "--subscription",
                            subscription_id,
                        ]
                    )
                    if result.returncode != 0:
                        raise RuntimeError(result.stderr.strip() or "Role deletion failed")
    elif not _is_not_found(identity_result.stderr):
        raise RuntimeError(identity_result.stderr.strip() or "Identity lookup failed")

    commands = (
        [
            "identity",
            "delete",
            "--name",
            identity_name,
            "--resource-group",
            resource_group,
            "--subscription",
            subscription_id,
        ],
        [
            "network",
            "vnet",
            "subnet",
            "delete",
            "--name",
            "container-apps",
            "--vnet-name",
            virtual_network_name,
            "--resource-group",
            resource_group,
            "--subscription",
            subscription_id,
        ],
        [
            "network",
            "nsg",
            "delete",
            "--name",
            network_security_group_name,
            "--resource-group",
            resource_group,
            "--subscription",
            subscription_id,
        ],
    )
    for command in commands:
        result = _az_cmd(command)
        if result.returncode != 0 and not _is_not_found(result.stderr):
            details = result.stderr.strip() or f"Azure deletion failed: {' '.join(command)}"
            raise RuntimeError(details)


def _is_not_found(message: str) -> bool:
    normalized = message.lower()
    return "not found" in normalized or "could not be found" in normalized


def _az_json(args: list[str]) -> list[dict]:
    result = _az_cmd(args)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Azure query failed")
    payload = json.loads(result.stdout or "[]")
    if not isinstance(payload, list):
        raise RuntimeError("Azure query returned an invalid response")
    return payload


def delete_resource_group(cfg: RetrieveConfig):
    """Delete the entire resource group (final cleanup).

    This removes all Azure resources. Use after teardown() when you
    want to clean up everything, not just search artifacts.
    """
    rg = cfg.azure.resource_group
    if not rg:
        console.print("[yellow]No resource_group set — nothing to delete.[/yellow]")
        return

    console.print(f"\n[bold]Deleting resource group '{rg}'...[/bold]")
    result = _az_cmd(["group", "delete", "-n", rg, "--yes", "--no-wait"])
    if result.returncode == 0:
        console.print(f"  [green]Resource group '{rg}' deletion initiated[/green]")
    else:
        console.print(f"  [red]Failed: {result.stderr[:200]}[/red]")
