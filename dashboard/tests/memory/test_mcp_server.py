"""Unit tests for mcp_server.

Focus areas:
- The `_DropStreamParseErrors` log filter that hides MCP stream-parse noise.
- The monkey-patch of `mcp.server.lowlevel.Server._handle_message` that
  silences "Internal Server Error" notifications when stdin receives junk.
- Helper utilities: `tool_enabled`, `optional_tool`, `_slugify`.
- End-to-end stdio behavior: real subprocess, garbage on stdin, verify
  the client never receives `Internal Server Error` notifications.

These tests deliberately avoid loading the full AgenticMemorySystem (heavy
deps, embedding models, network). The module's background-init thread runs
on import but is a daemon and is allowed to fail silently in tests.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

# Import the module under test. Do this once at module level so the side
# effects (monkey-patch, filter installation) happen exactly once.
from dashboard.memory import mcp_server  # noqa: E402


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SERVER_PATH = os.path.join(REPO_ROOT, "mcp_server.py")


class TestDropStreamParseErrorsFilter(unittest.TestCase):
    """The logging filter should drop noise records and keep real ones."""

    def setUp(self):
        self.flt = mcp_server._DropStreamParseErrors()

    def _record(self, msg: str) -> logging.LogRecord:
        return logging.LogRecord(
            name="mcp.server.lowlevel.server",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg=msg,
            args=None,
            exc_info=None,
        )

    def test_drops_received_exception_from_stream(self):
        self.assertFalse(self.flt.filter(self._record("Received exception from stream: foo")))

    def test_drops_invalid_json(self):
        self.assertFalse(self.flt.filter(self._record("Invalid JSON: EOF while parsing")))

    def test_drops_internal_server_error(self):
        self.assertFalse(self.flt.filter(self._record("Internal Server Error")))

    def test_keeps_unrelated_messages(self):
        self.assertTrue(self.flt.filter(self._record("Processing request of type ListToolsRequest")))
        self.assertTrue(self.flt.filter(self._record("save_memory: id=abc")))

    def test_filter_installed_on_lowlevel_logger(self):
        target = logging.getLogger("mcp.server.lowlevel.server")
        self.assertTrue(
            any(isinstance(f, mcp_server._DropStreamParseErrors) for f in target.filters),
            "noise filter should be attached to mcp.server.lowlevel.server",
        )


class TestExceptionSilencePatch(unittest.TestCase):
    """The monkey-patch should be installed and should swallow Exception messages."""

    def test_patch_installed(self):
        from mcp.server.lowlevel import server as lowlevel

        # The patched coroutine has our marker name.
        self.assertEqual(
            lowlevel.Server._handle_message.__name__,
            "_handle_message_quiet",
            "mcp_server should monkey-patch lowlevel.Server._handle_message",
        )

    def test_exception_message_does_not_send_log(self):
        """An Exception arriving on the read stream must NOT trigger send_log_message."""
        from mcp.server.lowlevel import server as lowlevel

        fake_self = MagicMock(spec=lowlevel.Server)
        fake_self._handle_request = AsyncMock()
        fake_self._handle_notification = AsyncMock()

        fake_session = MagicMock()
        fake_session.send_log_message = AsyncMock()

        # Drive the patched coroutine directly.
        asyncio.run(
            lowlevel.Server._handle_message(
                fake_self,
                ValueError("garbage on stdin"),
                fake_session,
                lifespan_context=None,
                raise_exceptions=False,
            )
        )

        fake_session.send_log_message.assert_not_called()
        fake_self._handle_request.assert_not_called()
        fake_self._handle_notification.assert_not_called()

    def test_exception_with_raise_exceptions_propagates(self):
        from mcp.server.lowlevel import server as lowlevel

        fake_self = MagicMock(spec=lowlevel.Server)
        fake_self._handle_request = AsyncMock()
        fake_self._handle_notification = AsyncMock()
        fake_session = MagicMock()
        fake_session.send_log_message = AsyncMock()

        with self.assertRaises(RuntimeError):
            asyncio.run(
                lowlevel.Server._handle_message(
                    fake_self,
                    RuntimeError("boom"),
                    fake_session,
                    lifespan_context=None,
                    raise_exceptions=True,
                )
            )

    def test_client_notification_still_dispatched(self):
        """Real notifications must still reach _handle_notification."""
        from mcp.server.lowlevel import server as lowlevel
        from mcp import types as mcp_types

        fake_self = MagicMock(spec=lowlevel.Server)
        fake_self._handle_request = AsyncMock()
        fake_self._handle_notification = AsyncMock()
        fake_session = MagicMock()

        notif = mcp_types.ClientNotification(mcp_types.InitializedNotification(method="notifications/initialized"))
        asyncio.run(lowlevel.Server._handle_message(fake_self, notif, fake_session, lifespan_context=None))
        fake_self._handle_notification.assert_awaited_once_with(notif.root)


class TestToolEnablement(unittest.TestCase):
    def test_save_memory_enabled_by_default(self):
        self.assertTrue(mcp_server.tool_enabled("save_memory"))
        self.assertTrue(mcp_server.tool_enabled("search_memory"))
        self.assertTrue(mcp_server.tool_enabled("memory_tree"))

    def test_disabled_tools_default_set(self):
        # These are disabled by default per DISABLED_TOOLS env default.
        for name in [
            "read_memory",
            "update_memory",
            "delete_memory",
            "link_memories",
            "unlink_memories",
            "memory_stats",
            "sync_from_disk",
            "sync_to_disk",
            "graph_snapshot",
        ]:
            self.assertFalse(
                mcp_server.tool_enabled(name),
                f"{name} should be disabled by default",
            )

    def test_optional_tool_returns_noop_for_disabled(self):
        deco = mcp_server.optional_tool("read_memory")  # disabled

        def f():
            return 42

        wrapped = deco(f)
        # Noop decorator returns the function unchanged.
        self.assertIs(wrapped, f)
        self.assertEqual(wrapped(), 42)


class TestSlugify(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(mcp_server._slugify("Hello World"), "hello-world")

    def test_strips_punctuation(self):
        self.assertEqual(mcp_server._slugify("Foo, Bar! Baz?"), "foo-bar-baz")

    def test_underscores_become_dashes(self):
        self.assertEqual(mcp_server._slugify("snake_case_thing"), "snake-case-thing")

    def test_empty_falls_back_to_unfiled(self):
        self.assertEqual(mcp_server._slugify(""), "unfiled")
        self.assertEqual(mcp_server._slugify("!!!"), "unfiled")


class TestGetMemoryErrorReporting(unittest.TestCase):
    """get_memory() must surface the underlying init exception, not a generic message."""

    def setUp(self):
        # Snapshot the module globals we mutate.
        self._saved_memory = mcp_server._memory
        self._saved_err = mcp_server._memory_init_error
        self._saved_event = mcp_server._memory_ready

    def tearDown(self):
        mcp_server._memory = self._saved_memory
        mcp_server._memory_init_error = self._saved_err
        mcp_server._memory_ready = self._saved_event

    def test_includes_underlying_exception_message(self):
        import threading as _t

        mcp_server._memory = None
        mcp_server._memory_init_error = ModuleNotFoundError("No module named 'requests'")
        ev = _t.Event()
        ev.set()  # don't actually wait
        mcp_server._memory_ready = ev

        with self.assertRaises(RuntimeError) as ctx:
            mcp_server.get_memory()
        msg = str(ctx.exception)
        self.assertIn("ModuleNotFoundError", msg)
        self.assertIn("requests", msg)
        self.assertIn("python=", msg)
        # __cause__ should be set so traceback shows the original error.
        self.assertIsInstance(ctx.exception.__cause__, ModuleNotFoundError)

    def test_no_recorded_error_falls_back_to_timeout_message(self):
        import threading as _t

        mcp_server._memory = None
        mcp_server._memory_init_error = None
        ev = _t.Event()
        ev.set()
        mcp_server._memory_ready = ev

        with self.assertRaises(RuntimeError) as ctx:
            mcp_server.get_memory()
        self.assertIn("60s", str(ctx.exception))


class TestStdioEndToEnd(unittest.TestCase):
    """Spawn the real server as a subprocess, send valid + garbage input,
    confirm responses come back and no `Internal Server Error` notifications
    are emitted to the client."""

    @classmethod
    def setUpClass(cls):
        cls.python = sys.executable
        if not os.path.isfile(SERVER_PATH):
            raise unittest.SkipTest(f"mcp_server.py not found at {SERVER_PATH}")

    def _run(self, payload: str, timeout: int = 20) -> str:
        env = os.environ.copy()
        # Avoid auto-sync side effects during the test.
        env["MEMORY_AUTO_SYNC"] = "false"
        proc = subprocess.run(
            [self.python, SERVER_PATH],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=REPO_ROOT,
        )
        return proc.stdout

    def test_initialize_and_tools_list_with_garbage(self):
        # Garbage lines are placed AFTER all valid requests so the server
        # processes initialize + tools/list before encountering bad input.
        # Previously garbage was interleaved, which caused a race on slower
        # CI runners where the server would close stdin before reading
        # the tools/list request.
        payload = "\n".join(
            [
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "unit-test", "version": "0"},
                        },
                    }
                ),
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
                "",
                "",
                "",  # blank line — would normally trigger parse error
                "this is not json at all",  # garbage
                "",
            ]
        )
        stdout = self._run(payload)

        responses = []
        spam = 0
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("method") == "notifications/message":
                if "Internal Server Error" in json.dumps(msg):
                    spam += 1
            if msg.get("id") is not None:
                responses.append(msg)

        self.assertEqual(
            spam,
            0,
            f"Expected zero 'Internal Server Error' notifications, got {spam}.\nstdout:\n{stdout}",
        )
        ids = {r["id"] for r in responses}
        self.assertIn(1, ids, "missing initialize response")
        self.assertIn(2, ids, "missing tools/list response")

        tools_resp = next(r for r in responses if r["id"] == 2)
        tools = tools_resp.get("result", {}).get("tools", [])
        self.assertGreater(len(tools), 0, "tools/list returned no tools")
        names = {t["name"] for t in tools}
        # save_memory + search_memory are always enabled by default config.
        self.assertIn("save_memory", names)
        self.assertIn("search_memory", names)


if __name__ == "__main__":
    unittest.main()
