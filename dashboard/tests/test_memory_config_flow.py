"""Unit tests for the Memory Panel → config.json → memory system config flow.

Covers:
  - MemorySettings / KnowledgeSettings field preservation (models.py)
  - Resolver backward compat (embedding_provider → embedding_backend)
  - AI gateway compatible_url / compatible_key resolution (ai/__init__.py)
  - create_client base_url passthrough (llm_client.py)
  - BaseLLMWrapper base_url / api_key passthrough (llm_wrapper.py)
  - agentic_memory config extraction of compatible fields (dashboard/agentic_memory/config.py)
  - MemoryLLM compatible settings resolution (memory_llm.py)
  - KnowledgeLLM compatible settings resolution (knowledge/llm.py)

These tests protect the commit that wired LLM/embedding config from the
frontend MemoryPanel through to the backend dashboard.agentic_memory system.
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from dashboard.models import MemorySettings, KnowledgeSettings


# ═══════════════════════════════════════════════════════════════════════════════
# 1. MemorySettings / KnowledgeSettings — field preservation
# ═══════════════════════════════════════════════════════════════════════════════

class TestMemorySettingsFields:
    """All new fields must survive _safe_model() filtering in the resolver."""

    def test_llm_backend_preserved(self):
        ms = MemorySettings(llm_backend="ollama")
        assert ms.llm_backend == "ollama"

    def test_llm_model_preserved(self):
        ms = MemorySettings(llm_model="llama3.2")
        assert ms.llm_model == "llama3.2"

    def test_llm_compatible_url_preserved(self):
        ms = MemorySettings(llm_compatible_url="http://my-server:8080/v1")
        assert ms.llm_compatible_url == "http://my-server:8080/v1"

    def test_llm_compatible_key_preserved(self):
        ms = MemorySettings(llm_compatible_key="sk-test-123")
        assert ms.llm_compatible_key == "sk-test-123"

    def test_embedding_backend_preserved(self):
        ms = MemorySettings(embedding_backend="openai-compatible")
        assert ms.embedding_backend == "openai-compatible"

    def test_embedding_model_preserved(self):
        ms = MemorySettings(embedding_model="text-embedding-3-small")
        assert ms.embedding_model == "text-embedding-3-small"

    def test_embedding_compatible_url_preserved(self):
        ms = MemorySettings(embedding_compatible_url="http://embed:8080/v1")
        assert ms.embedding_compatible_url == "http://embed:8080/v1"

    def test_embedding_compatible_key_preserved(self):
        ms = MemorySettings(embedding_compatible_key="sk-embed-key")
        assert ms.embedding_compatible_key == "sk-embed-key"

    def test_legacy_embedding_provider_preserved(self):
        ms = MemorySettings(embedding_provider="ollama")
        assert ms.embedding_provider == "ollama"

    def test_extra_fields_allowed(self):
        """ConfigDict(extra='allow') must not strip unknown fields."""
        ms = MemorySettings(llm_backend="ollama", future_field="hello")
        assert ms.future_field == "hello"

    def test_all_defaults_are_empty_strings(self):
        """LLM/embedding fields default to empty strings (no override)."""
        ms = MemorySettings()
        for field_name in (
            "llm_backend", "llm_model", "llm_compatible_url", "llm_compatible_key",
            "embedding_backend", "embedding_model", "embedding_compatible_url",
            "embedding_compatible_key", "embedding_provider",
        ):
            assert getattr(ms, field_name) == "", f"{field_name} should default to ''"

    def test_model_dump_includes_all_new_fields(self):
        ms = MemorySettings(llm_backend="ollama", embedding_compatible_url="http://x")
        dumped = ms.model_dump()
        assert dumped["llm_backend"] == "ollama"
        assert dumped["embedding_compatible_url"] == "http://x"


class TestKnowledgeSettingsFields:
    """All new compatible fields must survive _safe_model() filtering."""

    def test_llm_compatible_url_preserved(self):
        ks = KnowledgeSettings(knowledge_llm_compatible_url="http://llm:8080/v1")
        assert ks.knowledge_llm_compatible_url == "http://llm:8080/v1"

    def test_llm_compatible_key_preserved(self):
        ks = KnowledgeSettings(knowledge_llm_compatible_key="sk-llm")
        assert ks.knowledge_llm_compatible_key == "sk-llm"

    def test_embedding_compatible_url_preserved(self):
        ks = KnowledgeSettings(knowledge_embedding_compatible_url="http://embed:8080/v1")
        assert ks.knowledge_embedding_compatible_url == "http://embed:8080/v1"

    def test_embedding_compatible_key_preserved(self):
        ks = KnowledgeSettings(knowledge_embedding_compatible_key="sk-embed")
        assert ks.knowledge_embedding_compatible_key == "sk-embed"

    def test_extra_fields_allowed(self):
        ks = KnowledgeSettings(future_param="yes")
        assert ks.future_param == "yes"

    def test_llm_backend_and_model_preserved(self):
        ks = KnowledgeSettings(knowledge_llm_backend="openai-compatible", knowledge_llm_model="my-llm")
        assert ks.knowledge_llm_backend == "openai-compatible"
        assert ks.knowledge_llm_model == "my-llm"

    def test_embedding_backend_and_model_preserved(self):
        ks = KnowledgeSettings(knowledge_embedding_backend="ollama", knowledge_embedding_model="nomic")
        assert ks.knowledge_embedding_backend == "ollama"
        assert ks.knowledge_embedding_model == "nomic"

    def test_dimension_overridden_by_env(self):
        """knowledge_embedding_dimension is always overridden from env default."""
        ks = KnowledgeSettings(knowledge_embedding_dimension=999)
        from dashboard.llm_client import DEFAULT_EMBEDDING_DIMENSION
        assert ks.knowledge_embedding_dimension == DEFAULT_EMBEDDING_DIMENSION


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Resolver backward compat (embedding_provider → embedding_backend)
# ═══════════════════════════════════════════════════════════════════════════════

class TestResolverBackwardCompat:
    """Legacy embedding_provider must be mapped to embedding_backend."""

    @pytest.fixture
    def temp_project(self, tmp_path):
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir()
        (agents_dir / "config.json").write_text(json.dumps({}))
        return tmp_path

    @pytest.fixture
    def resolver(self, temp_project):
        from dashboard.lib.settings.resolver import SettingsResolver
        config_path = temp_project / ".agents" / "config.json"
        with patch("dashboard.lib.settings.resolver.AGENTS_DIR", temp_project / ".agents"), \
             patch("dashboard.lib.settings.resolver.PROJECT_ROOT", temp_project):
            r = SettingsResolver(config_path=config_path)
            r.vault = MagicMock()
            r.vault.get.return_value = None
            yield r

    def test_embedding_provider_mapped_to_embedding_backend(self, resolver, temp_project):
        """When only embedding_provider is set, _extract_memory maps it to embedding_backend."""
        config = {
            "memory": {
                "embedding_provider": "ollama",
            }
        }
        (temp_project / ".agents" / "config.json").write_text(json.dumps(config))
        resolver._cache = None  # invalidate cache

        master = resolver.get_master_settings()
        assert master.memory.embedding_backend == "ollama"

    def test_embedding_backend_wins_over_provider(self, resolver, temp_project):
        """When both are set, embedding_backend takes precedence."""
        config = {
            "memory": {
                "embedding_provider": "ollama",
                "embedding_backend": "openai-compatible",
            }
        }
        (temp_project / ".agents" / "config.json").write_text(json.dumps(config))
        resolver._cache = None

        master = resolver.get_master_settings()
        assert master.memory.embedding_backend == "openai-compatible"

    def test_llm_fields_survive_resolver(self, resolver, temp_project):
        """LLM fields must survive _safe_model() filtering."""
        config = {
            "memory": {
                "llm_backend": "ollama",
                "llm_model": "llama3.2",
                "llm_compatible_url": "http://my-server:8080/v1",
                "llm_compatible_key": "sk-test-key",
            }
        }
        (temp_project / ".agents" / "config.json").write_text(json.dumps(config))
        resolver._cache = None

        master = resolver.get_master_settings()
        assert master.memory.llm_backend == "ollama"
        assert master.memory.llm_model == "llama3.2"
        assert master.memory.llm_compatible_url == "http://my-server:8080/v1"
        assert master.memory.llm_compatible_key == "sk-test-key"

    def test_embedding_fields_survive_resolver(self, resolver, temp_project):
        """Embedding compatible fields must survive _safe_model() filtering."""
        config = {
            "memory": {
                "embedding_backend": "openai-compatible",
                "embedding_compatible_url": "http://embed:8080/v1",
                "embedding_compatible_key": "sk-embed-key",
            }
        }
        (temp_project / ".agents" / "config.json").write_text(json.dumps(config))
        resolver._cache = None

        master = resolver.get_master_settings()
        assert master.memory.embedding_backend == "openai-compatible"
        assert master.memory.embedding_compatible_url == "http://embed:8080/v1"
        assert master.memory.embedding_compatible_key == "sk-embed-key"

    def test_knowledge_fields_survive_resolver(self, resolver, temp_project):
        """Knowledge compatible fields must survive _safe_model() filtering."""
        config = {
            "knowledge": {
                "knowledge_llm_backend": "openai-compatible",
                "knowledge_llm_compatible_url": "http://llm:8080/v1",
                "knowledge_llm_compatible_key": "sk-llm",
                "knowledge_embedding_compatible_url": "http://embed:8080/v1",
                "knowledge_embedding_compatible_key": "sk-embed",
            }
        }
        (temp_project / ".agents" / "config.json").write_text(json.dumps(config))
        resolver._cache = None

        master = resolver.get_master_settings()
        assert master.knowledge.knowledge_llm_backend == "openai-compatible"
        assert master.knowledge.knowledge_llm_compatible_url == "http://llm:8080/v1"
        assert master.knowledge.knowledge_llm_compatible_key == "sk-llm"
        assert master.knowledge.knowledge_embedding_compatible_url == "http://embed:8080/v1"
        assert master.knowledge.knowledge_embedding_compatible_key == "sk-embed"

    def test_patch_namespace_memory_preserves_fields(self, resolver, temp_project):
        """Patching the memory namespace must preserve all new fields."""
        resolver.patch_namespace("memory", {
            "llm_backend": "openai-compatible",
            "llm_compatible_url": "http://my-server:8080/v1",
            "embedding_compatible_key": "sk-test",
        })

        raw = json.loads((temp_project / ".agents" / "config.json").read_text())
        assert raw["memory"]["llm_backend"] == "openai-compatible"
        assert raw["memory"]["llm_compatible_url"] == "http://my-server:8080/v1"
        assert raw["memory"]["embedding_compatible_key"] == "sk-test"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. AI gateway compatible_url / compatible_key resolution
# ═══════════════════════════════════════════════════════════════════════════════

class TestAIGatewayCompatibleResolution:
    """_detect_embed_compatible_url / _detect_embed_compatible_key must
    read from MemorySettings / KnowledgeSettings correctly."""

    @pytest.fixture
    def mock_resolver(self):
        """Mock the settings resolver to return controlled master settings."""
        with patch("dashboard.lib.settings.resolver.get_settings_resolver") as mock_get:
            mock_resolver = MagicMock()
            mock_get.return_value = mock_resolver
            yield mock_resolver

    def _make_master(self, memory_kwargs=None, knowledge_kwargs=None):
        from dashboard.models import MasterSettings
        mem = MemorySettings(**(memory_kwargs or {}))
        know = KnowledgeSettings(**(knowledge_kwargs or {}))
        return MasterSettings(memory=mem, knowledge=know)

    # -- Memory purpose ----------------------------------------------------

    def test_memory_embedding_compatible_url(self, mock_resolver):
        from dashboard.ai import _detect_embed_compatible_url
        master = self._make_master(memory_kwargs={
            "embedding_compatible_url": "http://embed:8080/v1",
        })
        mock_resolver.get_master_settings.return_value = master
        assert _detect_embed_compatible_url("memory") == "http://embed:8080/v1"

    def test_memory_falls_back_to_llm_compatible_url(self, mock_resolver):
        from dashboard.ai import _detect_embed_compatible_url
        master = self._make_master(memory_kwargs={
            "llm_compatible_url": "http://llm:8080/v1",
        })
        mock_resolver.get_master_settings.return_value = master
        assert _detect_embed_compatible_url("memory") == "http://llm:8080/v1"

    def test_memory_embedding_url_takes_priority_over_llm_url(self, mock_resolver):
        from dashboard.ai import _detect_embed_compatible_url
        master = self._make_master(memory_kwargs={
            "embedding_compatible_url": "http://embed:8080/v1",
            "llm_compatible_url": "http://llm:8080/v1",
        })
        mock_resolver.get_master_settings.return_value = master
        assert _detect_embed_compatible_url("memory") == "http://embed:8080/v1"

    def test_memory_embedding_compatible_key(self, mock_resolver):
        from dashboard.ai import _detect_embed_compatible_key
        master = self._make_master(memory_kwargs={
            "embedding_compatible_key": "sk-embed-key",
        })
        mock_resolver.get_master_settings.return_value = master
        assert _detect_embed_compatible_key("memory") == "sk-embed-key"

    def test_memory_falls_back_to_llm_compatible_key(self, mock_resolver):
        from dashboard.ai import _detect_embed_compatible_key
        master = self._make_master(memory_kwargs={
            "llm_compatible_key": "sk-llm-key",
        })
        mock_resolver.get_master_settings.return_value = master
        assert _detect_embed_compatible_key("memory") == "sk-llm-key"

    # -- Knowledge purpose -------------------------------------------------

    def test_knowledge_embedding_compatible_url(self, mock_resolver):
        from dashboard.ai import _detect_embed_compatible_url
        master = self._make_master(knowledge_kwargs={
            "knowledge_embedding_compatible_url": "http://kembed:8080/v1",
        })
        mock_resolver.get_master_settings.return_value = master
        assert _detect_embed_compatible_url("knowledge") == "http://kembed:8080/v1"

    def test_knowledge_falls_back_to_llm_compatible_url(self, mock_resolver):
        from dashboard.ai import _detect_embed_compatible_url
        master = self._make_master(knowledge_kwargs={
            "knowledge_llm_compatible_url": "http://kllm:8080/v1",
        })
        mock_resolver.get_master_settings.return_value = master
        assert _detect_embed_compatible_url("knowledge") == "http://kllm:8080/v1"

    def test_knowledge_embedding_compatible_key(self, mock_resolver):
        from dashboard.ai import _detect_embed_compatible_key
        master = self._make_master(knowledge_kwargs={
            "knowledge_embedding_compatible_key": "sk-kembed",
        })
        mock_resolver.get_master_settings.return_value = master
        assert _detect_embed_compatible_key("knowledge") == "sk-kembed"

    # -- Empty / fallback --------------------------------------------------

    def test_returns_none_when_no_settings(self, mock_resolver):
        from dashboard.ai import _detect_embed_compatible_url, _detect_embed_compatible_key
        master = self._make_master()
        mock_resolver.get_master_settings.return_value = master
        assert _detect_embed_compatible_url("memory") is None
        assert _detect_embed_compatible_url("knowledge") is None
        assert _detect_embed_compatible_key("memory") is None
        assert _detect_embed_compatible_key("knowledge") is None

    def test_exception_returns_none(self, mock_resolver):
        from dashboard.ai import _detect_embed_compatible_url
        mock_resolver.get_master_settings.side_effect = RuntimeError("oops")
        assert _detect_embed_compatible_url("memory") is None


# ═══════════════════════════════════════════════════════════════════════════════
# 4. _get_embedder_for — cache key includes compatible_url
# ═══════════════════════════════════════════════════════════════════════════════

class TestEmbedderCache:
    """The embedder cache key must include compatible_url so that different
    endpoints get different client instances."""

    def test_cache_key_includes_compatible_url(self):
        from dashboard.ai import _embedder_cache
        _embedder_cache.clear()

        with patch("dashboard.ai._detect_embed_model", return_value="my-model"), \
             patch("dashboard.ai._detect_embed_provider", return_value="openai-compatible"), \
             patch("dashboard.ai._detect_embed_compatible_url", return_value="http://x:8080"), \
             patch("dashboard.ai._detect_embed_compatible_key", return_value=None), \
             patch("dashboard.llm_client.create_embedding_client") as mock_create:
            mock_create.return_value = MagicMock()

            from dashboard.ai import _get_embedder_for
            _get_embedder_for("knowledge")

            # Should have been called with base_url
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs.get("base_url") == "http://x:8080"

        _embedder_cache.clear()

    def test_cache_key_different_url_creates_different_client(self):
        from dashboard.ai import _embedder_cache
        _embedder_cache.clear()

        mock_client_1 = MagicMock()
        mock_client_2 = MagicMock()

        with patch("dashboard.ai._detect_embed_model", return_value="my-model"), \
             patch("dashboard.ai._detect_embed_provider", return_value="openai-compatible"), \
             patch("dashboard.ai._detect_embed_compatible_key", return_value=None), \
             patch("dashboard.llm_client.create_embedding_client", side_effect=[mock_client_1, mock_client_2]):

            from dashboard.ai import _get_embedder_for

            with patch("dashboard.ai._detect_embed_compatible_url", return_value="http://x:8080"):
                result1, _, _ = _get_embedder_for("knowledge")

            with patch("dashboard.ai._detect_embed_compatible_url", return_value="http://y:9090"):
                result2, _, _ = _get_embedder_for("knowledge")

            assert result1 is mock_client_1
            assert result2 is mock_client_2
            assert mock_client_1 is not mock_client_2

        _embedder_cache.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# 5. create_client base_url passthrough
# ═══════════════════════════════════════════════════════════════════════════════

class TestCreateClientBaseUrl:
    """create_client must pass base_url through to the underlying client."""

    def test_base_url_passed_to_openai_client(self):
        from dashboard.llm_client import create_client
        with patch("dashboard.lib.settings.resolver.get_settings_resolver"):
            client = create_client(
                model="my-model",
                provider="openai-compatible",
                api_key="sk-test-fake-key",
                base_url="http://custom:8080/v1",
            )
            assert client.base_url == "http://custom:8080/v1"

    def test_base_url_passed_to_ollama_client(self):
        from dashboard.llm_client import create_client
        with patch("dashboard.lib.settings.resolver.get_settings_resolver"):
            client = create_client(
                model="llama3",
                provider="ollama",
                base_url="http://custom-ollama:11434",
            )
            assert client.base_url == "http://custom-ollama:11434"

    def test_base_url_overrides_default(self):
        """base_url param should override the auto-detected provider URL."""
        from dashboard.llm_client import create_client
        with patch("dashboard.lib.settings.resolver.get_settings_resolver"):
            client = create_client(
                model="gpt-4",
                provider="openai",
                api_key="test-key",
                base_url="http://proxy:8080/v1",
            )
            assert client.base_url == "http://proxy:8080/v1"

    def test_no_base_url_uses_default(self):
        """When base_url is None, the provider's default URL is used."""
        from dashboard.llm_client import create_client
        with patch("dashboard.lib.settings.resolver.get_settings_resolver"):
            client = create_client(
                model="gpt-4",
                provider="openai",
                api_key="test-key",
                base_url=None,
            )
            # Should not be a custom URL
            assert client.base_url != "http://custom:8080/v1"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. BaseLLMWrapper base_url / api_key passthrough
