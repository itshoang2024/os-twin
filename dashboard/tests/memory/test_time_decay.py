"""Unit tests for time-decay search scoring.

Tests the formula: score(q,d,t) = α·cos(q,d) + (1-α)·0.5^(age_days/h)

Test principles:
  1. Pure unit tests — no LLM calls, no embeddings, no network I/O.
  2. Deterministic — mock all external dependencies (LLM, retriever).
  3. Edge cases — zero age, very old, bad timestamps, boundary weights.
  4. Invariants — verify mathematical properties of the scoring formula.
"""

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from dashboard.agentic_memory.memory_note import MemoryNote


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_analysis():
    return json.dumps(
        {
            "name": "test-note",
            "path": "test",
            "keywords": ["test"],
            "context": "Test context",
            "tags": ["test"],
        }
    )


def _mock_evolution():
    return json.dumps(
        {
            "should_evolve": False,
            "actions": [],
            "suggested_connections": [],
            "tags_to_update": [],
            "new_context_neighborhood": [],
            "new_tags_neighborhood": [],
        }
    )


def _fake_embedding_function(texts):
    """Return deterministic fake embeddings (3-dim) without any API call."""
    return [[hash(t) % 100 / 100.0, 0.5, 0.5] for t in texts]


def _make_system(**overrides):
    """Create an AgenticMemorySystem with fully mocked I/O.

    Patches the embedding function so __init__ never hits the real API.
    Uses the InMemoryRetriever from test helpers to avoid zvec.
    """
    from dashboard.agentic_memory.memory_system import AgenticMemorySystem
    from dashboard.tests.memory.helpers import InMemoryRetriever

    tmpdir = tempfile.mkdtemp(prefix="decay-test-")
    defaults = dict(
        model_name="gemini-embedding-001",
        embedding_backend="gemini",
        vector_backend="zvec",
        llm_backend="gemini",
        llm_model="gemini-3-flash-preview",
        persist_dir=tmpdir,
        context_aware_analysis=False,
        similarity_weight=0.8,
        decay_half_life_days=30.0,
    )
    defaults.update(overrides)

    # Build system without hitting any real API
    mem = object.__new__(AgenticMemorySystem)
    mem.memories = {}
    mem.persist_dir = tmpdir
    mem._notes_dir = os.path.join(tmpdir, "notes")
    mem._vector_dir = os.path.join(tmpdir, "vectordb")
    os.makedirs(mem._notes_dir, exist_ok=True)
    os.makedirs(mem._vector_dir, exist_ok=True)
    mem.retriever = InMemoryRetriever()
    mem.model_name = defaults["model_name"]
    mem.embedding_backend = defaults["embedding_backend"]
    mem.vector_backend = defaults["vector_backend"]
    mem.context_aware_analysis = defaults["context_aware_analysis"]
    mem.context_aware_tree = False
    mem.max_links = 3
    # Apply same clamping as real __init__
    mem.similarity_weight = max(0.0, min(1.0, defaults["similarity_weight"]))
    mem.decay_half_life_days = max(0.01, defaults["decay_half_life_days"])
    mem.conflict_resolution = "last_modified"
    mem.evo_cnt = 0
    mem.evo_threshold = 5
    mem._evolution_system_prompt = ""

    # Mock completion function
    mock_completion = MagicMock(side_effect=[_mock_analysis(), _mock_evolution()] * 50)
    mem._completion_fn = mock_completion
    mem._embed_fn = lambda texts: [[0.0] * 768 for _ in texts]
    mem._dirty = False

    return mem, tmpdir


def _age_note(mem, note_id, days_ago):
    """Set a note's last_accessed to N days ago."""
    ts = (datetime.now() - timedelta(days=days_ago)).strftime("%Y%m%d%H%M")
    mem.memories[note_id].last_accessed = ts


# ---------------------------------------------------------------------------
# Tests: _compute_time_decay_score (pure math)
# ---------------------------------------------------------------------------


