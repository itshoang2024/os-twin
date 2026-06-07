"""
test_plan_versions.py — Verify plan versioning API endpoints.

Tests the version snapshot-on-save flow, version listing, fetching,
and restoring previous versions.

Usage:
    python test_plan_versions.py
    DASHBOARD_URL=http://localhost:9001 python test_plan_versions.py
"""

import os
import sys
import httpx
import pytest
from fastapi.testclient import TestClient
from dashboard.api import app
from dashboard import global_state

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://localhost:3366")

PLAN_V1 = """# Plan: Version Test Plan

> Created: 2026-03-16T00:00:00Z
> Status: draft
> Project: /tmp/test-versions

## Config

working_dir: /tmp/test-versions

---

## Goal

Test the versioning system.

## Epic: EPIC-001 — Initial Setup

### Definition of Done
- [ ] Core structure created

### Tasks
- [ ] TASK-001 — Scaffold project
"""

PLAN_V2 = """# Plan: Version Test Plan (Updated)

> Created: 2026-03-16T00:00:00Z
> Status: draft
> Project: /tmp/test-versions

## Config

working_dir: /tmp/test-versions

---

## Goal

Test the versioning system with expanded epics.

## Epic: EPIC-001 — Initial Setup

### Definition of Done
- [ ] Core structure created
- [ ] Tests added

### Tasks
- [ ] TASK-001 — Scaffold project
- [ ] TASK-002 — Add unit tests

## Epic: EPIC-002 — Authentication

### Definition of Done
- [ ] Login flow works

### Tasks
- [ ] TASK-001 — Implement OAuth
"""

PLAN_V3 = """# Plan: Version Test Plan (Final)

> Status: draft

## Config

working_dir: /tmp/test-versions

---

## Goal

Final version of the plan.

## Epic: EPIC-001 — Everything

### Tasks
- [ ] TASK-001 — Do everything
"""


HEADERS = {"X-API-Key": "test-key"}


class FakePlanVersionStore:
    def __init__(self):
        self._plans = {}
        self._versions = {}

    def save_plan_version(self, **kwargs):
        plan_id = kwargs["plan_id"]
        versions = self._versions.setdefault(plan_id, [])
        record = {
            **kwargs,
            "version": len(versions) + 1,
            "created_at": "2026-06-07T00:00:00Z",
        }
        versions.append(record)
        return record

    def get_plan_versions(self, plan_id: str):
        return [
            {k: v for k, v in record.items() if k != "content"}
            for record in reversed(self._versions.get(plan_id, []))
        ]

    def get_plan_version(self, plan_id: str, version: int):
        for record in self._versions.get(plan_id, []):
            if record["version"] == version:
                return record
        return None

    def index_plan(self, **kwargs):
        self._plans[kwargs["plan_id"]] = dict(kwargs)

    def get_plan(self, plan_id: str):
        return self._plans.get(plan_id)

    def get_epics_for_plan(self, plan_id: str):
        return []


@pytest.fixture
def fake_version_store(monkeypatch):
    store = FakePlanVersionStore()
    monkeypatch.setattr(global_state, "store", store)
    return store


