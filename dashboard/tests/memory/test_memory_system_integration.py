import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dashboard.agentic_memory.memory_system import MemoryNote
from dashboard.tests.memory.helpers import DeterministicLLM, EvolvingLLM, patched_memory_system


class TestAgenticMemorySystemIntegration(unittest.TestCase):
    def test_memory_lifecycle_with_deterministic_dependencies(self):
        with patched_memory_system() as (memory_system, fake_llm):
            memory_id = memory_system.add_note("Python services and queues for background jobs")
            note = memory_system.read(memory_id)

            self.assertEqual(fake_llm.analysis_calls, 1)
            self.assertIsNotNone(note)
            self.assertEqual(note.content, "Python services and queues for background jobs")
            self.assertTrue(note.keywords)
            self.assertTrue(note.tags)

            search_results = memory_system.search_agentic("Python queues", k=3)
            self.assertEqual(search_results[0]["id"], memory_id)

            original_keywords = list(note.keywords)
            updated = memory_system.update(
                memory_id,
                content="Python APIs and workers for background jobs",
                context="Explicit update context",
            )
            updated_note = memory_system.read(memory_id)

            self.assertTrue(updated)
            self.assertEqual(updated_note.context, "Explicit update context")
            self.assertNotEqual(updated_note.keywords, original_keywords)

            raw_neighbors, neighbor_ids = memory_system.find_related_memories("Python workers", k=3)
            self.assertIn(memory_id, neighbor_ids)
            self.assertIn("memory_id:", raw_neighbors)

            self.assertTrue(memory_system.delete(memory_id))
            self.assertIsNone(memory_system.read(memory_id))
            self.assertEqual(memory_system.search_agentic("Python workers", k=3), [])

    def test_persistence_round_trip_rebuilds_backlinks(self):
        with TemporaryDirectory() as temp_dir:
            with patched_memory_system(persist_dir=temp_dir) as (memory_system, _fake_llm):
                first_id = memory_system.add_note(
                    "Docker basics for local development",
                    name="Docker Basics",
                    path="devops/containerization",
                )
                second_id = memory_system.add_note(
                    "Kubernetes service discovery patterns",
                    name="Kubernetes Services",
                    path="devops/containerization",
                )
                memory_system.add_link(first_id, second_id)

                sync_stats = memory_system.sync_to_disk()
                note_files = sorted(Path(temp_dir, "notes").rglob("*.md"))

                self.assertEqual(sync_stats["written"], 2)
                self.assertEqual(len(note_files), 2)

            with patched_memory_system(persist_dir=temp_dir) as (reloaded, _fake_llm):
                self.assertCountEqual(reloaded.memories.keys(), [first_id, second_id])
                self.assertIn(first_id, reloaded.read(second_id).backlinks)
                self.assertIn("devops", reloaded.tree())
                self.assertIn("containerization", reloaded.tree())

    def test_sync_from_disk_detects_added_updated_and_removed_notes(self):
        with TemporaryDirectory() as temp_dir:
            with patched_memory_system(persist_dir=temp_dir) as (memory_system, _fake_llm):
                kept_id = memory_system.add_note(
                    "Keep this memory in sync",
                    name="Keep Memory",
                    path="ops/sync",
                )
                removed_id = memory_system.add_note(
                    "Delete this memory from disk",
                    name="Delete Memory",
                    path="ops/sync",
                )
                memory_system.sync_to_disk()

                kept_note = memory_system.read(kept_id)
                kept_path = Path(temp_dir, "notes", kept_note.filepath)
                kept_path.write_text(
                    MemoryNote(
                        content="Updated from disk",
                        id=kept_note.id,
                        name=kept_note.name,
                        path=kept_note.path,
                        keywords=["updated", "disk", "sync"],
                        links=kept_note.links,
                        retrieval_count=kept_note.retrieval_count,
                        timestamp=kept_note.timestamp,
                        last_accessed=kept_note.last_accessed,
                        context="Disk wins",
                        evolution_history=kept_note.evolution_history,
                        category=kept_note.category,
                        tags=["disk", "sync"],
                        summary=kept_note.summary,
                    ).to_markdown(),
                    encoding="utf-8",
                )

                removed_note = memory_system.read(removed_id)
                Path(temp_dir, "notes", removed_note.filepath).unlink()

                extra_note = MemoryNote(
                    content="Added directly on disk",
                    id="disk-only-note",
                    name="Disk Only",
                    path="ops/sync",
                    keywords=["disk", "added", "sync"],
                    context="Created on disk",
                    tags=["disk", "sync"],
                )
                extra_path = Path(temp_dir, "notes", extra_note.filepath)
                extra_path.parent.mkdir(parents=True, exist_ok=True)
                extra_path.write_text(extra_note.to_markdown(), encoding="utf-8")

                sync_stats = memory_system.sync_from_disk()

                self.assertEqual(sync_stats, {"added": 1, "updated": 1, "removed": 1})
                self.assertEqual(memory_system.read(kept_id).content, "Updated from disk")
                self.assertEqual(memory_system.read(kept_id).context, "Disk wins")
                self.assertIsNone(memory_system.read(removed_id))
                self.assertIsNotNone(memory_system.read("disk-only-note"))

    def test_process_memory_applies_evolution_actions(self):
        with patched_memory_system(llm=DeterministicLLM()) as (memory_system, _fake_llm):
            first_id = memory_system.add_note("Shared domain memory about Python services")
            second_id = memory_system.add_note("Shared domain memory about Python queues")

            memory_system._completion_fn = EvolvingLLM(max_connections=1).get_completion

            candidate = MemoryNote(
                content="Shared domain bridge note for Python workers",
                keywords=["shared", "domain", "bridge"],
                context="Bridge context",
                tags=["bridge"],
            )
            memory_system.memories[candidate.id] = candidate

            evolved, processed_note = memory_system.process_memory(candidate)

            self.assertTrue(evolved)
            self.assertEqual(processed_note.tags, ["evolved", "linked"])
            self.assertEqual(len(processed_note.links), 1)
            self.assertIn(processed_note.links[0], {first_id, second_id})

            updated_neighbor = memory_system.read(processed_note.links[0])
            self.assertTrue(updated_neighbor.context.startswith("Updated context"))
            self.assertIn("updated", updated_neighbor.tags)

    def test_vector_index_rebuilt_on_startup_when_missing(self):
        """Test that vector index is rebuilt from persisted notes on startup."""
        import shutil

        with TemporaryDirectory() as temp_dir:
            # Phase 1: Create memories and persist
            with patched_memory_system(persist_dir=temp_dir) as (memory_system, _fake_llm):
                memory_id = memory_system.add_note(
                    "Python async programming with asyncio and coroutines",
                    name="Async Python",
                    path="programming/python",
                )
                memory_system.sync_to_disk()

                # Verify search works before restart
                results = memory_system.search("async programming", k=1)
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0]["id"], memory_id)

            # Phase 2: Delete vectordb but keep notes
            vectordb_path = Path(temp_dir) / "vectordb"
            if vectordb_path.exists():
                shutil.rmtree(vectordb_path)

            # Verify notes still exist but vectordb is gone
            notes_path = Path(temp_dir) / "notes"
            self.assertTrue(notes_path.exists())
            self.assertFalse(vectordb_path.exists())

            # Phase 3: Reload - vector index should be rebuilt
            with patched_memory_system(persist_dir=temp_dir) as (reloaded, _fake_llm):
                # Memories should be loaded
                self.assertEqual(len(reloaded.memories), 1)

                # Search should work (vector index rebuilt)
                results = reloaded.search("async programming", k=1)
                self.assertEqual(len(results), 1, "Search should return results after index rebuild")
                self.assertEqual(results[0]["id"], memory_id)
