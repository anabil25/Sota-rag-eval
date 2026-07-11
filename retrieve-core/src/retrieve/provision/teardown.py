"""Teardown orchestrator — tears down unselected Azure resources.

Skills reference: skills/azure-bicep-iac.md (teardown patterns)
See Retrieve.md Phase 6.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from typing import Any

from rich.console import Console
from rich.table import Table

from retrieve.config import RetrieveConfig
from retrieve.db import RetrieveDB
from retrieve.observability import emit_error, emit_progress, step

log = logging.getLogger(__name__)
console = Console()

IS_WINDOWS = sys.platform == "win32"


def _az_cmd(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["az"] + args, capture_output=True, text=True, shell=IS_WINDOWS
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
        all_archs = []
        for name in cfg.architectures:
            arch = db.get_architecture(name)
            if arch and arch["status"] in ("provisioned", "active"):
                all_archs.append(arch)

        if not all_archs:
            console.print("[yellow]No provisioned architectures to tear down.[/yellow]")
            return

        keep_set = set(keep) if keep else set()
        to_keep = [a for a in all_archs if a["name"] in keep_set]
        to_teardown = [a for a in all_archs if a["name"] not in keep_set]

        if not to_teardown:
            console.print("[green]Nothing to tear down — all architectures are in the keep list.[/green]")
            return

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

        # Teardown: delete indexes, indexers, skillsets, data sources
        for arch in to_teardown:
            arch_config = arch["config"]
            endpoint = arch_config.get("search_endpoint", "")
            index_name = arch_config.get("index_name", "")

            if endpoint and index_name:
                console.print(f"  Removing [red]{arch['name']}[/red] search resources...")
                with step("teardown.delete_search_resources", architecture=arch["name"]):
                    try:
                        _delete_search_resources(endpoint, index_name)
                        emit_progress(
                            f"Removed search resources for {arch['name']}",
                            stage="teardown.delete", architecture=arch["name"],
                        )
                    except Exception as exc:
                        emit_error(
                            f"Failed to delete search resources for {arch['name']}",
                            exc, stage="teardown.delete", architecture=arch["name"],
                        )

            # Update status
            db.conn.execute(
                "UPDATE architectures SET status = 'torn_down' WHERE id = ?",
                (arch["id"],),
            )

        # Mark keepers as active
        for arch in to_keep:
            db.conn.execute(
                "UPDATE architectures SET status = 'active' WHERE id = ?",
                (arch["id"],),
            )

        db.conn.commit()

        # Deployment summary
        console.print("\n[bold green]Teardown complete![/bold green]\n")
        emit_progress(
            f"Teardown complete: kept {len(to_keep)}, removed {len(to_teardown)}",
            stage="teardown.summary", kept=len(to_keep), removed=len(to_teardown),
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
                log.warning("Failed to delete %s: %s", name, e)

    console.print(f"    [dim]Search resources removed[/dim]")


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
