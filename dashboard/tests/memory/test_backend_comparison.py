"""Backend Comparison: Gemini vs LiquidAI/LFM2-1.2B-Extract

Evaluates both LLM backends against the same annotated memory corpus.

Metrics:
  1. Analysis Quality   — metadata completeness + keyword/tag relevance
  2. Search Relevance   — Precision@3, Recall@3, MRR
  3. Evolution Quality   — link count + semantic link correctness
  4. Latency            — per-operation timing

Usage:
  GEMINI_API_KEY=... HF_TOKEN=... python tests/test_backend_comparison.py
"""

import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

# ══════════════════════════════════════════════════════════════════════════
#  GROUND TRUTH CORPUS
# ══════════════════════════════════════════════════════════════════════════
# Each note carries expected topics (fuzzy keyword match) and a domain tag.
# The search queries carry ground truth relevance judgments (note indices).

CORPUS = [
    # 0 — Docker
    {
        "content": (
            "Docker containers provide lightweight virtualization by sharing "
            "the host OS kernel, unlike virtual machines which need a full "
            "guest OS. Images are layered and cached for fast builds."
        ),
        "expected_topics": {"docker", "container", "virtualization", "kernel", "image"},
        "domain": "devops",
    },
    # 1 — PostgreSQL
    {
        "content": (
            "PostgreSQL supports JSONB columns which allow storing and querying "
            "semi-structured data with GIN indexing support. It outperforms "
            "document stores for mixed relational/JSON workloads."
        ),
        "expected_topics": {"postgresql", "jsonb", "index", "database", "query"},
        "domain": "database",
    },
    # 2 — Git
    {
        "content": (
            "Git rebase rewrites commit history by replaying commits on top of "
            "another branch, while merge preserves the original history. "
            "Interactive rebase lets you squash, reorder, or edit commits."
        ),
        "expected_topics": {"git", "rebase", "merge", "commit", "branch"},
        "domain": "version-control",
    },
    # 3 — Redis
    {
        "content": (
            "Redis is an in-memory data store used as cache, message broker, "
            "and session store. It supports sorted sets, pub/sub, and Lua "
            "scripting. Persistence options include RDB snapshots and AOF."
        ),
        "expected_topics": {"redis", "cache", "memory", "session", "broker"},
        "domain": "database",
    },
    # 4 — Kubernetes
    {
        "content": (
            "Kubernetes orchestrates container deployments, handling scaling, "
            "load balancing, and self-healing. Pods are the smallest deployable "
            "unit. Services expose pods via stable DNS names."
        ),
        "expected_topics": {"kubernetes", "container", "pod", "scaling", "deploy"},
        "domain": "devops",
    },
    # 5 — Transformer
    {
        "content": (
            "Transformer architecture uses self-attention to process sequences "
            "in parallel, replacing sequential RNNs. Multi-head attention "
            "captures different relationship types simultaneously."
        ),
        "expected_topics": {"transformer", "attention", "sequence", "parallel", "rnn"},
        "domain": "ml",
    },
    # 6 — RAG
    {
        "content": (
            "RAG (Retrieval Augmented Generation) combines vector search with "
            "LLM generation to reduce hallucination. Documents are chunked, "
            "embedded, and stored in a vector database for retrieval."
        ),
        "expected_topics": {"rag", "retrieval", "vector", "generation", "llm"},
        "domain": "ml",
    },
    # 7 — LoRA
    {
        "content": (
            "Fine-tuning LLMs with LoRA reduces memory by only training low-rank "
            "adapter matrices instead of the full weight matrix. QLoRA adds "
            "4-bit quantization for even lower memory usage."
        ),
        "expected_topics": {"lora", "fine-tun", "adapter", "memory", "quantiz"},
        "domain": "ml",
    },
    # 8 — CI/CD
    {
        "content": (
            "Our CI/CD pipeline uses GitHub Actions with matrix builds across "
            "Python 3.10-3.12. Docker layer caching and parallel test execution "
            "reduced build time from 15 minutes to 4 minutes."
        ),
        "expected_topics": {"ci", "pipeline", "github", "test", "docker", "build"},
        "domain": "devops",
    },
    # 9 — API gateway
    {
        "content": (
            "The API gateway enforces rate limiting at 1000 req/s per user and "
            "uses circuit breaker pattern to prevent cascade failures. "
            "JWT validation happens at the gateway before routing to services."
        ),
        "expected_topics": {"api", "gateway", "rate", "circuit", "jwt"},
        "domain": "backend",
    },
]

