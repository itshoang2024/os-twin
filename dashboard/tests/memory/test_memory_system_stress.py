import unittest

from dashboard.tests.memory.helpers import patched_memory_system


class TestAgenticMemorySystemStress(unittest.TestCase):
    def test_bulk_operations_keep_state_consistent(self):
        total_notes = 150

        with patched_memory_system() as (memory_system, fake_llm):
            memory_ids = []
            for index in range(total_notes):
                memory_ids.append(
                    memory_system.add_note(f"Load test memory {index} about Python services queues workers")
                )

            self.assertEqual(len(memory_system.memories), total_notes)
            self.assertEqual(fake_llm.analysis_calls, total_notes)

            for index in range(0, total_notes, 10):
                memory_system.update(
                    memory_ids[index],
                    content=f"Updated load test memory {index} about Python pipelines workers",
                )

            for index in range(1, 30):
                memory_system.add_link(memory_ids[index - 1], memory_ids[index])

            results = memory_system.search_agentic("Python pipelines workers", k=10)
            self.assertGreaterEqual(len(results), 5)

            removed_ids = set()
            for index in range(0, total_notes, 3):
                removed_ids.add(memory_ids[index])
                memory_system.delete(memory_ids[index])

            memory_system.consolidate_memories()
            remaining_ids = set(memory_system.memories.keys())

            self.assertEqual(len(remaining_ids), total_notes - len(removed_ids))
            self.assertTrue(removed_ids.isdisjoint(remaining_ids))

            search_ids = {item["id"] for item in memory_system.search_agentic("Python services", k=50)}
            self.assertTrue(search_ids.issubset(remaining_ids))

            for note in memory_system.memories.values():
                self.assertTrue(set(note.links).issubset(remaining_ids))
                self.assertTrue(set(note.backlinks).issubset(remaining_ids))
