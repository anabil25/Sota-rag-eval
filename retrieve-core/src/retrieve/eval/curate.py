"""Eval set curation — category-level steering and regeneration.

Skills reference: copilot-sdk/python/README.md (send_and_wait, session reuse),
    copilot-sdk/docs/features/steering-and-queueing.md (enqueue mode)

See Retrieve.md Phase 2 Step 2:
  - Operates at the category level, not per-question
  - SME feedback: "more cross-document, fewer direct lookups, add fraud category"
  - Regenerates/rebalances → writes new eval set version
"""

from __future__ import annotations

import json
import logging
from typing import Any

from rich.console import Console
from rich.table import Table

from retrieve.config import RetrieveConfig
from retrieve.copilot import get_client, run_sync, stop_client
from retrieve.db import RetrieveDB
from retrieve.eval.chunks import load_corpus_chunks
from retrieve.eval.generate import SYSTEM_MESSAGE
from retrieve.observability import emit_error, emit_progress, step

log = logging.getLogger(__name__)
console = Console()


def show_eval_set_summary(eval_set_version: str = "latest", cfg: RetrieveConfig | None = None):
    """Display category summary table for an eval set."""
    if cfg is None:
        cfg = RetrieveConfig()

    db = RetrieveDB(cfg.db_path)
    try:
        with step("curate.load_eval_set"):
            if eval_set_version == "latest":
                es = db.get_latest_eval_set()
            else:
                es = db.get_eval_set_by_version(eval_set_version)

            if not es:
                console.print("[red]No eval set found.[/red]")
                return None

        cats = (
            json.loads(es["category_counts"])
            if isinstance(es["category_counts"], str)
            else es["category_counts"]
        )

        console.print(f"\n[bold]Eval Set: {es['version_label']}[/bold]")
        console.print(f"  Total questions: [green]{es['question_count']}[/green]")
        console.print(f"  Created: {es['created_at']}")
        if es.get("notes"):
            console.print(f"  Notes: {es['notes']}")

        t = Table(title="Category Breakdown")
        t.add_column("Category")
        t.add_column("Count", justify="right")
        t.add_column("Examples")

        # Get example questions per category
        questions = db.get_questions(es["id"])
        cat_examples: dict[str, list[str]] = {}
        for q in questions:
            cat = q["category"]
            cat_examples.setdefault(cat, [])
            if len(cat_examples[cat]) < 2:
                cat_examples[cat].append(q["question_text"][:60])

        for cat, count in sorted(cats.items()):
            examples = cat_examples.get(cat, [])
            example_str = " | ".join(f'"{e}"' for e in examples)
            t.add_row(cat, str(count), example_str)

        console.print(t)

        qt_rows = db.conn.execute(
            "SELECT question_type, COUNT(*) AS cnt FROM eval_questions "
            "WHERE eval_set_id = ? GROUP BY question_type ORDER BY cnt DESC",
            (es["id"],),
        ).fetchall()
        if qt_rows:
            t2 = Table(title="Question Type Breakdown")
            t2.add_column("Question Type")
            t2.add_column("Count", justify="right")
            for r in qt_rows:
                t2.add_row(r["question_type"], str(r["cnt"]))
            console.print(t2)
        return es

    finally:
        db.close()