QUERIES = [
    {
        "text": "container orchestration and deployment",
        "relevant": {0, 4, 8},  # Docker, Kubernetes, CI/CD
    },
    {
        "text": "database storage and indexing",
        "relevant": {1, 3},  # PostgreSQL, Redis
    },
    {
        "text": "machine learning model training",
        "relevant": {5, 6, 7},  # Transformer, RAG, LoRA
    },
    {
        "text": "version control branching strategy",
        "relevant": {2},  # Git
    },
    {
        "text": "caching and performance optimization",
        "relevant": {3, 8, 9},  # Redis, CI/CD, API gateway
    },
    {
        "text": "microservices architecture patterns",
        "relevant": {4, 9},  # Kubernetes, API gateway
    },
]

# Which notes are semantically related (should ideally be linked after evolution)
EXPECTED_LINKS = [
    (0, 4),  # Docker <-> Kubernetes
    (0, 8),  # Docker <-> CI/CD (Docker layer caching)
    (1, 3),  # PostgreSQL <-> Redis (both databases)
    (5, 6),  # Transformer <-> RAG (ML)
    (5, 7),  # Transformer <-> LoRA (ML)
    (6, 7),  # RAG <-> LoRA (ML)
]


# ══════════════════════════════════════════════════════════════════════════
#  EVALUATION FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════


@dataclass
class AnalysisScore:
    """Per-note analysis quality."""

    note_idx: int
    has_name: bool = False
    has_path: bool = False
    has_keywords: bool = False
    has_tags: bool = False
    has_context: bool = False
    keyword_precision: float = 0.0
    keyword_recall: float = 0.0
    keyword_f1: float = 0.0

    @property
    def completeness(self) -> int:
        return sum(
            [
                self.has_name,
                self.has_path,
                self.has_keywords,
                self.has_tags,
                self.has_context,
            ]
        )


@dataclass
class SearchScore:
    """Per-query search quality."""

    query_idx: int
    precision_at_3: float = 0.0
    recall_at_3: float = 0.0
    mrr: float = 0.0  # Mean Reciprocal Rank


@dataclass
class BackendReport:
    """Full evaluation report for one backend."""

    name: str
    analysis_scores: List[AnalysisScore] = field(default_factory=list)
    search_scores: List[SearchScore] = field(default_factory=list)
    total_links: int = 0
    correct_links: int = 0
    add_times: List[float] = field(default_factory=list)
    search_times: List[float] = field(default_factory=list)
    init_time: float = 0.0

    # --- Aggregates ---
    @property
    def avg_completeness(self) -> float:
        if not self.analysis_scores:
            return 0.0
        return sum(s.completeness for s in self.analysis_scores) / len(self.analysis_scores)

    @property
    def avg_keyword_f1(self) -> float:
        scores = [s.keyword_f1 for s in self.analysis_scores if s.keyword_f1 > 0]
        return sum(scores) / len(scores) if scores else 0.0

    @property
    def avg_precision(self) -> float:
        if not self.search_scores:
            return 0.0
        return sum(s.precision_at_3 for s in self.search_scores) / len(self.search_scores)

    @property
    def avg_recall(self) -> float:
        if not self.search_scores:
            return 0.0
        return sum(s.recall_at_3 for s in self.search_scores) / len(self.search_scores)

    @property
    def avg_mrr(self) -> float:
        if not self.search_scores:
            return 0.0
        return sum(s.mrr for s in self.search_scores) / len(self.search_scores)

    @property
    def link_precision(self) -> float:
        return self.correct_links / max(self.total_links, 1)

    @property
    def avg_add_time(self) -> float:
        return sum(self.add_times) / len(self.add_times) if self.add_times else 0.0

    @property
    def avg_search_time(self) -> float:
        return sum(self.search_times) / len(self.search_times) if self.search_times else 0.0