# ═══════════════════════════════════════════════════════════════════════════════

class TestBaseLLMWrapperBaseUrl:
    """BaseLLMWrapper must store and pass base_url to create_client."""

    def test_base_url_stored(self):
        from dashboard.llm_wrapper import BaseLLMWrapper
        w = BaseLLMWrapper(model="my-model", provider="openai-compatible", base_url="http://custom:8080/v1")
        assert w._explicit_base_url == "http://custom:8080/v1"

    def test_base_url_default_none(self):
        from dashboard.llm_wrapper import BaseLLMWrapper
        w = BaseLLMWrapper()
        assert w._explicit_base_url is None

    def test_base_url_passed_to_get_client(self):
        from dashboard.llm_wrapper import BaseLLMWrapper
        w = BaseLLMWrapper(
            model="my-model",
            provider="openai-compatible",
            api_key="sk-test",
            base_url="http://custom:8080/v1",
        )
        with patch("dashboard.llm_wrapper.create_client") as mock_create:
            mock_create.return_value = MagicMock()
            w._get_client(max_tokens=1024)
            _, kwargs = mock_create.call_args
            assert kwargs.get("base_url") == "http://custom:8080/v1"

    def test_api_key_passed_to_get_client(self):
        from dashboard.llm_wrapper import BaseLLMWrapper
        w = BaseLLMWrapper(
            model="my-model",
            provider="openai-compatible",
            api_key="sk-explicit",
        )
        with patch("dashboard.llm_wrapper.create_client") as mock_create:
            mock_create.return_value = MagicMock()
            w._get_client(max_tokens=1024)
            _, kwargs = mock_create.call_args
            assert kwargs.get("api_key") == "sk-explicit"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. dashboard.agentic_memory config extraction of compatible fields
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgenticMemoryConfigExtraction:
    """_extract_memory_settings must map flat dashboard keys to nested
    config.default.json shape, including compatible_url / compatible_key."""

    def test_llm_compatible_url_extracted(self):
        from dashboard.agentic_memory.config import _extract_memory_settings
        raw = {"memory": {"llm_compatible_url": "http://my-server:8080/v1"}}
        result = _extract_memory_settings(raw)
        assert result["llm"]["compatible_url"] == "http://my-server:8080/v1"

    def test_llm_compatible_key_extracted(self):
        from dashboard.agentic_memory.config import _extract_memory_settings
        raw = {"memory": {"llm_compatible_key": "sk-test-key"}}
        result = _extract_memory_settings(raw)
        assert result["llm"]["compatible_key"] == "sk-test-key"

    def test_embedding_compatible_url_extracted(self):
        from dashboard.agentic_memory.config import _extract_memory_settings
        raw = {"memory": {"embedding_compatible_url": "http://embed:8080/v1"}}
        result = _extract_memory_settings(raw)
        assert result["embedding"]["compatible_url"] == "http://embed:8080/v1"

    def test_embedding_compatible_key_extracted(self):
        from dashboard.agentic_memory.config import _extract_memory_settings
        raw = {"memory": {"embedding_compatible_key": "sk-embed-key"}}
        result = _extract_memory_settings(raw)
        assert result["embedding"]["compatible_key"] == "sk-embed-key"

    def test_llm_backend_and_model_extracted(self):
        from dashboard.agentic_memory.config import _extract_memory_settings
        raw = {"memory": {"llm_backend": "ollama", "llm_model": "llama3.2"}}
        result = _extract_memory_settings(raw)
        assert result["llm"]["backend"] == "ollama"
        assert result["llm"]["model"] == "llama3.2"

    def test_embedding_backend_and_model_extracted(self):
        from dashboard.agentic_memory.config import _extract_memory_settings
        raw = {"memory": {"embedding_backend": "gemini", "embedding_model": "text-embedding-005"}}
        result = _extract_memory_settings(raw)
        assert result["embedding"]["backend"] == "gemini"
        assert result["embedding"]["model"] == "text-embedding-005"

    def test_empty_memory_returns_empty(self):
        from dashboard.agentic_memory.config import _extract_memory_settings
        assert _extract_memory_settings({}) == {}
        assert _extract_memory_settings({"memory": {}}) == {}
        assert _extract_memory_settings({"memory": None}) == {}

    def test_all_fields_extracted_together(self):
        from dashboard.agentic_memory.config import _extract_memory_settings
        raw = {
            "memory": {
                "llm_backend": "openai-compatible",
                "llm_model": "my-llm",
                "llm_compatible_url": "http://llm:8080/v1",
                "llm_compatible_key": "sk-llm",
                "embedding_backend": "openai-compatible",
                "embedding_model": "my-embed",
                "embedding_compatible_url": "http://embed:8080/v1",
                "embedding_compatible_key": "sk-embed",
                "vector_backend": "chroma",
                "similarity_weight": 0.9,
            }
        }
        result = _extract_memory_settings(raw)
        assert result["llm"]["backend"] == "openai-compatible"
        assert result["llm"]["compatible_url"] == "http://llm:8080/v1"
        assert result["embedding"]["compatible_url"] == "http://embed:8080/v1"
        assert result["vector"]["backend"] == "chroma"
        assert result["search"]["similarity_weight"] == 0.9

    def test_pool_settings_extracted(self):
        from dashboard.agentic_memory.config import _extract_memory_settings
        raw = {
            "memory": {
                "pool_idle_timeout_s": 600,
                "pool_max_instances": 20,
                "pool_eviction_policy": "oldest",
                "pool_sync_interval_s": 120,
            }
        }
        result = _extract_memory_settings(raw)
        assert result["pool"]["idle_timeout_s"] == 600
        assert result["pool"]["max_instances"] == 20
        assert result["pool"]["eviction_policy"] == "oldest"
        assert result["pool"]["sync_interval_s"] == 120


