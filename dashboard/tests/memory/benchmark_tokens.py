#!/usr/bin/env python3
"""
Benchmark: estimate LLM token usage per save_memory call.

Intercepts all LLM calls to count prompt/completion tokens.
Uses the real Gemini API — requires GOOGLE_API_KEY.

Usage:
    cd os-twin
    PYTHONPATH=. python dashboard/tests/memory/benchmark_tokens.py --notes 3
"""

import json
import os
import sys
import tempfile
import shutil
import time


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English."""
    return max(1, len(text) // 4)


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--notes", type=int, default=3)
    parser.add_argument("--persist-dir", type=str, default="")
    args = parser.parse_args()

    # Setup
    persist_dir = args.persist_dir or tempfile.mkdtemp(prefix="token-bench-")
    cleanup = not args.persist_dir

    print("=" * 70)
    print("Token Usage Benchmark for Agentic Memory")
    print("=" * 70)
    print(f"  Notes to save:  {args.notes}")
    print(f"  Persist dir:    {persist_dir}")
    print()

    # Import and init
    print("Importing agentic_memory...", flush=True)
    t0 = time.time()
    from dashboard.agentic_memory.memory_system import AgenticMemorySystem

    print(f"  Import took {time.time() - t0:.1f}s", flush=True)

    print("Initializing system...", flush=True)
    t0 = time.time()
    memory = AgenticMemorySystem(
        model_name="gemini-embedding-001",
        embedding_backend="gemini",
        vector_backend="zvec",
        llm_backend="gemini",
        llm_model="gemini-3-flash-preview",
        persist_dir=persist_dir,
        context_aware_analysis=True,
        max_links=3,
    )
    print(f"  Init took {time.time() - t0:.1f}s", flush=True)
    print(flush=True)

    # Monkey-patch LLM to intercept calls and count tokens
    call_log = []
    original_get_completion = memory.llm.get_completion

    def intercepted_get_completion(prompt, **kwargs):
        t_start = time.time()
        response = original_get_completion(prompt, **kwargs)
        elapsed = time.time() - t_start

        prompt_tokens = estimate_tokens(prompt)
        completion_tokens = estimate_tokens(response)

        call_log.append(
            {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "prompt_chars": len(prompt),
                "completion_chars": len(response),
                "elapsed_s": elapsed,
            }
        )
        return response

    memory.llm.get_completion = intercepted_get_completion

    # Also intercept embedding calls
    embed_log = []
    original_embed = memory.retriever.embedding_function

    def intercepted_embed(texts):
        for t in texts:
            embed_log.append(
                {
                    "input_tokens": estimate_tokens(t),
                    "input_chars": len(t),
                }
            )
        return original_embed(texts)

    memory.retriever.embedding_function = intercepted_embed

    # Sample contents of varying sizes
    sample_contents = [
        # Short note (~50 words)
        "Docker containers share the host kernel unlike VMs which run full OS instances. "
        "This makes containers 10-100x faster to start. Key gotcha: shared kernel means "
        "a kernel vulnerability affects all containers. Use gVisor or Kata for untrusted workloads.",
        # Medium note (~100 words)
        "PostgreSQL JSONB with GIN indexes provides efficient semi-structured data querying. "
        "We chose JSONB over separate tables because product attributes vary per category "
        "(electronics have voltage/wattage, clothing has size/material). The GIN index on "
        "products.attributes reduced catalog search from 800ms to 12ms. Important: JSONB "
        "equality checks are exact-match, so always normalize before insertion. Also, GIN "
        "indexes don't support ordering — if you need sorted results, add a btree index on "
        "the sort column. Partial GIN indexes on specific JSONB paths cut index size by 60%.",
        # Long note (~200 words)
        "OAuth 2.0 implementation decisions for the API gateway: We chose Authorization Code "
        "flow with PKCE for all clients (including mobile). Considered Implicit flow but it's "
        "deprecated in OAuth 2.1. The access token lifetime is 15 minutes with a 7-day refresh "
        "token. Refresh tokens are rotated on each use (one-time use) to prevent replay attacks. "
        "Token storage: JWTs for access tokens (stateless validation), opaque strings for refresh "
        "tokens (server-side lookup required). JWT payload includes: sub, iss, exp, iat, scope, "
        "tenant_id. We do NOT include PII in JWTs since they're base64-visible. "
        "Rate limiting: 100 req/min per access token, enforced at the gateway layer using a "
        "sliding window counter in Redis. Token revocation uses a small bloom filter (10KB) "
        "checked on each request — false positive rate of 0.1% is acceptable since it just "
        "triggers a DB lookup. The JWKS endpoint rotates keys every 90 days with a 30-day "
        "overlap period for graceful key rollover.",
    ]

    # Run benchmark
    print(
        f"{'Note':<6} {'Words':<7} {'LLM Calls':<11} {'Prompt Tok':<12} {'Compl Tok':<11} {'Total Tok':<11} {'Embed Calls':<13} {'Embed Tok':<11} {'Time':<8}"
    )
    print("-" * 100)

    total_stats = {
        "llm_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "embed_calls": 0,
        "embed_tokens": 0,
        "time": 0,
    }

    for i in range(args.notes):
        content = sample_contents[i % len(sample_contents)]
        word_count = len(content.split())

        # Clear logs
        call_log.clear()
        embed_log.clear()

        t_start = time.time()
        note_id = memory.add_note(content)
        elapsed = time.time() - t_start

        # Aggregate
        llm_calls = len(call_log)
        prompt_tok = sum(c["prompt_tokens"] for c in call_log)
        compl_tok = sum(c["completion_tokens"] for c in call_log)
        total_tok = prompt_tok + compl_tok
        embed_calls = len(embed_log)
        embed_tok = sum(e["input_tokens"] for e in embed_log)

        print(
            f"  {i + 1:<4} {word_count:<7} {llm_calls:<11} {prompt_tok:<12} {compl_tok:<11} {total_tok:<11} {embed_calls:<13} {embed_tok:<11} {elapsed:<.1f}s",
            flush=True,
        )

        total_stats["llm_calls"] += llm_calls
        total_stats["prompt_tokens"] += prompt_tok
        total_stats["completion_tokens"] += compl_tok
        total_stats["total_tokens"] += total_tok
        total_stats["embed_calls"] += embed_calls
        total_stats["embed_tokens"] += embed_tok
        total_stats["time"] += elapsed

        # Print LLM call details
        for j, c in enumerate(call_log):
            label = "analysis" if j == 0 else "evolution"
            print(
                f"         └─ {label}: prompt={c['prompt_tokens']} compl={c['completion_tokens']} ({c['elapsed_s']:.1f}s)",
                flush=True,
            )

    # Summary
    n = args.notes
    print()
    print("=" * 100)
    print(f"  TOTALS ({n} notes)")
    print(f"    LLM calls:        {total_stats['llm_calls']}  ({total_stats['llm_calls'] / n:.1f} per note)")
    print(f"    Prompt tokens:    {total_stats['prompt_tokens']}  ({total_stats['prompt_tokens'] / n:.0f} per note)")
    print(
        f"    Completion tokens:{total_stats['completion_tokens']}  ({total_stats['completion_tokens'] / n:.0f} per note)"
    )
    print(f"    Total LLM tokens: {total_stats['total_tokens']}  ({total_stats['total_tokens'] / n:.0f} per note)")
    print(f"    Embed calls:      {total_stats['embed_calls']}  ({total_stats['embed_calls'] / n:.1f} per note)")
    print(f"    Embed tokens:     {total_stats['embed_tokens']}  ({total_stats['embed_tokens'] / n:.0f} per note)")
    print(f"    Total time:       {total_stats['time']:.1f}s  ({total_stats['time'] / n:.1f}s per note)")
    print()
    print(f"  NOTE: Token counts are estimates (~4 chars/token). Actual billing may differ.")

    if cleanup:
        shutil.rmtree(persist_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
