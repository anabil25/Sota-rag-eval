"""SOTA Eval Runner — iterates over toggle combinations and measures per-component delta.

Given a SOTA path (from sota_paths.py), this runner:
1. Generates all meaningful toggle combinations
2. For each combination, provisions the index variant (if needed)
3. Runs the full eval set against each variant
4. Computes per-component delta (how much each toggle changes Recall@10, MRR@10, latency)
5. Produces a summary table + recommended configuration

The SOTA runner reuses the existing eval infrastructure (runner.py, search_index.py)
but adds toggle-aware index provisioning and comparative analysis.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console
from rich.table import Table

from retrieve.config import RetrieveConfig
from retrieve.eval.runner import query_ai_search, estimate_cost
from retrieve.observability import emit_progress
from retrieve.registry.sota_paths import (
    SOTAPath,
    generate_toggle_combinations,
    recommend_sota_path,
    SOTA_PATHS,
)

log = logging.getLogger(__name__)
console = Console()


@dataclass
class VariantResult:
    """Result of running eval against a single toggle variant."""

    toggles: dict[str, str]
    variant_label: str
    recall_at_10: float = 0.0
    mrr_at_10: float = 0.0
    avg_latency_ms: float = 0.0
    query_count: int = 0
    cost_estimate: dict[str, Any] = field(default_factory=dict)


@dataclass
class SOTARunResult:
    """Complete result of a SOTA eval run across all variants."""

    path_name: str
    base_architecture: str
    variants: list[VariantResult] = field(default_factory=list)
    component_deltas: dict[str, dict[str, float]] = field(default_factory=dict)
    recommended_config: dict[str, str] = field(default_factory=dict)


def run_sota_eval(
    cfg: RetrieveConfig,
    path_name: str | None = None,
    questions: list[dict] | None = None,
    top_k: int = 10,
    max_variants: int = 50,
) -> SOTARunResult:
    """Run SOTA eval mode for a given path (or auto-detected from corpus stats).

    Args:
        cfg: Retrieve configuration.
        path_name: SOTA path name (e.g. 'government-policy'). Auto-detected if None.
        questions: List of eval question dicts with 'question' and 'expected_chunk_ids'.
        top_k: Number of results per query.
        max_variants: Maximum number of toggle combinations to evaluate.

    Returns:
        SOTARunResult with all variant results and component deltas.
    """
    if not questions:
        # Load from eval database
        from retrieve.eval.store import EvalStore
        store = EvalStore(cfg.project_root)
        questions = store.get_approved_questions()
        if not questions:
            console.print("[red]No approved eval questions found. Run 'retrieve eval generate' first.[/red]")
            return SOTARunResult(path_name=path_name or "unknown", base_architecture="unknown")

    # Determine SOTA path
    if path_name:
        path = SOTA_PATHS.get(path_name)
        if not path:
            console.print(f"[red]Unknown SOTA path: {path_name}. Available: {', '.join(SOTA_PATHS.keys())}[/red]")
            return SOTARunResult(path_name=path_name, base_architecture="unknown")
    else:
        # Auto-detect from corpus stats
        from retrieve.eval.store import EvalStore
        store = EvalStore(cfg.project_root)
        stats = store.get_corpus_stats()
        path = recommend_sota_path(
            doc_count=stats.get("doc_count", 100),
            avg_doc_length=stats.get("avg_doc_length", 3000),
            cross_ref_density=stats.get("cross_ref_density", 1.0),
        )
        if not path:
            path = SOTA_PATHS["government-policy"]
            console.print(f"  [yellow]No matching SOTA path — defaulting to '{path.name}'[/yellow]")

    console.print(f"\n[bold]SOTA Eval: {path.name}[/bold]")
    console.print(f"  Base architecture: [cyan]{path.base_architecture}[/cyan]")
    console.print(f"  Components: {', '.join(c.name for c in path.components)}")
    console.print(f"  Eval questions: {len(questions)}")

    # Generate toggle combinations
    combinations = generate_toggle_combinations(path)
    if len(combinations) > max_variants:
        console.print(f"  [yellow]Capping at {max_variants} variants (of {len(combinations)})[/yellow]")
        combinations = combinations[:max_variants]

    console.print(f"  Variants to evaluate: {len(combinations)}\n")

    # Get search endpoint and index prefix from config
    arch_configs = cfg.get_architecture_configs()
    base_config = arch_configs.get(path.base_architecture, {})
    endpoint = base_config.get("search_endpoint", "")
    index_prefix = cfg.azure.name_prefix if hasattr(cfg, 'azure') else ""

    if not endpoint:
        console.print("[red]No search endpoint configured. Run 'retrieve provision' first.[/red]")
        return SOTARunResult(path_name=path.name, base_architecture=path.base_architecture)

    # Run eval for each variant
    result = SOTARunResult(
        path_name=path.name,
        base_architecture=path.base_architecture,
    )

    for i, toggles in enumerate(combinations):
        label = _variant_label(toggles, path)
        console.print(f"  [{i + 1}/{len(combinations)}] {label}")

        # Determine index name for this variant
        # For index-time toggles (chunk_size, embedding_model, chunking_strategy),
        # each unique combination needs a separate index.
        # For query-time toggles (semantic_reranker, query_expansion, rrf_weights),
        # the same index is reused.
        index_suffix = _index_suffix(toggles)
        index_name = f"{index_prefix}-{path.base_architecture}{index_suffix}"

        variant = _eval_variant(
            endpoint=endpoint,
            index_name=index_name,
            arch_name=path.base_architecture,
            questions=questions,
            toggles=toggles,
            top_k=top_k,
            label=label,
        )
        result.variants.append(variant)

        emit_progress(
            f"SOTA variant {i + 1}/{len(combinations)}: {label}",
            stage="eval.sota_variant",
            recall=variant.recall_at_10,
            mrr=variant.mrr_at_10,
            latency_ms=variant.avg_latency_ms,
        )

    # Compute per-component deltas
    result.component_deltas = _compute_deltas(result.variants, path)

    # Determine recommended configuration
    best = max(result.variants, key=lambda v: v.recall_at_10)
    result.recommended_config = best.toggles.copy()

    # Print summary
    _print_summary(result, path)

    return result


def _variant_label(toggles: dict[str, str], path: SOTAPath) -> str:
    """Human-readable label for a toggle combination."""
    defaults = {c.name: c.default for c in path.components}
    diffs = []
    for k, v in toggles.items():
        if v != defaults.get(k):
            diffs.append(f"{k}={v}")
    return " + ".join(diffs) if diffs else "(defaults)"


def _index_suffix(toggles: dict[str, str]) -> str:
    """Generate index name suffix from index-time toggle values."""
    # Only index-time toggles affect the index structure
    index_time_keys = ["chunk_size", "embedding_model", "chunking_strategy"]
    parts = []
    for key in sorted(index_time_keys):
        if key in toggles:
            val = toggles[key].replace("-", "").replace("_", "")[:8]
            parts.append(f"-{val}")
    return "".join(parts) if parts else ""


def _eval_variant(
    endpoint: str,
    index_name: str,
    arch_name: str,
    questions: list[dict],
    toggles: dict[str, str],
    top_k: int,
    label: str,
) -> VariantResult:
    """Evaluate a single variant — run all questions and compute metrics."""
    hits = 0
    rr_sum = 0.0
    latency_sum = 0.0
    count = 0

    for q in questions:
        question_text = q.get("question", "")
        expected = q.get("expected_chunk_ids", [])
        if isinstance(expected, str):
            expected = [expected]

        try:
            chunk_ids, latency_ms = query_ai_search(
                endpoint=endpoint,
                index_name=index_name,
                query=question_text,
                arch_name=arch_name,
                top_k=top_k,
                toggles=toggles,
            )
        except ConnectionError:
            # Index doesn't exist — skip this variant
            console.print(f"    [yellow]Index '{index_name}' not found, skipping[/yellow]")
            return VariantResult(
                toggles=toggles,
                variant_label=label,
                query_count=0,
            )

        latency_sum += latency_ms
        count += 1

        # Recall@k — any expected chunk in top-k results?
        if expected and any(eid in chunk_ids for eid in expected):
            hits += 1

        # MRR — reciprocal rank of first expected hit
        for rank, cid in enumerate(chunk_ids, 1):
            if cid in expected:
                rr_sum += 1.0 / rank
                break

    recall = hits / count if count else 0.0
    mrr = rr_sum / count if count else 0.0
    avg_latency = latency_sum / count if count else 0.0

    cost_est = estimate_cost(arch_name, count)

    return VariantResult(
        toggles=toggles,
        variant_label=label,
        recall_at_10=round(recall, 4),
        mrr_at_10=round(mrr, 4),
        avg_latency_ms=round(avg_latency, 2),
        query_count=count,
        cost_estimate=cost_est,
    )


def _compute_deltas(
    variants: list[VariantResult],
    path: SOTAPath,
) -> dict[str, dict[str, float]]:
    """Compute per-component marginal delta on recall.

    For each component, compares variants that differ only in that component's
    value vs the default, averaging over all other combinations.
    """
    defaults = {c.name: c.default for c in path.components}
    deltas: dict[str, dict[str, float]] = {}

    # Find the default variant
    default_variant = None
    for v in variants:
        if v.toggles == defaults:
            default_variant = v
            break

    if not default_variant or default_variant.query_count == 0:
        return deltas

    base_recall = default_variant.recall_at_10

    for component in path.components:
        for option in component.options:
            if option == component.default:
                continue
            # Find variant that differs only in this component
            for v in variants:
                if v.query_count == 0:
                    continue
                diff_keys = [k for k in v.toggles if v.toggles[k] != defaults.get(k)]
                if diff_keys == [component.name] and v.toggles[component.name] == option:
                    delta_key = f"{component.name}={option}"
                    deltas[delta_key] = {
                        "recall_delta": round(v.recall_at_10 - base_recall, 4),
                        "mrr_delta": round(v.mrr_at_10 - default_variant.mrr_at_10, 4),
                        "latency_delta_ms": round(v.avg_latency_ms - default_variant.avg_latency_ms, 2),
                        "recall": v.recall_at_10,
                    }
                    break

    return deltas


def _print_summary(result: SOTARunResult, path: SOTAPath):
    """Print a rich summary table of SOTA eval results."""
    console.print(f"\n[bold]SOTA Eval Results: {result.path_name}[/bold]\n")

    # Variants table
    table = Table(title="Variant Results")
    table.add_column("Variant", style="cyan")
    table.add_column("Recall@10", justify="right")
    table.add_column("MRR@10", justify="right")
    table.add_column("Avg Latency (ms)", justify="right")
    table.add_column("Queries", justify="right")

    for v in sorted(result.variants, key=lambda x: -x.recall_at_10):
        if v.query_count == 0:
            continue
        table.add_row(
            v.variant_label,
            f"{v.recall_at_10:.4f}",
            f"{v.mrr_at_10:.4f}",
            f"{v.avg_latency_ms:.1f}",
            str(v.query_count),
        )

    console.print(table)

    # Component deltas table
    if result.component_deltas:
        delta_table = Table(title="Per-Component Marginal Delta (vs defaults)")
        delta_table.add_column("Component Change", style="cyan")
        delta_table.add_column("Recall Δ", justify="right")
        delta_table.add_column("MRR Δ", justify="right")
        delta_table.add_column("Latency Δ (ms)", justify="right")

        for change, d in sorted(
            result.component_deltas.items(),
            key=lambda x: -abs(x[1]["recall_delta"]),
        ):
            recall_color = "green" if d["recall_delta"] > 0 else "red" if d["recall_delta"] < 0 else "white"
            delta_table.add_row(
                change,
                f"[{recall_color}]{d['recall_delta']:+.4f}[/{recall_color}]",
                f"{d['mrr_delta']:+.4f}",
                f"{d['latency_delta_ms']:+.1f}",
            )

        console.print(delta_table)

    # Recommended config
    console.print(f"\n[bold green]Recommended configuration:[/bold green]")
    for k, v in result.recommended_config.items():
        console.print(f"  {k}: [cyan]{v}[/cyan]")