class TestLLMConfigAndEmbeddingConfig:
    """LLMConfig and EmbeddingConfig dataclasses must accept compatible fields."""

    def test_llm_config_compatible_url(self):
        from dashboard.agentic_memory.config import LLMConfig
        cfg = LLMConfig(backend="openai-compatible", model="my-model",
                        compatible_url="http://x:8080/v1", compatible_key="sk-test")
        assert cfg.compatible_url == "http://x:8080/v1"
        assert cfg.compatible_key == "sk-test"

    def test_embedding_config_compatible_url(self):
        from dashboard.agentic_memory.config import EmbeddingConfig
        cfg = EmbeddingConfig(backend="openai-compatible", model="my-embed",
                              compatible_url="http://y:8080/v1", compatible_key="sk-embed")
        assert cfg.compatible_url == "http://y:8080/v1"
        assert cfg.compatible_key == "sk-embed"

    def test_defaults_are_empty_strings(self):
        from dashboard.agentic_memory.config import LLMConfig, EmbeddingConfig
        llm = LLMConfig()
        embed = EmbeddingConfig()
        assert llm.compatible_url == ""
        assert llm.compatible_key == ""
        assert embed.compatible_url == ""
        assert embed.compatible_key == ""


# ═══════════════════════════════════════════════════════════════════════════════
# 8. MemoryLLM compatible settings resolution
# ═══════════════════════════════════════════════════════════════════════════════

