"""Domain adaptation — fine-tuning recommendations, LoRA automation, before/after comparison.

§16 from the vision doc. Provides:
1. Corpus analysis to recommend when fine-tuning would help
2. Synthetic training data generation from corpus
3. Azure OpenAI fine-tuning job management
4. Before/after eval comparison
5. Model versioning and registry
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from retrieve.observability import emit_progress

log = logging.getLogger(__name__)
console = Console()

IS_WINDOWS = sys.platform == "win32"


# ── Domain analysis ───────────────────────────────────────────────────


def analyze_domain_specificity(corpus_dir: str) -> dict[str, Any]:
    """Analyze a corpus for domain-specific terminology and patterns.

    Returns a recommendation on whether fine-tuning would likely improve retrieval.
    """
    corpus_path = Path(corpus_dir)
    md_files = list(corpus_path.glob("**/*.md"))

    if not md_files:
        return {"recommendation": "skip", "reason": "No corpus files found"}

    # Collect vocabulary stats
    all_words: dict[str, int] = {}
    total_docs = len(md_files)
    doc_lengths = []
    acronym_count = 0
    jargon_indicators = 0

    for md_file in md_files:
        content = md_file.read_text(encoding="utf-8", errors="replace")
        # Skip YAML frontmatter
        if content.startswith("---"):
            end = content.find("---", 3)
            if end > 0:
                content = content[end + 3 :]

        doc_lengths.append(len(content))

        words = content.lower().split()
        for word in words:
            clean = word.strip(".,;:!?()[]{}\"'")
            if len(clean) > 2:
                all_words[clean] = all_words.get(clean, 0) + 1

        # Count acronyms (ALL CAPS words of 2-6 chars)
        import re

        acronyms = re.findall(r"\b[A-Z]{2,6}\b", content)
        acronym_count += len(acronyms)

        # Count section-number references (e.g., "Section 100-3", "Policy 205")
        section_refs = re.findall(
            r"\b(?:section|policy|addendum|chapter)\s+\d+[\-\w]*", content, re.IGNORECASE
        )
        jargon_indicators += len(section_refs)

    avg_doc_length = sum(doc_lengths) / len(doc_lengths) if doc_lengths else 0
    unique_terms = len(all_words)
    total_words = sum(all_words.values())

    # Heuristic: domain-specific corpus benefits from fine-tuning when:
    # - High acronym density (> 5 per doc)
    # - High jargon/reference density
    # - Large unique vocabulary relative to corpus size
    acronym_density = acronym_count / total_docs if total_docs else 0
    jargon_density = jargon_indicators / total_docs if total_docs else 0
    vocab_ratio = unique_terms / total_words if total_words else 0

    score = 0
    reasons = []

    if acronym_density > 5:
        score += 2
        reasons.append(f"High acronym density ({acronym_density:.1f}/doc)")
    elif acronym_density > 2:
        score += 1
        reasons.append(f"Moderate acronym density ({acronym_density:.1f}/doc)")

    if jargon_density > 3:
        score += 2
        reasons.append(f"Heavy cross-reference patterns ({jargon_density:.1f}/doc)")
    elif jargon_density > 1:
        score += 1
        reasons.append(f"Some cross-references ({jargon_density:.1f}/doc)")

    if vocab_ratio > 0.15:
        score += 1
        reasons.append(f"High vocabulary diversity ({vocab_ratio:.3f})")

    if total_docs > 50:
        score += 1
        reasons.append(f"Sufficient training data ({total_docs} docs)")

    if score >= 4:
        recommendation = "recommended"
    elif score >= 2:
        recommendation = "consider"
    else:
        recommendation = "skip"

    result = {
        "recommendation": recommendation,
        "score": score,
        "reasons": reasons,
        "stats": {
            "total_docs": total_docs,
            "avg_doc_length": round(avg_doc_length),
            "unique_terms": unique_terms,
            "total_words": total_words,
            "acronym_density": round(acronym_density, 2),
            "jargon_density": round(jargon_density, 2),
            "vocab_ratio": round(vocab_ratio, 4),
        },
    }

    console.print("\n[bold]Domain Analysis[/bold]")
    console.print(f"  Documents: {total_docs}")
    console.print(f"  Avg length: {avg_doc_length:.0f} chars")
    console.print(f"  Acronym density: {acronym_density:.1f}/doc")
    console.print(f"  Reference density: {jargon_density:.1f}/doc")
    recommendation_style = {
        "recommended": "green",
        "consider": "yellow",
    }.get(recommendation, "dim")
    console.print(f"  Recommendation: [{recommendation_style}]{recommendation}[/]")
    for r in reasons:
        console.print(f"    • {r}")

    return result


# ── Synthetic training data generation ────────────────────────────────


def generate_training_pairs(
    corpus_dir: str,
    output_file: str = "training_pairs.jsonl",
    ai_services_endpoint: str = "",
    llm_model: str = "gpt-4.1",
    max_pairs: int = 500,
) -> str:
    """Generate synthetic query-document pairs for embedding fine-tuning.

    Uses an LLM to generate diverse search queries for each document,
    creating (query, positive_doc, negative_doc) triples for contrastive learning.
    """
    from azure.identity import DefaultAzureCredential
    from openai import AzureOpenAI

    corpus_path = Path(corpus_dir)
    md_files = list(corpus_path.glob("**/*.md"))

    if not ai_services_endpoint:
        console.print("[red]AI Services endpoint required for training data generation[/red]")
        return ""

    credential = DefaultAzureCredential()
    token = credential.get_token("https://cognitiveservices.azure.com/.default")

    client = AzureOpenAI(
        azure_endpoint=ai_services_endpoint,
        azure_ad_token=token.token,
        api_version="2025-04-01-preview",
    )

    output_path = Path(output_file)
    pairs_written = 0

    console.print("\n[bold]Generating training pairs[/bold]")
    console.print(f"  Corpus: {len(md_files)} documents")
    console.print(f"  Target: {max_pairs} pairs")

    with output_path.open("w", encoding="utf-8") as f:
        for md_file in md_files:
            if pairs_written >= max_pairs:
                break

            content = md_file.read_text(encoding="utf-8", errors="replace")
            # Skip frontmatter
            if content.startswith("---"):
                end = content.find("---", 3)
                if end > 0:
                    content = content[end + 3 :].strip()

            if len(content) < 100:
                continue

            # Truncate very long docs for prompt
            doc_excerpt = content[:3000]

            try:
                response = client.chat.completions.create(
                    model=llm_model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Generate 3 diverse search queries that a user would type "
                                "to find this document. Include: 1) a natural language question, "
                                "2) a keyword-style query, 3) a paraphrased question using "
                                "different terminology. "
                                "Return JSON array of strings, nothing else."
                            ),
                        },
                        {"role": "user", "content": doc_excerpt},
                    ],
                    temperature=0.7,
                    max_tokens=200,
                )

                queries = json.loads(response.choices[0].message.content or "[]")
                for query in queries:
                    if isinstance(query, str) and query.strip():
                        pair = {
                            "query": query.strip(),
                            "positive": md_file.stem,
                            "document_excerpt": doc_excerpt[:500],
                        }
                        f.write(json.dumps(pair) + "\n")
                        pairs_written += 1
                        if pairs_written >= max_pairs:
                            break

            except Exception as e:
                log.warning("Failed to generate queries for %s: %s", md_file.name, e)
                continue

            if pairs_written % 50 == 0:
                console.print(f"  Generated {pairs_written}/{max_pairs} pairs...")
                emit_progress(
                    f"Training pairs: {pairs_written}/{max_pairs}",
                    stage="domain.generate_pairs",
                    completed=pairs_written,
                    total=max_pairs,
                )

    console.print(f"  [green]Generated {pairs_written} training pairs → {output_path}[/green]")
    return str(output_path)


# ── Fine-tuning job management ────────────────────────────────────────


def submit_finetune_job(
    training_file: str,
    ai_services_endpoint: str,
    base_model: str = "gpt-4o-mini-2024-07-18",
    suffix: str = "retrieve-domain",
    n_epochs: int = 3,
) -> dict[str, Any]:
    """Submit an Azure OpenAI fine-tuning job.

    Note: As of 2025, Azure OpenAI fine-tuning is only available for select models
    (GPT-4o-mini, GPT-3.5-turbo). Embedding model fine-tuning is not yet available
    on Azure. This function submits the training data for LLM fine-tuning which
    can improve query understanding and rewriting.

    For embedding fine-tuning, use the training pairs with a local PEFT/LoRA
    workflow via the Sentence Transformers library.
    """
    from azure.identity import DefaultAzureCredential
    from openai import AzureOpenAI

    credential = DefaultAzureCredential()
    token = credential.get_token("https://cognitiveservices.azure.com/.default")

    client = AzureOpenAI(
        azure_endpoint=ai_services_endpoint,
        azure_ad_token=token.token,
        api_version="2025-04-01-preview",
    )

    # Upload training file
    console.print(f"  Uploading training file: {training_file}")
    with open(training_file, "rb") as f:
        file_response = client.files.create(file=f, purpose="fine-tune")

    console.print(f"  File uploaded: {file_response.id}")

    # Create fine-tuning job
    console.print(f"  Submitting fine-tuning job (base: {base_model})...")
    job = client.fine_tuning.jobs.create(
        training_file=file_response.id,
        model=base_model,
        suffix=suffix,
        hyperparameters={"n_epochs": n_epochs},
    )

    console.print(f"  [green]Job submitted: {job.id}[/green]")
    console.print(f"  Status: {job.status}")

    emit_progress(
        f"Fine-tuning job submitted: {job.id}",
        stage="domain.finetune",
        job_id=job.id,
        status=job.status,
    )

    return {
        "job_id": job.id,
        "status": job.status,
        "model": base_model,
        "training_file_id": file_response.id,
    }


def check_finetune_status(
    job_id: str,
    ai_services_endpoint: str,
) -> dict[str, Any]:
    """Check the status of a fine-tuning job."""
    from azure.identity import DefaultAzureCredential
    from openai import AzureOpenAI

    credential = DefaultAzureCredential()
    token = credential.get_token("https://cognitiveservices.azure.com/.default")

    client = AzureOpenAI(
        azure_endpoint=ai_services_endpoint,
        azure_ad_token=token.token,
        api_version="2025-04-01-preview",
    )

    job = client.fine_tuning.jobs.retrieve(job_id)

    console.print(f"\n[bold]Fine-tuning job: {job_id}[/bold]")
    console.print(f"  Status: {job.status}")
    console.print(f"  Model: {job.model}")
    if job.fine_tuned_model:
        console.print(f"  Fine-tuned model: [green]{job.fine_tuned_model}[/green]")
    if job.trained_tokens:
        console.print(f"  Trained tokens: {job.trained_tokens}")

    return {
        "job_id": job.id,
        "status": job.status,
        "fine_tuned_model": job.fine_tuned_model,
        "trained_tokens": job.trained_tokens,
    }


# ── Before/after comparison ───────────────────────────────────────────


def compare_before_after(
    cfg: Any,
    base_run_id: str,
    finetuned_run_id: str,
) -> dict[str, Any]:
    """Compare eval results before and after domain adaptation.

    Loads two eval runs from the database and computes the delta.
    """
    from retrieve.eval.store import EvalStore

    store = EvalStore(cfg.project_root)

    base_results = store.get_run_results(base_run_id)
    tuned_results = store.get_run_results(finetuned_run_id)

    if not base_results or not tuned_results:
        console.print("[red]Could not load both eval runs[/red]")
        return {}

    base_recall = base_results.get("recall_at_10", 0)
    tuned_recall = tuned_results.get("recall_at_10", 0)
    base_mrr = base_results.get("mrr_at_10", 0)
    tuned_mrr = tuned_results.get("mrr_at_10", 0)

    delta_recall = tuned_recall - base_recall
    delta_mrr = tuned_mrr - base_mrr

    table = Table(title="Domain Adaptation: Before vs After")
    table.add_column("Metric", style="cyan")
    table.add_column("Before", justify="right")
    table.add_column("After", justify="right")
    table.add_column("Delta", justify="right")

    recall_color = "green" if delta_recall > 0 else "red"
    mrr_color = "green" if delta_mrr > 0 else "red"

    table.add_row(
        "Recall@10",
        f"{base_recall:.4f}",
        f"{tuned_recall:.4f}",
        f"[{recall_color}]{delta_recall:+.4f}[/{recall_color}]",
    )
    table.add_row(
        "MRR@10",
        f"{base_mrr:.4f}",
        f"{tuned_mrr:.4f}",
        f"[{mrr_color}]{delta_mrr:+.4f}[/{mrr_color}]",
    )

    console.print(table)

    result = {
        "base_run": base_run_id,
        "finetuned_run": finetuned_run_id,
        "base_recall": base_recall,
        "tuned_recall": tuned_recall,
        "delta_recall": delta_recall,
        "base_mrr": base_mrr,
        "tuned_mrr": tuned_mrr,
        "delta_mrr": delta_mrr,
        "improvement": delta_recall > 0.01,
    }

    if delta_recall > 0.01:
        console.print(
            f"\n[green]✓ Domain adaptation improved recall by {delta_recall:+.4f}[/green]"
        )
    elif delta_recall < -0.01:
        console.print(f"\n[red]✗ Domain adaptation decreased recall by {delta_recall:+.4f}[/red]")
    else:
        console.print(f"\n[yellow]~ Negligible change in recall ({delta_recall:+.4f})[/yellow]")

    return result
