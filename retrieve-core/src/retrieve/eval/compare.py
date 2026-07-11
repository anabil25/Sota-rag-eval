"""Comparison dashboard — CLI tables + HTML export + web server.

Two views per the vision doc:
- Test Mode: architecture comparison table
- SOTA Eval Mode: component delta table with Δ column
Plus per-category breakdown and miss analysis.
"""

from __future__ import annotations

import csv
import json
import logging
import webbrowser
from io import StringIO
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from retrieve.config import RetrieveConfig
from retrieve.db import RetrieveDB
from retrieve.observability import emit_progress, step

log = logging.getLogger(__name__)
console = Console()


# ── CLI comparison ────────────────────────────────────────────────────


def _print_test_mode_table(runs: list[dict[str, Any]]):
    """Test Mode — architecture comparison table."""
    console.print("\n[bold]Architecture Comparison (Test Mode)[/bold]\n")

    t = Table(title="Retrieval Metrics")
    t.add_column("Architecture", style="bold")
    t.add_column("Recall@5", justify="right")
    t.add_column("Recall@10", justify="right")
    t.add_column("MRR@10", justify="right")
    t.add_column("nDCG@10", justify="right")
    t.add_column("Avg Latency", justify="right")
    t.add_column("Est. Monthly Cost", justify="right")

    for run in runs:
        m = run["aggregate_metrics"]
        cost = m.get("est_monthly_cost")
        cost_str = f"${cost:.0f}" if cost else "—"
        t.add_row(
            run["architecture_name"],
            f"{m.get('recall_at_5', 0):.3f}",
            f"{m.get('recall_at_10', 0):.3f}",
            f"{m.get('mrr_at_10', 0):.3f}",
            f"{m.get('ndcg_at_10', 0):.3f}",
            f"{m.get('avg_latency_ms', 0):.0f}ms",
            cost_str,
        )

    console.print(t)


def _print_sota_mode_table(runs: list[dict[str, Any]]):
    """SOTA Eval Mode — component delta table with Δ column."""
    console.print("\n[bold]Component Delta Table (SOTA Eval Mode)[/bold]\n")

    if not runs:
        return

    # First run is the baseline (full SOTA path)
    baseline = runs[0]
    baseline_ndcg = baseline["aggregate_metrics"].get("ndcg_at_10", 0)

    t = Table(title="Component Impact")
    t.add_column("Configuration", style="bold")
    t.add_column("MRR@10", justify="right")
    t.add_column("nDCG@10", justify="right")
    t.add_column("Δ nDCG", justify="right")
    t.add_column("Latency", justify="right")

    for run in runs:
        m = run["aggregate_metrics"]
        ndcg = m.get("ndcg_at_10", 0)
        delta = ndcg - baseline_ndcg

        delta_str = "—" if run is baseline else f"{delta:+.3f}"
        delta_style = ""
        if delta > 0:
            delta_str = f"[green]{delta_str}[/green]"
        elif delta < 0:
            delta_str = f"[red]{delta_str}[/red]"

        t.add_row(
            run["architecture_name"],
            f"{m.get('mrr_at_10', 0):.3f}",
            f"{ndcg:.3f}",
            delta_str,
            f"{m.get('avg_latency_ms', 0):.0f}ms",
        )

    console.print(t)


def _print_category_breakdown(db: RetrieveDB, runs: list[dict[str, Any]]):
    """Per-category nDCG@10 breakdown across architectures."""
    console.print("\n[bold]Per-Category nDCG@10[/bold]\n")

    # Collect all categories across runs
    all_cats: set[str] = set()
    run_cats: dict[int, dict[str, dict[str, float]]] = {}
    for run in runs:
        scores = db.get_per_category_scores(run["id"])
        run_cats[run["id"]] = scores
        all_cats.update(scores.keys())

    if not all_cats:
        console.print("  [dim]No category data available.[/dim]")
        return

    t = Table()
    t.add_column("Architecture", style="bold")
    for cat in sorted(all_cats):
        t.add_column(cat.replace("_", " ").title(), justify="right")

    for run in runs:
        scores = run_cats.get(run["id"], {})
        row = [run["architecture_name"]]
        for cat in sorted(all_cats):
            val = scores.get(cat, {}).get("ndcg_at_10", 0)
            row.append(f"{val:.3f}")
        t.add_row(*row)

    console.print(t)


def _print_miss_analysis(db: RetrieveDB, runs: list[dict[str, Any]]):
    """Miss analysis — list missed queries with classification types."""
    for run in runs:
        failures = db.get_failures_for_run(run["id"])
        if not failures:
            continue

        console.print(f"\n[bold yellow]Misses for {run['architecture_name']}[/bold yellow]")
        t = Table()
        t.add_column("#", justify="right", width=4)
        t.add_column("Miss Type")
        t.add_column("Question", max_width=60)
        t.add_column("Details", max_width=40)

        for i, f in enumerate(failures[:20], 1):
            t.add_row(
                str(i),
                f.get("failure_type", "unknown"),
                str(f.get("question_text", "")),
                str(f.get("failure_details", ""))[:40],
            )

        console.print(t)

        if len(failures) > 20:
            console.print(f"  [dim]... and {len(failures) - 20} more[/dim]")


