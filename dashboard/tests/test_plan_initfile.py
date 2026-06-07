"""
test_plan_initfile.py — Verify that /api/plans/create correctly uses
user-provided markdown content (simulating New-Plan.ps1 -InitFile)
and falls back to the API default template when no content is given.

This tests the contract that New-Plan.ps1 depends on:
  - When -InitFile is provided → content field is sent → API stores it verbatim
  - When -InitFile is NOT provided → no content field → API generates default

Usage:
    python test_plan_initfile.py
    DASHBOARD_URL=http://localhost:9001 python test_plan_initfile.py
"""

import os
import sys
import httpx
from fastapi.testclient import TestClient
from dashboard.api import app
from dotenv import load_dotenv
from pathlib import Path as pathlib_Path

_env = pathlib_Path.home() / ".ostwin" / ".env"
if _env.is_file():
    load_dotenv(_env, override=True)
import time

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://localhost:3366")
TEST_API_KEY = "test-key"


# --------------------------------------------------------------------------
# Fixtures: sample markdown content (what a user's InitFile would contain)
# --------------------------------------------------------------------------

SAMPLE_INIT_CONTENT = """# Plan: Migrate Auth to OAuth2

> Created: 2026-03-16T00:00:00Z
> Status: draft
> Project: /tmp/test-initfile

---

## Goal

Migrate the authentication system from session-based to OAuth2/OIDC.

## Epics

### EPIC-001 — OAuth2 Provider Setup

Roles: engineer:be
Working_dir: backend/auth

#### Definition of Done
- [ ] OAuth2 provider configured (Google, GitHub)
- [ ] Token refresh flow implemented
- [ ] Existing sessions migrated

#### Tasks
- [ ] TASK-001 — Configure OAuth2 provider
- [ ] TASK-002 — Implement token exchange
- [ ] TASK-003 — Session migration script

### EPIC-002 — Frontend Login Flow

Roles: engineer:fe
Working_dir: frontend/src

#### Definition of Done
- [ ] Login page updated with OAuth2 buttons
- [ ] Token storage in secure cookies

#### Tasks
- [ ] TASK-001 — Update login UI
- [ ] TASK-002 — Implement PKCE flow
"""

# A unique marker embedded in the content so we can prove
# the API stored the user's file, NOT a generated template.
UNIQUE_MARKER = "OAuth2/OIDC"
DEFAULT_TEMPLATE_MARKER = "## Config"  # present in API's default template


def test_create_with_initfile_content():
    """When content is provided, the API should store it verbatim — not the default template."""
    title = "Migrate Auth to OAuth2"
    working_dir = "/tmp/test-initfile"

    HEADERS = {"X-API-Key": TEST_API_KEY}
    with TestClient(app, headers=HEADERS) as client:
        # --- 1. Create plan WITH content (simulates -InitFile) ---
        resp = client.post("/api/plans/create", json={
            "path": working_dir,
            "title": title,
            "content": SAMPLE_INIT_CONTENT,
            "working_dir": working_dir,
        })
        assert resp.status_code == 200, f"Create failed: {resp.status_code} {resp.text}"
        data = resp.json()
        plan_id = data.get("plan_id")
        assert plan_id, f"No plan_id in response: {data}"
        print(f"  ✓ Created plan with content: {plan_id}")

        # --- 2. Verify response shape ---
        assert "url" in data, f"Missing 'url' in response: {data}"
        assert "filename" in data, f"Missing 'filename' in response: {data}"
        assert data["filename"] == f"{plan_id}.md", f"Unexpected filename: {data['filename']}"
        print(f"  ✓ Response shape OK")

        # --- 3. GET the plan and verify content was stored verbatim ---
        resp = client.get(f"/api/plans/{plan_id}")
        assert resp.status_code == 200, f"GET failed: {resp.status_code} {resp.text}"
        get_data = resp.json()
        plan_obj = get_data.get("plan", {})

        assert plan_obj.get("plan_id") == plan_id
        stored_content = plan_obj.get("content", "")

        # Must contain the unique marker from user's file
        assert UNIQUE_MARKER in stored_content, (
            f"User's content marker '{UNIQUE_MARKER}' not found in stored plan.\n"
            f"Stored content (first 300 chars): {stored_content[:300]}"
        )
        print(f"  ✓ Stored content contains user's markdown content")

        # Must NOT contain the API's default template marker
        assert DEFAULT_TEMPLATE_MARKER not in stored_content, (
            f"API default template marker '{DEFAULT_TEMPLATE_MARKER}' found — "
            f"content should be user's file, not the default template"
        )
        print(f"  ✓ Stored content does NOT contain default template")

        # --- 4. Verify EPIC-002 is present (multi-epic file preserved) ---
        assert "EPIC-002" in stored_content, (
            "Multi-epic structure not preserved — EPIC-002 missing from stored content"
        )
        print(f"  ✓ Multi-epic structure preserved")

        # --- 5. Verify specific content sections survived round-trip ---
        assert "engineer:be" in stored_content, "Role assignment 'engineer:be' not preserved"
        assert "engineer:fe" in stored_content, "Role assignment 'engineer:fe' not preserved"
        assert "backend/auth" in stored_content, "Working_dir 'backend/auth' not preserved"
        assert "frontend/src" in stored_content, "Working_dir 'frontend/src' not preserved"
        assert "PKCE flow" in stored_content, "Task detail 'PKCE flow' not preserved"
        print(f"  ✓ All content sections survived API round-trip")

        # --- 6. Verify meta has correct title and working_dir ---
        meta = plan_obj.get("meta", {})
        assert meta.get("plan_id") == plan_id, f"meta plan_id mismatch"
        assert meta.get("title") == title, f"meta title mismatch: {meta.get('title')}"
        assert meta.get("working_dir") == working_dir, f"meta working_dir mismatch"
        assert meta.get("status") == "draft", f"meta status should be 'draft', got: {meta.get('status')}"
        print(f"  ✓ meta.json has correct title, working_dir, and status")

    print(f"\n✅ test_create_with_initfile_content PASSED")
    return True


