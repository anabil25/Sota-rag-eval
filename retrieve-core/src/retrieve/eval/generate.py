"""Golden eval set generation via Copilot SDK.

Reads the ingested corpus, chunks it, and uses a Copilot SDK session
to generate categorized questions with ground-truth chunk pairings.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import time
from typing import Any

from rich.console import Console
from rich.progress import Progress

from retrieve.config import RetrieveConfig
from retrieve.copilot import get_client, run_sync, stop_client
from retrieve.db import RetrieveDB
from retrieve.eval.chunks import Chunk, load_corpus_chunks
from retrieve.observability import emit_progress, step

log = logging.getLogger(__name__)
console = Console()

# Maximum chunks per prompt.  20 chunks × ~1500 tokens ≈ 30K input tokens.
# Kept well below 128K to avoid context rot (quality degrades long before
# the hard token limit).  Groups with more chunks are split into parallel
# batches of this size.
BATCH_SIZE = 20

DEFAULT_OPERATOR_CONTEXT = (
    "You are generating evaluation data for users who search a reference corpus "
    "for authoritative answers to operational questions."
)


SYSTEM_MESSAGE_TEMPLATE = """You are an expert evaluation-set generator for information retrieval systems.

__OPERATOR_CONTEXT__

You must generate realistic question-answer pairs that mirror how real users search this corpus:
- finding specific facts, definitions, thresholds, or form names
- clarifying required steps, procedures, or workflows
- handling edge-case exceptions and special scenarios
- resolving ambiguous language and cross-document dependencies
- testing what happens when information spans multiple documents
- verifying the system correctly handles unanswerable questions

Before generating, use the corpus understanding and intent map provided by the caller.
Do not generate random trivia and do not overfit to lexical wording from one chunk.

Your task: given document chunks from a reference corpus, generate realistic questions
that the chunks can answer, plus concise canonical answers grounded in those chunks.

Return a JSON object with the target number of questions:
{
  "questions": [
    {
      "question": "the question text",
      "answer_text": "concise canonical answer grounded in source",
      "category": "one of: factual_lookup, procedural, cross_document, cross_policy, edge_case, negation, colloquial_mapping, calculation, unanswerable",
      "question_type": "one of: factual_lookup, procedural, cross_document, cross_policy, edge_case, negation, colloquial_mapping, calculation, unanswerable",
      "intent_family": "short intent label derived from the corpus domain",
      "difficulty": "easy|medium|hard",
      "expected_search_challenge": "one of: chunk_boundary, semantic_mismatch, cross_document, negation_handling, table_extraction, specificity_failure, hallucination_bait, similar_content, multi_document_reasoning",
      "ground_truth_chunk_ids": ["chunk_id_1"],
      "reasoning": "brief explanation of why these chunks answer this question",
      "evidence_summary": "1-2 sentence evidence trace"
    }
  ]
}

Category definitions:
- factual_lookup: factual question answered directly by the chunk (names, definitions, thresholds, dates)
- procedural: question about a process, workflow, or sequence of steps
- cross_document: question requiring information from multiple sections within the same document
- cross_policy: question requiring synthesis across multiple separate documents
- edge_case: question about exceptions, special cases, or unusual scenarios
- negation: question testing what is NOT allowed, excluded, or prohibited
- colloquial_mapping: question using informal/everyday language that doesn't match document terminology
- calculation: question requiring numeric computation or threshold comparison
- unanswerable: question that the corpus genuinely cannot answer (tests refusal behavior)