def _fuzzy_topic_match(extracted: List[str], expected: Set[str]) -> Tuple[float, float, float]:
    """Compute keyword precision / recall / F1 using substring matching.

    An extracted keyword matches if any expected topic appears as a substring
    (case-insensitive).  This is intentionally lenient — "containerization"
    matches expected topic "container".
    """
    if not extracted:
        return 0.0, 0.0, 0.0

    extracted_lower = [k.lower() for k in extracted]
    expected_lower = {t.lower() for t in expected}

    # How many extracted keywords are relevant?
    hits = 0
    for kw in extracted_lower:
        if any(topic in kw or kw in topic for topic in expected_lower):
            hits += 1
    precision = hits / len(extracted_lower)

    # How many expected topics were covered?
    covered = 0
    for topic in expected_lower:
        if any(topic in kw or kw in topic for kw in extracted_lower):
            covered += 1
    recall = covered / len(expected_lower)

    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


def evaluate_analysis(note_idx: int, note, expected: dict) -> AnalysisScore:
    """Score the LLM-generated metadata for a single note."""
    score = AnalysisScore(note_idx=note_idx)
    score.has_name = bool(note.name)
    score.has_path = bool(note.path)
    score.has_keywords = len(note.keywords) >= 2
    score.has_tags = len(note.tags) >= 2
    score.has_context = bool(note.context) and note.context != "General"

    all_extracted = note.keywords + note.tags
    p, r, f1 = _fuzzy_topic_match(all_extracted, expected["expected_topics"])
    score.keyword_precision = p
    score.keyword_recall = r
    score.keyword_f1 = f1
    return score


def evaluate_search(query_idx: int, results: list, relevant: set, id_map: dict) -> SearchScore:
    """Score a single search query's results against ground truth."""
    score = SearchScore(query_idx=query_idx)
    returned_indices = set()
    first_relevant_rank = None

    for rank, r in enumerate(results[:3]):
        idx = id_map.get(r["id"])
        if idx is not None:
            returned_indices.add(idx)
            if idx in relevant and first_relevant_rank is None:
                first_relevant_rank = rank + 1

    hits = returned_indices & relevant
    score.precision_at_3 = len(hits) / min(3, len(results)) if results else 0.0
    score.recall_at_3 = len(hits) / len(relevant) if relevant else 0.0
    score.mrr = 1.0 / first_relevant_rank if first_relevant_rank else 0.0
    return score


def evaluate_links(mem_system, id_list: list) -> Tuple[int, int]:
    """Count total links and how many match EXPECTED_LINKS."""
    total = 0
    correct = 0
    for note in mem_system.memories.values():
        total += len(note.links)

    idx_by_id = {mid: idx for idx, mid in enumerate(id_list)}
    for src_idx, dst_idx in EXPECTED_LINKS:
        src_id = id_list[src_idx]
        dst_id = id_list[dst_idx]
        src_note = mem_system.read(src_id)
        if src_note and dst_id in src_note.links:
            correct += 1
        # Check reverse direction too
        dst_note = mem_system.read(dst_id)
        if dst_note and src_id in dst_note.links:
            correct += 1

    return total, correct


# ══════════════════════════════════════════════════════════════════════════
#  BACKEND RUNNER
# ══════════════════════════════════════════════════════════════════════════


