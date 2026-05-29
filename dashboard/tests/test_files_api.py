import json
import base64
import pytest
from fastapi.testclient import TestClient
from dashboard.api import app
from dashboard.auth import get_current_user

async def mock_get_current_user():
    return {"user_id": "test_user"}

app.dependency_overrides[get_current_user] = mock_get_current_user

@pytest.fixture
def test_workspace(tmp_path):
    working_dir = tmp_path / "workspace"
    working_dir.mkdir()
    
    (working_dir / "src").mkdir()
    (working_dir / "src" / "main.py").write_text("print('hello')", encoding="utf-8")
    (working_dir / "README.md").write_text("# Project", encoding="utf-8")
    (working_dir / "data.bin").write_bytes(b"\x80\x81\x82")
    (working_dir / "data.csv").write_text("name,age\nAlice,30\nBob,25", encoding="utf-8")
    (working_dir / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    plan_id = "test-plan"
    meta = {
        "plan_id": plan_id,
        "working_dir": str(working_dir)
    }
    (plans_dir / f"{plan_id}.meta.json").write_text(json.dumps(meta))
    
    return {
        "working_dir": working_dir,
        "plans_dir": plans_dir,
        "plan_id": plan_id
    }

def test_list_files(test_workspace, monkeypatch):
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files")
    assert response.status_code == 200
    data = response.json()
    assert data["path"] == ""
    assert len(data["entries"]) == 5
    
    names = [e["name"] for e in data["entries"]]
    assert "src" in names
    assert "README.md" in names
    assert "data.bin" in names
    assert "data.csv" in names
    assert "photo.png" in names
    
    # Check sorting (dirs first)
    assert data["entries"][0]["name"] == "src"

def test_list_files_subdir(test_workspace, monkeypatch):
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files?path=src")
    assert response.status_code == 200
    data = response.json()
    assert data["path"] == "src"
    assert len(data["entries"]) == 1
    assert data["entries"][0]["name"] == "main.py"

def test_file_browser_ignores_standard_generated_entries(test_workspace, monkeypatch):
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)

    ignored_dirs = [
        ".opencode", ".codegraph", "node_modules", ".next", "__pycache__",
        ".pytest_cache", ".ruff_cache", ".gradle", "target", "dist",
        "build", "coverage",
    ]
    for dirname in ignored_dirs:
        generated_dir = test_workspace["working_dir"] / dirname
        generated_dir.mkdir()
        (generated_dir / "generated.txt").write_text("ignore me", encoding="utf-8")
        if dirname == ".next":
            (generated_dir / "server").mkdir()

    for filename in [
        "module.pyc", "Example.class", "npm-debug.log", ".eslintcache",
        "types.tsbuildinfo", "debug.log",
    ]:
        (test_workspace["working_dir"] / filename).write_text("ignore me", encoding="utf-8")

    (test_workspace["working_dir"] / ".gitignore").write_text("node_modules\n", encoding="utf-8")
    (test_workspace["working_dir"] / "src" / "__pycache__").mkdir()
    (test_workspace["working_dir"] / "src" / "main.pyc").write_text("ignore me", encoding="utf-8")

    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files")
    assert response.status_code == 200
    names = [entry["name"] for entry in response.json()["entries"]]

    for hidden_name in ignored_dirs + [
        "module.pyc", "Example.class", "npm-debug.log", ".eslintcache",
        "types.tsbuildinfo", "debug.log",
    ]:
        assert hidden_name not in names

    # Ignore config files are still useful project files; generated artifacts are hidden.
    assert ".gitignore" in names

    src_entry = next(entry for entry in response.json()["entries"] if entry["name"] == "src")
    assert src_entry["children_count"] == 1

    src_response = client.get(f"/api/plans/{test_workspace['plan_id']}/files?path=src")
    assert src_response.status_code == 200
    assert [entry["name"] for entry in src_response.json()["entries"]] == ["main.py"]

    ignored_response = client.get(f"/api/plans/{test_workspace['plan_id']}/files?path=.next")
    assert ignored_response.status_code == 200
    assert ignored_response.json()["entries"] == []

    nested_ignored_response = client.get(f"/api/plans/{test_workspace['plan_id']}/files?path=.next/server")
    assert nested_ignored_response.status_code == 200
    assert nested_ignored_response.json()["entries"] == []

    tree_response = client.get(f"/api/plans/{test_workspace['plan_id']}/files/tree")
    assert tree_response.status_code == 200
    tree_names = [entry["name"] for entry in tree_response.json()["tree"]]
    assert ".opencode" not in tree_names
    assert ".codegraph" not in tree_names
    assert "node_modules" not in tree_names
    assert ".next" not in tree_names


def test_get_content_text(test_workspace, monkeypatch):
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files/content?path=README.md")
    assert response.status_code == 200
    data = response.json()
    assert data["content"] == "# Project"
    assert data["encoding"] == "utf-8"
    assert data["truncated"] is False
    assert "download_url" in data
    assert "/download" in data["download_url"]