def regenerate_eval_set(
    source_version: str,
    new_version: str,
    steering: dict[str, Any],
    corpus_dir: str,
    cfg: RetrieveConfig | None = None,
) -> int:
    """Regenerate an eval set with category-level steering.

    steering dict format:
    {
        "more": ["cross_document", "edge_cases"],
        "fewer": ["direct_lookup"],
        "add_categories": ["fraud_referrals"],
        "remove_categories": [],
        "notes": "Add more DV-related cross-document questions"
    }

    Returns the new eval_set_id.
    """
    if cfg is None:
        cfg = RetrieveConfig()

    db = RetrieveDB(cfg.db_path)
    try:
        stored = db.get_generation_preferences("default")
        merged_steering = (
            dict(stored.get("steering", {})) if isinstance(stored.get("steering", {}), dict) else {}
        )
        merged_steering.update(steering)
        steering = merged_steering

        # Get source eval set
        source = db.get_eval_set_by_version(source_version)
        if not source:
            console.print(f"[red]Eval set '{source_version}' not found.[/red]")
            emit_error(f"Source eval set '{source_version}' not found", stage="curate.regenerate")
            return -1

        source_questions = db.get_questions(source["id"])
        source_cats = (
            json.loads(source["category_counts"])
            if isinstance(source["category_counts"], str)
            else source["category_counts"]
        )

        console.print("\n[bold]Regenerating eval set[/bold]")
        console.print(f"  Source: {source_version} ({source['question_count']} questions)")
        console.print(f"  New version: {new_version}")

        # Build steering instructions for the LLM
        steering_instructions = _build_steering_prompt(source_cats, steering)
        console.print(f"\n  Steering:\n{steering_instructions}\n")

        # Determine which questions to keep vs regenerate
        more_cats = set(steering.get("more", []))
        fewer_cats = set(steering.get("fewer", []))
        remove_cats = set(steering.get("remove_categories", []))
        add_cats = steering.get("add_categories", [])

        # Keep questions from categories not being reduced
        kept_questions: list[dict[str, Any]] = []
        for q in source_questions:
            if q["category"] in remove_cats:
                continue
            if q["category"] in fewer_cats:
                # Keep only half
                cat_kept = [kq for kq in kept_questions if kq["category"] == q["category"]]
                target = source_cats.get(q["category"], 0) // 2
                if len(cat_kept) < target:
                    kept_questions.append(q)
            else:
                kept_questions.append(q)

        console.print(f"  Keeping {len(kept_questions)} questions from source")
        emit_progress(
            f"Keeping {len(kept_questions)} questions from source",
            stage="curate.filter",
            kept=len(kept_questions),
        )

        # Generate new questions for "more" and "add" categories via Copilot SDK
        new_questions: list[dict[str, Any]] = []
        categories_to_generate = list(more_cats) + add_cats

        if categories_to_generate:
            chunks = load_corpus_chunks(corpus_dir)
            if not chunks:
                console.print("[red]No corpus chunks found. Run 'retrieve ingest' first.[/red]")
                emit_error("No corpus chunks found", stage="curate.regenerate")
                return -1

            console.print(f"  Generating new questions for: {categories_to_generate}")

            async def _generate():
                try:
                    return await _generate_steered_questions(
                        chunks, categories_to_generate, steering, cfg
                    )
                finally:
                    await stop_client()

            with step("curate.generate_steered"):
                new_questions = run_sync(_generate())
            emit_progress(
                f"Generated {len(new_questions)} new questions",
                stage="curate.generate",
                generated=len(new_questions),
            )
            console.print(f"  Generated {len(new_questions)} new questions")

        # Create new eval set version
        all_questions = kept_questions + new_questions
        notes = steering.get("notes", f"Regenerated from {source_version}")

        with step("curate.persist_eval_set"):
            new_id = db.create_eval_set(new_version, notes=notes)
            for q in all_questions:
                db.add_question(
                    new_id,
                    q.get("question_text", q.get("question", "")),
                    q.get("category", "direct_lookup"),
                    q.get("ground_truth_chunk_ids", []),
                    q.get("source_doc_id"),
                    q.get("metadata"),
                )
            db.update_eval_set_counts(new_id)

        # Show result
        new_es = db.get_eval_set_by_version(new_version)
        new_cats = (
            json.loads(new_es["category_counts"])
            if isinstance(new_es["category_counts"], str)
            else new_es["category_counts"]
        )

        console.print(f"\n[bold green]New eval set '{new_version}' created[/bold green]")
        console.print(f"  Total questions: {new_es['question_count']}")

        t = Table(title="Category Comparison")
        t.add_column("Category")
        t.add_column("Before", justify="right")
        t.add_column("After", justify="right")
        t.add_column("Δ", justify="right")

        all_cat_names = set(list(source_cats.keys()) + list(new_cats.keys()))
        for cat in sorted(all_cat_names):
            before = source_cats.get(cat, 0)
            after = new_cats.get(cat, 0)
            delta = after - before
            delta_str = f"{delta:+d}" if delta != 0 else "—"
            style = "green" if delta > 0 else ("red" if delta < 0 else "")
            t.add_row(
                cat,
                str(before),
                str(after),
                f"[{style}]{delta_str}[/{style}]" if style else delta_str,
            )

        console.print(t)

        # Persist cumulative steering preferences for future runs
        prefs = db.get_generation_preferences("default")
        prefs["steering"] = steering
        db.upsert_generation_preferences(prefs, "default")
        return new_id

    finally:
        db.close()


