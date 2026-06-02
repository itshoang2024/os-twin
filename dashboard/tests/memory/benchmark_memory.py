#!/usr/bin/env python3
"""
Benchmark: measure RAM usage of the Agentic Memory system.

NOTE: Run with PYTHONUNBUFFERED=1 or python -u for real-time output.

Usage:
    python benchmark_memory.py [--notes N] [--persist-dir DIR]

Measures memory at each stage:
  1. Baseline (before imports)
  2. After importing agentic_memory
  3. After initializing AgenticMemorySystem
  4. After saving N notes
  5. After searching
  6. After vector index rebuild
"""

import argparse
import os
import sys
import time
import resource
import tempfile
import shutil

# Measure baseline before any heavy imports
_baseline_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # KB on Linux


def get_rss_mb() -> float:
    """Current RSS in MB (Linux: ru_maxrss is in KB)."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def get_rss_delta_mb(baseline_kb: int) -> float:
    """Delta from baseline in MB."""
    return (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - baseline_kb) / 1024.0


def fmt(mb: float) -> str:
    return f"{mb:.1f} MB"


def print_stage(label: str, start_time: float, baseline_kb: int):
    elapsed = time.time() - start_time
    rss = get_rss_mb()
    delta = get_rss_delta_mb(baseline_kb)
    print(f"  {label:<45s}  RSS: {fmt(rss):>10s}  Δ: {fmt(delta):>10s}  ({elapsed:.2f}s)")


def main():
    parser = argparse.ArgumentParser(description="Benchmark memory system RAM usage")
    parser.add_argument("--notes", type=int, default=10, help="Number of test notes to save (default: 10)")
    parser.add_argument("--persist-dir", type=str, default="", help="Persist dir (default: temp dir)")
    parser.add_argument("--keep", action="store_true", help="Keep temp dir after benchmark")
    parser.add_argument("--skip-llm", action="store_true", help="Use mock LLM to skip API calls")
    args = parser.parse_args()

    # Setup persist dir
    if args.persist_dir:
        persist_dir = args.persist_dir
        os.makedirs(persist_dir, exist_ok=True)
        cleanup = False
    else:
        persist_dir = tempfile.mkdtemp(prefix="mem-bench-")
        cleanup = not args.keep

    print(f"Agentic Memory Benchmark")
    print(f"  Notes to save:  {args.notes}")
    print(f"  Persist dir:    {persist_dir}")
    print(f"  Skip LLM:       {args.skip_llm}")
    print(f"  Python:         {sys.executable}")
    print()

    baseline_kb = _baseline_rss
    print(f"{'Stage':<47s}  {'RSS':>10s}  {'Delta':>10s}  {'Time':>8s}")
    print("-" * 85)

    t0 = time.time()
    print_stage("1. Baseline (before imports)", t0, baseline_kb)

    # --- Stage 2: Import ---
    t = time.time()
    from dashboard.agentic_memory.memory_system import AgenticMemorySystem

    print_stage("2. After importing agentic_memory", t, baseline_kb)

    # --- Stage 3: Initialize ---
    t = time.time()
    if args.skip_llm:
        # Patch LLM to avoid API calls
        from unittest.mock import MagicMock, patch
        import json

        mock_analysis = json.dumps(
            {
                "name": "test note",
                "path": "test/benchmark",
                "keywords": ["benchmark", "test"],
                "context": "Benchmark test note",
                "tags": ["benchmark", "test"],
            }
        )
        mock_evolution = json.dumps(
            {
                "should_evolve": False,
                "actions": [],
                "suggested_connections": [],
                "tags_to_update": [],
                "new_context_neighborhood": [],
                "new_tags_neighborhood": [],
            }
        )

        # Create system then patch LLM
        memory = AgenticMemorySystem(
            model_name="gemini-embedding-001",
            embedding_backend="gemini",
            vector_backend="zvec",
            llm_backend="gemini",
            llm_model="gemini-3-flash-preview",
            persist_dir=persist_dir,
            context_aware_analysis=False,
        )
        # Mock the LLM calls
        memory.llm.get_completion = MagicMock(side_effect=[mock_analysis, mock_evolution] * (args.notes + 10))
    else:
        memory = AgenticMemorySystem(
            model_name="gemini-embedding-001",
            embedding_backend="gemini",
            vector_backend="zvec",
            llm_backend="gemini",
            llm_model="gemini-3-flash-preview",
            persist_dir=persist_dir,
            context_aware_analysis=True,
        )
    print_stage("3. After initializing system", t, baseline_kb)

    # --- Stage 4: Save notes ---
    t = time.time()
    note_ids = []
    sample_contents = [
        f"PostgreSQL JSONB indexing with GIN provides efficient semi-structured data access. "
        f"Test note number {i} covers database optimization techniques including query planning, "
        f"index selection strategies, and vacuum configuration for high-throughput OLTP workloads. "
        f"Key insight: partial indexes on JSONB paths reduce index bloat by 60% compared to full GIN."
        for i in range(args.notes)
    ]
    for i, content in enumerate(sample_contents):
        nid = memory.add_note(content)
        note_ids.append(nid)
        if (i + 1) % 5 == 0 or i == 0 or i == len(sample_contents) - 1:
            print_stage(f"4. After saving note {i + 1}/{args.notes}", t, baseline_kb)

    # --- Stage 5: Search ---
    t = time.time()
    results = memory.search("database indexing performance", k=5)
    print_stage(f"5. After search ({len(results)} results)", t, baseline_kb)

    # --- Stage 6: Vector index rebuild ---
    t = time.time()
    memory.consolidate_memories()
    print_stage("6. After vector index rebuild", t, baseline_kb)

    # --- Stage 7: Memory tree ---
    t = time.time()
    tree = memory.tree()
    print_stage("7. After tree generation", t, baseline_kb)

    # --- Summary ---
    print()
    print("=" * 85)
    final_rss = get_rss_mb()
    total_delta = get_rss_delta_mb(baseline_kb)
    total_time = time.time() - t0
    print(f"  Final RSS:      {fmt(final_rss)}")
    print(f"  Total increase: {fmt(total_delta)}")
    print(f"  Total time:     {total_time:.1f}s")
    print(f"  Notes stored:   {len(memory.memories)}")
    print(f"  Disk usage:     ", end="")
    # Check disk usage
    total_size = 0
    for dirpath, _dirnames, filenames in os.walk(persist_dir):
        for f in filenames:
            total_size += os.path.getsize(os.path.join(dirpath, f))
    print(f"{total_size / 1024:.1f} KB")

    if tree:
        print(f"\n  Memory tree:")
        for line in tree.split("\n")[:15]:
            print(f"    {line}")

    # Cleanup
    if cleanup:
        shutil.rmtree(persist_dir, ignore_errors=True)
        print(f"\n  Cleaned up {persist_dir}")


if __name__ == "__main__":
    main()
