#!/usr/bin/env python3
"""Tests for the Chrome DevTools MCP adapter (pure unit tests, no browser launch)."""

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path


def _load_chrome_devtools_server():
    """Load the MCP adapter module from its stable file path."""
    spec = importlib.util.spec_from_file_location(
        "chrome_devtools_server",
        Path(__file__).parent / "obscura-browser-server.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestSanitizeFilename:
    """Tests for _sanitize_filename helper."""

    def test_basic_filename(self):
        module = _load_chrome_devtools_server()
        assert module._sanitize_filename("document.pdf") == "document.pdf"
        assert module._sanitize_filename("image.png") == "image.png"
        assert module._sanitize_filename("file.txt") == "file.txt"

    def test_removes_forward_slash(self):
        """Cross-platform: strips / on all OSes."""
        module = _load_chrome_devtools_server()
        assert module._sanitize_filename("path/to/file.pdf") == "file.pdf"
        assert module._sanitize_filename("deep/nested/path/file.pdf") == "file.pdf"

    def test_removes_backslash(self):
        """Cross-platform: strips \\ on all OSes."""
        module = _load_chrome_devtools_server()
        assert module._sanitize_filename("path\\to\\file.pdf") == "file.pdf"
        assert module._sanitize_filename("C\\Users\\file.pdf") == "file.pdf"

    def test_removes_both_separators(self):
        """Cross-platform: strips both / and \\ on all OSes."""
        module = _load_chrome_devtools_server()
        assert module._sanitize_filename("path/to\\file.pdf") == "file.pdf"
        assert module._sanitize_filename("a/b\\c/d\\e.pdf") == "e.pdf"

    def test_removes_parent_references(self):
        module = _load_chrome_devtools_server()
        assert module._sanitize_filename("....secret") == "secret"
        assert module._sanitize_filename("..file.pdf") == "file.pdf"

    def test_removes_special_characters(self):
        module = _load_chrome_devtools_server()
        assert module._sanitize_filename("file<script>.pdf") == "file_script_.pdf"
        assert module._sanitize_filename("file|pipe.pdf") == "file_pipe.pdf"
        assert module._sanitize_filename("file:colon.pdf") == "file_colon.pdf"

    def test_empty_filename(self):
        module = _load_chrome_devtools_server()
        assert module._sanitize_filename("") == "download"
        assert module._sanitize_filename("   ") == "download"

    def test_dot_only_filename(self):
        module = _load_chrome_devtools_server()
        assert module._sanitize_filename(".") == "download"
        assert module._sanitize_filename("..") == "download"
        assert module._sanitize_filename("...") == "download"

    def test_max_length_preserves_extension(self):
        module = _load_chrome_devtools_server()
        long_name = "a" * 500 + ".pdf"
        result = module._sanitize_filename(long_name)
        assert len(result) == 255
        assert result.endswith(".pdf")

    def test_max_length_no_extension(self):
        module = _load_chrome_devtools_server()
        long_name = "a" * 500
        result = module._sanitize_filename(long_name)
        assert len(result) == 255

    def test_unicode_filename(self):
        module = _load_chrome_devtools_server()
        result = module._sanitize_filename("文档.pdf")
        assert ".pdf" in result


class TestIsSafeDownloadPath:
    """Tests for _is_safe_download_path helper."""

    def test_valid_path(self):
        module = _load_chrome_devtools_server()
        with tempfile.TemporaryDirectory() as tmpdir:
            assert module._is_safe_download_path(tmpdir, os.path.join(tmpdir, "file.pdf"))
            assert module._is_safe_download_path(tmpdir, os.path.join(tmpdir, "subdir", "file.pdf"))

    def test_blocks_parent_traversal(self):
        module = _load_chrome_devtools_server()
        with tempfile.TemporaryDirectory() as tmpdir:
            parent_dir = os.path.dirname(tmpdir)
            outside_path = os.path.join(parent_dir, "outside.pdf")
            assert not module._is_safe_download_path(tmpdir, outside_path)

    def test_blocks_absolute_outside(self):
        module = _load_chrome_devtools_server()
        with tempfile.TemporaryDirectory() as tmpdir:
            other_tmp = tempfile.mkdtemp()
            try:
                assert not module._is_safe_download_path(tmpdir, os.path.join(other_tmp, "file.pdf"))
            finally:
                os.rmdir(other_tmp)

    def test_same_directory(self):
        module = _load_chrome_devtools_server()
        with tempfile.TemporaryDirectory() as tmpdir:
            assert module._is_safe_download_path(tmpdir, tmpdir)


class TestSafeDownloadPath:
    """Tests for _safe_download_path helper."""

    def test_constructs_safe_path(self):
        module = _load_chrome_devtools_server()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = module._safe_download_path(tmpdir, "document.pdf")
            assert result == os.path.join(tmpdir, "document.pdf")

    def test_sanitizes_filename(self):
        module = _load_chrome_devtools_server()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = module._safe_download_path(tmpdir, "file<script>.pdf")
            assert result == os.path.join(tmpdir, "file_script_.pdf")

    def test_path_traversal_sanitized_not_raised(self):
        """Path traversal is prevented by sanitization."""
        module = _load_chrome_devtools_server()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = module._safe_download_path(tmpdir, "../../secret.pdf")
            assert result == os.path.join(tmpdir, "secret.pdf")
            assert module._is_safe_download_path(tmpdir, result)


class TestResolveDownloadDir:
    """Tests for _resolve_download_dir helper."""

    def test_uses_ostwin_browser_download_dir(self):
        module = _load_chrome_devtools_server()
        with tempfile.TemporaryDirectory() as tmpdir:
            old_val = os.environ.get("OSTWIN_BROWSER_DOWNLOAD_DIR")
            try:
                os.environ["OSTWIN_BROWSER_DOWNLOAD_DIR"] = tmpdir
                result = module._resolve_download_dir()
                assert os.path.abspath(result) == os.path.abspath(tmpdir)
            finally:
                if old_val is not None:
                    os.environ["OSTWIN_BROWSER_DOWNLOAD_DIR"] = old_val
                else:
                    os.environ.pop("OSTWIN_BROWSER_DOWNLOAD_DIR", None)

    def test_uses_agent_os_room_dir_fallback(self):
        module = _load_chrome_devtools_server()
        with tempfile.TemporaryDirectory() as tmpdir:
            old_browser = os.environ.get("OSTWIN_BROWSER_DOWNLOAD_DIR")
            old_room = os.environ.get("AGENT_OS_ROOM_DIR")
            try:
                os.environ.pop("OSTWIN_BROWSER_DOWNLOAD_DIR", None)
                os.environ["AGENT_OS_ROOM_DIR"] = tmpdir
                result = module._resolve_download_dir()
                expected = os.path.join(tmpdir, "artifacts", "downloads")
                assert os.path.abspath(result) == os.path.abspath(expected)
            finally:
                if old_browser is not None:
                    os.environ["OSTWIN_BROWSER_DOWNLOAD_DIR"] = old_browser
                else:
                    os.environ.pop("OSTWIN_BROWSER_DOWNLOAD_DIR", None)
                if old_room is not None:
                    os.environ["AGENT_OS_ROOM_DIR"] = old_room
                else:
                    os.environ.pop("AGENT_OS_ROOM_DIR", None)

    def test_creates_directory(self):
        module = _load_chrome_devtools_server()
        with tempfile.TemporaryDirectory() as tmpdir:
            download_path = os.path.join(tmpdir, "new_downloads")
            old_val = os.environ.get("OSTWIN_BROWSER_DOWNLOAD_DIR")
            try:
                os.environ["OSTWIN_BROWSER_DOWNLOAD_DIR"] = download_path
                assert not os.path.exists(download_path)
                result = module._resolve_download_dir()
                assert os.path.exists(download_path)
                assert os.path.isdir(download_path)
            finally:
                if old_val is not None:
                    os.environ["OSTWIN_BROWSER_DOWNLOAD_DIR"] = old_val
                else:
                    os.environ.pop("OSTWIN_BROWSER_DOWNLOAD_DIR", None)

    def test_default_fallback(self):
        module = _load_chrome_devtools_server()
        old_browser = os.environ.get("OSTWIN_BROWSER_DOWNLOAD_DIR")
        old_room = os.environ.get("AGENT_OS_ROOM_DIR")
        old_project = os.environ.get("AGENT_OS_ROOT")
        old_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                try:
                    os.chdir(tmpdir)
                    os.environ.pop("OSTWIN_BROWSER_DOWNLOAD_DIR", None)
                    os.environ.pop("AGENT_OS_ROOM_DIR", None)
                    os.environ.pop("AGENT_OS_ROOT", None)
                    result = module._resolve_download_dir()
                    expected = os.path.join(tmpdir, "artifacts", "browser-downloads")
                    assert os.path.abspath(result) == os.path.abspath(expected)
                finally:
                    os.chdir(old_cwd)
        finally:
            if old_browser is not None:
                os.environ["OSTWIN_BROWSER_DOWNLOAD_DIR"] = old_browser
            else:
                os.environ.pop("OSTWIN_BROWSER_DOWNLOAD_DIR", None)
            if old_room is not None:
                os.environ["AGENT_OS_ROOM_DIR"] = old_room
            else:
                os.environ.pop("AGENT_OS_ROOM_DIR", None)
            if old_project is not None:
                os.environ["AGENT_OS_ROOT"] = old_project
            else:
                os.environ.pop("AGENT_OS_ROOT", None)

    def test_uses_agent_os_root_fallback(self):
        module = _load_chrome_devtools_server()
        with tempfile.TemporaryDirectory() as tmpdir:
            old_browser = os.environ.get("OSTWIN_BROWSER_DOWNLOAD_DIR")
            old_room = os.environ.get("AGENT_OS_ROOM_DIR")
            old_project = os.environ.get("AGENT_OS_ROOT")
            try:
                os.environ.pop("OSTWIN_BROWSER_DOWNLOAD_DIR", None)
                os.environ.pop("AGENT_OS_ROOM_DIR", None)
                os.environ["AGENT_OS_ROOT"] = tmpdir
                result = module._resolve_download_dir()
                expected = os.path.join(tmpdir, "artifacts", "browser-downloads")
                assert os.path.abspath(result) == os.path.abspath(expected)
            finally:
                if old_browser is not None:
                    os.environ["OSTWIN_BROWSER_DOWNLOAD_DIR"] = old_browser
                else:
                    os.environ.pop("OSTWIN_BROWSER_DOWNLOAD_DIR", None)
                if old_room is not None:
                    os.environ["AGENT_OS_ROOM_DIR"] = old_room
                else:
                    os.environ.pop("AGENT_OS_ROOM_DIR", None)
                if old_project is not None:
                    os.environ["AGENT_OS_ROOT"] = old_project
                else:
                    os.environ.pop("AGENT_OS_ROOT", None)


class TestLaunchArgs:
    """Tests for launch arg helpers."""

    def test_default_chrome_devtools_bin_uses_env_override(self, monkeypatch):
        module = _load_chrome_devtools_server()
        monkeypatch.setenv("CHROME_DEVTOOLS_BIN", "/tmp/custom-runtime")
        assert module._default_chrome_devtools_bin() == "/tmp/custom-runtime"

    def test_default_chrome_devtools_bin_supports_legacy_env_override(self, monkeypatch):
        module = _load_chrome_devtools_server()
        monkeypatch.delenv("CHROME_DEVTOOLS_BIN", raising=False)
        monkeypatch.setenv("OBSCURA_BIN", "/tmp/custom-runtime")
        assert module._default_chrome_devtools_bin() == "/tmp/custom-runtime"

    def test_default_chrome_devtools_bin_falls_back_to_command_name(self, monkeypatch):
        module = _load_chrome_devtools_server()
        monkeypatch.delenv("CHROME_DEVTOOLS_BIN", raising=False)
        monkeypatch.delenv("OBSCURA_BIN", raising=False)
        result = module._default_chrome_devtools_bin()
        assert result == "obscura" or result.endswith(("obscura", "obscura.exe"))

    def test_default_args_no_stealth(self):
        """Default launch args must NOT include --stealth."""
        module = _load_chrome_devtools_server()
        args = module._get_default_launch_args(9222)
        assert args == ["serve", "--port", "9222"]
        assert "--stealth" not in args

    def test_build_launch_args_default(self):
        module = _load_chrome_devtools_server()
        args = module._build_launch_args(9222, "")
        assert args == ["serve", "--port", "9222"]
        assert "--stealth" not in args

    def test_build_launch_args_with_custom(self):
        module = _load_chrome_devtools_server()
        args = module._build_launch_args(9222, "--proxy http://localhost:8080")
        assert "serve" in args
        assert "--port" in args
        assert "9222" in args
        assert "--proxy" in args
        assert "http://localhost:8080" in args

    def test_build_launch_args_preserves_quoted_values(self):
        module = _load_chrome_devtools_server()
        args = module._build_launch_args(9222, '--user-agent "Ostwin Browser"')
        assert "--user-agent" in args
        assert "Ostwin Browser" in args

    def test_build_launch_args_rejects_malformed_quotes(self):
        module = _load_chrome_devtools_server()
        import pytest
        with pytest.raises(ValueError):
            module._build_launch_args(9222, '--user-agent "unterminated')

    def test_build_launch_args_with_stealth_explicit(self):
        """User can explicitly add --stealth via CHROME_DEVTOOLS_ARGS."""
        module = _load_chrome_devtools_server()
        args = module._build_launch_args(9222, "--stealth")
        assert "--stealth" in args


class TestCdpEndpointValidation:
    """Tests for CDP endpoint validation helpers."""

    def test_detects_chrome_devtools_browser_field(self):
        module = _load_chrome_devtools_server()
        assert module._is_chrome_devtools_cdp_endpoint({"Browser": "Chrome DevTools/0.1.2"})

    def test_detects_chrome_devtools_user_agent_field(self):
        module = _load_chrome_devtools_server()
        assert module._is_chrome_devtools_cdp_endpoint({"User-Agent": "Mozilla/5.0 Chrome DevTools"})

    def test_detects_legacy_runtime_user_agent_field(self):
        module = _load_chrome_devtools_server()
        assert module._is_chrome_devtools_cdp_endpoint({"User-Agent": "Mozilla/5.0 Obscura"})

    def test_rejects_plain_chrome_endpoint(self):
        module = _load_chrome_devtools_server()
        assert not module._is_chrome_devtools_cdp_endpoint({
            "Browser": "Chrome/124.0.0.0",
            "webSocketDebuggerUrl": "ws://localhost:9222/devtools/browser/abc",
        })

    def test_adapter_started_browser_alive(self, monkeypatch):
        module = _load_chrome_devtools_server()

        class FakeProcess:
            def poll(self):
                return None

        monkeypatch.setattr(module, "_browser_process", FakeProcess())
        assert module._adapter_started_browser_alive()

    def test_adapter_started_browser_exited(self, monkeypatch):
        module = _load_chrome_devtools_server()

        class FakeProcess:
            def poll(self):
                return 1

        monkeypatch.setattr(module, "_browser_process", FakeProcess())
        assert not module._adapter_started_browser_alive()


class TestRefMap:
    """Tests for element ref map helpers."""

    def test_reset_ref_map(self):
        module = _load_chrome_devtools_server()
        module._reset_ref_map()
        module._store_element("@e1", {"role": "button", "name": "Submit"})
        assert len(module._element_ref_map) == 1

        module._reset_ref_map()
        assert len(module._element_ref_map) == 0

    def test_build_ref_sequence(self):
        module = _load_chrome_devtools_server()
        module._reset_ref_map()

        ref1 = module._build_ref()
        ref2 = module._build_ref()
        ref3 = module._build_ref()

        assert ref1 == "@e1"
        assert ref2 == "@e2"
        assert ref3 == "@e3"

    def test_resolve_ref_returns_selector(self):
        module = _load_chrome_devtools_server()
        module._reset_ref_map()

        module._store_element("@e1", {"ref": "@e1", "role": "button", "name": "Submit", "selector": "button:has-text(\"Submit\")"})

        result = module._resolve_ref("@e1")
        assert result == 'button:has-text("Submit")'

    def test_resolve_ref_returns_raw_if_not_found(self):
        module = _load_chrome_devtools_server()
        module._reset_ref_map()

        result = module._resolve_ref("@e999")
        assert result == "@e999"

    def test_resolve_ref_returns_raw_if_not_ref_format(self):
        module = _load_chrome_devtools_server()
        result = module._resolve_ref("button.submit")
        assert result == "button.submit"

    def test_build_elements_from_dom_snapshot(self):
        module = _load_chrome_devtools_server()
        module._reset_ref_map()

        raw_elements = [
            {"role": "button", "name": "Submit", "selector": "button:nth-of-type(1)"},
            {"role": "link", "name": "Learn More", "selector": "a:nth-of-type(1)"},
        ]

        elements = module._build_elements_from_dom_snapshot(raw_elements)

        assert len(elements) == 2

        refs = [e["ref"] for e in elements]
        assert any(r.startswith("@e") for r in refs)
        assert module._resolve_ref("@e1") == "button:nth-of-type(1)"

    def test_build_elements_skips_unusable_items(self):
        module = _load_chrome_devtools_server()
        module._reset_ref_map()

        raw_elements = [
            {"role": "button", "name": "Submit", "selector": ""},
            {"role": "", "name": "", "selector": "button:nth-of-type(1)"},
            {"role": "link", "name": "Docs", "selector": "a:nth-of-type(1)"},
        ]

        elements = module._build_elements_from_dom_snapshot(raw_elements)

        assert len(elements) == 1
        assert elements[0]["name"] == "Docs"


class TestScreenshotFullPage:
    """Tests for browser_screenshot full_page routing logic."""

    def _make_fake_page(self, monkeypatch, module):
        """Set up a fake _page with mocked context and screenshot."""
        fake_page = type("FakePage", (), {})()
        fake_context = type("FakeContext", (), {})()

        async def fake_screenshot(path=None, full_page=False):
            with open(path, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\nfake_image_data_for_testing")

        cdp_sessions = []

        async def fake_new_cdp_session(page):
            session = type("FakeCDP", (), {})()
            session._send_called_with = None
            session._detached = False

            async def fake_send(method, params=None):
                session._send_called_with = (method, params)
                return {"data": base64.b64encode(b"cdp_screenshot_bytes").decode()}

            session.send = fake_send

            async def fake_detach():
                session._detached = True

            session.detach = fake_detach
            cdp_sessions.append(session)
            return session

        fake_page.screenshot = fake_screenshot
        fake_context.new_cdp_session = fake_new_cdp_session
        fake_page.context = fake_context
        monkeypatch.setattr(module, "_page", fake_page)
        return fake_page, cdp_sessions

    def test_full_page_true_uses_playwright_not_cdp(self, monkeypatch, tmp_path):
        module = _load_chrome_devtools_server()
        import asyncio
        import base64

        monkeypatch.setenv("OSTWIN_BROWSER_DOWNLOAD_DIR", str(tmp_path))
        fake_page, cdp_sessions = self._make_fake_page(monkeypatch, module)

        screenshot_calls = []
        original_screenshot = fake_page.screenshot

        async def tracking_screenshot(path=None, full_page=False):
            screenshot_calls.append({"path": path, "full_page": full_page})
            return await original_screenshot(path=path, full_page=full_page)

        fake_page.screenshot = tracking_screenshot

        result = asyncio.run(module.browser_screenshot(path="full.png", full_page=True))
        data = json.loads(result)

        assert data["success"] is True
        assert len(screenshot_calls) == 1
        assert screenshot_calls[0]["full_page"] is True
        assert len(cdp_sessions) == 0

    def test_full_page_false_uses_cdp_path(self, monkeypatch, tmp_path):
        module = _load_chrome_devtools_server()
        import asyncio
        import base64

        monkeypatch.setenv("OSTWIN_BROWSER_DOWNLOAD_DIR", str(tmp_path))
        fake_page, cdp_sessions = self._make_fake_page(monkeypatch, module)

        result = asyncio.run(module.browser_screenshot(path="viewport.png", full_page=False))
        data = json.loads(result)

        assert data["success"] is True
        assert len(cdp_sessions) == 1
        assert cdp_sessions[0]._send_called_with is not None
        assert cdp_sessions[0]._send_called_with[0] == "Page.captureScreenshot"

    def test_full_page_true_cdp_failure_returns_error(self, monkeypatch, tmp_path):
        module = _load_chrome_devtools_server()
        import asyncio

        monkeypatch.setenv("OSTWIN_BROWSER_DOWNLOAD_DIR", str(tmp_path))
        fake_page = type("FakePage", (), {})()

        async def failing_screenshot(path=None, full_page=False):
            raise RuntimeError("Playwright full-page screenshot failed")

        fake_page.screenshot = failing_screenshot
        fake_page.context = type("FakeContext", (), {})()
        monkeypatch.setattr(module, "_page", fake_page)

        result = asyncio.run(module.browser_screenshot(path="full.png", full_page=True))
        data = json.loads(result)

        assert data["success"] is False
        assert "Full-page screenshot failed" in data["error"]


class TestMCPTools:
    """Tests for MCP tool functions (no browser required)."""

    def test_start_browser_returns_dependency_error_without_launch(self, monkeypatch):
        module = _load_chrome_devtools_server()
        import asyncio

        async def fake_ensure_browser():
            return {"running": False, "port": 9222, "error": "playwright not installed"}

        def fail_popen(*_args, **_kwargs):
            raise AssertionError("Popen should not be called when client dependency is missing")

        monkeypatch.setattr(module, "_ensure_browser", fake_ensure_browser)
        monkeypatch.setattr(module.subprocess, "Popen", fail_popen)

        result = asyncio.run(module._start_browser())
        assert result["running"] is False
        assert result["error"] == "playwright not installed"

    def test_browser_close_returns_success(self):
        module = _load_chrome_devtools_server()
        import asyncio
        result = asyncio.run(module.browser_close())
        data = json.loads(result)
        assert data["success"] is True

    def test_browser_health_without_browser(self):
        module = _load_chrome_devtools_server()
        import asyncio
        result = asyncio.run(module.browser_health())
        data = json.loads(result)
        assert "running" in data
        assert "port" in data


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