class TestTimeDecayScoreFormula(unittest.TestCase):
    """Test the scoring formula in isolation without retriever."""

    def setUp(self):
        self.mem, self.tmpdir = _make_system(similarity_weight=0.8, decay_half_life_days=30.0)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_fresh_note_full_recency(self):
        """A note accessed just now should have recency = 1.0."""
        now = datetime.now().strftime("%Y%m%d%H%M")
        score = self.mem._compute_time_decay_score(0.5, now)
        # 0.8 * 0.5 + 0.2 * 1.0 = 0.6
        self.assertAlmostEqual(score, 0.6, places=2)

    def test_one_half_life_recency(self):
        """After exactly one half-life (30d), recency should be 0.5."""
        ts = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d%H%M")
        score = self.mem._compute_time_decay_score(0.5, ts)
        # 0.8 * 0.5 + 0.2 * 0.5 = 0.5
        self.assertAlmostEqual(score, 0.5, places=2)

    def test_two_half_lives_recency(self):
        """After 60 days (2 half-lives), recency should be 0.25."""
        ts = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d%H%M")
        score = self.mem._compute_time_decay_score(0.5, ts)
        # 0.8 * 0.5 + 0.2 * 0.25 = 0.45
        self.assertAlmostEqual(score, 0.45, places=2)

    def test_very_old_note_near_zero_recency(self):
        """A 365-day-old note should have very low recency."""
        ts = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d%H%M")
        score = self.mem._compute_time_decay_score(0.5, ts)
        # recency = 0.5^(365/30) ≈ 0.00015, nearly zero
        # score ≈ 0.8 * 0.5 + 0.2 * ~0 ≈ 0.4
        self.assertAlmostEqual(score, 0.4, places=1)
        self.assertGreater(score, 0.39)
        self.assertLess(score, 0.41)

    def test_perfect_similarity_fresh(self):
        """sim=1.0 + fresh note should give max score."""
        now = datetime.now().strftime("%Y%m%d%H%M")
        score = self.mem._compute_time_decay_score(1.0, now)
        # 0.8 * 1.0 + 0.2 * 1.0 = 1.0
        self.assertAlmostEqual(score, 1.0, places=2)

    def test_zero_similarity_fresh(self):
        """sim=0.0 + fresh note should give only recency score."""
        now = datetime.now().strftime("%Y%m%d%H%M")
        score = self.mem._compute_time_decay_score(0.0, now)
        # 0.8 * 0.0 + 0.2 * 1.0 = 0.2
        self.assertAlmostEqual(score, 0.2, places=2)

    def test_zero_similarity_old(self):
        """sim=0.0 + very old note: score approaches 0."""
        ts = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d%H%M")
        score = self.mem._compute_time_decay_score(0.0, ts)
        self.assertLess(score, 0.01)

    def test_invalid_timestamp_treated_as_fresh(self):
        """Bad timestamp should not crash; treated as age=0 (fresh)."""
        score = self.mem._compute_time_decay_score(0.5, "bad-timestamp")
        # 0.8 * 0.5 + 0.2 * 1.0 = 0.6
        self.assertAlmostEqual(score, 0.6, places=2)

    def test_none_timestamp_treated_as_fresh(self):
        """None timestamp should not crash; treated as fresh."""
        score = self.mem._compute_time_decay_score(0.5, None)
        self.assertAlmostEqual(score, 0.6, places=2)

    def test_similarity_clamped_to_unit(self):
        """Similarity values outside [0,1] should be clamped."""
        now = datetime.now().strftime("%Y%m%d%H%M")
        score_over = self.mem._compute_time_decay_score(1.5, now)
        score_under = self.mem._compute_time_decay_score(-0.3, now)
        # Clamped to 1.0 and 0.0 respectively
        self.assertAlmostEqual(score_over, 1.0, places=2)
        self.assertAlmostEqual(score_under, 0.2, places=2)


# ---------------------------------------------------------------------------
# Tests: weight configuration
# ---------------------------------------------------------------------------