def test_get_content_binary(test_workspace, monkeypatch):
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files/content?path=data.bin")
    assert response.status_code == 200
    data = response.json()
    assert data["content"] == base64.b64encode(b"\x80\x81\x82").decode("utf-8")
    assert data["encoding"] == "base64"
    assert "download_url" in data

def test_get_content_csv_forced_base64(test_workspace, monkeypatch):
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files/content?path=data.csv")
    assert response.status_code == 200
    data = response.json()
    assert data["encoding"] == "base64"
    assert data["truncated"] is False
    decoded = base64.b64decode(data["content"]).decode("utf-8")
    assert "name,age" in decoded

def test_get_content_binary_extension_skip_utf8(test_workspace, monkeypatch):
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files/content?path=photo.png")
    assert response.status_code == 200
    data = response.json()
    assert data["encoding"] == "base64"
    assert data["mime_type"] == "image/png"

def test_get_content_large_text_partial(test_workspace, monkeypatch):
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    large_file = test_workspace["working_dir"] / "large.txt"
    large_file.write_text("A" * (2 * 1024 * 1024 + 1))
    
    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files/content?path=large.txt")
    assert response.status_code == 200
    data = response.json()
    assert data["content"] is not None
    assert data["encoding"] == "utf-8"
    assert data["truncated"] is True
    assert len(data["content"]) > 0

def test_get_content_large_binary_null(test_workspace, monkeypatch):
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    large_bin = test_workspace["working_dir"] / "large.pdf"
    large_bin.write_bytes(b"\x00" * (2 * 1024 * 1024 + 1))
    
    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files/content?path=large.pdf")
    assert response.status_code == 200
    data = response.json()
    assert data["content"] is None
    assert data["truncated"] is True
    assert data["encoding"] == "base64"
    assert "download_url" in data

def test_get_tree(test_workspace, monkeypatch):
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files/tree")
    assert response.status_code == 200
    data = response.json()
    assert "tree" in data
    assert len(data["tree"]) > 0
    
    # Find 'src' in tree
    src_node = next((n for n in data["tree"] if n["name"] == "src"), None)
    assert src_node is not None
    assert "children" in src_node
    assert src_node["children"][0]["name"] == "main.py"

def test_path_traversal(test_workspace, monkeypatch):
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files?path=../../")
    assert response.status_code == 403
    assert "traversal" in response.json()["detail"].lower()

def test_git_changes_repo(test_workspace, monkeypatch):
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    # Init git
    import subprocess
    subprocess.run(["git", "init"], cwd=str(test_workspace["working_dir"]), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(test_workspace["working_dir"]), check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=str(test_workspace["working_dir"]), check=True)
    subprocess.run(["git", "add", "."], cwd=str(test_workspace["working_dir"]), check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(test_workspace["working_dir"]), check=True)
    
    # Make a change
    (test_workspace["working_dir"] / "new.txt").write_text("new file")
    
    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files/changes")
    assert response.status_code == 200
    data = response.json()
    assert data["git_enabled"] is True
    assert len(data["status"]) > 0
    assert "new.txt" in data["status"][0]
    assert len(data["recent_commits"]) == 1
    assert data["recent_commits"][0]["subject"] == "Initial commit"

def test_download_file(test_workspace, monkeypatch):
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files/download?path=README.md")
    assert response.status_code == 200
    assert response.content == b"# Project"
    assert "attachment" in response.headers.get("content-disposition", "")

def test_download_binary_file(test_workspace, monkeypatch):
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files/download?path=data.bin")
    assert response.status_code == 200
    assert response.content == b"\x80\x81\x82"

def test_download_nonexistent_file(test_workspace, monkeypatch):
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files/download?path=nonexistent.txt")
    assert response.status_code == 400

# ═══════════════════════════════════════════════════════════
# Security regression tests
# ═══════════════════════════════════════════════════════════

def test_path_traversal_prefix_bypass(test_workspace, monkeypatch):
    """Verify that string-prefix path traversal is blocked.
    
    Attack: a path like '../../workspace_evil' could bypass a naive
    str(target).startswith(str(working_dir)) check if a sibling
    directory shares the same prefix (e.g. /home/user/workspace_evil
    starts with /home/user/workspace).
    """
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    # Create a sibling dir that shares the prefix
    evil_dir = test_workspace["working_dir"].parent / (test_workspace["working_dir"].name + "_evil")
    evil_dir.mkdir()
    (evil_dir / "secrets.txt").write_text("stolen!", encoding="utf-8")
    
    response = client.get(
        f"/api/plans/{test_workspace['plan_id']}/files/content?path=../"
        + test_workspace["working_dir"].name + "_evil/secrets.txt"
    )
    assert response.status_code == 403

