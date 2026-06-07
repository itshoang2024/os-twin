"""Tests for knowledge retention and refresh functionality (EPIC-004).

Coverage:
- RetentionPolicy model validation
- RetentionSweeper background thread
- refresh_namespace method
- REST endpoints for retention and refresh
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

from dashboard.knowledge.namespace import (
    NamespaceManager,
    NamespaceMeta,
    ImportRecord,
    RetentionPolicy,
)
from dashboard.knowledge.service import (
    KnowledgeService,
    RetentionSweeper,
    DEFAULT_SWEEP_INTERVAL_HOURS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_knowledge_dir(tmp_path: Path) -> Path:
    """Create a temporary knowledge directory."""
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    return knowledge_dir


@pytest.fixture
def namespace_manager(temp_knowledge_dir: Path) -> NamespaceManager:
    """Create a NamespaceManager with a temp directory."""
    return NamespaceManager(base_dir=temp_knowledge_dir)


@pytest.fixture
def knowledge_service(namespace_manager: NamespaceManager) -> KnowledgeService:
    """Create a KnowledgeService with temp namespace manager."""
    return KnowledgeService(namespace_manager=namespace_manager)


# ---------------------------------------------------------------------------
# RetentionPolicy model tests
# ---------------------------------------------------------------------------


def test_retention_policy_defaults():
    """Test that RetentionPolicy has correct defaults."""
    policy = RetentionPolicy()
    
    assert policy.policy == "manual"
    assert policy.ttl_days is None
    assert policy.last_swept_at is None
    assert policy.auto_delete_when_empty is False


def test_retention_policy_ttl():
    """Test creating a TTL retention policy."""
    now = datetime.now(timezone.utc)
    policy = RetentionPolicy(
        policy="ttl_days",
        ttl_days=7,
        last_swept_at=now,
        auto_delete_when_empty=True,
    )
    
    assert policy.policy == "ttl_days"
    assert policy.ttl_days == 7
    assert policy.last_swept_at == now
    assert policy.auto_delete_when_empty is True


# ---------------------------------------------------------------------------
# NamespaceMeta retention field tests
# ---------------------------------------------------------------------------


def test_namespace_meta_has_retention(namespace_manager: NamespaceManager):
    """Test that NamespaceMeta includes retention field."""
    meta = namespace_manager.create("test-retention")
    
    assert hasattr(meta, "retention")
    assert meta.retention.policy == "manual"


def test_namespace_meta_retention_serialization(namespace_manager: NamespaceManager):
    """Test that retention field is serialized correctly."""
    namespace_manager.create("test-serialize")
    
    # Re-read from disk
    meta = namespace_manager.get("test-serialize")
    assert meta is not None
    assert meta.retention is not None
    assert meta.retention.policy == "manual"


# ---------------------------------------------------------------------------
# RetentionSweeper tests
# ---------------------------------------------------------------------------


def test_sweeper_initialization(knowledge_service: KnowledgeService):
    """Test that RetentionSweeper initializes correctly."""
    sweeper = RetentionSweeper(knowledge_service, interval_hours=1.0)
    
    assert sweeper._service is knowledge_service
    assert sweeper._interval_hours == 1.0
    assert sweeper.daemon is True
    assert sweeper.name == "RetentionSweeper"


def test_sweeper_uses_env_var(knowledge_service: KnowledgeService):
    """Test that sweeper reads interval from environment variable."""
    with patch.dict("os.environ", {"OSTWIN_KNOWLEDGE_SWEEP_INTERVAL_HOURS": "12"}):
        sweeper = RetentionSweeper(knowledge_service)
        assert sweeper._interval_hours == 12.0


def test_sweeper_stop(knowledge_service: KnowledgeService):
    """Test that sweeper can be stopped."""
    sweeper = RetentionSweeper(knowledge_service, interval_hours=0.001)
    
    # Start and stop immediately
    sweeper.start()
    time.sleep(0.1)
    sweeper.stop()
    sweeper.join(timeout=1.0)
    
    # Should have stopped
    assert not sweeper.is_alive()


def test_sweeper_skips_manual_namespaces(
    knowledge_service: KnowledgeService,
    namespace_manager: NamespaceManager,
):
    """Test that sweeper only processes ttl_days namespaces."""
    # Create namespace with manual policy
    ns_name = "manual-ns"
    namespace_manager.create(ns_name)
    
    # Add an old import
    meta = namespace_manager.get(ns_name)
    assert meta is not None
    
    old_import = ImportRecord(
        folder_path="/old/import",
        started_at=datetime.now(timezone.utc) - timedelta(days=30),
        finished_at=datetime.now(timezone.utc) - timedelta(days=29),
        status="completed",
    )
    namespace_manager.append_import(ns_name, old_import)
    
    # Run sweep
    sweeper = RetentionSweeper(knowledge_service)
    sweeper._sweep_once()
    
    # Import should still be there (manual policy)
    meta_after = namespace_manager.get(ns_name)
    assert meta_after is not None
    assert len(meta_after.imports) == 1


def test_sweeper_purges_expired_imports(
    knowledge_service: KnowledgeService,
    namespace_manager: NamespaceManager,
):
    """Test that sweeper purges imports older than TTL."""
    ns_name = "ttl-ns"
    namespace_manager.create(ns_name)
    
    # Set TTL policy
    meta = namespace_manager.get(ns_name)
    assert meta is not None
    meta.retention = RetentionPolicy(policy="ttl_days", ttl_days=7)
    namespace_manager.write_manifest(ns_name, meta)
    
    # Add old import (15 days ago)
    old_import = ImportRecord(
        folder_path="/old/import",
        started_at=datetime.now(timezone.utc) - timedelta(days=15),
        finished_at=datetime.now(timezone.utc) - timedelta(days=14),
        status="completed",
    )
    namespace_manager.append_import(ns_name, old_import)
    
    # Add recent import (2 days ago)
    recent_import = ImportRecord(
        folder_path="/recent/import",
        started_at=datetime.now(timezone.utc) - timedelta(days=2),
        finished_at=datetime.now(timezone.utc) - timedelta(days=2),
        status="completed",
    )
    namespace_manager.append_import(ns_name, recent_import)
    
    # Run sweep
    sweeper = RetentionSweeper(knowledge_service)
    sweeper._sweep_once()
    
    # Only recent import should remain
    meta_after = namespace_manager.get(ns_name)
    assert meta_after is not None
    assert len(meta_after.imports) == 1
    assert meta_after.imports[0].folder_path == "/recent/import"


def test_sweeper_deletes_empty_namespace(
    knowledge_service: KnowledgeService,
    namespace_manager: NamespaceManager,
):
    """Test that sweeper deletes namespace when all imports purged and auto_delete enabled."""
    ns_name = "auto-delete-ns"
    namespace_manager.create(ns_name)
    
    # Set TTL policy with auto_delete
    meta = namespace_manager.get(ns_name)
    assert meta is not None
    meta.retention = RetentionPolicy(
        policy="ttl_days",
        ttl_days=7,
        auto_delete_when_empty=True,
    )
    namespace_manager.write_manifest(ns_name, meta)
    
    # Add old import
    old_import = ImportRecord(
        folder_path="/old/import",
        started_at=datetime.now(timezone.utc) - timedelta(days=15),
        finished_at=datetime.now(timezone.utc) - timedelta(days=14),
        status="completed",
    )
    namespace_manager.append_import(ns_name, old_import)
    
    # Run sweep
    sweeper = RetentionSweeper(knowledge_service)
    sweeper._sweep_once()
    
    # Namespace should be deleted
    assert namespace_manager.get(ns_name) is None


def test_sweeper_updates_last_swept_at(
    knowledge_service: KnowledgeService,
    namespace_manager: NamespaceManager,
):
    """Test that sweeper updates last_swept_at timestamp."""
    ns_name = "swept-ns"
    namespace_manager.create(ns_name)
    
    # Set TTL policy
    meta = namespace_manager.get(ns_name)
    assert meta is not None
    meta.retention = RetentionPolicy(policy="ttl_days", ttl_days=7)
    namespace_manager.write_manifest(ns_name, meta)
    
    # Add an import (even if not expired, sweeper should still update timestamp)
    new_import = ImportRecord(
        folder_path="/test/import",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        status="completed",
    )
    namespace_manager.append_import(ns_name, new_import)
    
    # Run sweep
    sweeper = RetentionSweeper(knowledge_service)
    sweeper._sweep_once()
    
    # Check last_swept_at was set
    meta_after = namespace_manager.get(ns_name)
    assert meta_after is not None
    assert meta_after.retention.last_swept_at is not None


# ---------------------------------------------------------------------------
# KnowledgeService.start_background tests
# ---------------------------------------------------------------------------


def test_start_background_starts_sweeper(knowledge_service: KnowledgeService):
    """Test that start_background starts the retention sweeper."""
    knowledge_service.start_background()
    
    assert knowledge_service._sweeper is not None
    assert knowledge_service._sweeper.is_alive()
    
    # Cleanup
    knowledge_service.shutdown()


def test_start_background_idempotent(knowledge_service: KnowledgeService):
    """Test that start_background is idempotent."""
    knowledge_service.start_background()
    first_sweeper = knowledge_service._sweeper
    
    knowledge_service.start_background()  # Should be a no-op
    assert knowledge_service._sweeper is first_sweeper
    
    # Cleanup
    knowledge_service.shutdown()


def test_shutdown_stops_sweeper(knowledge_service: KnowledgeService):
    """Test that shutdown stops the retention sweeper."""
    knowledge_service.start_background()
    sweeper = knowledge_service._sweeper
    
    knowledge_service.shutdown()
    
    assert not sweeper.is_alive()


# ---------------------------------------------------------------------------
# refresh_namespace tests
# ---------------------------------------------------------------------------


def test_refresh_namespace_empty_namespace(knowledge_service: KnowledgeService):
    """Refreshing an empty namespace returns empty job list."""
    knowledge_service._nm.create("empty-refresh")
    job_ids = knowledge_service.refresh_namespace("empty-refresh")
    assert job_ids == []


def test_refresh_namespace_nonexistent_raises(knowledge_service: KnowledgeService):
    """Refreshing a missing namespace raises NamespaceNotFoundError."""
    from dashboard.knowledge.namespace import NamespaceNotFoundError
    with pytest.raises(NamespaceNotFoundError):
        knowledge_service.refresh_namespace("no-such-ns")


def test_refresh_namespace_returns_job_ids(
    knowledge_service: KnowledgeService,
    namespace_manager: NamespaceManager,
):
    """Refreshing namespace with imports triggers background jobs."""
    ns = "real-refresh"
    namespace_manager.create(ns)
    
    # Mock imports in manifest
    meta = namespace_manager.get(ns)
    now = datetime.now(timezone.utc)
    meta.imports = [
        ImportRecord(folder_path="/data/v1", started_at=now, status="completed"),
        ImportRecord(folder_path="/data/v2", started_at=now, status="completed"),
    ]
    namespace_manager.write_manifest(ns, meta)
    
    # Mock import_folder to return dummy job IDs
    with patch.object(knowledge_service, "import_folder") as mock_import:
        mock_import.side_effect = ["job-1", "job-2"]
        
        job_ids = knowledge_service.refresh_namespace(ns)
        
        assert len(job_ids) == 2
        assert "job-1" in job_ids
        assert "job-2" in job_ids
        assert mock_import.call_count == 2
        
        # Verify force=True was passed
        kwargs = mock_import.call_args[1]
        assert kwargs["options"] == {"force": True}


def test_refresh_namespace_skips_failed_imports(
    knowledge_service: KnowledgeService,
    namespace_manager: NamespaceManager,
):
    """Refreshing only triggers jobs for successful previous imports."""
    ns = "partial-refresh"
    namespace_manager.create(ns)
    
    meta = namespace_manager.get(ns)
    now = datetime.now(timezone.utc)
    meta.imports = [
        ImportRecord(folder_path="/data/ok", started_at=now, status="completed"),
        ImportRecord(folder_path="/data/bad", started_at=now, status="failed"),
    ]
    namespace_manager.write_manifest(ns, meta)
    
    with patch.object(knowledge_service, "import_folder") as mock_import:
        mock_import.return_value = "job-ok"
        
        job_ids = knowledge_service.refresh_namespace(ns)
        
        assert job_ids == ["job-ok"]
        mock_import.assert_called_once()
        assert mock_import.call_args[0][1] == "/data/ok"
# Schema migration tests
# ---------------------------------------------------------------------------


def test_schema_v1_migrates_to_v3(namespace_manager: NamespaceManager, tmp_path: Path):
    """Test that v1 manifests are migrated to v3 with retention and ontology metadata."""
    ns_name = "migration-test"
    ns_dir = namespace_manager.namespace_dir(ns_name)
    ns_dir.mkdir(parents=True, exist_ok=True)
    
    # Write a v1 manifest (no retention field)
    v1_manifest = {
        "schema_version": 1,
        "name": ns_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "language": "English",
        "embedding_model": "test-model",
        "embedding_dimension": 1024,
        "stats": {
            "files_indexed": 0,
            "chunks": 0,
            "entities": 0,
            "relations": 0,
            "vectors": 0,
            "bytes_on_disk": 0,
        },
        "imports": [],
    }
    
    manifest_path = ns_dir / "manifest.json"
    manifest_path.write_text(json.dumps(v1_manifest))
    
    # Read manifest (triggers migration)
    meta = namespace_manager.get(ns_name)
    
    assert meta is not None
    assert meta.schema_version == 3
    assert meta.retention is not None
    assert meta.retention.policy == "manual"
    assert meta.ontology_profile_version is None


def test_schema_missing_version_migrates(namespace_manager: NamespaceManager, tmp_path: Path):
    """Test that manifests without schema_version are migrated."""
    ns_name = "no-version-test"
    ns_dir = namespace_manager.namespace_dir(ns_name)
    ns_dir.mkdir(parents=True, exist_ok=True)
    
    # Write manifest without schema_version
    manifest = {
        "name": ns_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "language": "English",
        "embedding_model": "test-model",
        "embedding_dimension": 1024,
        "stats": {
            "files_indexed": 0,
            "chunks": 0,
            "entities": 0,
            "relations": 0,
            "vectors": 0,
            "bytes_on_disk": 0,
        },
        "imports": [],
    }
    
    manifest_path = ns_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    
    # Read manifest (triggers migration)
    meta = namespace_manager.get(ns_name)
    
    assert meta is not None
    assert meta.schema_version == 3
    assert meta.retention is not None
    assert meta.ontology_profile_version is None