def _build_steering_prompt(
    current_cats: dict[str, int],
    steering: dict[str, Any],
) -> str:
    """Build a human-readable steering instruction string."""
    lines = []
    for cat in steering.get("more", []):
        count = current_cats.get(cat, 0)
        lines.append(f"  + Generate MORE '{cat}' questions (currently {count})")
    for cat in steering.get("fewer", []):
        count = current_cats.get(cat, 0)
        lines.append(f"  - FEWER '{cat}' questions (currently {count}, keeping ~{count // 2})")
    for cat in steering.get("remove_categories", []):
        lines.append(f"  ✗ REMOVE all '{cat}' questions")
    for cat in steering.get("add_categories", []):
        lines.append(f"  ★ ADD new category '{cat}'")
    if steering.get("notes"):
        lines.append(f"  Note: {steering['notes']}")
    return "\n".join(lines) if lines else "  No steering changes"


async def _generate_steered_questions(
    chunks: list,
    target_categories: list[str],
    steering: dict[str, Any],
    cfg: RetrieveConfig,
) -> list[dict[str, Any]]:
    """Generate questions focused on specific categories via Copilot SDK."""
    from copilot import PermissionHandler

    client = await get_client(cfg.copilot)

    cat_instruction = ", ".join(target_categories)
    type_instruction = ", ".join(steering.get("question_types", []))
    notes = steering.get("notes", "")
    system_msg = (
        f"{SYSTEM_MESSAGE}\n\n"
        f"IMPORTANT: Focus ONLY on these categories: {cat_instruction}\n"
        f"Generate questions that specifically test these retrieval challenges.\n"
    )
    if type_instruction:
        system_msg += f"Bias question_type output toward: {type_instruction}.\n"
    if notes:
        system_msg += f"SME guidance: {notes}\n"

    session_config: dict[str, Any] = {
        "model": cfg.copilot.model,
        "on_permission_request": PermissionHandler.approve_all,
        "system_message": {"content": system_msg},
    }
    if cfg.copilot.provider:
        session_config["provider"] = cfg.copilot.provider.to_sdk_dict()

    all_questions: list[dict[str, Any]] = []
    # Sample a subset of chunks for targeted generation
    import random

    sample_size = min(len(chunks), 20)
    sampled = random.sample(chunks, sample_size)

    async with await client.create_session(**session_config) as session:
        for chunk in sampled:
            prompt = (
                f"Generate 2 evaluation questions for this chunk, "
                f"focusing on categories: {cat_instruction}\n\n"
                f"Chunk ID: {chunk.chunk_id}\n"
                f"Document: {chunk.doc_title} (policy {chunk.doc_id})\n\n"
                f"Content:\n{chunk.content[:2000]}\n\n"
                f"Return ONLY a JSON object with a 'questions' array."
            )

            # Use enqueue mode for batch generation — sends all prompts
            # concurrently and collects results, improving throughput.
            response = await session.send_and_wait(prompt, timeout=cfg.copilot.timeout)
            if not response or not response.data or not response.data.content:
                continue

            raw = response.data.content
            try:
                if "```json" in raw:
                    start = raw.index("```json") + 7
                    end = raw.index("```", start)
                    raw = raw[start:end]
                elif "```" in raw:
                    start = raw.index("```") + 3
                    end = raw.index("```", start)
                    raw = raw[start:end]

                data = json.loads(raw.strip())
                for q in data.get("questions", []):
                    q["source_doc_id"] = chunk.doc_id
                    q.setdefault("question_type", "operator_lookup")
                    gt = q.get("ground_truth_chunk_ids", [])
                    if chunk.chunk_id not in gt:
                        gt.append(chunk.chunk_id)
                    q["ground_truth_chunk_ids"] = gt
                    all_questions.append(q)
            except (json.JSONDecodeError, ValueError):
                continue

    return all_questions