# ── HTML dashboard ────────────────────────────────────────────────────


def _generate_html(runs: list[dict[str, Any]], db: RetrieveDB) -> str:
    """Generate a self-contained HTML comparison dashboard."""
    # Build data structures for the template
    rows = []
    for run in runs:
        m = run["aggregate_metrics"]
        cat_scores = db.get_per_category_scores(run["id"])
        failures = db.get_failures_for_run(run["id"])

        rows.append({
            "name": run["architecture_name"],
            "mode": run["mode"],
            "created_at": run["created_at"],
            "metrics": m,
            "categories": cat_scores,
            "miss_count": len(failures),
            "misses": [
                {
                    "type": f.get("failure_type", "unknown"),
                    "details": str(f.get("failure_details", ""))[:100],
                }
                for f in failures[:50]
            ],
        })

    data_json = json.dumps(rows, indent=2)

    # Build category columns
    all_cats = set()
    for r in rows:
        all_cats.update(r["categories"].keys())
    cats_sorted = sorted(all_cats)

    cat_headers = "".join(f"<th>{c.replace('_', ' ').title()}</th>" for c in cats_sorted)

    def cat_cells(row):
        cells = ""
        for c in cats_sorted:
            v = row["categories"].get(c, {}).get("ndcg_at_10", 0)
            cells += f"<td>{v:.3f}</td>"
        return cells

    # Main comparison table rows
    table_rows = ""
    baseline_ndcg = rows[0]["metrics"].get("ndcg_at_10", 0) if rows else 0
    for r in rows:
        m = r["metrics"]
        ndcg = m.get("ndcg_at_10", 0)
        delta = ndcg - baseline_ndcg
        delta_str = "—" if r is rows[0] else f"{delta:+.3f}"
        delta_class = "positive" if delta > 0 else ("negative" if delta < 0 else "")

        cost = m.get('est_monthly_cost')
        cost_str = f"${cost:.0f}" if cost else "—"

        table_rows += f"""<tr>
            <td class="arch-name">{r['name']}</td>
            <td>{m.get('recall_at_5', 0):.3f}</td>
            <td>{m.get('recall_at_10', 0):.3f}</td>
            <td>{m.get('mrr_at_10', 0):.3f}</td>
            <td>{ndcg:.3f}</td>
            <td class="{delta_class}">{delta_str}</td>
            <td>{m.get('avg_latency_ms', 0):.0f}ms</td>
            <td>{cost_str}</td>
        </tr>"""

    # Category table rows
    cat_table_rows = ""
    for r in rows:
        cat_table_rows += f"<tr><td class='arch-name'>{r['name']}</td>{cat_cells(r)}</tr>"

    # Miss details
    miss_sections = ""
    for r in rows:
        if r["misses"]:
            miss_rows = ""
            for f in r["misses"]:
                miss_rows += f"<tr><td>{f['type']}</td><td>{f['details']}</td></tr>"
            miss_sections += f"""
            <h3>{r['name']} — {len(r['misses'])} misses</h3>
            <table class="data-table">
                <tr><th>Type</th><th>Details</th></tr>
                {miss_rows}
            </table>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Retrieve — Comparison Dashboard</title>
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           max-width: 1200px; margin: 0 auto; padding: 2rem; background: #0d1117; color: #c9d1d9; }}
    h1 {{ color: #58a6ff; }}
    h2 {{ color: #79c0ff; border-bottom: 1px solid #21262d; padding-bottom: 0.5rem; }}
    h3 {{ color: #c9d1d9; }}
    .data-table {{ border-collapse: collapse; width: 100%; margin-bottom: 2rem; }}
    .data-table th {{ background: #161b22; padding: 0.75rem; text-align: left;
                      border: 1px solid #30363d; color: #8b949e; font-size: 0.85rem; }}
    .data-table td {{ padding: 0.75rem; border: 1px solid #30363d; }}
    .data-table tr:hover {{ background: #161b22; }}
    .arch-name {{ font-weight: 600; color: #58a6ff; }}
    .positive {{ color: #3fb950; font-weight: 600; }}
    .negative {{ color: #f85149; font-weight: 600; }}
    .tab-bar {{ display: flex; gap: 0; margin-bottom: 0; }}
    .tab {{ padding: 0.75rem 1.5rem; cursor: pointer; background: #161b22;
            border: 1px solid #30363d; border-bottom: none; color: #8b949e; }}
    .tab.active {{ background: #0d1117; color: #c9d1d9; border-bottom: 1px solid #0d1117; }}
    .tab-content {{ display: none; border: 1px solid #30363d; padding: 1.5rem; }}
    .tab-content.active {{ display: block; }}
    .timestamp {{ color: #8b949e; font-size: 0.85rem; }}
</style>
</head>
<body>
<h1>Retrieve — Comparison Dashboard</h1>
<p class="timestamp">Generated from {len(rows)} evaluation runs</p>

<div class="tab-bar">
    <div class="tab active" onclick="switchTab('metrics')">Metrics</div>
    <div class="tab" onclick="switchTab('categories')">Per-Category</div>
    <div class="tab" onclick="switchTab('misses')">Miss Analysis</div>
</div>

<div id="metrics" class="tab-content active">
<h2>Architecture Comparison</h2>
<table class="data-table">
<tr>
    <th>Architecture</th><th>Recall@5</th><th>Recall@10</th>
    <th>MRR@10</th><th>nDCG@10</th><th>Δ nDCG</th>
    <th>Avg Latency</th><th>Est. Cost</th>
</tr>
{table_rows}
</table>
</div>

<div id="categories" class="tab-content">
<h2>Per-Category nDCG@10</h2>
<table class="data-table">
<tr><th>Architecture</th>{cat_headers}</tr>
{cat_table_rows}
</table>
</div>

<div id="misses" class="tab-content">
<h2>Miss Analysis</h2>
{miss_sections if miss_sections else '<p>No misses recorded.</p>'}
</div>

<script>
function switchTab(name) {{
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
    document.getElementById(name).classList.add('active');
    event.target.classList.add('active');
}}
</script>

<script>const DATA = {data_json};</script>
</body>
</html>"""
    return html


