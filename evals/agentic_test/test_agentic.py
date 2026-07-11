#!/usr/bin/env python3
"""
test_agentic.py — Test agentic retrieval on cross-policy eval questions.

Calls the Knowledge Base retrieve endpoint, passes grounding data to gpt-4o
for answer generation, then judges the result.

Usage:
    python test_agentic.py -g akpolicy-v2-rg -p akpolicy2
    python test_agentic.py -g akpolicy-v2-rg -p akpolicy2 --limit 5
"""

import argparse
import json
import subprocess
import sys
import time
import logging
from pathlib import Path
from collections import defaultdict

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

KNOWLEDGE_BASE = "policy-knowledge-base"
SEARCH_API_VERSION = "2025-11-01-preview"
OPENAI_API_VERSION = "2024-10-21"
IS_WINDOWS = sys.platform == "win32"

SYSTEM_PROMPT = """You are a Policy Agent designed to help caseworkers retrieve accurate policy information.
Use ONLY the grounding data provided below. Do not rely on prior knowledge.

When answering:
- Be clear and precise. Include ALL specific numbers, dollar amounts, deadlines, and exceptions.
- When a question involves multiple programs, address EACH program separately under its own heading.
- NEVER apply one program's rule to another program.
- Only include numbers and dates that appear verbatim in the grounding data.
- Cite the source ref_id or document key for each claim. Format: [ref_id:N]
- If the grounding data doesn't contain relevant information, say so.
"""

JUDGE_PROMPT = """You are an evaluation judge for a policy search system.
Score the AI-generated answer against the ground truth.

Question: {question}
Ground Truth: {ground_truth}
AI Answer: {generated_answer}
Grounding Data (first 3000 chars): {grounding_preview}

Score answer_correctness from 1-5:
5 = all key facts correct and complete
4 = all major points correct, 1-2 minor details missing
3 = core answer correct but missing several important details
2 = addresses topic but gets key facts wrong
1 = wrong, contradicts ground truth, or refuses when info was available

Do NOT penalize for extra correct information beyond the ground truth.

Respond with ONLY a JSON object:
{{"answer_correctness": N, "judge_notes": "brief explanation"}}"""


def az_json(args):
    cmd = ["az"] + args + ["-o", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True, shell=IS_WINDOWS)
    if result.returncode != 0:
        sys.exit(f"ERROR: az {' '.join(args[:4])}\n  {result.stderr.strip()}")
    return json.loads(result.stdout)


def agentic_retrieve(question: str, search_endpoint: str, search_key: str) -> dict:
    """Call the Knowledge Base retrieve endpoint."""
    url = f"{search_endpoint}/knowledgebases/{KNOWLEDGE_BASE}/retrieve?api-version={SEARCH_API_VERSION}"
    headers = {"api-key": search_key, "Content-Type": "application/json"}
    body = {
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": question}]
            }
        ],
        "includeActivity": True,
        "knowledgeSourceParams": [
            {
                "knowledgeSourceName": "policy-knowledge-source",
                "kind": "searchIndex",
                "includeReferences": True,
                "includeReferenceSourceData": True,
            }
        ]
    }
    resp = requests.post(url, headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    return resp.json()


def extract_grounding(kb_response: dict) -> str:
    """Extract the unified grounding text from the KB response."""
    for msg in kb_response.get("response", []):
        for content in msg.get("content", []):
            if content.get("type") == "text":
                return content["text"]
    return ""


def extract_activity(kb_response: dict) -> list:
    """Extract activity log for analysis."""
    return kb_response.get("activity", [])


def generate_answer(question: str, grounding: str, client: AzureOpenAI,
                    deployment: str) -> str:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Grounding data:\n\n{grounding[:15000]}\n\nQuestion: {question}"},
    ]
    resp = client.chat.completions.create(
        model=deployment, messages=messages, temperature=0,
    )
    return resp.choices[0].message.content


