import unittest

from dashboard.agentic_memory.memory_system import MemoryNote


class TestMemoryNote(unittest.TestCase):
    def test_filepath_slugifies_name_and_path(self):
        note = MemoryNote(
            content="Container orchestration basics",
            name="Container Orchestration Basics!",
            path="DevOps/Kubernetes Guides",
        )

        self.assertEqual(
            note.filepath,
            "devops/kubernetes-guides/container-orchestration-basics.md",
        )

    def test_markdown_round_trip_preserves_metadata(self):
        original = MemoryNote(
            content="Persist this memory",
            id="note-123",
            name="Persist Note",
            path="knowledge/testing",
            keywords=["persist", "memory", "testing"],
            links=["note-456"],
            retrieval_count=7,
            timestamp="202604041200",
            last_accessed="202604041210",
            context="Persistence test",
            evolution_history=["created", "reviewed"],
            category="reference",
            tags=["testing", "integration"],
            summary="Short summary",
        )

        restored = MemoryNote.from_markdown(original.to_markdown())

        self.assertEqual(restored.id, original.id)
        self.assertEqual(restored.name, original.name)
        self.assertEqual(restored.path, original.path)
        self.assertEqual(restored.content, original.content)
        self.assertEqual(restored.keywords, original.keywords)
        self.assertEqual(restored.links, original.links)
        self.assertEqual(restored.retrieval_count, original.retrieval_count)
        self.assertEqual(restored.context, original.context)
        self.assertEqual(restored.evolution_history, original.evolution_history)
        self.assertEqual(restored.category, original.category)
        self.assertEqual(restored.tags, original.tags)
        self.assertEqual(restored.summary, original.summary)
