"""Live E2E test — uses real Copilot CLI + real Alaska policy corpus."""

import asyncio
import json
import sys
import time
from pathlib import Path

# Add the source to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from retrieve.config import RetrieveConfig
from retrieve.copilot import get_client, stop_client
from retrieve.db import RetrieveDB
from retrieve.eval.chunks import load_corpus_chunks
from retrieve.eval.metrics import compute_scores, aggregate_scores


async def run_live_test():
    cfg = RetrieveConfig()
    cfg.db_path = "e2e_live_test.db"
    results = {"steps": [], "errors": []}

    # ── Step 1: Verify corpus ─────────────────────────────────────────
    print("\n=== Step 1: Load corpus ===")
    policies_dir = str(Path(__file__).parent.parent / "policies")
    chunks = load_corpus_chunks(policies_dir)
    print(f"  Loaded {len(chunks)} chunks from {policies_dir}")
    results["steps"].append({"step": "load_corpus", "chunks": len(chunks), "status": "pass"})

    if not chunks:
        print("  ERROR: No chunks. Run ingestion first.")
        results["errors"].append("No chunks found")
        return results

    # ── Step 2: Test Copilot CLI connection ────────────────────────────
    print("\n=== Step 2: Test Copilot CLI ===")
    try:
        client = await get_client(cfg.copilot)
        print("  Copilot CLI started successfully")
        results["steps"].append({"step": "copilot_connect", "status": "pass"})
    except Exception as e:
        print(f"  ERROR: {e}")
        results["errors"].append(f"Copilot connection failed: {e}")
        results["steps"].append({"step": "copilot_connect", "status": "fail", "error": str(e)})
        return results

    # ── Step 3: Generate questions for 3 chunks ───────────────────────
    print("\n=== Step 3: Generate eval questions (3 chunks) ===")
    from copilot import PermissionHandler

    system_msg = (
        "You are an evaluation question generator. Given a document chunk, "
        "generate 2 realistic questions a caseworker would ask. "
        "Return JSON: {\"questions\": [{\"question\": \"...\", "
        "\"category\": \"direct_lookup|process_procedure|eligibility|cross_document|edge_cases\", "
        "\"ground_truth_chunk_ids\": [\"...\"], \"reasoning\": \"...\"}]}"
    )

    session_config = {
        "model": cfg.copilot.model,
        "on_permission_request": PermissionHandler.approve_all,
        "system_message": {"content": system_msg},
    }

    all_questions = []
    sample_chunks = chunks[:3]

    try:
        async with await client.create_session(**session_config) as session:
            for i, chunk in enumerate(sample_chunks):
                print(f"  Chunk {i+1}/3: {chunk.chunk_id} ({chunk.doc_title[:40]})")
                prompt = (
                    f"Chunk ID: {chunk.chunk_id}\n"
                    f"Document: {chunk.doc_title}\n\n"
                    f"Content:\n{chunk.content[:1500]}\n\n"
                    f"Return ONLY a JSON object."
                )

                start = time.perf_counter()
                response = await session.send_and_wait(prompt, timeout=60)
                elapsed = (time.perf_counter() - start) * 1000

                if response and response.data and response.data.content:
                    raw = response.data.content
                    print(f"    Response: {len(raw)} chars in {elapsed:.0f}ms")

                    # Parse JSON
                    try:
                        if "```json" in raw:
                            s = raw.index("```json") + 7
                            e = raw.index("```", s)
                            raw = raw[s:e]
                        elif "```" in raw:
                            s = raw.index("```") + 3
                            e = raw.index("```", s)
                            raw = raw[s:e]

                        data = json.loads(raw.strip())
                        qs = data.get("questions", [])
                        print(f"    Parsed {len(qs)} questions")
                        for q in qs:
                            q["source_doc_id"] = chunk.doc_id
                            if chunk.chunk_id not in q.get("ground_truth_chunk_ids", []):
                                q.setdefault("ground_truth_chunk_ids", []).append(chunk.chunk_id)
                            print(f"      [{q.get('category', '?')}] {q.get('question', '?')[:60]}")
                        all_questions.extend(qs)
                    except (json.JSONDecodeError, ValueError) as e:
                        print(f"    JSON parse error: {e}")
                        print(f"    Raw: {raw[:200]}")
                        results["errors"].append(f"JSON parse for {chunk.chunk_id}: {e}")
                else:
                    print(f"    No response")
                    results["errors"].append(f"No response for {chunk.chunk_id}")

        results["steps"].append({
            "step": "generate_questions",
            "chunks_processed": len(sample_chunks),
            "questions_generated": len(all_questions),
            "status": "pass" if all_questions else "fail",
        })
        print(f"\n  Total questions generated: {len(all_questions)}")

    except Exception as e:
        print(f"  ERROR during generation: {e}")
        results["errors"].append(f"Generation failed: {e}")
        results["steps"].append({"step": "generate_questions", "status": "fail", "error": str(e)})

    # ── Step 4: Store in SQLite ───────────────────────────────────────
    print("\n=== Step 4: Store eval set in SQLite ===")
    db = RetrieveDB(cfg.db_path)
    try:
        eval_set_id = db.create_eval_set("live-test-v1", notes="E2E live test with real Copilot CLI")
        for q in all_questions:
            db.add_question(
                eval_set_id,
                q.get("question", ""),
                q.get("category", "direct_lookup"),
                q.get("ground_truth_chunk_ids", []),
                q.get("source_doc_id"),
            )
        db.update_eval_set_counts(eval_set_id)
        es = db.get_eval_set_by_version("live-test-v1")
        print(f"  Eval set stored: {es['question_count']} questions")
        cats = json.loads(es["category_counts"]) if isinstance(es["category_counts"], str) else es["category_counts"]
        for cat, count in sorted(cats.items()):
            print(f"    {cat}: {count}")
        results["steps"].append({
            "step": "store_eval_set",
            "question_count": es["question_count"],
            "categories": cats,
            "status": "pass",
        })
    except Exception as e:
        print(f"  ERROR: {e}")
        results["errors"].append(f"SQLite storage failed: {e}")
    finally:
        db.close()

    # ── Step 5: SOTA path recommendation ──────────────────────────────
    print("\n=== Step 5: SOTA path recommendation ===")
    from retrieve.registry.sota_paths import recommend_sota_path
    path = recommend_sota_path(doc_count=305, avg_doc_length=3567, cross_ref_density=3.3)
    if path:
        print(f"  Recommended: {path.name}")
        print(f"  Base architecture: {path.base_architecture}")
        print(f"  Components: {[c.name for c in path.components]}")
        results["steps"].append({"step": "sota_recommendation", "path": path.name, "status": "pass"})
    else:
        print("  No recommendation")
        results["steps"].append({"step": "sota_recommendation", "status": "fail"})

    # ── Cleanup ───────────────────────────────────────────────────────
    await stop_client()

    # ── Summary ───────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("E2E LIVE TEST SUMMARY")
    print("=" * 60)
    passed = sum(1 for s in results["steps"] if s.get("status") == "pass")
    failed = sum(1 for s in results["steps"] if s.get("status") == "fail")
    print(f"  Steps: {passed} passed, {failed} failed")
    print(f"  Errors: {len(results['errors'])}")
    for err in results["errors"]:
        print(f"    - {err}")

    return results


if __name__ == "__main__":
    results = asyncio.run(run_live_test())

    # Save results
    with open("e2e_live_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Results saved to e2e_live_results.json")