class TestMemoryLLMCompatibleSettings:
    """MemoryLLM must resolve compatible_url/key from MemorySettings and pass
    them to BaseLLMWrapper."""

    @pytest.fixture
    def mock_resolver(self):
        with patch("dashboard.lib.settings.resolver.get_settings_resolver") as mock_get:
            mock_resolver = MagicMock()
            mock_get.return_value = mock_resolver
            yield mock_resolver

    def _make_master(self, **memory_kwargs):
        from dashboard.models import MasterSettings
        mem = MemorySettings(**memory_kwargs)
        return MasterSettings(memory=mem)

    def test_resolve_compatible_settings_returns_url_and_key(self, mock_resolver):
        from dashboard.agentic_memory.memory_llm import MemoryLLM
        master = self._make_master(
            llm_backend="openai-compatible",
            llm_compatible_url="http://my-server:8080/v1",
            llm_compatible_key="sk-test",
        )
        mock_resolver.get_master_settings.return_value = master
        url, key = MemoryLLM._resolve_compatible_settings()
        assert url == "http://my-server:8080/v1"
        assert key == "sk-test"

    def test_resolve_compatible_settings_falls_back_to_embedding(self, mock_resolver):
        from dashboard.agentic_memory.memory_llm import MemoryLLM
        master = self._make_master(
            embedding_backend="openai-compatible",
            embedding_compatible_url="http://embed:8080/v1",
            embedding_compatible_key="sk-embed",
        )
        mock_resolver.get_master_settings.return_value = master
        url, key = MemoryLLM._resolve_compatible_settings()
        assert url == "http://embed:8080/v1"
        assert key == "sk-embed"

    def test_resolve_compatible_settings_returns_none_when_not_compatible(self, mock_resolver):
        from dashboard.agentic_memory.memory_llm import MemoryLLM
        master = self._make_master(llm_backend="ollama")
        mock_resolver.get_master_settings.return_value = master
        url, key = MemoryLLM._resolve_compatible_settings()
        assert url is None
        assert key is None

    def test_resolve_compatible_settings_exception_returns_none(self, mock_resolver):
        from dashboard.agentic_memory.memory_llm import MemoryLLM
        mock_resolver.get_master_settings.side_effect = RuntimeError("oops")
        url, key = MemoryLLM._resolve_compatible_settings()
        assert url is None
        assert key is None

    def test_memory_llm_passes_base_url_to_wrapper(self, mock_resolver):
        from dashboard.agentic_memory.memory_llm import MemoryLLM
        master = self._make_master(
            llm_backend="openai-compatible",
            llm_compatible_url="http://my-server:8080/v1",
            llm_compatible_key="sk-test",
            llm_model="my-llm",
        )
        mock_resolver.get_master_settings.return_value = master
        llm = MemoryLLM()
        assert llm._explicit_base_url == "http://my-server:8080/v1"
        assert llm._explicit_key == "sk-test"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. KnowledgeLLM compatible settings resolution
