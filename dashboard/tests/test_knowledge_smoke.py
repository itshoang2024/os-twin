"""Smoke tests for the dashboard.knowledge package.

These tests intentionally avoid any functional behaviour beyond import + basic
class instantiation. They guarantee:

1. The public API surface imports cleanly.
2. ``KnowledgeService()`` constructs successfully (EPIC-002 — was placeholder
   in EPIC-001) and exposes ``list_namespaces`` returning a list.
3. ``KnowledgeService.import_folder`` is wired (EPIC-003 — surfaces
   FileNotFoundError for missing folders); ``query`` still raises
   ``NotImplementedError`` (EPIC-004 placeholder).
4. ``KnowledgeLLM`` degrades gracefully when no model or API key is configured.
5. ``KnowledgeEmbedder`` instantiates without triggering a model download.
6. Importing ``dashboard.knowledge`` does NOT pull in the heavy deps
   (kuzu, zvec, markitdown).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# 1) Import smoke
# ---------------------------------------------------------------------------


def test_top_level_package_imports() -> None:
    """`from dashboard.knowledge import ...` must succeed for every documented symbol."""
    from dashboard.knowledge import (  # noqa: F401
        EMBEDDING_DIMENSION,
        EMBEDDING_MODEL,
        KNOWLEDGE_DIR,
        LLM_MODEL,
        GraphRAGExtractor,
        GraphRAGQueryEngine,
        GraphRAGStore,
        ImportRecord,
        InvalidNamespaceIdError,
        KnowledgeEmbedder,
        KnowledgeLLM,
        KnowledgeService,
        KuzuLabelledPropertyGraph,
        NamespaceError,
        NamespaceExistsError,
        NamespaceManager,
        NamespaceMeta,
        NamespaceNotFoundError,
        NamespaceStats,
        NamespaceVectorStore,
        TrackVectorRetriever,
        VectorHit,
    )


# ---------------------------------------------------------------------------
# 2) KnowledgeService — real class (EPIC-002)
# ---------------------------------------------------------------------------


def test_knowledge_service_constructs_cleanly(tmp_path) -> None:
    """KnowledgeService() must NOT raise any more — the placeholder is gone."""
    from dashboard.knowledge import KnowledgeService, NamespaceManager

    svc = KnowledgeService(NamespaceManager(base_dir=tmp_path / "kb"))
    # Make sure the call returns and isn't a placeholder.
    assert svc is not None


def test_knowledge_service_list_namespaces_returns_list(tmp_path) -> None:
    """KnowledgeService().list_namespaces() returns a list (possibly empty)."""
    from dashboard.knowledge import KnowledgeService, NamespaceManager

    svc = KnowledgeService(NamespaceManager(base_dir=tmp_path / "kb"))
    result = svc.list_namespaces()
    assert isinstance(result, list)
    assert result == []


def test_knowledge_service_default_constructor_works() -> None:
    """KnowledgeService() with no args constructs against KNOWLEDGE_DIR.

    We don't write anything — just check construction succeeds (no raise).
    """
    from dashboard.knowledge import KnowledgeService

    svc = KnowledgeService()
    assert svc is not None


def test_knowledge_service_import_folder_wired_in_epic_003(tmp_path) -> None:
    """import_folder is wired in EPIC-003 — no longer the NotImplementedError placeholder.

    Verify it accepts the call shape and surfaces FileNotFoundError for a missing folder
    (full behaviour is covered by ``test_knowledge_ingestion.py``).
    """
    from dashboard.knowledge import KnowledgeService, NamespaceManager

    svc = KnowledgeService(NamespaceManager(base_dir=tmp_path / "kb"))
    with pytest.raises(FileNotFoundError):
        svc.import_folder("ns", str(tmp_path / "no-such-folder"))
    try:
        svc._get_job_manager().shutdown(wait=False)
    except Exception:
        pass


def test_knowledge_service_query_raises_NamespaceNotFound_for_missing_ns(tmp_path) -> None:
    """EPIC-004: ``query`` is implemented; missing namespace raises
    :class:`NamespaceNotFoundError` (not ``NotImplementedError`` any more)."""
    from dashboard.knowledge import (
        KnowledgeService,
        NamespaceManager,
        NamespaceNotFoundError,
    )

    svc = KnowledgeService(NamespaceManager(base_dir=tmp_path / "kb"))
    try:
        with pytest.raises(NamespaceNotFoundError):
            svc.query("ns", "what?")
    finally:
        svc.shutdown()


# ---------------------------------------------------------------------------
# 3) Config types
# ---------------------------------------------------------------------------


def test_knowledge_dir_is_path() -> None:
    """KNOWLEDGE_DIR must be a pathlib.Path."""
    from dashboard.knowledge.config import KNOWLEDGE_DIR

    assert isinstance(KNOWLEDGE_DIR, Path)


def test_namespace_path_helpers_are_paths() -> None:
    """The per-namespace helpers must return Path objects under KNOWLEDGE_DIR.

    Note: the on-disk vector directory is now ``vectors/`` (was ``chroma/``
    pre-EPIC-003 v2). The deprecated ``chroma_dir`` alias still resolves to
    the new path for back-compat.
    """
    from dashboard.knowledge.config import (
        KNOWLEDGE_DIR,
        chroma_dir,
        kuzu_db_path,
        manifest_path,
        namespace_dir,
        vector_dir,
    )

    assert namespace_dir("foo") == KNOWLEDGE_DIR / "foo"
    assert kuzu_db_path("foo") == KNOWLEDGE_DIR / "foo" / "graph.db"
    assert vector_dir("foo") == KNOWLEDGE_DIR / "foo" / "vectors"
    # Deprecated alias still works and resolves to the new path.
    assert chroma_dir("foo") == KNOWLEDGE_DIR / "foo" / "vectors"
    assert manifest_path("foo") == KNOWLEDGE_DIR / "foo" / "manifest.json"


def test_supported_extensions_are_sets() -> None:
    """File-type constants must be sets and cover common types."""
    from dashboard.knowledge.config import IMAGE_EXTENSIONS, SUPPORTED_DOCUMENT_EXTENSIONS

    assert isinstance(SUPPORTED_DOCUMENT_EXTENSIONS, set)
    assert ".pdf" in SUPPORTED_DOCUMENT_EXTENSIONS
    assert ".md" in SUPPORTED_DOCUMENT_EXTENSIONS
    assert isinstance(IMAGE_EXTENSIONS, set)
    assert ".png" in IMAGE_EXTENSIONS


# ---------------------------------------------------------------------------
# 4) KnowledgeLLM availability + graceful degradation
# ---------------------------------------------------------------------------


def test_llm_unavailable_without_model_or_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """is_available() must be False when no model is configured."""
    from dashboard.knowledge import KnowledgeLLM
    import dashboard.knowledge.llm as llm_mod

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    # Override the module-level LLM_MODEL so `model or LLM_MODEL` resolves empty.
    monkeypatch.setattr(llm_mod, "LLM_MODEL", "")
    llm = KnowledgeLLM()
    assert llm.is_available() is False


def test_llm_available_with_explicit_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit api_key + model passes is_available()."""
    from dashboard.knowledge import KnowledgeLLM

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    llm = KnowledgeLLM(api_key="sk-test", model="claude-sonnet-4-5-20251022")
    assert llm.is_available() is True