def test_version_snapshot_on_save(fake_version_store):
    """Saving a plan with changed content should create a version snapshot."""
    with TestClient(app, headers=HEADERS) as client:
        # 1. Create plan
        resp = client.post("/api/plans/create", json={
            "path": "/tmp/test-versions",
            "title": "Version Test Plan",
            "content": PLAN_V1,
            "working_dir": "/tmp/test-versions",
        })
        assert resp.status_code == 200, f"Create failed: {resp.status_code} {resp.text}"
        plan_id = resp.json()["plan_id"]
        print(f"  ✓ Created plan: {plan_id}")

        # 2. Check no versions yet
        resp = client.get(f"/api/plans/{plan_id}/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0, f"Expected 0 versions, got {data['count']}"
        print(f"  ✓ No versions initially")

        # 3. Save with new content → should create version 1 (snapshot of V1)
        resp = client.post(f"/api/plans/{plan_id}/save", json={
            "content": PLAN_V2,
            "change_source": "manual_save",
        })
        assert resp.status_code == 200
        print(f"  ✓ Saved V2")

        # 4. List versions → should have version 1
        resp = client.get(f"/api/plans/{plan_id}/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1, f"Expected 1 version, got {data['count']}"
        v1 = data["versions"][0]
        assert v1["version"] == 1
        assert v1["change_source"] == "manual_save"
        assert "Version Test Plan" in v1["title"]
        print(f"  ✓ Version 1 created with correct metadata")

        # 5. Save again → should create version 2 (snapshot of V2)
        resp = client.post(f"/api/plans/{plan_id}/save", json={
            "content": PLAN_V3,
            "change_source": "ai_refine",
        })
        assert resp.status_code == 200
        print(f"  ✓ Saved V3")

        resp = client.get(f"/api/plans/{plan_id}/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2, f"Expected 2 versions, got {data['count']}"
        # Versions should be sorted desc
        assert data["versions"][0]["version"] == 2
        assert data["versions"][1]["version"] == 1
        assert data["versions"][0]["change_source"] == "ai_refine"
        print(f"  ✓ Version 2 created, list sorted correctly")

        # 6. Fetch specific version
        resp = client.get(f"/api/plans/{plan_id}/versions/1")
        assert resp.status_code == 200
        v1_detail = resp.json()["version"]
        assert v1_detail["version"] == 1
        assert "Initial Setup" in v1_detail["content"], "V1 content should have EPIC-001"
        assert "EPIC-002" not in v1_detail["content"], "V1 content should NOT have EPIC-002"
        print(f"  ✓ Version 1 content is correct (original V1)")

        resp = client.get(f"/api/plans/{plan_id}/versions/2")
        assert resp.status_code == 200
        v2_detail = resp.json()["version"]
        assert "EPIC-002" in v2_detail["content"], "V2 content should have EPIC-002"
        print(f"  ✓ Version 2 content is correct (V2 with two epics)")

        # 7. Save the canonical current content again → should NOT create a version
        resp = client.get(f"/api/plans/{plan_id}")
        assert resp.status_code == 200
        current_content = resp.json()["plan"]["content"]

        resp = client.post(f"/api/plans/{plan_id}/save", json={
            "content": current_content,
            "change_source": "manual_save",
        })
        assert resp.status_code == 200
        resp = client.get(f"/api/plans/{plan_id}/versions")
        assert resp.json()["count"] == 2, "No-op save should not create version"
        print(f"  ✓ No-op save (same content) does not create a version")

    print(f"\n✅ test_version_snapshot_on_save PASSED for {plan_id}")
    return True


def test_restore_version(fake_version_store):
    """Restoring a version should set it as current and snapshot the previous current."""
    with TestClient(app, headers=HEADERS) as client:
        # 1. Create and populate
        resp = client.post("/api/plans/create", json={
            "path": "/tmp/test-restore",
            "title": "Restore Test",
            "content": PLAN_V1,
            "working_dir": "/tmp/test-restore",
        })
        plan_id = resp.json()["plan_id"]

        # Save V2 (creates version 1 = snapshot of V1)
        client.post(f"/api/plans/{plan_id}/save", json={"content": PLAN_V2})
        # Save V3 (creates version 2 = snapshot of V2)
        client.post(f"/api/plans/{plan_id}/save", json={"content": PLAN_V3})
        print(f"  ✓ Set up plan {plan_id} with 2 versions")

        # 2. Restore version 1 (original V1 content)
        resp = client.post(f"/api/plans/{plan_id}/versions/1/restore")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "restored"
        assert data["restored_version"] == 1
        print(f"  ✓ Restored version 1")

        # 3. Current plan content should now be V1
        resp = client.get(f"/api/plans/{plan_id}")
        current = resp.json()["plan"]["content"]
        assert "Initial Setup" in current, "Current content should match V1"
        assert "EPIC-002" not in current, "Current should NOT have EPIC-002 from V2"
        print(f"  ✓ Current content matches restored version")

        # 4. A new version should have been created (snapshot of V3 before restore)
        resp = client.get(f"/api/plans/{plan_id}/versions")
        data = resp.json()
        assert data["count"] == 3, f"Expected 3 versions after restore, got {data['count']}"
        # Latest version should have change_source "before_restore"
        latest = data["versions"][0]
        assert latest["change_source"] == "before_restore"
        print(f"  ✓ Version 3 created with 'before_restore' source")

        # 5. 404 for non-existent version
        resp = client.get(f"/api/plans/{plan_id}/versions/999")
        assert resp.status_code == 404
        print(f"  ✓ 404 for non-existent version")

    print(f"\n✅ test_restore_version PASSED for {plan_id}")
    return True


def main():
    print(f"Testing against: {DASHBOARD_URL}")
    print()

    # Health check
    try:
        resp = httpx.get(f"{DASHBOARD_URL}/api/status", timeout=5)
        if resp.status_code != 200:
            print(f"⚠ Dashboard returned {resp.status_code} for /api/status")
    except httpx.ConnectError:
        print(f"✗ Cannot connect to {DASHBOARD_URL}. Is the dashboard running?")
        print(f"  Start with: ostwin dashboard")
        sys.exit(1)

    tests = [
        ("version_snapshot_on_save", test_version_snapshot_on_save),
        ("restore_version", test_restore_version),
    ]

    passed = 0
    failed = 0
    for name, test_fn in tests:
        print(f"--- Test: {name} ---")
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"\n✗ FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"\n✗ ERROR: {e}")
            failed += 1
        print()

    print(f"{'='*50}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    if failed:
        print("❌ Some tests failed!")
        sys.exit(1)
    else:
        print("🎉 All tests passed!")


if __name__ == "__main__":
    main()