# ═══════════════════════════════════════════════════════════════════════════════

class TestKnowledgeLLMCompatibleSettings:
    """KnowledgeLLM must resolve compatible_url/key from KnowledgeSettings and
    pass them to BaseLLMWrapper."""

    @pytest.fixture
    def mock_resolver(self):
        with patch("dashboard.lib.settings.resolver.get_settings_resolver") as mock_get:
            mock_resolver = MagicMock()
            mock_get.return_value = mock_resolver
            yield mock_resolver

    def _make_master(self, **knowledge_kwargs):
        from dashboard.models import MasterSettings
        know = KnowledgeSettings(**knowledge_kwargs)
        return MasterSettings(knowledge=know)

    def test_resolve_compatible_settings_returns_url_and_key(self, mock_resolver):
        from dashboard.knowledge.llm import KnowledgeLLM
        master = self._make_master(
            knowledge_llm_backend="openai-compatible",
            knowledge_llm_compatible_url="http://kllm:8080/v1",
            knowledge_llm_compatible_key="sk-kllm",
        )
        mock_resolver.get_master_settings.return_value = master
        url, key = KnowledgeLLM._resolve_compatible_settings()
        assert url == "http://kllm:8080/v1"
        assert key == "sk-kllm"

    def test_resolve_compatible_settings_falls_back_to_embedding(self, mock_resolver):
        from dashboard.knowledge.llm import KnowledgeLLM
        master = self._make_master(
            knowledge_embedding_backend="openai-compatible",
            knowledge_embedding_compatible_url="http://kembed:8080/v1",
            knowledge_embedding_compatible_key="sk-kembed",
        )
        mock_resolver.get_master_settings.return_value = master
        url, key = KnowledgeLLM._resolve_compatible_settings()
        assert url == "http://kembed:8080/v1"
        assert key == "sk-kembed"

    def test_resolve_compatible_settings_returns_none_when_not_compatible(self, mock_resolver):
        from dashboard.knowledge.llm import KnowledgeLLM
        master = self._make_master(knowledge_llm_backend="ollama")
        mock_resolver.get_master_settings.return_value = master
        url, key = KnowledgeLLM._resolve_compatible_settings()
        assert url is None
        assert key is None

    def test_knowledge_llm_passes_base_url_to_wrapper(self, mock_resolver):
        from dashboard.knowledge.llm import KnowledgeLLM
        master = self._make_master(
            knowledge_llm_backend="openai-compatible",
            knowledge_llm_compatible_url="http://kllm:8080/v1",
            knowledge_llm_compatible_key="sk-kllm",
            knowledge_llm_model="my-kllm",
        )
        mock_resolver.get_master_settings.return_value = master
        llm = KnowledgeLLM()
        assert llm._explicit_base_url == "http://kllm:8080/v1"
        assert llm._explicit_key == "sk-kllm"