Guidelines:
- Questions should sound like what a real user of this corpus would ask
- Vary the complexity — some simple lookups, some requiring multi-hop synthesis
- Include genuinely multi-hop questions that require multiple chunks and broader top-k retrieval
- Each question must map to at least one ground_truth_chunk_id (except unanswerable)
- Do NOT generate questions that the chunk content cannot answer (except unanswerable category)
- Distribute questions proportionally across categories
- Return ONLY the JSON object, no other text
"""

# Backward-compatible default system message used by curation flows/tests.
SYSTEM_MESSAGE = SYSTEM_MESSAGE_TEMPLATE.replace("__OPERATOR_CONTEXT__", DEFAULT_OPERATOR_CONTEXT)


# ── Generation logic ──────────────────────────────────────────────────


def _format_chunk_block(chunk: Chunk) -> str:
    """Format a single chunk for inclusion in a batched prompt."""
    return (
        f"--- CHUNK ---\n"
        f"Chunk ID: {chunk.chunk_id}\n"
        f"Document: {chunk.doc_title} (policy {chunk.doc_id})\n"
        f"Section: {chunk.heading}\n\n"
        f"{chunk.content}\n"
    )


def _extract_json(raw: str) -> dict[str, Any] | None:
    """Extract a JSON object from a model response that may wrap it in markdown."""
    text = raw
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        text = text[start:end]
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        text = text[start:end]
    return json.loads(text.strip())


async def _generate_batch(
    batch_label: str,
    categories: list[str],
    batch_targets: dict[str, int],
    batch_chunks: list[Chunk],
    cfg: RetrieveConfig,
    system_message: str,
    corpus_summary: dict[str, Any],
    intent_map: dict[str, Any],
) -> list[dict[str, Any]]:
    """Generate questions for a single batch of chunks.

    One Copilot session, one prompt, one response.  Called in parallel
    when a group has more chunks than BATCH_SIZE.
    """
    from copilot import PermissionHandler

    batch_total = sum(batch_targets.values())
    if batch_total == 0 or not batch_chunks:
        return []

    client = await get_client(cfg.copilot)

    session_config: dict[str, Any] = {
        "model": cfg.copilot.model,
        "on_permission_request": PermissionHandler.approve_all,
        "system_message": {"content": system_message},
    }
    if cfg.copilot.provider:
        session_config["provider"] = cfg.copilot.provider.to_sdk_dict()

    cat_lines = "\n".join(f"  - {c}: {batch_targets.get(c, 0)}" for c in categories if batch_targets.get(c, 0) > 0)
    chunk_blocks = "\n".join(_format_chunk_block(c) for c in batch_chunks)
    chunk_id_list = [c.chunk_id for c in batch_chunks]

    prompt = (
        f"Generate exactly {batch_total} evaluation questions.\n\n"
        f"Category targets:\n{cat_lines}\n\n"
        f"Corpus summary:\n{json.dumps(corpus_summary)}\n\n"
        f"Intent map:\n{json.dumps(intent_map)}\n\n"
        f"Available chunk IDs: {chunk_id_list}\n\n"
        f"=== CHUNKS ===\n\n{chunk_blocks}\n\n"
        f"Return ONLY a JSON object with a 'questions' array containing "
        f"exactly {batch_total} questions."
    )

    async with await client.create_session(**session_config) as session:
        call_started = time.monotonic()

        async def _call_model():
            return await session.send_and_wait(prompt, timeout=cfg.copilot.timeout or 600)

        async def _heartbeat():
            while True:
                await asyncio.sleep(30)
                elapsed = int(time.monotonic() - call_started)
                console.print(f"  [dim]{batch_label} waiting on model ({elapsed}s)...[/dim]")
                emit_progress(
                    "Waiting on model",
                    stage="eval_generate",
                    batch=batch_label,
                    elapsed_seconds=elapsed,
                )

        model_task = asyncio.create_task(_call_model())
        heartbeat_task = asyncio.create_task(_heartbeat())
        response = None

        try:
            response = await asyncio.wait_for(model_task, timeout=600)
        except asyncio.TimeoutError:
            log.warning("%s timed out after 600s", batch_label)
            console.print(f"  [yellow]{batch_label} timed out[/yellow]")
            model_task.cancel()
            return []
        finally:
            heartbeat_task.cancel()

    elapsed = int(time.monotonic() - call_started)

    if not response or not response.data or not response.data.content:
        console.print(f"  [yellow]{batch_label} no response[/yellow]")
        return []

    raw = response.data.content
    chunk_by_id = {c.chunk_id: c for c in batch_chunks}
    questions: list[dict[str, Any]] = []

    try:
        data = _extract_json(raw)
        for q in data.get("questions", []):
            gt_ids = q.get("ground_truth_chunk_ids", [])
            source_doc = None
            for gt in gt_ids:
                if gt in chunk_by_id:
                    source_doc = chunk_by_id[gt].doc_id
                    break
            q["source_doc_id"] = source_doc
            q.setdefault("answer_text", "")
            q.setdefault("question_type", q.get("category", "factual_lookup"))
            q.setdefault("intent_family", "general")
            q.setdefault("difficulty", "medium")
            q.setdefault("expected_search_challenge", "")
            q.setdefault("evidence_summary", "")
            questions.append(q)

        console.print(f"  [green]{batch_label} +{len(questions)} questions in {elapsed}s[/green]")
        emit_progress(
            f"{batch_label} complete",
            stage="eval_generate",
            batch=batch_label,
            generated_questions=len(questions),
            elapsed_seconds=elapsed,
        )
    except (json.JSONDecodeError, ValueError) as e:
        log.warning("Failed to parse %s response: %s", batch_label, e)
        console.print(f"  [yellow]{batch_label} JSON parse failed: {e}[/yellow]")

    return questions


async def _generate_for_batch(
    chunks: list[Chunk],
    questions_per_chunk: int,
    batch_index: int,
    cfg: RetrieveConfig,
    batch_count: int,
    operator_context: str = DEFAULT_OPERATOR_CONTEXT,
    corpus_summary: dict[str, Any] | None = None,
    intent_map: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Legacy batch generator kept for older tests and simple generation calls."""
    if not chunks or questions_per_chunk <= 0:
        return []

    target = max(1, len(chunks) * questions_per_chunk)
    category = cfg.eval.categories[0] if cfg.eval.categories else "factual_lookup"
    system_message = SYSTEM_MESSAGE_TEMPLATE.replace("__OPERATOR_CONTEXT__", operator_context)
    return await _generate_batch(
        batch_label=f"[batch:{batch_index}/{batch_count}]",
        categories=[category],
        batch_targets={category: target},
        batch_chunks=chunks,
        cfg=cfg,
        system_message=system_message,
        corpus_summary=corpus_summary or _summarize_corpus(chunks),
        intent_map=intent_map or {"intent_families": [category]},
    )