def test_llm_available_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Env-var API key is picked up automatically for the detected provider."""
    from dashboard.knowledge import KnowledgeLLM

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-from-env")
    llm = KnowledgeLLM(model="claude-sonnet-4-5-20251022")
    assert llm.is_available() is True


def test_extract_entities_returns_empty_when_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """When unavailable, extract_entities returns ([], []) without raising."""
    from dashboard.knowledge import KnowledgeLLM
    import dashboard.knowledge.llm as llm_mod

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(llm_mod, "LLM_MODEL", "")
    llm = KnowledgeLLM(api_key=None)
    entities, relations = llm.extract_entities("any text")
    assert entities == []
    assert relations == []


def test_plan_query_falls_back_when_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """plan_query returns a single passthrough step when unavailable."""
    from dashboard.knowledge import KnowledgeLLM
    import dashboard.knowledge.llm as llm_mod

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(llm_mod, "LLM_MODEL", "")
    llm = KnowledgeLLM(api_key=None)
    plan = llm.plan_query("q")
    assert plan == [{"term": "q", "is_query": True}]


def test_aggregate_answers_concatenates_when_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """aggregate_answers concatenates snippets when unavailable."""
    from dashboard.knowledge import KnowledgeLLM
    import dashboard.knowledge.llm as llm_mod

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(llm_mod, "LLM_MODEL", "")
    llm = KnowledgeLLM(api_key=None)
    out = llm.aggregate_answers(["snippet a", "snippet b"], "q")
    assert "snippet a" in out
    assert "snippet b" in out


# ---------------------------------------------------------------------------
# 5) KnowledgeEmbedder instantiation (without model download)
# ---------------------------------------------------------------------------


def test_embedder_instantiates_without_loading_model() -> None:
    """KnowledgeEmbedder() must NOT eagerly instantiate the backend client.

    The centralized factory (dashboard.llm_client.create_embedding_client) is
    only called on first ``.embed()``/``.embed_one()``/``.dimension()`` call,
    so construction stays cheap even when no backend is reachable.
    """
    from dashboard.knowledge import KnowledgeEmbedder

    embedder = KnowledgeEmbedder()
    assert embedder.model_name  # truthy (default model)
    assert embedder.provider  # truthy (default provider)
    assert embedder._client is None  # lazy: no backend client created yet


def test_embedder_accepts_explicit_model_name() -> None:
    """KnowledgeEmbedder accepts a model_name override."""
    from dashboard.knowledge import KnowledgeEmbedder

    embedder = KnowledgeEmbedder(model_name="custom/model")
    assert embedder.model_name == "custom/model"


# ---------------------------------------------------------------------------
# 6) Heavy deps are not imported at package load time
# ---------------------------------------------------------------------------


_HEAVY_DEPS = ("kuzu", "zvec", "markitdown")


def test_lazy_imports_via_subprocess() -> None:
    """`python -c "import dashboard.knowledge"` must NOT load heavy deps.

    We use a subprocess to get a clean interpreter (the test runner may already
    have these modules cached from earlier tests).
    """
    code = (
        "import sys\n"
        "import dashboard.knowledge\n"
        "loaded = [m for m in {!r} if m in sys.modules]\n"
        "print('LOADED:' + ','.join(loaded))\n"
    ).format(_HEAVY_DEPS)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(Path(__file__).resolve().parent.parent.parent),
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ},
    )
    assert proc.returncode == 0, proc.stderr
    last_line = proc.stdout.strip().splitlines()[-1]
    assert last_line.startswith("LOADED:")
    loaded = last_line[len("LOADED:") :].split(",") if last_line[len("LOADED:") :] else []
    loaded = [m for m in loaded if m]
    assert loaded == [], f"Heavy deps were loaded eagerly: {loaded}"


# ---------------------------------------------------------------------------
# 7) CARRY-003 — KnowledgeService reads from MasterSettings (ADR-15)
# ---------------------------------------------------------------------------


def test_service_reads_knowledge_settings_from_master(monkeypatch: pytest.MonkeyPatch) -> None:
    """When MasterSettings.knowledge.knowledge_llm_model is set, KnowledgeService picks it up.

    Mocks ``dashboard.lib.settings.get_settings_resolver`` (the import path
    KnowledgeService uses) so we don't need a real config file.
    """
    from unittest.mock import MagicMock

    from dashboard.knowledge.service import KnowledgeService

    fake_settings = MagicMock()
    fake_settings.knowledge.knowledge_llm_model = "claude-haiku-CUSTOM"
    fake_settings.knowledge.knowledge_llm_provider = ""
    fake_settings.knowledge.knowledge_embedding_model = ""
    fake_settings.knowledge.knowledge_embedding_backend = ""
    fake_resolver = MagicMock()
    fake_resolver.get_master_settings.return_value = fake_settings

    # Patch the path the helper actually imports.
    import dashboard.lib.settings as settings_pkg

    monkeypatch.setattr(settings_pkg, "get_settings_resolver", lambda: fake_resolver)

    ks = KnowledgeService()
    # Trigger LLM construction.
    llm = ks._get_llm()
    assert llm.model == "claude-haiku-CUSTOM"


def test_service_falls_back_to_default_when_settings_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty knowledge settings → KnowledgeService uses the env-var default."""
    from unittest.mock import MagicMock

    from dashboard.knowledge.config import LLM_MODEL as _DEFAULT_LLM
    from dashboard.knowledge.service import KnowledgeService

    fake_settings = MagicMock()
    fake_settings.knowledge.knowledge_llm_model = ""
    fake_settings.knowledge.knowledge_llm_provider = ""
    fake_settings.knowledge.knowledge_embedding_model = ""
    fake_settings.knowledge.knowledge_embedding_backend = ""
    fake_resolver = MagicMock()
    fake_resolver.get_master_settings.return_value = fake_settings

    import dashboard.lib.settings as settings_pkg

    monkeypatch.setattr(settings_pkg, "get_settings_resolver", lambda: fake_resolver)

    ks = KnowledgeService()
    llm = ks._get_llm()
    assert llm.model == _DEFAULT_LLM


def test_service_handles_missing_settings_resolver_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the settings resolver raises, KnowledgeService still constructs and uses defaults."""
    from dashboard.knowledge.config import LLM_MODEL as _DEFAULT_LLM
    from dashboard.knowledge.service import KnowledgeService

    def _broken_resolver():
        raise RuntimeError("config gone walkabout")

    import dashboard.lib.settings as settings_pkg

    monkeypatch.setattr(settings_pkg, "get_settings_resolver", _broken_resolver)

    ks = KnowledgeService()
    llm = ks._get_llm()
    # Falls back to the hardcoded default — never crashes.
    assert llm.model == _DEFAULT_LLM
