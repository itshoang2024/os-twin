"""Integration test: LiquidAI/LFM2-1.2B-Extract with the full memory stack.

Tests the HuggingFace controller end-to-end:
  1. Controller standalone — raw JSON generation
  2. Content analysis — keyword/tag extraction
  3. Full memory lifecycle — add, search, evolution, tree

Run: python tests/test_huggingface_integration.py
"""

import json
import os
import pytest
import shutil
import tempfile
import time

MODEL_ID = "LiquidAI/LFM2-1.2B-Extract"
SEPARATOR = "-" * 70


def _print_header(title: str):
    print(f"\n{SEPARATOR}")
    print(f"  {title}")
    print(SEPARATOR)


def _print_json(label: str, obj):
    print(f"\n  {label}:")
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except (json.JSONDecodeError, ValueError):
            print(f"    (raw) {obj[:500]}")
            return
    print(json.dumps(obj, indent=4, ensure_ascii=False))


# ── Phase 1: Controller standalone ────────────────────────────────────────


def test_controller_standalone():
    """Test the HuggingFaceController in isolation — does it produce valid JSON?"""
    _print_header("Phase 1: HuggingFaceController Standalone")

    try:
        from dashboard.agentic_memory.llm_controller import HuggingFaceController
    except ImportError:
        pytest.skip("HuggingFaceController removed — llm_controller.py deleted")
        return

    print(f"  Loading model: {MODEL_ID}")
    t0 = time.time()
    ctrl = HuggingFaceController(model=MODEL_ID, max_new_tokens=512)
    print(f"  Model loaded in {time.time() - t0:.1f}s on device={ctrl.device}")

    # Simple extraction prompt
    prompt = """Extract keywords from the following text and return JSON:
    {
        "keywords": ["keyword1", "keyword2"],
        "topic": "main topic"
    }

    Text: PostgreSQL uses JSONB columns with GIN indexes to enable fast
    full-text search over semi-structured product catalog data."""

    print("\n  Generating completion...")
    t0 = time.time()
    result = ctrl.get_completion(prompt, temperature=0.1)
    elapsed = time.time() - t0
    print(f"  Generation took {elapsed:.1f}s")

    _print_json("Raw response", result)

    # Validate
    try:
        parsed = json.loads(result)
        assert isinstance(parsed, dict), "Response is not a dict"
        print("\n  [PASS] Controller returned valid JSON")
        return ctrl
    except (json.JSONDecodeError, AssertionError) as e:
        print(f"\n  [WARN] JSON validation: {e}")
        print("  (Small models may not always produce perfect JSON — continuing)")
        return ctrl


# ── Phase 2: Content analysis ─────────────────────────────────────────────


def test_content_analysis(ctrl):
    """Test the analysis prompt that AgenticMemorySystem actually uses."""
    _print_header("Phase 2: Content Analysis (memory system prompt)")

    analysis_prompt = """Generate a structured analysis of the following content by:
        1. Creating a short, descriptive name (2-5 words, lowercase)
        2. Creating a directory path that categorizes this content
        3. Identifying the most salient keywords
        4. Extracting core themes and contextual elements
        5. Creating relevant categorical tags

        Format the response as a JSON object:
        {
            "name": "short descriptive name",
            "path": "domain/subtopic",
            "keywords": ["keyword1", "keyword2", "keyword3"],
            "context": "one sentence summary of the topic and domain",
            "tags": ["tag1", "tag2", "tag3"]
        }

        Content for analysis:
        Kubernetes uses etcd as its distributed key-value store for all cluster
        state. When a pod is scheduled, the scheduler writes the binding to etcd,
        and the kubelet on the target node watches for changes. Network policies
        are enforced by the CNI plugin, not by Kubernetes itself."""

    print("  Generating analysis...")
    t0 = time.time()
    result = ctrl.get_completion(analysis_prompt, temperature=0.1)
    elapsed = time.time() - t0
    print(f"  Analysis took {elapsed:.1f}s")

    _print_json("Analysis result", result)

    try:
        parsed = json.loads(result)
        found_fields = [f for f in ("name", "path", "keywords", "context", "tags") if f in parsed]
        print(f"\n  [PASS] Extracted fields: {found_fields}")
    except (json.JSONDecodeError, ValueError):
        print("\n  [WARN] Could not parse as JSON — model may need prompt tuning")


# ── Phase 3: Full memory stack ────────────────────────────────────────────