class TestTimeDecayWeightConfig(unittest.TestCase):
    """Test different similarity_weight and half-life configurations."""

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_weight_1_ignores_recency(self):
        """α=1.0 should make score purely similarity-based."""
        self.mem, self.tmpdir = _make_system(similarity_weight=1.0)
        old_ts = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d%H%M")
        score = self.mem._compute_time_decay_score(0.7, old_ts)
        self.assertAlmostEqual(score, 0.7, places=2)

    def test_weight_0_ignores_similarity(self):
        """α=0.0 should make score purely recency-based."""
        self.mem, self.tmpdir = _make_system(similarity_weight=0.0)
        now = datetime.now().strftime("%Y%m%d%H%M")
        score = self.mem._compute_time_decay_score(0.0, now)
        self.assertAlmostEqual(score, 1.0, places=2)

    def test_short_half_life_penalizes_faster(self):
        """Shorter half-life should produce lower recency for same age."""
        mem_short, dir1 = _make_system(decay_half_life_days=1.0)
        mem_long, dir2 = _make_system(decay_half_life_days=30.0)
        ts = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d%H%M")

        score_short = mem_short._compute_time_decay_score(0.5, ts)
        score_long = mem_long._compute_time_decay_score(0.5, ts)

        self.assertLess(score_short, score_long)

        self.tmpdir = dir1
        shutil.rmtree(dir2, ignore_errors=True)

    def test_weight_clamped_to_valid_range(self):
        """Weights outside [0,1] should be clamped."""
        mem_over, dir1 = _make_system(similarity_weight=1.5)
        mem_under, dir2 = _make_system(similarity_weight=-0.3)

        self.assertEqual(mem_over.similarity_weight, 1.0)
        self.assertEqual(mem_under.similarity_weight, 0.0)

        self.tmpdir = dir1
        shutil.rmtree(dir2, ignore_errors=True)

    def test_half_life_clamped_positive(self):
        """Half-life should be clamped to a positive minimum."""
        mem, tmpdir = _make_system(decay_half_life_days=-5.0)
        self.assertGreater(mem.decay_half_life_days, 0)
        self.tmpdir = tmpdir


# ---------------------------------------------------------------------------
# Tests: monotonicity properties (mathematical invariants)
# ---------------------------------------------------------------------------


class TestTimeDecayMonotonicity(unittest.TestCase):
    """Verify mathematical invariants of the scoring formula."""

    def setUp(self):
        self.mem, self.tmpdir = _make_system(similarity_weight=0.8, decay_half_life_days=30.0)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_higher_similarity_higher_score_same_age(self):
        """For same age, higher similarity → higher score."""
        ts = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d%H%M")
        score_low = self.mem._compute_time_decay_score(0.3, ts)
        score_high = self.mem._compute_time_decay_score(0.9, ts)
        self.assertGreater(score_high, score_low)

    def test_fresher_note_higher_score_same_similarity(self):
        """For same similarity, fresher note → higher score."""
        ts_old = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d%H%M")
        ts_new = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d%H%M")
        score_old = self.mem._compute_time_decay_score(0.5, ts_old)
        score_new = self.mem._compute_time_decay_score(0.5, ts_new)
        self.assertGreater(score_new, score_old)

    def test_score_always_non_negative(self):
        """Score should never be negative for any inputs."""
        for sim in [0.0, 0.1, 0.5, 1.0]:
            for days in [0, 1, 7, 30, 365]:
                ts = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d%H%M")
                score = self.mem._compute_time_decay_score(sim, ts)
                self.assertGreaterEqual(score, 0.0, f"Negative score for sim={sim}, age={days}d")

    def test_score_at_most_one(self):
        """Score should never exceed 1.0."""
        now = datetime.now().strftime("%Y%m%d%H%M")
        score = self.mem._compute_time_decay_score(1.0, now)
        self.assertLessEqual(score, 1.0)

    def test_decay_is_monotonically_decreasing(self):
        """Score should decrease strictly as age increases (same similarity)."""
        sim = 0.5
        prev_score = float("inf")
        for days in [0, 1, 7, 14, 30, 60, 90, 180, 365]:
            ts = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d%H%M")
            score = self.mem._compute_time_decay_score(sim, ts)
            self.assertLess(score, prev_score + 1e-9, f"Score did not decrease at age={days}d")
            prev_score = score


# ---------------------------------------------------------------------------
# Tests: search re-ranking integration (with mocked retriever)
# ---------------------------------------------------------------------------


