"""Retrieve CLI — typer-based command-line interface."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from retrieve.config import load_config
from retrieve.observability import capture_module_consoles, configure_observability, operation, step

app = typer.Typer(
    name="retrieve",
    help="Eval-driven retrieval architecture selection.",
    no_args_is_help=True,
)
eval_app = typer.Typer(name="eval", help="Evaluation commands.", no_args_is_help=True)
app.add_typer(eval_app)
domain_app = typer.Typer(name="domain", help="Domain adaptation commands.", no_args_is_help=True)
app.add_typer(domain_app)

console = Console()

ConfigOpt = Annotated[Path, typer.Option("--config", "-c", help="Path to retrieve.yaml")]


@app.callback()
def main_callback(
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
    azure_sdk_logging: Annotated[
        bool, typer.Option("--azure-sdk-logging", help="Enable verbose Azure SDK HTTP logging")
    ] = False,
):
    configure_observability(verbose=verbose, azure_sdk_logging=azure_sdk_logging)


# ── ingest ────────────────────────────────────────────────────────────


@app.command()
def ingest(
    source: Annotated[
        str, typer.Option("--source", "-s", help="URL or local path to corpus source")
    ],
    plugin: Annotated[
        str, typer.Option("--plugin", "-p", help="Ingestion plugin: html, pdf, markdown")
    ] = "html",
    output: Annotated[
        str, typer.Option("--output", "-o", help="Output directory for Markdown files")
    ] = "corpus",
    config: ConfigOpt = Path("retrieve.yaml"),
    delay: Annotated[float, typer.Option("--delay", help="Seconds between HTTP requests")] = 0.5,
):
    """Ingest a document corpus into structured Markdown."""
    from retrieve.ingest import run_ingest

    with operation(
        "cli.ingest",
        source="cli",
        metadata={"source": source, "plugin": plugin, "output": output},
    ):
        with step("load_config"):
            cfg = load_config(config)
        with step("run_ingest"):
            with capture_module_consoles([run_ingest]):
                run_ingest(
                    source=source, plugin_name=plugin, output_dir=output, delay=delay, cfg=cfg
                )


# ── eval generate ────────────────────────────────────────────────────


@eval_app.command("generate")
def eval_generate(
    corpus: Annotated[str, typer.Option("--corpus", help="Path to corpus directory")],
    output: Annotated[str, typer.Option("--output", help="Eval set version label")] = "v1",
    config: ConfigOpt = Path("retrieve.yaml"),
    mode: Annotated[
        str,
        typer.Option(
            "--mode", "-m", help="Eval mode: 'sample' (~30 questions) or 'full' (~0.5 per doc)"
        ),
    ] = "sample",
    fresh: Annotated[
        bool, typer.Option("--fresh", help="Start fresh instead of building on latest eval set")
    ] = False,
    base_eval_set: Annotated[
        str, typer.Option("--base-eval-set", help="Base eval set version (default: latest)")
    ] = "latest",
    operator_context: Annotated[
        str, typer.Option("--operator-context", help="Domain context for question generation")
    ] = "",
):
    """Generate a golden evaluation set from the corpus."""
    from retrieve.eval import generate as eval_generate_mod
    from retrieve.eval.generate import DEFAULT_OPERATOR_CONTEXT, generate_eval_set

    with operation(
        "cli.eval.generate",
        source="cli",
        metadata={
            "corpus": corpus,
            "output": output,
            "mode": mode,
        },
    ):
        with step("load_config"):
            cfg = load_config(config)
        with step("generate_eval_set"):
            with capture_module_consoles([eval_generate_mod]):
                generate_eval_set(
                    corpus_dir=corpus,
                    version_label=output,
                    cfg=cfg,
                    fresh=fresh,
                    base_eval_set_version=base_eval_set,
                    operator_context=operator_context or DEFAULT_OPERATOR_CONTEXT,
                    mode=mode,
                )


# ── eval curate ──────────────────────────────────────────────────────


@eval_app.command("curate")
def eval_curate(
    eval_set: Annotated[
        str, typer.Option("--eval-set", help="Eval set version to curate")
    ] = "latest",
    config: ConfigOpt = Path("retrieve.yaml"),
    more: Annotated[
        str | None, typer.Option("--more", help="Categories to add more of (comma-separated)")
    ] = None,
    fewer: Annotated[
        str | None, typer.Option("--fewer", help="Categories to reduce (comma-separated)")
    ] = None,
    add_category: Annotated[
        str | None, typer.Option("--add-category", help="New categories to add (comma-separated)")
    ] = None,
    remove_category: Annotated[
        str | None, typer.Option("--remove-category", help="Categories to remove (comma-separated)")
    ] = None,
    question_types: Annotated[
        str | None,
        typer.Option("--question-types", help="Question types to bias toward (comma-separated)"),
    ] = None,
    output: Annotated[str | None, typer.Option("--output", "-o", help="New version label")] = None,
    corpus: Annotated[
        str | None, typer.Option("--corpus", help="Corpus directory for regeneration")
    ] = None,
    notes: Annotated[str | None, typer.Option("--notes", help="SME notes for steering")] = None,
):
    """Review and steer eval set categories, regenerate with new balance."""
    from retrieve.eval import curate as eval_curate_mod
    from retrieve.eval.curate import regenerate_eval_set, show_eval_set_summary

    with operation("cli.eval.curate", source="cli", metadata={"eval_set": eval_set}):
        with step("load_config"):
            cfg = load_config(config)

        # If no steering flags -> just show the summary
        has_steering = any([more, fewer, add_category, remove_category])
        if not has_steering:
            with step("show_eval_set_summary"):
                with capture_module_consoles([eval_curate_mod]):
                    show_eval_set_summary(eval_set, cfg)
                    console.print(
                        "\n[dim]To steer: --more cross_document "
                        "--fewer direct_lookup --output v2[/dim]"
                    )
            return

        # Build steering dict
        steering = {
            "more": more.split(",") if more else [],
            "fewer": fewer.split(",") if fewer else [],
            "add_categories": add_category.split(",") if add_category else [],
            "remove_categories": remove_category.split(",") if remove_category else [],
            "question_types": question_types.split(",") if question_types else [],
            "notes": notes or "",
        }

        new_version = output or f"{eval_set}-curated"
        corpus_dir = corpus or cfg.corpus.output_dir

        with step("regenerate_eval_set"):
            with capture_module_consoles([eval_curate_mod]):
                regenerate_eval_set(
                    source_version=eval_set,
                    new_version=new_version,
                    steering=steering,
                    corpus_dir=corpus_dir,
                    cfg=cfg,
                )


@eval_app.command("export-csv")
def eval_export_csv(
    eval_set: Annotated[
        str, typer.Option("--eval-set", help="Eval set version to export")
    ] = "latest",
    output: Annotated[
        str, typer.Option("--output", "-o", help="Output CSV path")
    ] = "eval_questions.csv",
    config: ConfigOpt = Path("retrieve.yaml"),
):
    """Export eval questions (with Q/A pairs and metadata) to CSV."""
    from retrieve.db import RetrieveDB
    from retrieve.eval.io_csv import export_eval_set_to_csv

    with operation(
        "cli.eval.export_csv", source="cli", metadata={"eval_set": eval_set, "output": output}
    ):
        with step("load_config"):
            cfg = load_config(config)
        db = RetrieveDB(cfg.db_path)
        try:
            with step("resolve_eval_set"):
                if eval_set == "latest":
                    es = db.get_latest_eval_set()
                else:
                    es = db.get_eval_set_by_version(eval_set)
                if not es:
                    raise typer.BadParameter(f"Eval set not found: {eval_set}")

            with step("export_eval_set_csv"):
                count = export_eval_set_to_csv(db, es["id"], output)
            console.print(f"[green]Exported[/green] {count} questions to [cyan]{output}[/cyan]")
        finally:
            db.close()


@eval_app.command("import-csv")
def eval_import_csv(
    input_csv: Annotated[
        str, typer.Option("--input", "-i", help="Input CSV path")
    ] = "eval_questions.csv",
    output_version: Annotated[
        str, typer.Option("--output", "-o", help="New eval set version label")
    ] = "v-imported",
    base_eval_set: Annotated[
        str, typer.Option("--base-eval-set", help="Base eval set to extend (default: latest)")
    ] = "latest",
    fresh: Annotated[
        bool, typer.Option("--fresh", help="Import into a fresh eval set (do not extend base)")
    ] = False,
    config: ConfigOpt = Path("retrieve.yaml"),
):
    """Import eval questions from CSV into a new eval set version."""
    from retrieve.db import RetrieveDB
    from retrieve.eval.io_csv import import_eval_set_from_csv

    with operation(
        "cli.eval.import_csv",
        source="cli",
        metadata={"input": input_csv, "output_version": output_version, "fresh": fresh},
    ):
        with step("load_config"):
            cfg = load_config(config)
        db = RetrieveDB(cfg.db_path)
        try:
            with step("resolve_base_eval_set"):
                base_id = None
                if not fresh:
                    if base_eval_set == "latest":
                        base = db.get_latest_eval_set()
                    else:
                        base = db.get_eval_set_by_version(base_eval_set)
                    base_id = base["id"] if base else None

            with step("import_eval_set_csv"):
                new_id, imported = import_eval_set_from_csv(
                    db,
                    input_path=input_csv,
                    version_label=output_version,
                    base_eval_set_id=base_id,
                    fresh=fresh,
                )
            console.print(
                f"[green]Imported[/green] {imported} questions into eval set "
                f"[cyan]{output_version}[/cyan] (id={new_id})"
            )
        finally:
            db.close()


# ── eval run ─────────────────────────────────────────────────────────


@eval_app.command("run")
def eval_run(
    eval_set: Annotated[str, typer.Option("--eval-set", help="Eval set version to run")] = "latest",
    architectures: Annotated[
        str, typer.Option("--architectures", "-a", help="Comma-separated list or 'all'")
    ] = "all",
    config: ConfigOpt = Path("retrieve.yaml"),
    parallel: Annotated[
        bool, typer.Option("--parallel", help="Run different architectures in parallel")
    ] = False,
):
    """Run the golden eval set against provisioned architectures."""
    from retrieve.eval import runner as eval_runner_mod
    from retrieve.eval.runner import run_evaluation

    with operation(
        "cli.eval.run",
        source="cli",
        metadata={"eval_set": eval_set, "architectures": architectures},
    ):
        with step("load_config"):
            cfg = load_config(config)
        with step("run_evaluation"):
            arch_list = None if architectures == "all" else architectures.split(",")
            with capture_module_consoles([eval_runner_mod]):
                run_evaluation(
                    eval_set_version=eval_set,
                    architectures=arch_list,
                    cfg=cfg,
                    parallel=parallel,
                )


# ── eval compare ─────────────────────────────────────────────────────


@eval_app.command("compare")
def eval_compare(
    runs: Annotated[
        str | None, typer.Option("--runs", help="Comma-separated run IDs to compare")
    ] = None,
    export: Annotated[
        str | None, typer.Option("--export", help="Export path (csv or json)")
    ] = None,
    web: Annotated[
        bool, typer.Option("--web", help="Open comparison dashboard in browser")
    ] = False,
    config: ConfigOpt = Path("retrieve.yaml"),
):
    """Compare evaluation runs side by side."""
    from retrieve.eval import compare as eval_compare_mod
    from retrieve.eval.compare import compare_runs

    with operation(
        "cli.eval.compare",
        source="cli",
        metadata={"runs": runs, "export": export, "web": web},
    ):
        with step("load_config"):
            cfg = load_config(config)
        with step("compare_runs"):
            run_ids = [int(x) for x in runs.split(",")] if runs else None
            with capture_module_consoles([eval_compare_mod]):
                compare_runs(run_ids=run_ids, export_path=export, open_web=web, cfg=cfg)


# ── provision ────────────────────────────────────────────────────────


@app.command()
def provision(
    config: ConfigOpt = Path("retrieve.yaml"),
):
    """Provision Azure resources for selected architectures."""
    from retrieve.provision import azd as provision_mod
    from retrieve.provision import provision_architectures

    with operation("cli.provision", source="cli"):
        with step("load_config"):
            cfg = load_config(config)
        with step("provision_architectures"):
            with capture_module_consoles([provision_mod]):
                provision_architectures(cfg, config_path=config)


# ── index ────────────────────────────────────────────────────────────


@app.command()
def index(
    config: ConfigOpt = Path("retrieve.yaml"),
):
    """Upload corpus and build search indexes."""
    from retrieve.indexing import blob_upload as blob_upload_mod
    from retrieve.indexing import index_corpus
    from retrieve.indexing import run as indexing_run_mod
    from retrieve.indexing import search_index as search_index_mod

    with operation("cli.index", source="cli"):
        with step("load_config"):
            cfg = load_config(config)
        with step("index_corpus"):
            with capture_module_consoles([indexing_run_mod, blob_upload_mod, search_index_mod]):
                index_corpus(cfg)


# ── teardown ─────────────────────────────────────────────────────────


@app.command()
def teardown(
    keep: Annotated[
        str | None, typer.Option("--keep", help="Architectures to keep (comma-separated)")
    ] = None,
    config: ConfigOpt = Path("retrieve.yaml"),
):
    """Tear down unselected Azure resources."""
    from retrieve.provision import teardown as teardown_mod
    from retrieve.provision.teardown import teardown as do_teardown

    with operation("cli.teardown", source="cli", metadata={"keep": keep or ""}):
        with step("load_config"):
            cfg = load_config(config)
        with step("teardown"):
            keep_list = keep.split(",") if keep else None
            with capture_module_consoles([teardown_mod]):
                do_teardown(keep=keep_list, cfg=cfg)


# ── validate ─────────────────────────────────────────────────────────


@app.command()
def validate(
    config: ConfigOpt = Path("retrieve.yaml"),
):
    """Validate Bicep templates and configuration before deployment."""
    import shutil
    import subprocess

    with operation("cli.validate", source="cli"):
        with step("load_config"):
            cfg = load_config(config)

        bicep_dir = Path(__file__).resolve().parents[3] / "infra"
        main_bicep = bicep_dir / "main.bicep"

        # Check az CLI is available
        az_path = shutil.which("az")
        if not az_path:
            console.print(
                "[red]Azure CLI not found. Install it: https://aka.ms/installazurecli[/red]"
            )
            raise typer.Exit(1)

        # Validate Bicep templates
        with step("validate_bicep"):
            console.print("\n[bold]Validating root infrastructure Bicep...[/bold]\n")
            result = subprocess.run(
                [az_path, "bicep", "build", "--file", str(main_bicep), "--stdout"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                console.print("  [red]✗[/red] infra/main.bicep")
                for line in result.stderr.strip().split("\n"):
                    if line.strip():
                        console.print(f"    {line}")
                raise typer.Exit(1)
            console.print("  [green]✓[/green] infra/main.bicep and referenced modules")

        # Validate configuration
        with step("validate_config"):
            console.print("\n[bold]Validating configuration...[/bold]\n")
            issues = []

            if not cfg.azure.name_prefix:
                issues.append("azure.name_prefix is not set")
            if not cfg.azure.resource_group:
                issues.append("azure.resource_group is not set")
            if not cfg.azure.location:
                issues.append("azure.location is not set")
            if not cfg.architectures:
                issues.append("No architectures configured")

            for issue in issues:
                console.print(f"  [yellow]⚠[/yellow] {issue}")

            if not issues:
                console.print("  [green]✓[/green] Configuration valid")
            else:
                console.print(f"\n[yellow]{len(issues)} configuration warning(s).[/yellow]")

        console.print()


# ── info ─────────────────────────────────────────────────────────────


@app.command()
def info(config: ConfigOpt = Path("retrieve.yaml")):
    """Show architecture registry and configuration."""
    from rich.table import Table

    from retrieve.registry.architectures import ARCHITECTURES
    from retrieve.registry.models import EMBEDDING_MODELS, RERANKER_MODELS

    with operation("cli.info", source="cli"):
        console.print("\n[bold]Architecture Registry[/bold]\n")
        t = Table()
        t.add_column("Name")
        t.add_column("Accuracy")
        t.add_column("Cost")
        t.add_column("Latency")
        t.add_column("Best For")
        for a in ARCHITECTURES.values():
            t.add_row(a.name, a.accuracy, a.cost, a.latency, a.best_for)
        console.print(t)

        console.print("\n[bold]Embedding Models[/bold]\n")
        t2 = Table()
        t2.add_column("Name")
        t2.add_column("Dimensions")
        t2.add_column("MTEB")
        t2.add_column("Cost/1M tok")
        t2.add_column("Notes")
        for m in EMBEDDING_MODELS.values():
            t2.add_row(m.name, str(m.dimensions), str(m.mteb_avg), m.cost_per_1m, m.notes)
        console.print(t2)

        console.print("\n[bold]Reranker Models[/bold]\n")
        t3 = Table()
        t3.add_column("Name")
        t3.add_column("Notes")
        for r in RERANKER_MODELS.values():
            t3.add_row(r.name, r.notes)
        console.print(t3)


# ── ui ────────────────────────────────────────────────────────────────


@app.command()
def ui(
    config: ConfigOpt = Path("retrieve.yaml"),
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8000,
):
    """Launch the web UI (primary interface)."""
    import uvicorn

    from retrieve.web.app import create_app

    with operation("cli.ui", source="cli", metadata={"host": host, "port": port}):
        console.print("\n[bold]Starting Retrieve UI[/bold]")
        console.print(f"  → [cyan]http://{host}:{port}[/cyan]\n")

        web_app = create_app(str(config))
        uvicorn.run(web_app, host=host, port=port, log_level="info")


# ── eval sota ────────────────────────────────────────────────────────


@eval_app.command("sota")
def eval_sota(
    path_name: Annotated[
        str | None, typer.Option("--path", "-p", help="SOTA path name (auto-detected if omitted)")
    ] = None,
    max_variants: Annotated[
        int, typer.Option("--max-variants", help="Max toggle combinations")
    ] = 50,
    config: ConfigOpt = Path("retrieve.yaml"),
):
    """Run SOTA eval mode — test all toggle combinations for a pipeline path."""
    from retrieve.eval.sota_runner import run_sota_eval

    with operation("cli.eval.sota", source="cli", metadata={"path": path_name}):
        with step("load_config"):
            cfg = load_config(config)
        with step("run_sota_eval"):
            run_sota_eval(cfg, path_name=path_name, max_variants=max_variants)


# ── domain analyze ───────────────────────────────────────────────────


@domain_app.command("analyze")
def domain_analyze(
    corpus: Annotated[str, typer.Option("--corpus", help="Path to corpus directory")] = "corpus",
    config: ConfigOpt = Path("retrieve.yaml"),
):
    """Analyze corpus for domain-specific terminology and recommend fine-tuning."""
    from retrieve.eval.domain_adapt import analyze_domain_specificity

    with operation("cli.domain.analyze", source="cli"):
        analyze_domain_specificity(corpus)


@domain_app.command("generate-training")
def domain_generate_training(
    corpus: Annotated[str, typer.Option("--corpus", help="Path to corpus directory")] = "corpus",
    output: Annotated[
        str, typer.Option("--output", "-o", help="Output JSONL file")
    ] = "training_pairs.jsonl",
    max_pairs: Annotated[int, typer.Option("--max-pairs", help="Maximum training pairs")] = 500,
    config: ConfigOpt = Path("retrieve.yaml"),
):
    """Generate synthetic training pairs from the corpus for fine-tuning."""
    from retrieve.eval.domain_adapt import generate_training_pairs

    with operation("cli.domain.generate_training", source="cli"):
        with step("load_config"):
            cfg = load_config(config)
        generate_training_pairs(
            corpus_dir=corpus,
            output_file=output,
            ai_services_endpoint=cfg.azure.ai_services_endpoint
            if hasattr(cfg.azure, "ai_services_endpoint")
            else "",
            max_pairs=max_pairs,
        )


@domain_app.command("finetune")
def domain_finetune(
    training_file: Annotated[
        str, typer.Option("--training-file", help="Training data JSONL file")
    ] = "training_pairs.jsonl",
    base_model: Annotated[
        str, typer.Option("--base-model", help="Base model for fine-tuning")
    ] = "gpt-4o-mini-2024-07-18",
    config: ConfigOpt = Path("retrieve.yaml"),
):
    """Submit a fine-tuning job to Azure OpenAI."""
    from retrieve.eval.domain_adapt import submit_finetune_job

    with operation("cli.domain.finetune", source="cli"):
        with step("load_config"):
            cfg = load_config(config)
        submit_finetune_job(
            training_file=training_file,
            ai_services_endpoint=cfg.azure.ai_services_endpoint
            if hasattr(cfg.azure, "ai_services_endpoint")
            else "",
            base_model=base_model,
        )


@domain_app.command("status")
def domain_status(
    job_id: Annotated[str, typer.Argument(help="Fine-tuning job ID")],
    config: ConfigOpt = Path("retrieve.yaml"),
):
    """Check the status of a fine-tuning job."""
    from retrieve.eval.domain_adapt import check_finetune_status

    with operation("cli.domain.status", source="cli"):
        with step("load_config"):
            cfg = load_config(config)
        check_finetune_status(
            job_id=job_id,
            ai_services_endpoint=cfg.azure.ai_services_endpoint
            if hasattr(cfg.azure, "ai_services_endpoint")
            else "",
        )


@domain_app.command("compare")
def domain_compare(
    base_run: Annotated[str, typer.Option("--base", help="Base eval run ID")],
    tuned_run: Annotated[str, typer.Option("--tuned", help="Fine-tuned eval run ID")],
    config: ConfigOpt = Path("retrieve.yaml"),
):
    """Compare eval results before and after domain adaptation."""
    from retrieve.eval.domain_adapt import compare_before_after

    with operation("cli.domain.compare", source="cli"):
        with step("load_config"):
            cfg = load_config(config)
        compare_before_after(cfg, base_run, tuned_run)


if __name__ == "__main__":
    app()