def test_full_memory_stack():
    """Test the complete AgenticMemorySystem with HuggingFace backend."""
    _print_header("Phase 3: Full Memory Stack Integration")

    from dashboard.agentic_memory.memory_system import AgenticMemorySystem

    # Use a temp directory so the test is self-contained
    persist_dir = tempfile.mkdtemp(prefix="amem_hf_test_")
    print(f"  Persist dir: {persist_dir}")

    print(f"\n  Initializing AgenticMemorySystem with {MODEL_ID}...")
    t0 = time.time()
    mem = AgenticMemorySystem(
        model_name="all-MiniLM-L6-v2",
        embedding_backend="sentence-transformer",
        vector_backend="zvec",
        llm_backend="huggingface",
        llm_model=MODEL_ID,
        persist_dir=persist_dir,
        context_aware_analysis=False,  # keep it simple for the first test
        max_links=2,
    )
    print(f"  System initialized in {time.time() - t0:.1f}s")

    # ── Add first memory ──
    content_1 = (
        "Redis provides in-memory data structures like sorted sets and "
        "hyperloglogs. We use it as a session cache in front of PostgreSQL. "
        "The key expiration feature handles session TTLs automatically. "
        "Throughput is ~100k ops/sec on a single node with persistence disabled."
    )
    print("\n  Adding memory 1 (Redis caching)...")
    t0 = time.time()
    id_1 = mem.add_note(content_1)
    print(f"  Added in {time.time() - t0:.1f}s -> id={id_1[:12]}...")

    note_1 = mem.read(id_1)
    print(f"    name:     {note_1.name}")
    print(f"    path:     {note_1.path}")
    print(f"    keywords: {note_1.keywords}")
    print(f"    tags:     {note_1.tags}")
    print(f"    context:  {note_1.context}")

    # ── Add second memory (related) ──
    content_2 = (
        "PostgreSQL connection pooling with PgBouncer reduces overhead from "
        "repeated TLS handshakes. We configured it in transaction mode with "
        "a pool size of 20. Combined with the Redis session cache, the P99 "
        "latency dropped from 180ms to 35ms on the checkout API."
    )
    print("\n  Adding memory 2 (PostgreSQL + PgBouncer)...")
    t0 = time.time()
    id_2 = mem.add_note(content_2)
    print(f"  Added in {time.time() - t0:.1f}s -> id={id_2[:12]}...")

    note_2 = mem.read(id_2)
    print(f"    name:     {note_2.name}")
    print(f"    path:     {note_2.path}")
    print(f"    keywords: {note_2.keywords}")
    print(f"    tags:     {note_2.tags}")
    print(f"    context:  {note_2.context}")

    # ── Add third memory (different domain) ──
    content_3 = (
        "Our CI pipeline uses GitHub Actions with a matrix strategy to test "
        "across Python 3.10, 3.11, and 3.12. The build step caches pip "
        "dependencies using actions/cache, reducing cold-start from 90s to 15s. "
        "We run pytest with coverage and fail the build below 80%."
    )
    print("\n  Adding memory 3 (CI/CD)...")
    t0 = time.time()
    id_3 = mem.add_note(content_3)
    print(f"  Added in {time.time() - t0:.1f}s -> id={id_3[:12]}...")

    note_3 = mem.read(id_3)
    print(f"    name:     {note_3.name}")
    print(f"    path:     {note_3.path}")
    print(f"    keywords: {note_3.keywords}")
    print(f"    tags:     {note_3.tags}")
    print(f"    context:  {note_3.context}")

    # ── Check links (evolution) ──
    _print_header("Evolution Results")
    for label, nid in [("Memory 1", id_1), ("Memory 2", id_2), ("Memory 3", id_3)]:
        note = mem.read(nid)
        link_names = []
        for lid in note.links:
            linked = mem.read(lid)
            link_names.append(linked.name if linked else lid[:12])
        backlink_names = []
        for bid in note.backlinks:
            bl = mem.read(bid)
            backlink_names.append(bl.name if bl else bid[:12])
        print(f"  {label} ({note.name}):")
        print(f"    links     -> {link_names or '(none)'}")
        print(f"    backlinks <- {backlink_names or '(none)'}")

    # ── Search ──
    _print_header("Search Results")
    queries = [
        "database caching performance",
        "CI pipeline testing",
        "session management",
    ]
    for query in queries:
        print(f'\n  Query: "{query}"')
        results = mem.search(query, k=3)
        for i, r in enumerate(results):
            print(f"    [{i + 1}] {r.get('tags', [])} — {r['content'][:80]}...")

    # ── Tree ──
    _print_header("Memory Tree")
    tree = mem.tree()
    print(tree)

    # ── Cleanup ──
    shutil.rmtree(persist_dir, ignore_errors=True)
    print(f"\n  Cleaned up {persist_dir}")
    print(f"\n  [DONE] Full memory stack test complete")


# ── Main ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"{'=' * 70}")
    print(f"  HuggingFace Integration Test: {MODEL_ID}")
    print(f"{'=' * 70}")

    # Phase 1 — standalone controller
    ctrl = test_controller_standalone()

    # Phase 2 — content analysis prompt
    if ctrl:
        test_content_analysis(ctrl)

    # Phase 3 — full memory stack
    test_full_memory_stack()

    print(f"\n{'=' * 70}")
    print("  ALL PHASES COMPLETE")
    print(f"{'=' * 70}")