def judge_answer(question, ground_truth, generated, grounding, client, deployment):
    prompt = JUDGE_PROMPT.format(
        question=question, ground_truth=ground_truth,
        generated_answer=generated, grounding_preview=grounding[:3000],
    )
    resp = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    text = resp.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"answer_correctness": 0, "judge_notes": f"Parse error: {text[:200]}"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-g", "--resource-group", required=True)
    parser.add_argument("-p", "--name-prefix", default="akpolicy")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--deployment", default="gpt-4o")
    parser.add_argument("--question-ids", nargs="*", help="Specific question IDs to test")
    args = parser.parse_args()

    search_name = f"{args.name_prefix}-search"
    search_endpoint = f"https://{search_name}.search.windows.net"
    openai_account = f"{args.name_prefix}ai"

    # Get credentials
    search_key = az_json(["search", "admin-key", "show", "-g", args.resource_group,
                          "--service-name", search_name])["primaryKey"]
    openai_endpoint = az_json(["cognitiveservices", "account", "show", "-n", openai_account,
                               "-g", args.resource_group])["properties"]["endpoint"]

    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")
    client = AzureOpenAI(azure_endpoint=openai_endpoint, azure_ad_token_provider=token_provider,
                         api_version=OPENAI_API_VERSION)

    # Load cross-policy questions from eval
    questions = []
    with open("eval_questions.jsonl", "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                q = json.loads(line)
                if args.question_ids:
                    if q["question_id"] in args.question_ids:
                        questions.append(q)
                elif q["question_id"].startswith("CROSS"):
                    questions.append(q)

    if args.limit > 0:
        questions = questions[:args.limit]

    log.info("Testing %d questions via agentic retrieval", len(questions))

    # Load v2 results for comparison
    v2_by_id = {}
    if Path("eval_results_v2.jsonl").exists():
        with open("eval_results_v2.jsonl", "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    v2_by_id[r["question_id"]] = r

    results = []
    output_path = Path("eval_results_agentic.jsonl")

    with open(output_path, "w", encoding="utf-8") as out_f:
        for i, q in enumerate(questions, 1):
            qid = q["question_id"]
            question = q["question"]
            ground_truth = q["ground_truth"]

            log.info("[%d/%d] %s: %s", i, len(questions), qid, question[:80])

            # Step 1: Agentic retrieve
            try:
                kb_resp = agentic_retrieve(question, search_endpoint, search_key)
                grounding = extract_grounding(kb_resp)
                activity = extract_activity(kb_resp)
            except Exception as e:
                log.error("  Retrieval failed: %s", e)
                grounding = ""
                activity = []

            # Count sub-queries
            sub_queries = [a for a in activity if a.get("type") == "searchIndex"]
            log.info("  Agentic: %d sub-queries, %d chars grounding", len(sub_queries), len(grounding))

            # Step 2: Generate answer
            try:
                generated = generate_answer(question, grounding, client, args.deployment)
            except Exception as e:
                log.error("  Generation failed: %s", e)
                generated = f"ERROR: {e}"

            # Step 3: Judge
            try:
                scores = judge_answer(question, ground_truth, generated, grounding,
                                      client, args.deployment)
            except Exception as e:
                scores = {"answer_correctness": 0, "judge_notes": str(e)}

            corr = scores.get("answer_correctness", 0)
            v2_corr = v2_by_id.get(qid, {}).get("scores", {}).get("answer_correctness", "?")
            log.info("  Score: %s (v2 was: %s) %s", corr, v2_corr,
                     "▲" if isinstance(v2_corr, int) and corr > v2_corr else
                     "▼" if isinstance(v2_corr, int) and corr < v2_corr else "=")

            result = {
                "question_id": qid,
                "question": question,
                "question_type": q.get("question_type", ""),
                "ground_truth": ground_truth,
                "generated_answer": generated,
                "scores": scores,
                "agentic_activity": [
                    {"type": a.get("type"), "elapsed_ms": a.get("elapsedMs")}
                    for a in activity
                ],
                "sub_query_count": len(sub_queries),
                "grounding_length": len(grounding),
            }
            out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
            out_f.flush()
            results.append(result)

            time.sleep(1)

    # Summary
    log.info("=" * 60)
    log.info("AGENTIC RETRIEVAL TEST COMPLETE")
    log.info("=" * 60)
    corr_vals = [r["scores"].get("answer_correctness", 0) for r in results]
    if corr_vals:
        log.info("  Avg correctness: %.2f", sum(corr_vals) / len(corr_vals))
        for s in range(1, 6):
            log.info("    Score %d: %d", s, corr_vals.count(s))

    # Compare with v2
    if v2_by_id:
        log.info("\n  Head-to-head vs Run 2:")
        improved = degraded = same = 0
        for r in results:
            v2r = v2_by_id.get(r["question_id"])
            if v2r:
                v2c = v2r["scores"].get("answer_correctness", 0)
                ac = r["scores"].get("answer_correctness", 0)
                if ac > v2c:
                    improved += 1
                elif ac < v2c:
                    degraded += 1
                else:
                    same += 1
        log.info("    Improved: %d  Same: %d  Degraded: %d", improved, same, degraded)

    log.info("Results written to %s", output_path)


if __name__ == "__main__":
    main()