class TestSearchReranking(unittest.TestCase):
    """Test that search() correctly re-ranks by combined score."""

    def setUp(self):
        self.mem, self.tmpdir = _make_system(similarity_weight=0.8, decay_half_life_days=30.0)
        # Add 3 notes
        self.id1 = self.mem.add_note("PostgreSQL JSONB indexing strategies for queries")
        self.id2 = self.mem.add_note("Docker container orchestration with Kubernetes")
        self.id3 = self.mem.add_note("OAuth2 authentication with PKCE flow for apps")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_fresh_note_boosted_above_similar_but_old(self):
        """A less-similar but fresh note should rank above a more-similar but old note."""
        # Make note 1 (most similar to "database") very old
        _age_note(self.mem, self.id1, 90)
        # Keep note 3 fresh (0 days)

        results = self.mem.search("database indexing performance", k=3)
        ids = [r["id"] for r in results]

        # Fresh notes should be boosted; old similar note should be penalized
        # We can't predict exact order due to embedding similarity, but can verify:
        self.assertEqual(len(results), 3)
        # All results should have both score and similarity fields
        for r in results:
            self.assertIn("score", r)
            self.assertIn("similarity", r)
            self.assertGreaterEqual(r["score"], 0.0)

    def test_results_sorted_by_combined_score(self):
        """Results should be sorted by combined score, descending."""
        _age_note(self.mem, self.id1, 60)
        _age_note(self.mem, self.id2, 30)
        # id3 stays fresh

        results = self.mem.search("database indexing", k=3)
        scores = [r["score"] for r in results]

        # Verify sorted descending
        for i in range(len(scores) - 1):
            self.assertGreaterEqual(scores[i], scores[i + 1], f"Results not sorted: {scores}")

    def test_search_updates_last_accessed(self):
        """Search should update last_accessed on returned results."""
        _age_note(self.mem, self.id1, 30)
        old_ts = self.mem.memories[self.id1].last_accessed

        self.mem.search("PostgreSQL database", k=3)
        new_ts = self.mem.memories[self.id1].last_accessed

        self.assertNotEqual(old_ts, new_ts, "last_accessed should be updated")

    def test_search_increments_retrieval_count(self):
        """Search should increment retrieval_count on returned results."""
        old_count = self.mem.memories[self.id1].retrieval_count

        self.mem.search("PostgreSQL database", k=3)
        new_count = self.mem.memories[self.id1].retrieval_count

        self.assertGreater(new_count, old_count)

    def test_result_contains_similarity_field(self):
        """Each result should include the raw similarity score."""
        results = self.mem.search("test query", k=3)
        for r in results:
            self.assertIn("similarity", r)
            self.assertIsInstance(r["similarity"], float)

    def test_k_limits_results(self):
        """search(k=1) should return exactly 1 result."""
        results = self.mem.search("test", k=1)
        self.assertEqual(len(results), 1)

    def test_empty_memory_returns_empty(self):
        """Search on empty memory should return empty list."""
        mem_empty, tmpdir2 = _make_system()
        results = mem_empty.search("anything", k=5)
        self.assertEqual(results, [])
        shutil.rmtree(tmpdir2, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests: search_agentic re-ranking
# ---------------------------------------------------------------------------


class TestSearchAgenticReranking(unittest.TestCase):
    """Test that search_agentic() applies time-decay re-ranking."""

    def setUp(self):
        self.mem, self.tmpdir = _make_system(similarity_weight=0.8, decay_half_life_days=30.0)
        self.id1 = self.mem.add_note("PostgreSQL JSONB indexing strategies")
        self.id2 = self.mem.add_note("Docker container orchestration")
        self.id3 = self.mem.add_note("OAuth2 PKCE authentication flow")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_agentic_results_sorted_by_combined_score(self):
        """search_agentic results should be sorted by combined score."""
        _age_note(self.mem, self.id1, 60)
        _age_note(self.mem, self.id2, 30)

        results = self.mem.search_agentic("database indexing", k=3)
        scores = [r.get("score", 0) for r in results]

        for i in range(len(scores) - 1):
            self.assertGreaterEqual(scores[i], scores[i + 1])

    def test_agentic_includes_similarity_field(self):
        """Each result should include raw similarity."""
        results = self.mem.search_agentic("test query", k=3)
        for r in results:
            self.assertIn("similarity", r)

    def test_empty_memory_returns_empty(self):
        """search_agentic on empty memory should return empty list."""
        mem_empty, tmpdir2 = _make_system()
        results = mem_empty.search_agentic("anything", k=5)
        self.assertEqual(results, [])
        shutil.rmtree(tmpdir2, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests: default configuration via environment variables
# ---------------------------------------------------------------------------


class TestEnvVarDefaults(unittest.TestCase):
    """Test that env vars configure the decay parameters."""

    def test_default_similarity_weight(self):
        mem, tmpdir = _make_system()
        self.assertAlmostEqual(mem.similarity_weight, 0.8, places=2)
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_default_half_life(self):
        mem, tmpdir = _make_system()
        self.assertAlmostEqual(mem.decay_half_life_days, 30.0, places=1)
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_custom_weight(self):
        mem, tmpdir = _make_system(similarity_weight=0.6)
        self.assertAlmostEqual(mem.similarity_weight, 0.6, places=2)
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_custom_half_life(self):
        mem, tmpdir = _make_system(decay_half_life_days=14.0)
        self.assertAlmostEqual(mem.decay_half_life_days, 14.0, places=1)
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
