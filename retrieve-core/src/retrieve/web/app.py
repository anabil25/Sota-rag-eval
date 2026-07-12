"""FastAPI application — thin wrapper over CLI-tested core modules.

All routes call the same functions as the CLI commands.
Long-running jobs run via asyncio.to_thread() and stream progress
through the observability event bus (no RichCapture monkey-patching).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from retrieve.config import RetrieveConfig, load_config
from retrieve.config_io import atomic_update_yaml
from retrieve.db import ActiveOperationJobError, IdempotencyConflictError, RetrieveDB
from retrieve.observability import (
    configure_event_journal,
    configure_observability,
    operation,
    sse_event_stream,
    step,
)
from retrieve.web.auth import AuthenticatedPrincipal, authorize_mutation

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"

STEP_ORDER = ["ingest", "eval", "mode", "configure", "provision", "compare"]
STEP_TEMPLATES = {
    "ingest": "steps/ingest.html",
    "eval": "steps/eval.html",
    "mode": "steps/mode.html",
    "configure": "steps/configure.html",
    "provision": "steps/provision.html",
    "compare": "steps/compare.html",
    "history": "steps/history.html",
    "settings": "steps/settings.html",
}

STEP_TITLES = {
    "ingest": ("Step 1 - Ingest", "Convert policy source into markdown corpus."),
    "eval": ("Step 2 - Golden Eval Set", "Generate and curate realistic operator questions."),
    "mode": ("Step 3 - Mode Selection", "Choose test mode or SOTA pathing."),
    "configure": ("Step 4 - Configure", "Set architecture and model choices before provisioning."),
    "provision": ("Step 5 - Provision", "Deploy Azure resources and indexing pipeline."),
    "compare": ("Step 6 - Evaluate & Select", "Run eval, compare metrics, and pick a winner."),
    "history": ("History", "Review previous runs and outcomes."),
    "settings": ("Settings", "Review current retrieve configuration."),
}

ALLOWED_JOB_KINDS = frozenset(
    {
        "ingest",
        "eval_generate",
        "eval_curate",
        "provision",
        "provision_index",
        "index",
        "deploy_foundry_embedding",
        "evaluate",
        "teardown",
    }
)
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_UNSAFE_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_SENSITIVE_ARG_TOKENS = ("secret", "password", "token", "api_key", "apikey", "key")


def _redact_job_args(value: Any, key: str = "") -> Any:
    if key and any(token in key.lower() for token in _SENSITIVE_ARG_TOKENS):
        return "***"
    if isinstance(value, dict):
        return {
            str(item_key): _redact_job_args(item, str(item_key)) for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_job_args(item) for item in value]
    return value


# ── Job runner ─────────────────────────────────────────────────────────
# Each job is a thin sync wrapper that calls the SAME core function the
# CLI uses, inside an operation() context so events flow to the event bus.
# asyncio.to_thread() bridges sync→async cleanly (one bridge, no nesting).


def _apply_azure_args(
    args: dict[str, Any],
    cfg: RetrieveConfig,
    config_path: str | Path = "retrieve.yaml",
) -> None:
    """Apply resource_group / location from job args to cfg and persist to retrieve.yaml."""
    rg = str(args.get("resource_group", "")).strip()
    loc = str(args.get("location", "")).strip()
    changed = False
    if rg and rg != cfg.azure.resource_group:
        cfg.azure.resource_group = rg
        changed = True
    if loc and loc != cfg.azure.location:
        cfg.azure.location = loc
        changed = True
    if changed:

        def update(raw: dict[str, Any]) -> dict[str, Any]:
            azure = raw.setdefault("azure", {})
            if not isinstance(azure, dict):
                raise ValueError("retrieve.yaml azure section must be a mapping")
            azure["resource_group"] = cfg.azure.resource_group
            azure["location"] = cfg.azure.location
            return raw

        atomic_update_yaml(config_path, update)


def _load_ui_session(cfg: RetrieveConfig) -> dict[str, Any]:
    try:
        db = RetrieveDB(cfg.db_path)
        try:
            ui = db.get_generation_preferences("ui_session")
        finally:
            db.close()
    except Exception:
        return {}
    return ui if isinstance(ui, dict) else {}


def _patch_ui_session(
    cfg: RetrieveConfig,
    patch: dict[str, Any],
    completed_job_id: str | None = None,
) -> None:
    db = RetrieveDB(cfg.db_path)
    try:
        session = db.get_generation_preferences("ui_session") or {}
        session.update(patch)
        if completed_job_id and session.get("active_job_id") == completed_job_id:
            session["active_job_id"] = ""
            session["active_job_kind"] = ""
            session["active_job_started_at"] = ""
        db.upsert_generation_preferences(session, "ui_session")
    finally:
        db.close()


def _apply_ui_selections(args: dict[str, Any], cfg: RetrieveConfig) -> None:
    """Override cfg.architectures with the user's UI selections (Step 4 — Configure)
    if the caller didn't pass an explicit override in `args`.
    """
    explicit_architectures = args.get("architectures")
    if explicit_architectures:
        if isinstance(explicit_architectures, list):
            cfg.architectures = [str(name) for name in explicit_architectures if str(name)]
        elif isinstance(explicit_architectures, str):
            cfg.architectures = [
                name.strip() for name in explicit_architectures.split(",") if name.strip()
            ]
        if cfg.architectures:
            return  # explicit override wins
    ui = _load_ui_session(cfg)
    if not ui:
        return
    mode = ui.get("selected_mode")
    if mode == "sota":
        # SOTA mode: derive base architecture from the chosen path.
        try:
            from retrieve.registry.sota_paths import SOTA_PATHS

            path_key = ui.get("selected_sota_path")
            path = SOTA_PATHS.get(path_key) if path_key else None
            if path:
                cfg.architectures = [path.base_architecture]
                return
        except Exception:
            pass
    selected = ui.get("selected_architectures")
    if isinstance(selected, list) and selected:
        cfg.architectures = list(selected)


def _embedding_config_from_ui(ui: dict[str, Any]) -> dict[str, Any]:
    selected_embedding = str(ui.get("selected_embedding") or "text-embedding-3-large")
    selected_vectorizer = str(ui.get("selected_vectorizer") or "azure_openai")
    config: dict[str, Any] = {
        "embedding_model": selected_embedding,
        "vectorizer_source": selected_vectorizer,
    }

    if selected_vectorizer == "foundry_deployed":
        deployed_source = str(ui.get("foundry_deployed_vectorizer_source") or "")
        deployed_model = str(ui.get("foundry_deployed_model_name") or selected_embedding)
        deployed_uri = str(ui.get("foundry_deployed_uri") or "")
        if deployed_source == "foundry_cohere" or "cohere" in deployed_model.lower():
            config["vectorizer_source"] = "foundry_cohere"
            config["cohere_uri"] = deployed_uri
            config["cohere_model_name"] = deployed_model
        else:
            config["vectorizer_source"] = "custom_web_api"
            config["custom_embedding_uri"] = deployed_uri
            config["custom_embedding_header_name"] = str(
                ui.get("custom_embedding_header_name") or "api-key"
            )
            raw_dimensions = (
                ui.get("foundry_deployed_dimensions") or ui.get("custom_embedding_dimensions") or 0
            )
            try:
                config["custom_embedding_dimensions"] = int(raw_dimensions)
            except (TypeError, ValueError):
                config["custom_embedding_dimensions"] = 0
    elif selected_vectorizer == "foundry_cohere":
        config["cohere_uri"] = str(ui.get("cohere_uri") or "")
        config["cohere_model_name"] = str(ui.get("cohere_model_name") or "")
    elif selected_vectorizer == "custom_web_api":
        config["custom_embedding_uri"] = str(ui.get("custom_embedding_uri") or "")
        config["custom_embedding_header_name"] = str(
            ui.get("custom_embedding_header_name") or "api-key"
        )
        raw_dimensions = ui.get("custom_embedding_dimensions") or 0
        try:
            config["custom_embedding_dimensions"] = int(raw_dimensions)
        except (TypeError, ValueError):
            config["custom_embedding_dimensions"] = 0
    return {key: value for key, value in config.items() if value not in ("", None)}


def _parse_foundry_catalog_choice(value: Any) -> dict[str, Any]:
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"model_id": value.strip(), "name": value.strip()}
    return parsed if isinstance(parsed, dict) else {}


def _persist_ui_embedding_config(cfg: RetrieveConfig) -> None:
    ui = _load_ui_session(cfg)
    common_overrides = _embedding_config_from_ui(ui)
    architecture_options = ui.get("architecture_options") or {}
    if not common_overrides and not architecture_options:
        return
    db = RetrieveDB(cfg.db_path)
    try:
        for name in cfg.architectures:
            arch = db.get_architecture(name)
            if not arch:
                continue
            selected_options = architecture_options.get(name) or {}
            if not isinstance(selected_options, dict):
                selected_options = {}
            arch_config = {
                **arch.get("config", {}),
                **common_overrides,
                **selected_options,
            }
            db.conn.execute(
                "UPDATE architectures SET config = ? WHERE id = ?",
                (json.dumps(arch_config), arch["id"]),
            )
        db.conn.commit()
    finally:
        db.close()


def _config_summary(cfg: RetrieveConfig) -> dict[str, Any]:
    return {
        "db_path": cfg.db_path,
        "log_level": cfg.log_level,
        "azure_sdk_logging": cfg.azure_sdk_logging,
        "architectures": cfg.architectures,
        "corpus": {
            "source": cfg.corpus.source,
            "plugin": cfg.corpus.plugin,
            "output_dir": cfg.corpus.output_dir,
        },
        "azure": {
            "resource_group": cfg.azure.resource_group,
            "location": cfg.azure.location,
            "name_prefix": cfg.azure.name_prefix,
            "subscription_id": cfg.azure.subscription_id,
            "deployer_object_id": cfg.azure.deployer_object_id,
        },
        "copilot": {
            "model": cfg.copilot.model,
            "provider_type": cfg.copilot.provider.type
            if cfg.copilot.provider
            else "signed-in-user",
            "timeout": cfg.copilot.timeout,
        },
        "eval": {
            "mode": cfg.eval.mode,
            "categories": cfg.eval.categories,
        },
    }


def _architecture_rows(db: RetrieveDB, cfg: RetrieveConfig) -> list[dict[str, Any]]:
    from retrieve.indexing.reconcile import reconcile_architecture_rows

    rows = []
    for name in cfg.architectures:
        rows.append(
            db.get_architecture(name)
            or {
                "name": name,
                "status": "registered",
                "config": {},
                "resources_provisioned": {},
            }
        )
    return reconcile_architecture_rows(db, rows)


def _corpus_file_rows(output_dir: str, cfg: RetrieveConfig) -> list[dict[str, Any]]:
    output_path = Path(output_dir or cfg.corpus.output_dir)
    if not output_path.is_absolute():
        output_path = (
            Path(cfg.corpus.source).parent / output_path if cfg.corpus.source else output_path
        )
    if not output_path.is_dir():
        return []
    return [{"name": f.name, "size": f.stat().st_size} for f in sorted(output_path.glob("*.md"))]


def _sota_recommendation(ui: dict[str, Any]) -> dict[str, Any]:
    from retrieve.registry.sota_paths import recommend_sota_path  # type: ignore

    ingest_stats = ui.get("ingest_stats", {}) or {}
    try:
        doc_count = int(ingest_stats.get("doc_count", 0))
        avg_doc_length = float(ingest_stats.get("avg_doc_length", 0.0))
        cross_ref_density = float(ingest_stats.get("cross_ref_density", 0.0))
        rec = recommend_sota_path(
            doc_count=doc_count,
            avg_doc_length=avg_doc_length,
            cross_ref_density=cross_ref_density,
        )
        if not rec:
            return {"recommended_sota": None, "rationale": ""}
        recommended = rec.model_dump()
        return {
            "recommended_sota": recommended,
            "rationale": (
                f"doc_count={doc_count}, avg_doc_length={avg_doc_length:.0f}, "
                f"cross_ref_density={cross_ref_density:.2f} — matches the "
                f"{recommended['name']} pattern."
            ),
        }
    except Exception:
        return {"recommended_sota": None, "rationale": ""}


def _compare_context(db: RetrieveDB, cfg: RetrieveConfig, ui: dict[str, Any]) -> dict[str, Any]:
    from retrieve.registry.architectures import ARCHITECTURES

    active_version = str(ui.get("active_experiment_eval_set_version") or "").strip()
    active_eval = db.get_eval_set_by_version(active_version) if active_version else None
    active_architectures = ui.get("active_experiment_architectures") or []
    runs = (
        db.get_completed_runs_for_experiment(
            str(ui.get("active_experiment_id") or ""),
            eval_set_id=int(active_eval["id"]),
            architecture_names=[str(name) for name in active_architectures],
            corpus_fingerprint=str(ui.get("active_experiment_corpus_fingerprint") or ""),
        )
        if active_eval and isinstance(active_architectures, list)
        else []
    )
    categories = {}
    failures = {}
    for run in runs:
        categories[run["id"]] = db.get_per_category_scores(run["id"])
        failures[run["id"]] = db.get_failures_for_run(run["id"])

    arch_costs: dict[str, int] = {}
    for run in runs:
        key = run["architecture_name"]
        cfg_blob = run.get("architecture_config") or {}
        base_key = cfg_blob.get("_variant_of") or key.split("[", 1)[0]
        if base_key in ARCHITECTURES:
            arch_costs[key] = ARCHITECTURES[base_key].est_monthly_usd

    winners: list[str] = ui.get("winners") or []
    deployments = []
    for name in winners:
        arch = db.get_architecture(name)
        if not arch:
            continue
        cfg_data = arch.get("config") or {}
        resources = arch.get("resources_provisioned") or {}
        arch_meta = ARCHITECTURES.get(name)
        if name == "agentic-kb":
            handoff_kind = "agentic-kb"
            endpoint = resources.get("search_endpoint") or cfg_data.get("search_endpoint")
            query_target = resources.get("index_name") or cfg_data.get("index_name")
            handoff_note = (
                "This winner uses Azure AI Search Knowledge Base retrieval. "
                "Call it through the Retrieve backend adapter; it is not a docs/search request."
            )
        elif name == "graphrag":
            handoff_kind = "graphrag-job"
            endpoint = None
            query_target = cfg_data.get("graph_job_name")
            handoff_note = (
                "This winner is queried through the Retrieve GraphRAG job adapter. "
                "No direct production HTTP endpoint is deployed."
            )
        elif name == "lightrag":
            handoff_kind = (
                "lightrag-http" if cfg_data.get("container_app_endpoint") else "lightrag-local"
            )
            endpoint = cfg_data.get("container_app_endpoint") or None
            query_target = cfg_data.get("lightrag_working_dir")
            handoff_note = (
                "Use the configured LightRAG HTTP service."
                if endpoint
                else "This evaluated winner is a local LightRAG index. Deploy a persistent query "
                "service before connecting an external client."
            )
        else:
            handoff_kind = "azure-ai-search"
            endpoint = resources.get("search_endpoint") or cfg_data.get("search_endpoint")
            query_target = resources.get("index_name") or cfg_data.get("index_name")
            handoff_note = "Use Azure AI Search data-plane retrieval with managed identity."
        deployments.append(
            {
                "architecture_name": name,
                "status": arch.get("status", "unknown"),
                "handoff_kind": handoff_kind,
                "endpoint": endpoint,
                "index_name": query_target if handoff_kind == "azure-ai-search" else None,
                "query_target": query_target,
                "artifact_prefix": cfg_data.get("graph_worker_artifact_prefix"),
                "working_dir": cfg_data.get("lightrag_working_dir"),
                "handoff_note": handoff_note,
                "resource_group": resources.get("resource_group") or cfg.azure.resource_group,
                "location": resources.get("location") or cfg.azure.location,
                "est_monthly_usd": arch_meta.est_monthly_usd if arch_meta else None,
            }
        )

    return {
        "runs": runs,
        "categories": categories,
        "failures": failures,
        "latest_eval": active_eval or db.get_latest_eval_set(),
        "experiment_id": str(ui.get("active_experiment_id") or ""),
        "selected_mode": ui.get("selected_mode") or "",
        "arch_costs": arch_costs,
        "winners": winners,
        "deployments": deployments,
    }


def _run_job_sync(
    kind: str,
    args: dict[str, Any],
    cfg: RetrieveConfig,
    operation_id: str,
    principal_id: str = "",
    config_path: str | Path = "retrieve.yaml",
) -> dict[str, Any]:
    """Execute a job synchronously (called via asyncio.to_thread).

    This function mirrors the CLI command implementations exactly.
    """
    with operation(
        f"web.job.{kind}",
        source="web",
        metadata={
            "job_id": operation_id,
            "args": _redact_job_args(args),
            "principal_id": principal_id,
        },
        operation_id=operation_id,
    ):
        if kind == "ingest":
            from retrieve.ingest import run_ingest

            with step("ingest"):
                stats = run_ingest(
                    source=str(args.get("source", cfg.corpus.source)),
                    plugin_name=str(args.get("plugin", cfg.corpus.plugin)),
                    output_dir=str(args.get("output", cfg.corpus.output_dir)),
                    delay=float(args.get("delay", 0.5)),
                    cfg=cfg,
                )

            _patch_ui_session(
                cfg,
                {
                    "ingest_done": True,
                    "eval_done": False,
                    "configure_done": False,
                    "provision_done": False,
                    "run_done": False,
                    "compare_done": False,
                    "teardown_done": False,
                    "winners": [],
                    "ingest_stats": {
                        "doc_count": stats.doc_count,
                        "avg_doc_length": stats.avg_doc_length,
                        "cross_ref_density": stats.cross_ref_density,
                    },
                },
                completed_job_id=operation_id,
            )
            return {"doc_count": stats.doc_count}

        elif kind == "eval_generate":
            from retrieve.eval.generate import DEFAULT_OPERATOR_CONTEXT, generate_eval_set

            with step("eval_generate"):
                eval_set_id = generate_eval_set(
                    corpus_dir=str(args.get("corpus", cfg.corpus.output_dir)),
                    version_label=str(args.get("version", "v-next")),
                    cfg=cfg,
                    fresh=bool(args.get("fresh", False)),
                    base_eval_set_version=str(args.get("base_eval_set", "latest")),
                    operator_context=str(args.get("operator_context", ""))
                    or DEFAULT_OPERATOR_CONTEXT,
                    mode=str(args.get("mode", cfg.eval.mode)),
                )
            _patch_ui_session(
                cfg,
                {
                    "eval_done": True,
                    "run_done": False,
                    "compare_done": False,
                    "teardown_done": False,
                    "winners": [],
                },
                completed_job_id=operation_id,
            )
            return {"eval_set_id": eval_set_id}

        elif kind == "eval_curate":
            from retrieve.eval.curate import regenerate_eval_set

            source_version = str(args.get("source_version", "latest"))
            if source_version == "latest":
                db = RetrieveDB(cfg.db_path)
                latest = db.get_latest_eval_set()
                db.close()
                if latest:
                    source_version = latest["version_label"]
            with step("eval_curate"):
                eval_set_id = regenerate_eval_set(
                    source_version=source_version,
                    new_version=str(args.get("new_version", f"{source_version}-curated")),
                    steering=args.get("steering", {}),
                    corpus_dir=str(args.get("corpus", cfg.corpus.output_dir)),
                    cfg=cfg,
                )
            _patch_ui_session(
                cfg,
                {
                    "eval_done": True,
                    "run_done": False,
                    "compare_done": False,
                    "teardown_done": False,
                    "winners": [],
                },
                completed_job_id=operation_id,
            )
            return {"eval_set_id": eval_set_id}

        elif kind == "provision":
            from retrieve.provision import provision_architectures

            _apply_azure_args(args, cfg, config_path)
            _apply_ui_selections(args, cfg)
            with step("provision"):
                provision_architectures(cfg, config_path=config_path)
            _persist_ui_embedding_config(cfg)
            _patch_ui_session(
                cfg,
                {
                    "resource_group": cfg.azure.resource_group,
                    "location": cfg.azure.location,
                    "name_prefix": cfg.azure.name_prefix,
                    "provision_done": True,
                    "run_done": False,
                    "compare_done": False,
                    "teardown_done": False,
                    "winners": [],
                },
                completed_job_id=operation_id,
            )
            return {"status": "provisioned"}

        elif kind == "provision_index":
            from retrieve.indexing.run import index_corpus
            from retrieve.provision import provision_architectures

            _apply_azure_args(args, cfg, config_path)
            _apply_ui_selections(args, cfg)
            with step("provision"):
                provision_architectures(cfg, config_path=config_path)
            _persist_ui_embedding_config(cfg)
            with step("index"):
                index_result = index_corpus(cfg) or {}
            _patch_ui_session(
                cfg,
                {
                    "resource_group": cfg.azure.resource_group,
                    "location": cfg.azure.location,
                    "name_prefix": cfg.azure.name_prefix,
                    "provision_done": True,
                    "run_done": False,
                    "compare_done": False,
                    "teardown_done": False,
                    "winners": [],
                },
                completed_job_id=operation_id,
            )
            return {"status": "provisioned_indexed", **index_result}

        elif kind == "index":
            from retrieve.indexing.run import index_corpus

            _apply_azure_args(args, cfg, config_path)
            _apply_ui_selections(args, cfg)
            _persist_ui_embedding_config(cfg)
            with step("index"):
                index_result = index_corpus(cfg) or {}
            _patch_ui_session(
                cfg,
                {
                    "provision_done": True,
                    "run_done": False,
                    "compare_done": False,
                    "teardown_done": False,
                    "winners": [],
                },
                completed_job_id=operation_id,
            )
            return {"status": "indexed", **index_result}

        elif kind == "deploy_foundry_embedding":
            from retrieve.indexing.advanced import deploy_foundry_catalog_model

            choice = _parse_foundry_catalog_choice(args.get("selected_foundry_catalog_model"))
            model_id = str(args.get("model_id") or choice.get("model_id") or "").strip()
            model_name = str(choice.get("name") or args.get("model_name") or model_id).strip()
            if not model_id:
                raise ValueError("Select a Foundry catalog embedding model before deploying")
            workspace_name = str(
                args.get("foundry_workspace_name") or args.get("foundry_project_name") or ""
            ).strip()
            if not workspace_name:
                raise ValueError("Foundry project/workspace name is required")
            resource_group = str(
                args.get("foundry_resource_group") or cfg.azure.resource_group
            ).strip()
            endpoint_name = str(
                args.get("foundry_endpoint_name")
                or f"retrieve-{model_name.lower().replace('_', '-')}"
            ).strip()
            with step("deploy_foundry_embedding"):
                result = deploy_foundry_catalog_model(
                    model_id=model_id,
                    endpoint_name=endpoint_name,
                    project_name=workspace_name,
                    resource_group=resource_group,
                )

            vectorizer_source = (
                "foundry_cohere" if "cohere" in model_name.lower() else "custom_web_api"
            )
            dimensions = int(choice.get("dimensions") or 0)
            db = RetrieveDB(cfg.db_path)
            try:
                sess = db.get_generation_preferences("ui_session") or {}
                sess.update(
                    {
                        "selected_vectorizer": "foundry_deployed",
                        "selected_embedding": model_name,
                        "foundry_resource_group": resource_group,
                        "foundry_workspace_name": workspace_name,
                        "foundry_deployed_endpoint": endpoint_name,
                        "foundry_deployed_uri": result.get("uri", ""),
                        "foundry_deployed_model_name": result.get("model_name", model_name),
                        "foundry_deployed_dimensions": dimensions,
                        "foundry_deployed_vectorizer_source": vectorizer_source,
                        "foundry_catalog_deploy_done": True,
                    }
                )
                if vectorizer_source == "foundry_cohere":
                    sess.update(
                        {
                            "cohere_uri": result.get("uri", ""),
                            "cohere_model_name": result.get("model_name", model_name),
                        }
                    )
                else:
                    sess.update(
                        {
                            "custom_embedding_uri": result.get("uri", ""),
                            "custom_embedding_dimensions": str(dimensions or ""),
                        }
                    )
                db.upsert_generation_preferences(sess, "ui_session")
            finally:
                db.close()
            return {"status": "deployed", **result}

        elif kind == "evaluate":
            from retrieve.eval.runner import run_evaluation

            _apply_ui_selections(args, cfg)

            # Build SOTA variants from the UI selections. Each checked option
            # participates in a bounded cartesian product so SOTA mode can show
            # per-component deltas instead of only one normalized run.
            variants: list[dict[str, Any]] | None = None
            mode = "test"
            try:
                db = RetrieveDB(cfg.db_path)
                try:
                    ui = db.get_generation_preferences("ui_session") or {}
                finally:
                    db.close()
            except Exception:
                ui = {}
            if ui.get("selected_mode") == "sota":
                mode = "sota"
                from itertools import product

                from retrieve.registry.sota_paths import SOTA_PATHS

                path_key = ui.get("selected_sota_path")
                path = SOTA_PATHS.get(path_key) if path_key else None
                raw_toggles = ui.get("sota_toggles") or ui.get("sotaToggles") or {}
                if path:
                    base = path.base_architecture
                    component_options: dict[str, list[str]] = {}
                    for comp in path.components:
                        v = raw_toggles.get(comp.name)
                        if isinstance(v, list) and v:
                            component_options[comp.name] = [str(opt) for opt in v]
                        elif isinstance(v, str) and v:
                            component_options[comp.name] = [v]
                        else:
                            component_options[comp.name] = [comp.default]

                    keys = list(component_options.keys())
                    combos = list(product(*[component_options[k] for k in keys]))
                    combos = combos[:8]

                    variants = []
                    for combo in combos:
                        toggles = dict(zip(keys, combo))
                        label_bits = []
                        for k, v in toggles.items():
                            comp = next((c for c in path.components if c.name == k), None)
                            if comp and v == comp.default:
                                continue
                            label_bits.append(f"{k}={v}")
                        label = base if not label_bits else f"{base}[{','.join(label_bits)}]"
                        variants.append({"base": base, "name": label, "toggles": toggles})

            with step("evaluate"):
                requested_architectures = args.get("architectures") or cfg.architectures
                from retrieve.eval.readiness import validate_architecture_readiness
                from retrieve.indexing.reconcile import reconcile_architecture_rows

                db = RetrieveDB(cfg.db_path)
                try:
                    ready_architectures = []
                    rows = [db.get_architecture(str(name)) for name in requested_architectures]
                    reconcile_architecture_rows(
                        db,
                        [row for row in rows if row is not None],
                    )
                    validate_architecture_readiness(
                        db,
                        cfg,
                        [str(name) for name in requested_architectures],
                    )
                    rows_by_name = {
                        str(name): db.get_architecture(str(name))
                        for name in requested_architectures
                    }
                    not_ready: list[str] = []
                    for name in requested_architectures:
                        row = rows_by_name.get(str(name))
                        row_config = row.get("config", {}) if row else {}
                        if not row or row.get("status") != "active":
                            not_ready.append(str(name))
                            continue
                        if row_config.get("cloud_index_status") in {"started", "failed"}:
                            not_ready.append(str(name))
                            continue
                        ready_architectures.append(str(name))
                finally:
                    db.close()
                if not_ready:
                    raise ValueError(
                        "All selected candidates must pass grounded readiness before evaluation: "
                        + ", ".join(not_ready)
                    )
                experiment = run_evaluation(
                    eval_set_version=str(args.get("eval_set_version", "latest")),
                    architectures=ready_architectures,
                    cfg=cfg,
                    variants=variants,
                    mode=mode,
                    experiment_id=operation_id,
                )
            _patch_ui_session(
                cfg,
                {
                    "run_done": True,
                    "compare_done": False,
                    "teardown_done": False,
                    "winners": [],
                },
                completed_job_id=operation_id,
            )
            return {"status": "completed", **(experiment or {})}

        elif kind == "teardown":
            from retrieve.provision.teardown import teardown

            with step("teardown"):
                keep_list = args.get("keep") or None
                if isinstance(keep_list, str):
                    keep_list = [k.strip() for k in keep_list.split(",") if k.strip()]
                teardown(keep=keep_list, cfg=cfg)
            _patch_ui_session(
                cfg,
                {"teardown_done": True},
                completed_job_id=operation_id,
            )
            return {"status": "torn_down"}

        else:
            raise ValueError(f"Unknown job kind: {kind}")


def create_app(config_path: str = "retrieve.yaml") -> FastAPI:
    configure_observability()
    cfg = load_config(config_path)

    def persist_event(event: dict[str, Any]) -> int:
        event_db = RetrieveDB(cfg.db_path)
        try:
            return event_db.append_operation_event(
                str(event["operation_id"]),
                event,
            )
        finally:
            event_db.close()

    configure_event_journal(persist_event)
    startup_db = RetrieveDB(cfg.db_path)
    try:
        interrupted_jobs = startup_db.mark_interrupted_operation_jobs_failed()
        interrupted_runs = startup_db.mark_interrupted_runs_failed()
        if interrupted_jobs:
            log.warning(
                "Marked %d interrupted operation job(s) failed during startup",
                interrupted_jobs,
            )
        if interrupted_runs:
            log.warning(
                "Marked %d interrupted evaluation run(s) failed during startup",
                interrupted_runs,
            )
    finally:
        startup_db.close()
    app = FastAPI(title="Retrieve", version="0.1.0")
    app.state.cfg = cfg
    app.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    # Track active jobs: operation_id → {kind, task, done, error, result}
    app.state.jobs: dict[str, dict[str, Any]] = {}
    app.state.admission_lock = asyncio.Lock()
    app.state.direct_mutation_active = False

    @app.middleware("http")
    async def authorize_and_serialize_mutations(request: Request, call_next):
        is_mutation = (
            request.url.path.startswith("/api/") and request.method.upper() in _UNSAFE_HTTP_METHODS
        )
        if not is_mutation:
            return await call_next(request)

        try:
            principal = authorize_mutation(request)
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
            )
        request.state.principal = principal

        # Job start performs atomic admission in the route so the background job
        # remains represented after this request returns.
        if request.url.path == "/api/ui/job/start":
            return await call_next(request)

        async with app.state.admission_lock:
            active_job = next(
                (job for job in app.state.jobs.values() if not job.get("done")),
                None,
            )
            admission_db = RetrieveDB(cfg.db_path)
            try:
                durable_active_job = admission_db.get_active_operation_job()
            finally:
                admission_db.close()
            if app.state.direct_mutation_active or active_job or durable_active_job:
                return JSONResponse(
                    status_code=409,
                    content={"detail": "Another environment mutation is already running"},
                )
            app.state.direct_mutation_active = True
        try:
            return await call_next(request)
        finally:
            async with app.state.admission_lock:
                app.state.direct_mutation_active = False

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ── HTML pages ─────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        return RedirectResponse(url="/step/ingest", status_code=302)

    @app.get("/compare", response_class=HTMLResponse)
    async def compare_legacy():
        return RedirectResponse(url="/step/compare", status_code=302)

    @app.get("/history", response_class=HTMLResponse)
    async def history_legacy():
        return RedirectResponse(url="/step/history", status_code=302)

    @app.get("/eval-sets", response_class=HTMLResponse)
    async def eval_sets_legacy():
        return RedirectResponse(url="/step/eval", status_code=302)

    @app.get("/eval-workbench", response_class=HTMLResponse)
    async def eval_workbench_legacy():
        return RedirectResponse(url="/step/eval", status_code=302)

    @app.get("/step/{step_name}", response_class=HTMLResponse)
    async def step_page(request: Request, step_name: str):
        if step_name not in STEP_TEMPLATES:
            raise HTTPException(404, "Unknown step")

        db = RetrieveDB(cfg.db_path)
        try:
            ctx = _build_step_context(step_name, db, cfg)
            ui_session = db.get_generation_preferences("ui_session")
            step_states = _compute_step_states(db, cfg, ui_session)
        finally:
            db.close()

        title, subtitle = STEP_TITLES.get(step_name, ("Retrieve", ""))
        template_ctx = {
            "request": request,
            "cfg": cfg,
            "current_step": step_name,
            "step_states": step_states,
            "ui": ui_session,
            "page_title": title,
            "page_subtitle": subtitle,
            **ctx,
        }
        template_ctx["step_template"] = STEP_TEMPLATES[step_name]

        templates: Jinja2Templates = app.state.templates
        if request.headers.get("HX-Request") == "true":
            return templates.TemplateResponse(request, "partials/content_shell.html", template_ctx)

        return templates.TemplateResponse(request, "base.html", template_ctx)

    # ── REST API (read-only) ───────────────────────────────────────────

    @app.get("/api/status")
    async def api_status():
        db = RetrieveDB(cfg.db_path)
        try:
            latest_eval = db.get_latest_eval_set()
            runs = db.get_all_completed_runs()
            return {
                "eval_set": latest_eval,
                "run_count": len(runs),
                "architectures": cfg.architectures,
            }
        finally:
            db.close()

    @app.get("/api/config")
    async def api_config():
        return _config_summary(cfg)

    @app.get("/api/architecture-status")
    async def api_architecture_status():
        db = RetrieveDB(cfg.db_path)
        try:
            return _architecture_rows(db, cfg)
        finally:
            db.close()

    @app.get("/api/corpus-files")
    async def api_corpus_files(output: str | None = None):
        return {
            "output": output or cfg.corpus.output_dir,
            "files": _corpus_file_rows(output or cfg.corpus.output_dir, cfg),
        }

    @app.get("/api/sota-recommendation")
    async def api_sota_recommendation():
        db = RetrieveDB(cfg.db_path)
        try:
            return _sota_recommendation(db.get_generation_preferences("ui_session"))
        finally:
            db.close()

    @app.get("/api/compare-context")
    async def api_compare_context():
        db = RetrieveDB(cfg.db_path)
        try:
            ui = db.get_generation_preferences("ui_session")
            return _compare_context(db, cfg, ui)
        finally:
            db.close()

    @app.get("/api/runs")
    async def api_runs():
        db = RetrieveDB(cfg.db_path)
        try:
            return db.get_all_completed_runs()
        finally:
            db.close()

    @app.get("/api/runs/{run_id}")
    async def api_run_detail(run_id: int):
        db = RetrieveDB(cfg.db_path)
        try:
            run = db.get_run(run_id)
            if not run:
                raise HTTPException(404, "Run not found")
            results = db.get_results_for_run(run_id)
            category_scores = db.get_per_category_scores(run_id)
            categories = []
            for category, scores in category_scores.items():
                total_questions = sum(1 for r in results if r.get("category") == category)
                failure_count = sum(
                    1 for r in results if r.get("category") == category and r.get("failure_type")
                )
                categories.append(
                    {
                        "category": category,
                        **scores,
                        "total_questions": total_questions,
                        "failure_count": failure_count,
                    }
                )
            failures = db.get_failures_for_run(run_id)
            return {
                "run": run,
                "results": results,
                "categories": categories,
                "failures": failures,
            }
        finally:
            db.close()

    @app.get("/api/eval-sets")
    async def api_eval_sets():
        db = RetrieveDB(cfg.db_path)
        try:
            rows = db.conn.execute("SELECT * FROM eval_sets ORDER BY id DESC").fetchall()
            return [dict(r) for r in rows]
        finally:
            db.close()

    @app.get("/api/eval-sets/{eval_set_id}/questions")
    async def api_eval_questions(eval_set_id: int):
        db = RetrieveDB(cfg.db_path)
        try:
            return db.get_questions(eval_set_id)
        finally:
            db.close()

    @app.get("/api/eval-sets/{eval_set_id}/questions/browse")
    async def api_eval_questions_browse(
        eval_set_id: int,
        category: str | None = None,
        question_type: str | None = None,
        persona: str | None = None,
        intent_family: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ):
        db = RetrieveDB(cfg.db_path)
        try:
            rows = db.get_questions_filtered(
                eval_set_id,
                category=category,
                question_type=question_type,
                persona=persona,
                intent_family=intent_family,
                limit=limit,
                offset=offset,
            )
            total = db.count_questions_filtered(
                eval_set_id,
                category=category,
                question_type=question_type,
                persona=persona,
                intent_family=intent_family,
            )
            return {"total": total, "items": rows}
        finally:
            db.close()

    @app.get("/api/eval-sets/{eval_set_id}/summary")
    async def api_eval_set_summary(eval_set_id: int):
        db = RetrieveDB(cfg.db_path)
        try:
            row = db.conn.execute("SELECT * FROM eval_sets WHERE id = ?", (eval_set_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Eval set not found")
            es = dict(row)
            cats = (
                json.loads(es["category_counts"])
                if isinstance(es["category_counts"], str)
                else es["category_counts"]
            )
            questions = db.get_questions(eval_set_id)
            cat_examples: dict[str, list[str]] = {}
            for q in questions:
                cat = q["category"]
                cat_examples.setdefault(cat, [])
                if len(cat_examples[cat]) < 3:
                    cat_examples[cat].append(q["question_text"])
            return {
                "eval_set": es,
                "categories": cats,
                "examples": cat_examples,
            }
        finally:
            db.close()

    @app.get("/api/architectures")
    async def api_architectures():
        from retrieve.registry.architectures import ARCHITECTURES

        return {k: v.model_dump() for k, v in ARCHITECTURES.items()}

    @app.get("/api/models")
    async def api_models():
        from retrieve.registry.models import EMBEDDING_MODELS, RERANKER_MODELS

        return {
            "embedding": {k: v.model_dump() for k, v in EMBEDDING_MODELS.items()},
            "reranker": {k: v.model_dump() for k, v in RERANKER_MODELS.items()},
        }

    @app.get("/api/foundry/embeddings/deployed")
    async def api_foundry_embeddings_deployed(
        resource_group: str = "",
        workspace_name: str = "",
    ):
        from retrieve.foundry import list_deployed_foundry_embeddings

        return list_deployed_foundry_embeddings(resource_group, workspace_name)

    @app.get("/api/foundry/embeddings/catalog")
    async def api_foundry_embeddings_catalog(query: str = ""):
        from retrieve.foundry import search_foundry_embedding_catalog

        return search_foundry_embedding_catalog(query)

    @app.get("/api/sota-paths")
    async def api_sota_paths():
        from retrieve.registry.sota_paths import SOTA_PATHS

        return {k: v.model_dump() for k, v in SOTA_PATHS.items()}

    # ── REST API (mutations — thin wrappers over core) ─────────────────

    @app.post("/api/ingest")
    async def api_ingest(request: Request):
        body = await request.json()
        source = body.get("source", cfg.corpus.source)
        plugin = body.get("plugin", cfg.corpus.plugin)
        output = body.get("output", cfg.corpus.output_dir)

        from retrieve.ingest import run_ingest

        stats = await asyncio.to_thread(
            run_ingest,
            source=source,
            plugin_name=plugin,
            output_dir=output,
            delay=float(body.get("delay", 0.5)),
            cfg=cfg,
        )
        return {
            "status": "complete",
            "stats": {
                "doc_count": stats.doc_count,
                "avg_doc_length": stats.avg_doc_length,
                "cross_ref_density": stats.cross_ref_density,
            },
        }

    @app.post("/api/eval/generate")
    async def api_eval_generate(request: Request):
        body = await request.json()
        corpus = body.get("corpus", cfg.corpus.output_dir)
        version = body.get("version", "v1")
        fresh = bool(body.get("fresh", False))
        base_eval_set = body.get("base_eval_set", "latest")
        operator_context = body.get("operator_context", "")
        mode = body.get("mode", cfg.eval.mode)

        from retrieve.eval.generate import DEFAULT_OPERATOR_CONTEXT, generate_eval_set

        eval_set_id = await asyncio.to_thread(
            generate_eval_set,
            corpus_dir=corpus,
            version_label=version,
            cfg=cfg,
            fresh=fresh,
            base_eval_set_version=base_eval_set,
            operator_context=operator_context or DEFAULT_OPERATOR_CONTEXT,
            mode=mode,
        )
        return {"status": "complete", "eval_set_id": eval_set_id}

    @app.post("/api/eval/curate")
    async def api_eval_curate(request: Request):
        body = await request.json()
        source_version = body.get("source_version", "latest")
        new_version = body.get("new_version", f"{source_version}-curated")
        corpus = body.get("corpus", cfg.corpus.output_dir)
        steering = body.get("steering", {})
        if source_version == "latest":
            db = RetrieveDB(cfg.db_path)
            latest = db.get_latest_eval_set()
            db.close()
            if latest:
                source_version = latest["version_label"]
        from retrieve.eval.curate import regenerate_eval_set

        eval_set_id = await asyncio.to_thread(
            regenerate_eval_set,
            source_version=source_version,
            new_version=new_version,
            steering=steering,
            corpus_dir=corpus,
            cfg=cfg,
        )
        return {"status": "complete", "eval_set_id": eval_set_id}

    @app.post("/api/eval/export-csv")
    async def api_eval_export_csv(request: Request):
        body = await request.json()
        eval_set = body.get("eval_set", "latest")
        output = body.get("output", "eval_questions.csv")

        from retrieve.eval.io_csv import export_eval_set_to_csv

        db = RetrieveDB(cfg.db_path)
        try:
            if eval_set == "latest":
                es = db.get_latest_eval_set()
            else:
                es = db.get_eval_set_by_version(str(eval_set))
            if not es:
                raise HTTPException(404, "Eval set not found")

            count = export_eval_set_to_csv(db, es["id"], output)
            return {"status": "ok", "rows": count, "output": output}
        finally:
            db.close()

    @app.post("/api/eval/import-csv")
    async def api_eval_import_csv(request: Request):
        body = await request.json()
        input_path = body.get("input")
        version = body.get("version", "v-imported")
        base_eval_set = body.get("base_eval_set", "latest")
        fresh = bool(body.get("fresh", False))
        if not input_path:
            raise HTTPException(400, "input path is required")

        from retrieve.eval.io_csv import import_eval_set_from_csv

        db = RetrieveDB(cfg.db_path)
        try:
            base_id = None
            if not fresh:
                if base_eval_set == "latest":
                    base = db.get_latest_eval_set()
                else:
                    base = db.get_eval_set_by_version(str(base_eval_set))
                base_id = base["id"] if base else None

            new_id, imported = import_eval_set_from_csv(
                db,
                input_path=input_path,
                version_label=version,
                base_eval_set_id=base_id,
                fresh=fresh,
            )
            return {"status": "ok", "eval_set_id": new_id, "imported": imported}
        finally:
            db.close()

    # ── Preferences / UI session ───────────────────────────────────────

    @app.get("/api/eval/preferences")
    async def api_eval_preferences(scope_key: str = "default"):
        db = RetrieveDB(cfg.db_path)
        try:
            return db.get_generation_preferences(scope_key)
        finally:
            db.close()

    @app.post("/api/eval/preferences")
    async def api_eval_preferences_update(request: Request):
        body = await request.json()
        scope_key = body.get("scope_key", "default")
        prefs = body.get("preferences", {})
        if not isinstance(prefs, dict):
            raise HTTPException(400, "preferences must be an object")

        db = RetrieveDB(cfg.db_path)
        try:
            current = db.get_generation_preferences(scope_key)
            current.update(prefs)
            db.upsert_generation_preferences(current, scope_key)
            return {"status": "ok", "preferences": current}
        finally:
            db.close()

    @app.get("/api/ui/session")
    async def api_ui_session_get():
        db = RetrieveDB(cfg.db_path)
        try:
            return db.get_generation_preferences("ui_session")
        finally:
            db.close()

    @app.post("/api/ui/session")
    async def api_ui_session_update(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "body must be an object")
        db = RetrieveDB(cfg.db_path)
        try:
            current = db.get_generation_preferences("ui_session")
            current.update(body)
            db.upsert_generation_preferences(current, "ui_session")
            return {"status": "ok", "session": current}
        finally:
            db.close()

    # ── Job system (long-running operations with SSE streaming) ────────
    # Start a job → get an operation_id → stream events via SSE.
    # Jobs run the SAME core functions as the CLI, in a worker thread.

    @app.post("/api/ui/job/start")
    async def api_ui_job_start(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "body must be an object")
        kind = str(body.get("kind", "")).strip()
        args = body.get("args", {}) if isinstance(body.get("args", {}), dict) else {}
        if not kind:
            raise HTTPException(400, "kind is required")
        if kind not in ALLOWED_JOB_KINDS:
            raise HTTPException(400, f"unsupported job kind: {kind}")

        principal = request.state.principal
        if not isinstance(principal, AuthenticatedPrincipal):
            raise HTTPException(401, "Authentication required")
        idempotency_key = request.headers.get("idempotency-key", "").strip()
        if idempotency_key and not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise HTTPException(400, "Invalid Idempotency-Key")
        request_hash = hashlib.sha256(
            json.dumps(
                {"kind": kind, "args": args},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        async with app.state.admission_lock:
            if app.state.direct_mutation_active:
                raise HTTPException(409, "Another environment mutation is already running")

            operation_id = str(uuid.uuid4())
            admission_db = RetrieveDB(cfg.db_path)
            try:
                durable_job, replayed = admission_db.admit_operation_job(
                    job_id=operation_id,
                    kind=kind,
                    owner_id=principal.principal_id,
                    request_hash=request_hash,
                    idempotency_key=idempotency_key,
                    args=_redact_job_args(args),
                )
            except IdempotencyConflictError as exc:
                raise HTTPException(409, str(exc)) from exc
            except ActiveOperationJobError as exc:
                raise HTTPException(409, str(exc)) from exc
            finally:
                admission_db.close()

            if replayed:
                return {
                    "job_id": durable_job["id"],
                    "kind": durable_job["kind"],
                    "operation_id": durable_job["id"],
                    "idempotent_replay": True,
                }

            job: dict[str, Any] = {
                "id": operation_id,
                "kind": kind,
                "operation_id": operation_id,
                "owner_id": principal.principal_id,
                "request_hash": request_hash,
                "state": "queued",
                "done": False,
                "error": "",
                "result": {},
            }
            app.state.jobs[operation_id] = job
            try:
                _patch_ui_session(
                    cfg,
                    {
                        "active_job_id": operation_id,
                        "active_job_kind": kind,
                        "active_job_started_at": datetime.now(UTC).isoformat(),
                    },
                )
            except Exception:
                app.state.jobs.pop(operation_id, None)
                failure_db = RetrieveDB(cfg.db_path)
                try:
                    failure_db.update_operation_job(
                        operation_id,
                        state="failed",
                        error="Failed to persist active job session",
                    )
                finally:
                    failure_db.close()
                raise

        async def _run():
            running_db = RetrieveDB(cfg.db_path)
            try:
                running_db.update_operation_job(operation_id, state="running")
                job["state"] = "running"
                result = await asyncio.to_thread(
                    _run_job_sync,
                    kind,
                    args,
                    cfg,
                    operation_id,
                    principal.principal_id,
                    config_path,
                )
                job["result"] = result
                job["state"] = "succeeded"
                running_db.update_operation_job(
                    operation_id,
                    state="succeeded",
                    result=result,
                )
            except Exception as exc:
                job["error"] = str(exc)
                job["state"] = "failed"
                running_db.update_operation_job(
                    operation_id,
                    state="failed",
                    error=str(exc),
                )
                log.exception("Job %s (%s) failed", operation_id, kind)
                _patch_ui_session(cfg, {}, completed_job_id=operation_id)
            finally:
                job["done"] = True
                running_db.close()

        # Fire and forget — the SSE stream will deliver progress
        asyncio.create_task(_run())

        return {"job_id": operation_id, "kind": kind, "operation_id": operation_id}

    @app.get("/api/ui/job/{job_id}/status")
    async def api_ui_job_status(job_id: str):
        status_db = RetrieveDB(cfg.db_path)
        try:
            durable_job = status_db.get_operation_job(job_id)
        finally:
            status_db.close()
        job = durable_job or app.state.jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        return {
            "id": job["id"],
            "kind": job["kind"],
            "operation_id": job.get("operation_id", job["id"]),
            "state": job.get("state", ""),
            "done": bool(job["done"]),
            "error": job["error"],
            "result": job["result"],
        }

    @app.get("/api/ui/job/{job_id}/stream")
    async def api_ui_job_stream(job_id: str, request: Request):
        job = app.state.jobs.get(job_id)
        if not job:
            stream_db = RetrieveDB(cfg.db_path)
            try:
                job = stream_db.get_operation_job(job_id)
            finally:
                stream_db.close()
        if not job:
            raise HTTPException(404, "job not found")

        last_event_id = request.headers.get("last-event-id", "0").strip() or "0"
        if not last_event_id.isdigit():
            raise HTTPException(400, "Last-Event-ID must be a non-negative integer")

        def load_events(operation_id: str, after_sequence: int) -> list[dict[str, Any]]:
            event_db = RetrieveDB(cfg.db_path)
            try:
                return event_db.list_operation_events(
                    operation_id,
                    after_sequence=after_sequence,
                )
            finally:
                event_db.close()

        return StreamingResponse(
            sse_event_stream(
                job.get("operation_id", job["id"]),
                event_loader=load_events,
                after_sequence=int(last_event_id),
                done=bool(job["done"]),
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    return app


# ── Step context helpers ───────────────────────────────────────────────


def _compute_step_states(db: RetrieveDB, cfg: RetrieveConfig, ui: dict[str, Any]) -> dict[str, str]:
    latest_eval = db.get_latest_eval_set()
    runs = db.get_all_completed_runs()
    provisioned = []
    for name in cfg.architectures:
        arch = db.get_architecture(name)
        if arch and arch["status"] in ("provisioned", "active"):
            provisioned.append(arch)

    states = {
        "ingest": "done" if ui.get("ingest_done") else "pending",
        "eval": "done" if latest_eval else "pending",
        "mode": "done" if ui.get("selected_mode") else "pending",
        "configure": "done"
        if (
            ui.get("configure_done")
            or ui.get("selected_architectures")
            or ui.get("selected_sota_path")
        )
        else "pending",
        "provision": "done" if provisioned else "pending",
        "compare": "done" if runs else "pending",
        "history": "done" if runs else "pending",
        "settings": "done",
    }
    return states


def _build_step_context(step_name: str, db: RetrieveDB, cfg: RetrieveConfig) -> dict[str, Any]:
    ui = db.get_generation_preferences("ui_session")
    latest_eval = db.get_latest_eval_set()
    runs = db.get_all_completed_runs()

    if step_name == "ingest":
        output_dir = ui.get("output", cfg.corpus.output_dir)
        corpus_files = []
        output_path = Path(output_dir)
        if not output_path.is_absolute():
            output_path = (
                Path(cfg.corpus.source).parent / output_dir if cfg.corpus.source else output_path
            )
        if output_path.is_dir():
            for f in sorted(output_path.glob("*.md")):
                corpus_files.append({"name": f.name, "size": f.stat().st_size})
        return {
            "ingest_stats": ui.get("ingest_stats", {}),
            "source": ui.get("source", cfg.corpus.source),
            "plugin": ui.get("plugin", cfg.corpus.plugin),
            "output": ui.get("output", cfg.corpus.output_dir),
            "corpus_files": corpus_files,
        }

    if step_name == "eval":
        rows = db.conn.execute("SELECT * FROM eval_sets ORDER BY id DESC").fetchall()
        eval_sets = [dict(r) for r in rows]
        questions = db.get_questions(latest_eval["id"]) if latest_eval else []
        return {
            "eval_set": latest_eval,
            "eval_sets": eval_sets,
            "questions": questions[:200],
            "operator_context": ui.get(
                "operator_context",
                "",
            ),
        }

    if step_name == "mode":
        from retrieve.registry.sota_paths import SOTA_PATHS

        recommendation = _sota_recommendation(ui)
        return {
            "architectures": cfg.architectures,
            "selected_mode": ui.get("selected_mode"),
            "sota_paths": {k: v.model_dump() for k, v in SOTA_PATHS.items()},
            **recommendation,
        }

    if step_name == "configure":
        from retrieve.registry.architectures import ARCHITECTURES
        from retrieve.registry.models import EMBEDDING_MODELS
        from retrieve.registry.sota_paths import SOTA_PATHS

        return {
            "architectures": cfg.architectures,
            "selected_mode": ui.get("selected_mode") or "test",
            "selected_architectures": ui.get("selected_architectures") or list(cfg.architectures),
            "selected_embedding": ui.get("selected_embedding") or "text-embedding-3-large",
            "selected_sota_path": ui.get("selected_sota_path"),
            "sota_toggles": ui.get("sota_toggles") or {},
            "all_architectures": {k: v.model_dump() for k, v in ARCHITECTURES.items()},
            "embedding_models": {k: v.model_dump() for k, v in EMBEDDING_MODELS.items()},
            "sota_paths": {k: v.model_dump() for k, v in SOTA_PATHS.items()},
        }

    if step_name == "provision":
        return {
            "architectures": _architecture_rows(db, cfg),
            "resource_group": cfg.azure.resource_group,
            "location": cfg.azure.location,
        }

    if step_name == "compare":
        return _compare_context(db, cfg, ui)

    if step_name == "history":
        return {"runs": runs}

    if step_name == "settings":
        return {"cfg": cfg}

    return {}