def test_create_without_content_uses_default():
    """When no content is provided, the API should generate its own default template."""
    title = f"Default Template Test {int(time.time())}"
    working_dir = "/tmp/test-no-initfile"

    HEADERS = {"X-API-Key": TEST_API_KEY}
    with TestClient(app, headers=HEADERS) as client:
        # --- 1. Create plan WITHOUT content (no -InitFile) ---
        resp = client.post("/api/plans/create", json={
            "path": working_dir,
            "title": title,
            "working_dir": working_dir,
            # NO "content" field — simulates ostwin plan create "Title" without --file
        })
        assert resp.status_code == 200, f"Create failed: {resp.status_code} {resp.text}"
        data = resp.json()
        plan_id = data.get("plan_id")
        assert plan_id, f"No plan_id in response: {data}"
        print(f"  ✓ Created plan without content: {plan_id}")

        # --- 2. GET the plan and verify API generated default content ---
        resp = client.get(f"/api/plans/{plan_id}")
        assert resp.status_code == 200, f"GET failed: {resp.status_code} {resp.text}"
        get_data = resp.json()
        plan_obj = get_data.get("plan", {})
        stored_content = plan_obj.get("content", "")

        # Must contain the title
        assert title in stored_content, (
            f"Title '{title}' not found in API-generated content"
        )
        print(f"  ✓ API default content includes the title")

        # Must contain the API's default template markers
        assert DEFAULT_TEMPLATE_MARKER in stored_content, (
            f"API default template marker '{DEFAULT_TEMPLATE_MARKER}' not found — "
            f"API should generate its own default when no content is provided"
        )
        print(f"  ✓ API generated its own default template")

        # Must NOT contain the user's unique marker
        assert UNIQUE_MARKER not in stored_content, (
            f"User marker '{UNIQUE_MARKER}' found in default plan — unexpected"
        )
        print(f"  ✓ Default plan does not contain user-specific content")

        # --- 3. Verify the placeholder drafting state is present ---
        assert "AI worker is drafting the plan structure" in stored_content, (
            "Default plan missing drafting placeholder"
        )
        print(f"  ✓ Default plan has drafting placeholder")

    print(f"\n✅ test_create_without_content_uses_default PASSED")
    return True


def test_content_with_explicit_title_override():
    """When both content and a different title are given, title should come from the request."""
    override_title = f"Override Title {int(time.time())}"
    working_dir = "/tmp/test-title-override"

    HEADERS = {"X-API-Key": TEST_API_KEY}
    with TestClient(app, headers=HEADERS) as client:
        resp = client.post("/api/plans/create", json={
            "path": working_dir,
            "title": override_title,               # explicit title
            "content": SAMPLE_INIT_CONTENT,         # file has its own title
            "working_dir": working_dir,
        })
        assert resp.status_code == 200, f"Create failed: {resp.status_code} {resp.text}"
        data = resp.json()
        plan_id = data.get("plan_id")
        assert plan_id, f"No plan_id in response: {data}"
        print(f"  ✓ Created plan with title override: {plan_id}")

        # --- GET and verify ---
        resp = client.get(f"/api/plans/{plan_id}")
        assert resp.status_code == 200, f"GET failed: {resp.status_code} {resp.text}"
        plan_obj = resp.json().get("plan", {})

        # meta should have the explicit title, not the in-file title
        meta = plan_obj.get("meta", {})
        assert meta.get("title") == override_title, (
            f"Expected title '{override_title}', got '{meta.get('title')}'"
        )
        print(f"  ✓ meta uses the explicit title override")

        # Content should still be the user's file content
        stored_content = plan_obj.get("content", "")
        assert UNIQUE_MARKER in stored_content, (
            "Even with title override, content should be the user's file"
        )
        print(f"  ✓ Content still uses user's file despite title override")

    print(f"\n✅ test_content_with_explicit_title_override PASSED")
    return True