def run_backend(backend_name: str, llm_backend: str, llm_model: str, **extra_kwargs) -> BackendReport:
    """Run the full evaluation pipeline for a single backend."""
    from dashboard.agentic_memory.memory_system import AgenticMemorySystem

    report = BackendReport(name=backend_name)
    persist_dir = tempfile.mkdtemp(prefix=f"amem_cmp_{llm_backend}_")

    # --- Initialize ---
    print(f"\n  Initializing {backend_name}...")
    t0 = time.time()
    mem = AgenticMemorySystem(
        model_name="all-MiniLM-L6-v2",
        embedding_backend="sentence-transformer",
        vector_backend="zvec",
        llm_backend=llm_backend,
        llm_model=llm_model,
        persist_dir=persist_dir,
        context_aware_analysis=False,
        max_links=3,
        **extra_kwargs,
    )
    report.init_time = time.time() - t0
    print(f"  Initialized in {report.init_time:.1f}s")

    # --- Add notes ---
    id_list = []
    for i, entry in enumerate(CORPUS):
        t0 = time.time()
        try:
            mid = mem.add_note(entry["content"])
        except Exception as e:
            elapsed = time.time() - t0
            print(f"    [{i}] +{elapsed:5.1f}s  [ERROR] {e}")
            import uuid as _uuid

            mid = str(_uuid.uuid4())
            report.add_times.append(elapsed)
            id_list.append(mid)
            continue
        elapsed = time.time() - t0
        report.add_times.append(elapsed)
        id_list.append(mid)

        note = mem.read(mid)
        if note is None:
            print(f"    [{i}] +{elapsed:5.1f}s  [WARN] note not found after add")
            continue
        print(
            f"    [{i}] +{elapsed:5.1f}s  name={str(note.name):<30s}  "
            f"kw={len(note.keywords)}  tags={len(note.tags)}  "
            f"links={len(note.links)}"
        )

    # --- Evaluate analysis ---
    for i, mid in enumerate(id_list):
        note = mem.read(mid)
        if note is None:
            report.analysis_scores.append(AnalysisScore(note_idx=i))
            continue
        score = evaluate_analysis(i, note, CORPUS[i])
        report.analysis_scores.append(score)

    # --- Search ---
    id_map = {mid: idx for idx, mid in enumerate(id_list)}
    for qi, q in enumerate(QUERIES):
        t0 = time.time()
        results = mem.search(q["text"], k=3)
        elapsed = time.time() - t0
        report.search_times.append(elapsed)

        score = evaluate_search(qi, results, q["relevant"], id_map)
        report.search_scores.append(score)

    # --- Evolution / links ---
    report.total_links, report.correct_links = evaluate_links(mem, id_list)

    # Cleanup
    shutil.rmtree(persist_dir, ignore_errors=True)
    return report


# ══════════════════════════════════════════════════════════════════════════
#  REPORTING
# ══════════════════════════════════════════════════════════════════════════


def _bar(value: float, width: int = 20) -> str:
    filled = int(value * width)
    return "[" + "#" * filled + "." * (width - filled) + "]"