# ── Export helpers ─────────────────────────────────────────────────────


def _export_csv(runs: list[dict[str, Any]], path: str):
    """Export comparison table as CSV."""
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Architecture", "Mode", "Recall@5", "Recall@10", "MRR@10",
        "nDCG@10", "Avg Latency (ms)", "Est. Monthly Cost",
    ])
    for run in runs:
        m = run["aggregate_metrics"]
        writer.writerow([
            run["architecture_name"],
            run["mode"],
            f"{m.get('recall_at_5', 0):.3f}",
            f"{m.get('recall_at_10', 0):.3f}",
            f"{m.get('mrr_at_10', 0):.3f}",
            f"{m.get('ndcg_at_10', 0):.3f}",
            f"{m.get('avg_latency_ms', 0):.0f}",
            str(m.get("est_monthly_cost", "")),
        ])

    Path(path).write_text(output.getvalue(), encoding="utf-8")
    console.print(f"  Exported CSV to [cyan]{path}[/cyan]")


def _export_json(runs: list[dict[str, Any]], path: str):
    """Export full run data as JSON."""
    Path(path).write_text(json.dumps(runs, indent=2), encoding="utf-8")
    console.print(f"  Exported JSON to [cyan]{path}[/cyan]")


# ── Main entry point ──────────────────────────────────────────────────


def compare_runs(
    run_ids: list[int] | None = None,
    export_path: str | None = None,
    open_web: bool = False,
    cfg: RetrieveConfig | None = None,
):
    """Compare evaluation runs side-by-side."""
    if cfg is None:
        cfg = RetrieveConfig()

    db = RetrieveDB(cfg.db_path)
    try:
        # Get runs to compare
        with step("compare.load_runs"):
            if run_ids:
                runs = db.compare_runs(run_ids)
            else:
                runs = db.get_all_completed_runs()

        if not runs:
            console.print("[red]No completed runs to compare. Run 'retrieve eval run' first.[/red]")
            return

        emit_progress(
            f"Loaded {len(runs)} runs for comparison",
            stage="compare.load", run_count=len(runs),
        )

        # Determine mode from runs
        modes = {r["mode"] for r in runs}
        is_sota = "sota" in modes

        # Print tables
        if is_sota:
            _print_sota_mode_table(runs)
        else:
            _print_test_mode_table(runs)

        _print_category_breakdown(db, runs)
        _print_miss_analysis(db, runs)

        # Export
        if export_path:
            with step("compare.export"):
                if export_path.endswith(".csv"):
                    _export_csv(runs, export_path)
                elif export_path.endswith(".json"):
                    _export_json(runs, export_path)
                else:
                    _export_json(runs, export_path)
            emit_progress(f"Exported to {export_path}", stage="compare.export")

        # Web dashboard
        if open_web:
            with step("compare.dashboard"):
                html = _generate_html(runs, db)
                html_path = Path("retrieve-dashboard.html")
                html_path.write_text(html, encoding="utf-8")
            console.print(f"\n  Dashboard saved to [cyan]{html_path}[/cyan]")
            emit_progress("Dashboard generated", stage="compare.dashboard")
            webbrowser.open(str(html_path.resolve()))

    finally:
        db.close()