def test_symlink_escape_blocked(test_workspace, monkeypatch):
    """Verify that symlinks pointing outside working_dir are blocked."""
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    # Create a symlink inside workspace pointing to /etc/passwd (or /tmp)
    link_path = test_workspace["working_dir"] / "escape_link"
    try:
        link_path.symlink_to("/etc/passwd")
    except OSError:
        # If /etc/passwd doesn't exist on this system, skip
        link_path.symlink_to("/tmp")
    
    response = client.get(
        f"/api/plans/{test_workspace['plan_id']}/files/content?path=escape_link"
    )
    assert response.status_code == 403
    assert "symlink" in response.json()["detail"].lower() or "traversal" in response.json()["detail"].lower()

def test_sensitive_file_blocked_content(test_workspace, monkeypatch):
    """Verify that .env files cannot be read via /content."""
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    (test_workspace["working_dir"] / ".env").write_text("SECRET_KEY=supersecret", encoding="utf-8")
    
    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files/content?path=.env")
    assert response.status_code == 403
    assert "restricted" in response.json()["detail"].lower()

def test_sensitive_file_blocked_download(test_workspace, monkeypatch):
    """Verify that .env files cannot be downloaded via /download."""
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    (test_workspace["working_dir"] / ".env").write_text("SECRET_KEY=supersecret", encoding="utf-8")
    
    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files/download?path=.env")
    assert response.status_code == 403

def test_sensitive_ssh_key_blocked(test_workspace, monkeypatch):
    """Verify that SSH private keys cannot be accessed."""
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    ssh_dir = test_workspace["working_dir"] / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "id_rsa").write_text("-----BEGIN RSA PRIVATE KEY-----\nFAKE", encoding="utf-8")
    
    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files/content?path=.ssh/id_rsa")
    assert response.status_code == 403

def test_download_security_headers(test_workspace, monkeypatch):
    """Verify that /download includes security headers."""
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files/download?path=README.md")
    assert response.status_code == 200
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert "default-src 'none'" in response.headers.get("content-security-policy", "")

def test_error_message_no_path_leak(test_workspace, monkeypatch):
    """Verify that error messages don't leak filesystem paths."""
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    # This should return a generic error, not a path
    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files?path=../../")
    assert response.status_code == 403
    assert str(test_workspace["working_dir"]) not in response.json().get("detail", "")

# ═══════════════════════════════════════════════════════════
# New security regression tests (2026-05-14 batch)
# ═══════════════════════════════════════════════════════════

def test_env_variant_blocked(test_workspace, monkeypatch):
    """P1-6: Verify that .env.production.local is blocked by pattern matching."""
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    (test_workspace["working_dir"] / ".env.production.local").write_text("SECRET=leaked", encoding="utf-8")
    
    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files/content?path=.env.production.local")
    assert response.status_code == 403

def test_env_backup_blocked(test_workspace, monkeypatch):
    """P1-6: Verify that .env.backup is blocked by pattern matching."""
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    (test_workspace["working_dir"] / ".env.backup").write_text("SECRET=leaked", encoding="utf-8")
    
    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files/content?path=.env.backup")
    assert response.status_code == 403

def test_null_byte_in_path_rejected(test_workspace, monkeypatch):
    """P3-22: Verify that null bytes in paths are rejected."""
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files/content?path=README.md%00.txt")
    assert response.status_code == 400
    assert "null byte" in response.json()["detail"].lower()

def test_content_security_headers(test_workspace, monkeypatch):
    """P3-21: Verify that /content includes security headers."""
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", test_workspace["plans_dir"])
    client = TestClient(app)
    
    response = client.get(f"/api/plans/{test_workspace['plan_id']}/files/content?path=README.md")
    assert response.status_code == 200
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"

def test_working_dir_system_escape_blocked(tmp_path, monkeypatch):
    """P1-8: Verify that working_dir pointing to /etc is rejected."""
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    plan_id = "evil-plan"
    meta = {"plan_id": plan_id, "working_dir": "/etc"}
    (plans_dir / f"{plan_id}.meta.json").write_text(json.dumps(meta))
    
    monkeypatch.setattr("dashboard.routes.files.PLANS_DIR", plans_dir)
    client = TestClient(app)
    
    response = client.get(f"/api/plans/{plan_id}/files/content?path=passwd")
    assert response.status_code == 403

def test_shell_endpoint_requires_auth(test_workspace, monkeypatch):
    """P0-1: Verify that /api/shell requires authentication.
    
    Since our test fixture overrides get_current_user, we temporarily
    restore the real auth dependency for this test.
    """
    # Remove the mock auth override to test the real auth behavior
    if get_current_user in app.dependency_overrides:
        saved_override = app.dependency_overrides.pop(get_current_user)
        try:
            client = TestClient(app)
            # Without auth should get 401
            response = client.post("/api/shell?command=echo+pwned")
            assert response.status_code == 401
        finally:
            # Restore the mock
            app.dependency_overrides[get_current_user] = saved_override
    else:
        # If no override exists, just verify the endpoint exists and requires auth
        client = TestClient(app)
        response = client.post("/api/shell?command=echo+pwned")
        assert response.status_code == 401