def test_empty_content_treated_as_no_content():
    """When content is an empty string, API should treat it as no content and use default."""
    title = f"Empty Content Test {int(time.time())}"
    working_dir = "/tmp/test-empty-content"

    HEADERS = {"X-API-Key": TEST_API_KEY}
    with TestClient(app, headers=HEADERS) as client:
        resp = client.post("/api/plans/create", json={
            "path": working_dir,
            "title": title,
            "content": "",  # empty string, not None
            "working_dir": working_dir,
        })
        assert resp.status_code == 200, f"Create failed: {resp.status_code} {resp.text}"
        data = resp.json()
        plan_id = data.get("plan_id")
        assert plan_id, f"No plan_id in response: {data}"
        print(f"  ✓ Created plan with empty content: {plan_id}")

        # --- GET and verify API used its default ---
        resp = client.get(f"/api/plans/{plan_id}")
        assert resp.status_code == 200, f"GET failed: {resp.status_code} {resp.text}"
        stored_content = resp.json().get("plan", {}).get("content", "")

        # Empty string is falsy → API should use its default template
        assert DEFAULT_TEMPLATE_MARKER in stored_content, (
            "Empty content should trigger API's default template generation"
        )
        print(f"  ✓ Empty content correctly falls back to API default")

    print(f"\n✅ test_empty_content_treated_as_no_content PASSED")
    return True


def test_content_gets_plan_header_without_extra_sections():
    """API normalizes the plan header without injecting unrelated sections."""
    # Minimal markdown — no "# Plan:" header, no "## Config" section
    minimal_content = "# My Custom Plan\n\nJust some notes.\n\n## Tasks\n- [ ] Do something\n"
    title = f"Minimal Content Test {int(time.time())}"
    working_dir = "/tmp/test-minimal"

    HEADERS = {"X-API-Key": TEST_API_KEY}
    with TestClient(app, headers=HEADERS) as client:
        resp = client.post("/api/plans/create", json={
            "path": working_dir,
            "title": title,
            "content": minimal_content,
            "working_dir": working_dir,
        })
        assert resp.status_code == 200, f"Create failed: {resp.status_code} {resp.text}"
        plan_id = resp.json().get("plan_id")
        print(f"  ✓ Created plan with minimal content: {plan_id}")

        # --- GET and verify content was not augmented ---
        resp = client.get(f"/api/plans/{plan_id}")
        assert resp.status_code == 200
        stored_content = resp.json().get("plan", {}).get("content", "")

        assert stored_content.startswith(f"# Plan: {title}\n\n")
        assert "# My Custom Plan" in stored_content
        assert "Just some notes." in stored_content
        assert "## Tasks\n- [ ] Do something" in stored_content
        assert "## Config" not in stored_content
        print(f"  ✓ Content got a plan header without unrelated sections")

    print(f"\n✅ test_content_not_mutated_by_api PASSED")
    return True


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

def main():
    print(f"Testing against: {DASHBOARD_URL}")
    print()

    # Quick health check
    try:
        resp = httpx.get(f"{DASHBOARD_URL}/api/status", timeout=5)
        if resp.status_code != 200:
            print(f"⚠ Dashboard returned {resp.status_code} for /api/status")
    except httpx.ConnectError:
        print(f"✗ Cannot connect to {DASHBOARD_URL}. Is the dashboard running?")
        print(f"  Start with: ostwin dashboard")
        sys.exit(1)

    tests = [
        ("create_with_initfile_content", test_create_with_initfile_content),
        ("create_without_content_uses_default", test_create_without_content_uses_default),
        ("content_with_explicit_title_override", test_content_with_explicit_title_override),
        ("empty_content_treated_as_no_content", test_empty_content_treated_as_no_content),
        ("content_gets_plan_header_without_extra_sections", test_content_gets_plan_header_without_extra_sections),
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