# ═══════════════════════════════════════════════════════════════════════════════
# 10. _detect_embed_provider backward compat
# ═══════════════════════════════════════════════════════════════════════════════

class TestDetectEmbedProviderBackwardCompat:
    """_detect_embed_provider must read embedding_backend with fallback to
    embedding_provider for backward compat."""

    @pytest.fixture
    def mock_resolver(self):
        with patch("dashboard.lib.settings.resolver.get_settings_resolver") as mock_get:
            mock_resolver = MagicMock()
            mock_get.return_value = mock_resolver
            yield mock_resolver

    def _make_master(self, **memory_kwargs):
        from dashboard.models import MasterSettings
        mem = MemorySettings(**memory_kwargs)
        return MasterSettings(memory=mem)

    def test_memory_purpose_reads_embedding_backend(self, mock_resolver):
        from dashboard.ai import _detect_embed_provider
        master = self._make_master(embedding_backend="openai-compatible")
        mock_resolver.get_master_settings.return_value = master
        assert _detect_embed_provider("memory") == "openai-compatible"

    def test_memory_purpose_falls_back_to_embedding_provider(self, mock_resolver):
        from dashboard.ai import _detect_embed_provider
        # embedding_provider is set, embedding_backend is empty (legacy config)
        master = self._make_master(embedding_provider="ollama")
        mock_resolver.get_master_settings.return_value = master
        assert _detect_embed_provider("memory") == "ollama"

    def test_memory_embedding_backend_takes_priority(self, mock_resolver):
        from dashboard.ai import _detect_embed_provider
        master = self._make_master(embedding_backend="gemini", embedding_provider="ollama")
        mock_resolver.get_master_settings.return_value = master
        assert _detect_embed_provider("memory") == "gemini"

    def test_knowledge_purpose_reads_knowledge_embedding_backend(self, mock_resolver):
        from dashboard.ai import _detect_embed_provider
        from dashboard.models import MasterSettings, KnowledgeSettings
        know = KnowledgeSettings(knowledge_embedding_backend="ollama")
        master = MasterSettings(knowledge=know)
        mock_resolver.get_master_settings.return_value = master
        assert _detect_embed_provider("knowledge") == "ollama"
