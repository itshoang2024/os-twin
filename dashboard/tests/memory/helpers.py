import json
import re
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from dashboard.agentic_memory.memory_system import AgenticMemorySystem


_STOP_WORDS = {
    "a",
    "an",
    "and",
    "about",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


def tokenize(text: str) -> list[str]:
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return [token for token in normalized.split() if token and token not in _STOP_WORDS]


def _build_analysis_payload(content: str, wants_summary: bool) -> dict:
    tokens = tokenize(content)
    keywords = list(dict.fromkeys(tokens[:4])) or ["memory", "note", "general"]
    tags = list(dict.fromkeys(tokens[:2] + ["test"]))[:3]
    words = [word.lower() for word in content.split()[:3]]
    if not words:
        words = ["memory", "note"]
    if len(words) == 1:
        words.append("note")

    payload = {
        "name": " ".join(words),
        "path": f"knowledge/{keywords[0]}",
        "keywords": keywords[:3],
        "context": f"Context for {' '.join(words)}",
        "tags": tags,
    }
    if wants_summary:
        payload["summary"] = " ".join(content.split()[:20])
    return payload


class DeterministicLLM:
    def __init__(self):
        self.analysis_calls = 0
        self.evolution_calls = 0

    def get_completion(self, prompt: str, response_format: dict | None = None, temperature: float = 1.0) -> str:
        del temperature
        schema = ((response_format or {}).get("json_schema") or {}).get("schema", {})
        properties = schema.get("properties", {})

        if "should_evolve" in properties:
            self.evolution_calls += 1
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

        self.analysis_calls += 1
        if "Content for analysis:" in prompt:
            content = prompt.split("Content for analysis:", 1)[1].strip()
        else:
            content = prompt
        return json.dumps(_build_analysis_payload(content, wants_summary="summary" in properties))


class EvolvingLLM(DeterministicLLM):
    def __init__(self, max_connections: int = 1):
        super().__init__()
        self.max_connections = max_connections

    def get_completion(self, prompt: str, response_format: dict | None = None, temperature: float = 1.0) -> str:
        schema = ((response_format or {}).get("json_schema") or {}).get("schema", {})
        properties = schema.get("properties", {})
        if "should_evolve" not in properties:
            return super().get_completion(prompt, response_format, temperature)

        self.evolution_calls += 1
        memory_ids = [match.strip() for match in re.findall(r"memory_id:([^\t\n]+)", prompt)]
        should_evolve = bool(memory_ids)
        return json.dumps(
            {
                "should_evolve": should_evolve,
                "actions": ["strengthen", "update_neighbor"] if should_evolve else [],
                "suggested_connections": memory_ids[: self.max_connections],
                "tags_to_update": ["evolved", "linked"] if should_evolve else [],
                "new_context_neighborhood": [f"Updated context {index}" for index in range(1, len(memory_ids) + 1)],
                "new_tags_neighborhood": [[f"neighbor-{index}", "updated"] for index in range(1, len(memory_ids) + 1)],
            }
        )


class InMemoryRetriever:
    def __init__(
        self,
        collection_name: str = "memories",
        model_name: str = "microsoft/harrier-oss-v1-270m",
        persist_dir: str | None = None,
        embedding_backend: str = "sentence-transformer",
        embed_fn=None,
    ):
        del collection_name, model_name, persist_dir, embedding_backend, embed_fn
        self._documents: dict[str, dict] = {}
        self.client = SimpleNamespace(reset=lambda: None)

    def add_document(self, document: str, metadata: dict, doc_id: str):
        self._documents[doc_id] = {
            "document": document,
            "metadata": deepcopy(metadata),
        }

    def clear(self):
        self._documents.clear()

    def has_document(self, doc_id: str) -> bool:
        return doc_id in self._documents

    def existing_ids(self, doc_ids: list[str]) -> set:
        return {did for did in doc_ids if did in self._documents}

    def get_stored_hashes(self, doc_ids: list[str]) -> dict[str, str | None]:
        out: dict[str, str | None] = {}
        for did in doc_ids:
            if did in self._documents:
                meta = self._documents[did].get("metadata", {})
                out[did] = meta.get("content_hash")
        return out

    def delete_document(self, doc_id: str):
        self._documents.pop(doc_id, None)

    def search(self, query: str, k: int = 5) -> dict:
        query_tokens = set(tokenize(query))
        ranked = []

        for doc_id, payload in self._documents.items():
            metadata = payload["metadata"]
            haystack_parts = [
                payload["document"],
                metadata.get("context", ""),
                " ".join(metadata.get("keywords", [])),
                " ".join(metadata.get("tags", [])),
            ]
            haystack = " ".join(part for part in haystack_parts if part).lower()
            doc_tokens = set(tokenize(haystack))
            overlap = len(query_tokens & doc_tokens)
            substring_bonus = 1 if query.lower() and query.lower() in haystack else 0
            score = overlap * 10 + substring_bonus

            # Assign a small baseline score to non-matching docs so
            # this retriever behaves like vector search (always returns
            # k nearest neighbors, even with low similarity).
            if score <= 0:
                score = 0.01

            ranked.append((score, doc_id, deepcopy(metadata)))

        ranked.sort(key=lambda item: (-item[0], item[1]))
        ranked = ranked[:k]

        # Normalize scores to 0.0-1.0 range (cosine-like) so time-decay
        # tests get float similarity values instead of raw integer counts.
        max_score = ranked[0][0] if ranked else 1
        max_score = max(max_score, 1)  # avoid div-by-zero

        return {
            "ids": [[item[1] for item in ranked]],
            "metadatas": [[item[2] for item in ranked]],
            "distances": [[float(item[0]) / max_score for item in ranked]],
        }


@contextmanager
def patched_memory_system(llm: DeterministicLLM | None = None, **kwargs):
    fake_llm = llm or DeterministicLLM()

    def _dummy_embed(texts):
        """Return zero vectors — tests use InMemoryRetriever which ignores embeddings.

        Must match EMBEDDING_DIMENSION (1024) so zvec collections accept
        these vectors when rebuilding from disk.
        """
        try:
            from dashboard.agentic_memory.retrievers import EMBEDDING_DIMENSION

            dim = EMBEDDING_DIMENSION
        except ImportError:
            dim = 1024
        return [[0.0] * dim for _ in texts]

    with (
        patch("dashboard.agentic_memory.memory_system.ZvecRetriever", new=InMemoryRetriever),
    ):
        # Inject completion_fn and embed_fn directly — no gateway needed.
        system = AgenticMemorySystem(
            completion_fn=fake_llm.get_completion,
            embed_fn=_dummy_embed,
            **kwargs,
        )
        yield system, fake_llm