def _split_targets(
    categories: list[str],
    category_targets: dict[str, int],
    n_batches: int,
) -> list[dict[str, int]]:
    """Distribute category targets across n_batches as evenly as possible.

    Guarantees every question is assigned to exactly one batch (no
    rounding gaps) via remainder distribution.
    """
    batch_targets: list[dict[str, int]] = [{} for _ in range(n_batches)]
    for cat in categories:
        total = category_targets.get(cat, 0)
        base = total // n_batches
        remainder = total % n_batches
        for i in range(n_batches):
            batch_targets[i][cat] = base + (1 if i < remainder else 0)
    return batch_targets


async def _generate_for_group(
    group_name: str,
    categories: list[str],
    category_targets: dict[str, int],
    chunks: list[Chunk],
    cfg: RetrieveConfig,
    operator_context: str,
    corpus_summary: dict[str, Any],
    intent_map: dict[str, Any],
    system_prompt_extra: str = "",
    max_q_per_chunk: int = 1,
) -> list[dict[str, Any]]:
    """Generate questions for a category group, batching if needed.

    If the group has more than BATCH_SIZE chunks, it is split into
    parallel batches — each batch gets its own Copilot session and a
    proportional share of the category targets.
    """
    target_count = sum(category_targets.get(c, 0) for c in categories)
    if target_count == 0 or not chunks:
        return []

    # Cap target so we don't ask more questions than chunks can support.
    max_reasonable = len(chunks) * max_q_per_chunk
    if target_count > max_reasonable:
        log.info(
            "%s: capping target from %d to %d (%d × %d chunks)",
            group_name, target_count, max_reasonable, max_q_per_chunk, len(chunks),
        )
        scale = max_reasonable / target_count
        category_targets = {c: max(1, round(category_targets.get(c, 0) * scale)) for c in categories}
        target_count = sum(category_targets.get(c, 0) for c in categories)

    # Build the system message (shared across all batches in this group)
    cat_list = ", ".join(categories)
    system_message = (
        SYSTEM_MESSAGE_TEMPLATE.replace("__OPERATOR_CONTEXT__", operator_context)
        + f"\n\nFOCUS: Generate ONLY questions in these categories: {cat_list}.\n"
        + system_prompt_extra
    )

    # Split into batches of BATCH_SIZE chunks
    chunk_batches = [chunks[i:i + BATCH_SIZE] for i in range(0, len(chunks), BATCH_SIZE)]
    n_batches = len(chunk_batches)
    batch_target_list = _split_targets(categories, category_targets, n_batches)

    label = f"[{group_name}]"
    if n_batches == 1:
        console.print(f"  {label} {target_count} questions from {len(chunks)} chunks...")
    else:
        console.print(
            f"  {label} {target_count} questions from {len(chunks)} chunks "
            f"({n_batches} batches of ≤{BATCH_SIZE})..."
        )

    emit_progress(
        f"Starting {group_name} generation ({target_count} questions, "
        f"{len(chunks)} chunks, {n_batches} batches)",
        stage="eval_generate",
        group=group_name,
        target_count=target_count,
        chunk_count=len(chunks),
        batch_count=n_batches,
    )

    # Run all batches in parallel
    tasks = []
    for bi, (b_chunks, b_targets) in enumerate(zip(chunk_batches, batch_target_list)):
        b_label = f"[{group_name}]" if n_batches == 1 else f"[{group_name}:{bi+1}/{n_batches}]"
        tasks.append(
            _generate_batch(
                batch_label=b_label,
                categories=categories,
                batch_targets=b_targets,
                batch_chunks=b_chunks,
                cfg=cfg,
                system_message=system_message,
                corpus_summary=corpus_summary,
                intent_map=intent_map,
            )
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_questions: list[dict[str, Any]] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            b_label = f"{group_name}:{i+1}" if n_batches > 1 else group_name
            log.warning("Batch %s failed: %s", b_label, result)
            console.print(f"  [yellow]{label} batch {i+1} failed: {result}[/yellow]")
        else:
            all_questions.extend(result)

    return all_questions


# ── Chunk selection ───────────────────────────────────────────────────


def _select_docs(
    chunks: list[Chunk],
    n_docs: int,
    seed: int,
    exclude_docs: set[str] | None = None,
) -> list[Chunk]:
    """Randomly select n_docs and return all their chunks.

    Each file = 1 doc.  Seeded for reproducibility.  If ``exclude_docs``
    removes too many, falls back to the full pool.
    """
    by_doc: dict[str, list[Chunk]] = {}
    for c in chunks:
        if exclude_docs and c.doc_id in exclude_docs:
            continue
        by_doc.setdefault(c.doc_id, []).append(c)

    if not by_doc and exclude_docs:
        # Corpus too small for exclusive partitioning — use full pool
        by_doc = {}
        for c in chunks:
            by_doc.setdefault(c.doc_id, []).append(c)

    docs = sorted(by_doc.keys())
    random.Random(seed).shuffle(docs)
    picked = docs[:min(n_docs, len(docs))]
    selected: list[Chunk] = []
    for doc_id in picked:
        selected.extend(by_doc[doc_id])
    return selected


def _summarize_corpus(chunks: list[Chunk]) -> dict[str, Any]:
    """Build a deterministic corpus summary for generation context."""
    docs: dict[str, dict[str, Any]] = {}
    categories = {
        "factual_lookup": 0,
        "procedural": 0,
        "cross_document": 0,
        "cross_policy": 0,
        "edge_case": 0,
        "negation": 0,
        "calculation": 0,
        "unanswerable": 0,
    }
    xrefs = 0
    for c in chunks:
        d = docs.setdefault(c.doc_id, {"title": c.doc_title, "chunks": 0})
        d["chunks"] += 1
        xrefs += len(c.metadata.get("cross_references", [])) if isinstance(c.metadata.get("cross_references", []), list) else 0

    return {
        "document_count": len(docs),
        "chunk_count": len(chunks),
        "cross_reference_count": xrefs,
        "default_categories": categories,
        "sample_docs": [{"doc_id": k, "title": v["title"], "chunks": v["chunks"]} for k, v in list(docs.items())[:20]],
    }


async def _derive_intent_map_with_llm(
    cfg: RetrieveConfig,
    corpus_summary: dict[str, Any],
    operator_context: str,
) -> dict[str, Any]:
    """Use a short Copilot call to derive operator intent families and retrieval challenge mix."""
    prompt = (
        "Create an intent map for retrieval evaluation generation. Return ONLY JSON with keys: "
        "intent_families (list), question_type_mix (object), challenge_mix (object), multi_hop_focus (list).\n\n"
        f"Operator context: {operator_context}\n"
        f"Corpus summary: {json.dumps(corpus_summary)}"
    )
    raw = await run_single_prompt(cfg, prompt)
    if not raw:
        return {
            "intent_families": ["definitions", "procedures", "requirements", "exceptions", "cross_references"],
            "question_type_mix": {
                "factual_lookup": 0.20,
                "procedural": 0.20,
                "cross_document": 0.15,
                "cross_policy": 0.15,
                "edge_case": 0.10,
                "negation": 0.10,
                "calculation": 0.05,
                "unanswerable": 0.05,
            },
            "challenge_mix": {
                "chunk_boundary": 0.15,
                "semantic_mismatch": 0.15,
                "cross_document": 0.20,
                "negation_handling": 0.15,
                "specificity_failure": 0.10,
                "table_extraction": 0.10,
                "hallucination_bait": 0.05,
                "multi_document_reasoning": 0.10,
            },
            "multi_hop_focus": ["cross-document exceptions", "procedure preconditions", "requirement dependencies"],
        }

    try:
        if "```json" in raw:
            s = raw.index("```json") + 7
            e = raw.index("```", s)
            raw = raw[s:e]
        elif "```" in raw:
            s = raw.index("```") + 3
            e = raw.index("```", s)
            raw = raw[s:e]
        return json.loads(raw.strip())
    except Exception:
        return {
            "intent_families": ["definitions", "procedures", "requirements", "exceptions", "cross_references"],
            "question_type_mix": {
                "factual_lookup": 0.20,
                "procedural": 0.20,
                "cross_document": 0.15,
                "cross_policy": 0.15,
                "edge_case": 0.10,
                "negation": 0.10,
                "calculation": 0.05,
                "unanswerable": 0.05,
            },
            "challenge_mix": {
                "chunk_boundary": 0.15,
                "semantic_mismatch": 0.15,
                "cross_document": 0.20,
                "negation_handling": 0.15,
                "specificity_failure": 0.10,
                "table_extraction": 0.10,
                "hallucination_bait": 0.05,
                "multi_document_reasoning": 0.10,
            },
            "multi_hop_focus": ["cross-document exceptions", "procedure preconditions", "requirement dependencies"],
        }


async def run_single_prompt(cfg: RetrieveConfig, prompt: str) -> str:
    from retrieve.copilot import send_and_wait
    return await send_and_wait(cfg.copilot, prompt, timeout=cfg.copilot.timeout)


# Category mix — derived from real eval data across 10 policy manuals (191 questions).
# Ordered by corpus coverage efficiency (cross-doc questions touch ~2 docs each).
CATEGORY_MIX = {
    "cross_policy": 0.20,        # multi-doc synthesis, highest coverage efficiency
    "factual_lookup": 0.15,      # baseline retrieval
    "procedural": 0.15,          # common real-world pattern
    "edge_case": 0.15,           # where architectures diverge most
    "cross_document": 0.10,      # within-doc cross-section questions
    "negation": 0.08,            # what's NOT in docs — tricky for vector search
    "colloquial_mapping": 0.07,  # user language ≠ doc language
    "calculation": 0.05,         # numeric/threshold questions
    "unanswerable": 0.05,        # refusal behavior, guards against hallucination
}

# Doc coverage targets per mode
_MODE_CONFIG = {
    "sample": {"doc_coverage": 0.25, "min_per_category": 2, "fixed_total": 25},
    "full":   {"doc_coverage": 0.70, "min_per_category": 5, "doc_fraction": 0.67},
}


def _compute_eval_targets(doc_count: int, chunk_count: int, mode: str) -> dict[str, Any]:
    """Compute question generation targets based on corpus size and mode.

    Total questions:
      sample: fixed 25
      full:   ~2/3 of docs (e.g. 305 docs → ~204 questions)

    Category mix percentages stay constant regardless of mode.
    Min per-category floor ensures every failure mode is tested.
    """
    mc = _MODE_CONFIG.get(mode, _MODE_CONFIG["sample"])
    doc_coverage = mc["doc_coverage"]
    min_per_cat = mc["min_per_category"]

    # Total questions: fixed 25 for sample, 2/3 of docs for full
    if "fixed_total" in mc:
        total_raw = mc["fixed_total"]
    else:
        total_raw = max(len(CATEGORY_MIX) * min_per_cat, round(doc_count * mc["doc_fraction"]))

    # Compute per-category targets
    category_targets = {}
    for cat, pct in CATEGORY_MIX.items():
        category_targets[cat] = max(min_per_cat, round(total_raw * pct))

    # If fixed total, scale categories to match exactly
    if "fixed_total" in mc:
        cat_sum = sum(category_targets.values())
        if cat_sum != total_raw:
            scale = total_raw / max(1, cat_sum)
            category_targets = {k: max(1, round(v * scale)) for k, v in category_targets.items()}

    total = sum(category_targets.values())

    # Coverage target for chunk selection
    chunk_coverage = doc_coverage

    # Questions per chunk for the prompt (total / selected chunks estimate)
    estimated_chunks = max(1, int(chunk_count * chunk_coverage * 0.5))  # ~half of covered chunks
    qpc = max(1, min(3, total // max(1, estimated_chunks)))

    return {
        "total_target": total,
        "coverage_target": chunk_coverage,
        "questions_per_chunk": qpc,
        "category_targets": category_targets,
        "mode": mode,
        "doc_coverage": doc_coverage,
        "min_per_category": min_per_cat,
    }


def generate_eval_set(
    corpus_dir: str,
    version_label: str,
    cfg: RetrieveConfig | None = None,
    base_eval_set_version: str | None = "latest",
    fresh: bool = False,
    operator_context: str = DEFAULT_OPERATOR_CONTEXT,
    preference_scope: str = "default",
    mode: str | None = None,
    # Legacy params — ignored if mode is set
    questions_per_chunk: int | None = None,
    coverage_target: float | None = None,
) -> int:
    """Generate a golden eval set and store it in SQLite.

    Returns the eval_set_id.
    """
    if cfg is None:
        cfg = RetrieveConfig()

    # Resolve mode from param > config > default
    eval_mode = mode or cfg.eval.mode or "sample"

    with step("eval_generate.load_corpus", corpus_dir=corpus_dir):
        console.print(f"\n[bold]Loading corpus from [cyan]{corpus_dir}[/cyan]...[/bold]")
        chunks = load_corpus_chunks(corpus_dir)
        console.print(f"  Loaded [green]{len(chunks)}[/green] chunks from corpus\n")

    if not chunks:
        console.print("[red]No chunks found. Run 'retrieve ingest' first.[/red]")
        return -1

    if questions_per_chunk is not None and mode is None:
        corpus_summary = _summarize_corpus(chunks)
        intent_map = {"intent_families": cfg.eval.categories}

        async def _legacy_run():
            try:
                return await _generate_for_batch(
                    chunks,
                    questions_per_chunk,
                    1,
                    cfg,
                    1,
                    operator_context,
                    corpus_summary,
                    intent_map,
                )
            finally:
                await stop_client()

        all_questions = run_sync(_legacy_run())
        if not all_questions:
            console.print("[red]No questions generated. Check your Copilot SDK configuration.[/red]")
            return -1

        db = RetrieveDB(cfg.db_path)
        try:
            eval_set_id = db.create_eval_set(
                version_label=version_label,
                notes=f"legacy; questions_per_chunk={questions_per_chunk}",
                build_mode="fresh" if fresh else "extend",
                steering_state={"operator_context": operator_context},
                operator_context=operator_context,
            )
            for q in all_questions:
                question_text = q.get("question", "").strip()
                if not question_text:
                    continue
                db.add_question(
                    eval_set_id=eval_set_id,
                    question_text=question_text,
                    category=q.get("category", "factual_lookup"),
                    ground_truth_chunk_ids=q.get("ground_truth_chunk_ids", []),
                    source_doc_id=q.get("source_doc_id"),
                    metadata={"reasoning": q.get("reasoning", "")},
                    answer_text=q.get("answer_text", ""),
                    question_type=q.get("question_type", q.get("category", "factual_lookup")),
                    persona="domain_user",
                    intent_family=q.get("intent_family", "general"),
                    difficulty=q.get("difficulty", "medium"),
                    expected_search_challenge=q.get("expected_search_challenge", ""),
                    evidence_summary=q.get("evidence_summary", ""),
                    status="active",
                )
            db.update_eval_set_counts(eval_set_id)
            return eval_set_id
        finally:
            db.close()

    # Compute targets based on corpus size and mode
    doc_ids = set(c.doc_id for c in chunks)
    targets = _compute_eval_targets(len(doc_ids), len(chunks), eval_mode)

    # Legacy params override if explicitly passed
    if coverage_target is not None:
        targets["coverage_target"] = coverage_target
    if questions_per_chunk is not None:
        targets["questions_per_chunk"] = questions_per_chunk

    db = RetrieveDB(cfg.db_path)
    try:
        # Merge persisted generation preferences (build-on by default)
        persisted = db.get_generation_preferences(preference_scope)
        if persisted:
            operator_context = persisted.get("operator_context", operator_context)

        with step("eval_generate.intent_map"):
            corpus_summary = _summarize_corpus(chunks)

        async def _intent_plan():
            try:
                return await _derive_intent_map_with_llm(cfg, corpus_summary, operator_context)
            except Exception:
                return {
                    "intent_families": ["definitions", "procedures", "requirements", "exceptions", "cross_references"],
                    "question_type_mix": {
                        "factual_lookup": 0.20,
                        "procedural": 0.20,
                        "cross_document": 0.15,
                        "cross_policy": 0.15,
                        "edge_case": 0.10,
                        "negation": 0.10,
                        "calculation": 0.05,
                        "unanswerable": 0.05,
                    },
                    "challenge_mix": {
                        "chunk_boundary": 0.15,
                        "semantic_mismatch": 0.15,
                        "cross_document": 0.20,
                        "negation_handling": 0.15,
                        "specificity_failure": 0.10,
                        "table_extraction": 0.10,
                        "hallucination_bait": 0.05,
                        "multi_document_reasoning": 0.10,
                    },
                    "multi_hop_focus": ["cross-document exceptions", "procedure preconditions", "requirement dependencies"],
                }
            finally:
                await stop_client()

        intent_map = run_sync(_intent_plan())

        # ── Category-group parallel generation ────────────────────────
        # Each group gets a random sample of docs (seeded, no overlap).
        # The groups differ by what categories they generate + prompt guidance.

        cat_targets = targets.get("category_targets", {})
        n_docs = len(set(c.doc_id for c in chunks))

        # Compute how many docs each group needs (1 doc per question for
        # single_doc, ≥3 docs for cross groups, a handful for unanswerable).
        single_doc_n = sum(cat_targets.get(c, 0) for c in ["factual_lookup", "procedural", "negation", "calculation", "colloquial_mapping"])
        cross_doc_n = max(3, sum(cat_targets.get(c, 0) for c in ["cross_policy", "edge_case"]))
        cross_section_n = max(3, cat_targets.get("cross_document", 2))
        unanswerable_n = max(3, cat_targets.get("unanswerable", 2))

        # Select docs per group — different seeds, exclude already-claimed docs
        # cross_doc selects first (biggest cross group), cross_section excludes those
        cross_doc_chunks = _select_docs(chunks, cross_doc_n, seed=9)
        cross_doc_docs = {c.doc_id for c in cross_doc_chunks}

        cross_section_chunks = _select_docs(chunks, cross_section_n, seed=8, exclude_docs=cross_doc_docs)
        cross_section_docs = {c.doc_id for c in cross_section_chunks}

        claimed = cross_doc_docs | cross_section_docs
        single_doc_chunks = _select_docs(chunks, single_doc_n, seed=7, exclude_docs=claimed)

        unanswerable_chunks = _select_docs(chunks, unanswerable_n, seed=10)

        # Define the 4 category groups with pre-selected chunks
        CATEGORY_GROUPS = {
            "single_doc": {
                "categories": ["factual_lookup", "procedural", "negation", "calculation", "colloquial_mapping"],
                "chunks": single_doc_chunks,
                "max_q_per_chunk": 1,
                "prompt_extra": (
                    "\nEach question must be grounded in exactly ONE chunk. "
                    "Do not generate more questions than there are chunks."
                    "\nFor colloquial_mapping questions: rephrase using informal everyday language "
                    "that does NOT match the document terminology. Test whether retrieval bridges "
                    "the vocabulary gap between how users talk and how documents are written."
                ),
            },
            "cross_doc": {
                "categories": ["cross_policy", "edge_case"],
                "chunks": cross_doc_chunks,
                "max_q_per_chunk": 2,
                "prompt_extra": (
                    "\nYou are given chunks from DIFFERENT documents."
                    "\nFor cross_policy: generate questions that require synthesizing "
                    "information across multiple documents to answer. "
                    "Each question must reference chunk IDs from ≥2 different documents."
                    "\nFor edge_case: generate questions about exceptions, boundary conditions, "
                    "and unusual scenarios that sit at the intersection of rules from "
                    "different documents. These should test multi-document retrieval."
                ),
            },
            "cross_section": {
                "categories": ["cross_document"],
                "chunks": cross_section_chunks,
                "max_q_per_chunk": 2,
                "prompt_extra": (
                    "\nYou are given multiple sections from the SAME document. "
                    "Generate questions that require combining information "
                    "from different sections to answer. Reference ≥2 chunk IDs."
                ),
            },
            "unanswerable": {
                "categories": ["unanswerable"],
                "chunks": unanswerable_chunks,
                "max_q_per_chunk": 2,
                "prompt_extra": (
                    "\nGenerate questions that these chunks CANNOT answer. The questions should "
                    "sound plausible and related to the corpus domain, but the actual answer "
                    "is not present in any of the provided chunks. Set ground_truth_chunk_ids "
                    "to an empty array [] for each question."
                ),
            },
        }

        # Filter to only groups that have targets > 0
        active_groups = {
            name: grp for name, grp in CATEGORY_GROUPS.items()
            if any(cat_targets.get(c, 0) > 0 for c in grp["categories"])
        }

        total_target = sum(cat_targets.values())
        console.print(
            f"[bold]Generating eval questions via Copilot SDK "
            f"(model: [cyan]{cfg.copilot.model}[/cyan], "
            f"mode: [cyan]{eval_mode}[/cyan], "
            f"target: [cyan]~{total_target}[/cyan] questions, "
            f"parallel groups: [cyan]{len(active_groups)}[/cyan])...[/bold]\n"
        )

        # Show category targets grouped
        for grp_name, grp in active_groups.items():
            cats = grp["categories"]
            grp_total = sum(cat_targets.get(c, 0) for c in cats)
            grp_chunks = len(grp["chunks"])
            grp_docs = len(set(c.doc_id for c in grp["chunks"]))
            cat_detail = ", ".join(f"{c}:{cat_targets.get(c, 0)}" for c in cats)
            console.print(f"  [dim]{grp_name}: {grp_total} questions, {grp_docs} docs, {grp_chunks} chunks ({cat_detail})[/dim]")
        console.print()

        emit_progress(
            "Starting parallel generation",
            stage="eval_generate",
            groups=len(active_groups),
            total_target=total_target,
            mode=eval_mode,
        )

        async def _run():
            try:
                # Build tasks — one per category group, all run in parallel
                tasks = []
                for grp_name, grp in active_groups.items():
                    tasks.append(
                        _generate_for_group(
                            group_name=grp_name,
                            categories=grp["categories"],
                            category_targets=cat_targets,
                            chunks=grp["chunks"],
                            cfg=cfg,
                            operator_context=operator_context,
                            corpus_summary=corpus_summary,
                            intent_map=intent_map,
                            system_prompt_extra=grp["prompt_extra"],
                            max_q_per_chunk=grp.get("max_q_per_chunk", 1),
                        )
                    )

                results = await asyncio.gather(*tasks, return_exceptions=True)
                merged: list[dict[str, Any]] = []
                for i, result in enumerate(results):
                    grp_name = list(active_groups.keys())[i]
                    if isinstance(result, Exception):
                        log.warning("Group %s failed: %s", grp_name, result)
                        console.print(f"  [yellow][{grp_name}] failed: {result}[/yellow]")
                    else:
                        merged.extend(result)
                return merged
            finally:
                await stop_client()

        with step("eval_generate.generate_questions", total_target=total_target):
            all_questions = run_sync(_run())

        console.print(f"\n  Generated [green]{len(all_questions)}[/green] questions total\n")

        if not all_questions:
            console.print("[red]No questions generated. Check your Copilot SDK configuration.[/red]")
            return -1

        # Semantic deduplication — remove near-duplicate questions
        from retrieve.eval.dedup import deduplicate_questions

        with step("eval_generate.semantic_dedup"):
            all_questions, removed = deduplicate_questions(all_questions, threshold=0.90)
            if removed:
                console.print(
                    f"  Removed [yellow]{len(removed)}[/yellow] near-duplicate questions "
                    f"(kept [green]{len(all_questions)}[/green])\n"
                )

        # Resolve base eval set (build-on default unless explicitly fresh)
        base_eval = None
        if not fresh:
            if base_eval_set_version == "latest":
                base_eval = db.get_latest_eval_set()
            elif base_eval_set_version:
                base_eval = db.get_eval_set_by_version(base_eval_set_version)

        notes = (
            f"mode={eval_mode}; target={targets['total_target']}; "
            f"coverage={targets['coverage_target']:.2f}; "
            f"build_on={'yes' if base_eval else 'no'}"
        )
        eval_set_id = db.create_eval_set(
            version_label=version_label,
            notes=notes,
            parent_eval_set_id=base_eval["id"] if base_eval else None,
            build_mode="fresh" if fresh else "extend",
            steering_state={"coverage_target": targets["coverage_target"], "operator_context": operator_context, "mode": eval_mode},
            operator_context=operator_context,
        )

        # Keep prior questions by default (extend behavior)
        dedup: set[tuple[str, str]] = set()
        if base_eval:
            for q in db.get_questions(base_eval["id"]):
                key = (q["question_text"].strip().lower(), q.get("answer_text", "").strip().lower())
                dedup.add(key)
                db.add_question(
                    eval_set_id=eval_set_id,
                    question_text=q["question_text"],
                    category=q["category"],
                    ground_truth_chunk_ids=q["ground_truth_chunk_ids"],
                    source_doc_id=q.get("source_doc_id"),
                    metadata=q.get("metadata"),
                    answer_text=q.get("answer_text", ""),
                    question_type=q.get("question_type", "factual_lookup"),
                    persona=q.get("persona", "domain_user"),
                    intent_family=q.get("intent_family", "general"),
                    difficulty=q.get("difficulty", "medium"),
                    expected_search_challenge=q.get("expected_search_challenge", ""),
                    evidence_summary=q.get("evidence_summary", ""),
                    status=q.get("status", "active"),
                )

        for q in all_questions:
            question_text = q.get("question", "").strip()
            answer_text = q.get("answer_text", "").strip()
            if not question_text:
                continue
            key = (question_text.lower(), answer_text.lower())
            if key in dedup:
                continue
            dedup.add(key)

            db.add_question(
                eval_set_id=eval_set_id,
                question_text=question_text,
                category=q.get("category", "factual_lookup"),
                ground_truth_chunk_ids=q.get("ground_truth_chunk_ids", []),
                source_doc_id=q.get("source_doc_id"),
                metadata={"reasoning": q.get("reasoning", "")},
                answer_text=answer_text,
                question_type=q.get("question_type", "factual_lookup"),
                persona="domain_user",
                intent_family=q.get("intent_family", "general"),
                difficulty=q.get("difficulty", "medium"),
                expected_search_challenge=q.get("expected_search_challenge", ""),
                evidence_summary=q.get("evidence_summary", ""),
                status="active",
            )

        db.update_eval_set_counts(eval_set_id)
        db.create_generation_session(
            eval_set_id=eval_set_id,
            session_type="generation",
            corpus_coverage_target=targets["coverage_target"],
            corpus_summary=corpus_summary,
            intent_map=intent_map,
            plan={"category_groups": list(active_groups.keys()), "mode": eval_mode, "total_target": total_target, "category_targets": cat_targets},
        )
        db.upsert_generation_preferences(
            {
                "operator_context": operator_context,
                "coverage_target": targets["coverage_target"],
                "build_on_default": True,
                "mode": eval_mode,
            },
            scope_key=preference_scope,
        )

        eval_set = db.get_eval_set_by_version(version_label)

        # Print summary
        console.print(f"[bold green]Eval set '{version_label}' saved[/bold green] (id={eval_set_id})")
        if eval_set:
            cats = json.loads(eval_set["category_counts"]) if isinstance(eval_set["category_counts"], str) else eval_set["category_counts"]
            console.print(f"  Total questions: [green]{eval_set['question_count']}[/green]")
            console.print("  Categories:")
            for cat, count in sorted(cats.items()):
                console.print(f"    {cat}: [cyan]{count}[/cyan]")

        return eval_set_id
    finally:
        db.close()