def print_comparison(reports: List[BackendReport]):
    W = 72
    print(f"\n{'=' * W}")
    print("  BACKEND COMPARISON RESULTS")
    print(f"{'=' * W}")

    # --- Header ---
    labels = [r.name for r in reports]
    col = 22
    header = f"  {'Metric':<28s}"
    for lab in labels:
        header += f"{lab:>{col}s}"
    print(f"\n{header}")
    print(f"  {'-' * 28}" + f"{'-' * col}" * len(reports))

    def _row(label, values, fmt=".2f"):
        line = f"  {label:<28s}"
        for v in values:
            formatted = f"{v:{fmt}}" if isinstance(v, float) else str(v)
            line += f"{formatted:>{col}s}"
        print(line)

    # --- Analysis Quality ---
    print(f"\n  {'ANALYSIS QUALITY':^{28 + col * len(reports)}s}")
    _row("Completeness (0-5)", [r.avg_completeness for r in reports])
    _row("Keyword+Tag F1", [r.avg_keyword_f1 for r in reports])

    # Per-field breakdown
    for field_name, attr in [
        ("  has name", "has_name"),
        ("  has path", "has_path"),
        ("  has keywords (>=2)", "has_keywords"),
        ("  has tags (>=2)", "has_tags"),
        ("  has context", "has_context"),
    ]:
        vals = []
        for r in reports:
            count = sum(1 for s in r.analysis_scores if getattr(s, attr))
            vals.append(f"{count}/{len(r.analysis_scores)}")
        line = f"  {field_name:<28s}"
        for v in vals:
            line += f"{v:>{col}s}"
        print(line)

    # --- Search Relevance ---
    print(f"\n  {'SEARCH RELEVANCE':^{28 + col * len(reports)}s}")
    _row("Precision@3", [r.avg_precision for r in reports])
    _row("Recall@3", [r.avg_recall for r in reports])
    _row("MRR", [r.avg_mrr for r in reports])

    # Per-query breakdown
    for qi, q in enumerate(QUERIES):
        query_short = q["text"][:35]
        vals_p = [r.search_scores[qi].precision_at_3 for r in reports]
        vals_r = [r.search_scores[qi].recall_at_3 for r in reports]
        line = f'    Q{qi}: "{query_short}"'
        print(line)
        _row(f"      P@3 / R@3", [f"{p:.2f} / {rc:.2f}" for p, rc in zip(vals_p, vals_r)], fmt="s")

    # --- Evolution ---
    print(f"\n  {'EVOLUTION QUALITY':^{28 + col * len(reports)}s}")
    _row("Total links created", [r.total_links for r in reports], fmt="d")
    _row("Correct links (of expected)", [r.correct_links for r in reports], fmt="d")
    _row("Expected link pairs", [len(EXPECTED_LINKS)] * len(reports), fmt="d")

    # --- Latency ---
    print(f"\n  {'LATENCY':^{28 + col * len(reports)}s}")
    _row("Init time (s)", [r.init_time for r in reports], fmt=".1f")
    _row("Avg add_note (s)", [r.avg_add_time for r in reports], fmt=".1f")
    _row("Total add time (s)", [sum(r.add_times) for r in reports], fmt=".1f")
    _row("Avg search (s)", [r.avg_search_time for r in reports], fmt=".3f")

    # --- Visual bars ---
    print(f"\n  {'VISUAL SUMMARY':^{28 + col * len(reports)}s}")
    metrics = [
        ("Analysis F1", [r.avg_keyword_f1 for r in reports]),
        ("Search P@3", [r.avg_precision for r in reports]),
        ("Search MRR", [r.avg_mrr for r in reports]),
    ]
    for label, vals in metrics:
        line = f"  {label:<16s}"
        for i, v in enumerate(vals):
            line += f"  {labels[i][:10]:>10s} {_bar(v)} {v:.0%}"
        print(line)

    # --- Verdict ---
    print(f"\n{'=' * W}")
    gemini = reports[0]
    hf = reports[1]
    wins_g, wins_h = 0, 0
    comparisons = [
        ("Analysis F1", gemini.avg_keyword_f1, hf.avg_keyword_f1),
        ("Search P@3", gemini.avg_precision, hf.avg_precision),
        ("Search MRR", gemini.avg_mrr, hf.avg_mrr),
        ("Completeness", gemini.avg_completeness, hf.avg_completeness),
    ]
    for label, g, h in comparisons:
        if g > h + 0.01:
            wins_g += 1
        elif h > g + 0.01:
            wins_h += 1
    print(f"  {gemini.name} wins {wins_g} metrics, {hf.name} wins {wins_h} metrics")

    cost_note = "  Note: Gemini uses cloud API (cost per token), LFM2 runs locally (free after download)."
    print(cost_note)
    print(f"{'=' * W}\n")


# ══════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 72)
    print("  Backend Comparison: Gemini vs LFM2-1.2B-Extract")
    print(f"  Corpus: {len(CORPUS)} notes, {len(QUERIES)} queries, {len(EXPECTED_LINKS)} expected link pairs")
    print("=" * 72)

    reports = []

    # --- Gemini ---
    print(f"\n{'─' * 72}")
    print("  BACKEND 1: Gemini (gemini-3.1-flash-lite-preview)")
    print(f"{'─' * 72}")
    try:
        r_gemini = run_backend(
            backend_name="Gemini-flash-lite",
            llm_backend="gemini",
            llm_model="gemini-3.1-flash-lite-preview",
        )
        reports.append(r_gemini)
    except Exception as e:
        print(f"  [ERROR] Gemini backend failed: {e}")
        # Create an empty report so comparison can still run
        reports.append(BackendReport(name="Gemini-flash-lite"))

    # --- HuggingFace LFM2 ---
    print(f"\n{'─' * 72}")
    print("  BACKEND 2: LiquidAI/LFM2-1.2B-Extract (local)")
    print(f"{'─' * 72}")
    try:
        r_hf = run_backend(
            backend_name="LFM2-1.2B",
            llm_backend="huggingface",
            llm_model="LiquidAI/LFM2-1.2B-Extract",
        )
        reports.append(r_hf)
    except Exception as e:
        print(f"  [ERROR] HuggingFace backend failed: {e}")
        reports.append(BackendReport(name="LFM2-1.2B"))

    # --- Comparison ---
    if len(reports) == 2:
        print_comparison(reports)
    else:
        print("\n  [SKIP] Cannot compare — one or both backends failed.")
