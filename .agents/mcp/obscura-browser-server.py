#!/usr/bin/env python3
"""
Agent OS - MCP Chrome DevTools Server

Controls the Chrome DevTools browser runtime through a CDP-compatible endpoint.
Uses Playwright Python as the CDP client only; it launches the bundled runtime,
not the user's default Chrome profile.

Environment:
    CHROME_DEVTOOLS_BIN   Path to runtime binary (default: installed .agents/bin copy, then PATH)
    CHROME_DEVTOOLS_PORT  CDP port (default: 9222)
    CHROME_DEVTOOLS_ARGS  Additional args for runtime serve (e.g., "--stealth")
    OSTWIN_BROWSER_DOWNLOAD_DIR  Preferred artifact directory for downloads/screenshots/PDFs
    AGENT_OS_ROOM_DIR     Room fallback: <room>/artifacts/downloads
    AGENT_OS_ROOT         Project fallback: <project>/artifacts/browser-downloads
"""

import asyncio
import base64
import json
import os
import re
import shlex
import shutil
import subprocess
from typing import Annotated, Any, Dict, List, Optional

from pydantic import Field
from mcp.server.fastmcp import FastMCP


def _default_chrome_devtools_bin() -> str:
    """Prefer the installer-managed binary, then fall back to PATH lookup."""
    configured = os.environ.get("CHROME_DEVTOOLS_BIN") or os.environ.get("OBSCURA_BIN")
    if configured:
        return configured

    bin_name = "obscura.exe" if os.name == "nt" else "obscura"
    local_bin = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "bin", bin_name)
    )
    if os.path.isfile(local_bin):
        return local_bin

    return "obscura"


CHROME_DEVTOOLS_BIN = _default_chrome_devtools_bin()
CHROME_DEVTOOLS_PORT = int(
    os.environ.get("CHROME_DEVTOOLS_PORT") or os.environ.get("OBSCURA_PORT", "9222")
)
CHROME_DEVTOOLS_ARGS = os.environ.get("CHROME_DEVTOOLS_ARGS") or os.environ.get("OBSCURA_ARGS", "")
INTERACTIVE_SELECTOR = (
    "a, button, input, textarea, select, option, [role], [aria-label], "
    "[title], [tabindex]:not([tabindex='-1'])"
)
DOM_SNAPSHOT_SCRIPT = r"""
(elements) => {
  const cssEscape = (value) => {
    if (window.CSS && typeof window.CSS.escape === "function") {
      return window.CSS.escape(value);
    }
    return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
  };

  const visible = (el) => {
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style && style.visibility !== "hidden" && style.display !== "none" &&
      rect.width > 0 && rect.height > 0;
  };

  const roleFor = (el) => {
    const explicit = el.getAttribute("role");
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === "a") return "link";
    if (tag === "button") return "button";
    if (tag === "input" || tag === "textarea") return "textbox";
    if (tag === "select") return "combobox";
    return tag;
  };

  const nameFor = (el) => {
    return (
      el.getAttribute("aria-label") ||
      el.getAttribute("title") ||
      el.getAttribute("alt") ||
      el.getAttribute("placeholder") ||
      el.value ||
      el.innerText ||
      el.textContent ||
      ""
    ).trim().replace(/\s+/g, " ").slice(0, 160);
  };

  const selectorFor = (el) => {
    if (el.id) return "#" + cssEscape(el.id);
    const parts = [];
    let current = el;
    while (current && current.nodeType === Node.ELEMENT_NODE && parts.length < 6) {
      let part = current.tagName.toLowerCase();
      const classes = Array.from(current.classList || []).slice(0, 2);
      if (classes.length) {
        part += "." + classes.map(cssEscape).join(".");
      }
      let nth = 1;
      let sibling = current.previousElementSibling;
      while (sibling) {
        if (sibling.tagName === current.tagName) nth += 1;
        sibling = sibling.previousElementSibling;
      }
      part += `:nth-of-type(${nth})`;
      parts.unshift(part);
      current = current.parentElement;
    }
    return parts.join(" > ");
  };

  return elements
    .filter(visible)
    .slice(0, 200)
    .map((el) => ({
      role: roleFor(el),
      name: nameFor(el),
      selector: selectorFor(el)
    }))
    .filter((item) => item.selector && (item.role || item.name));
}
"""


def _resolve_download_dir() -> str:
    """Resolve download directory from env, with safe fallbacks."""
    download_dir = os.environ.get("OSTWIN_BROWSER_DOWNLOAD_DIR", "")
    if download_dir:
        path = os.path.abspath(download_dir)
    else:
        room_dir = os.environ.get("AGENT_OS_ROOM_DIR", "")
        if room_dir:
            path = os.path.join(room_dir, "artifacts", "downloads")
        else:
            project_dir = os.environ.get("AGENT_OS_ROOT", "")
            if project_dir:
                path = os.path.join(project_dir, "artifacts", "browser-downloads")
            else:
                path = os.path.abspath(os.path.join("artifacts", "browser-downloads"))
    os.makedirs(path, exist_ok=True)
    return path


def _sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal and invalid characters.

    Cross-platform: strips both / and \\ separators on all OSes.
    - Extracts basename (last component after / or \\)
    - Removes parent directory references
    - Keeps only alphanumeric, dash, underscore, dot
    - Strips leading dots (hidden files)
    - Preserves extension when truncating
    - Max length 255
    """
    if not filename:
        return "download"
    parts = re.split(r"[/\\]", filename)
    filename = parts[-1] if parts else "download"
    filename = re.sub(r"[^\w\-.]", "_", filename)
    filename = re.sub(r"_+", "_", filename).strip("_")
    filename = filename.lstrip(".")
    if not filename:
        filename = "download"
    if len(filename) > 255:
        ext = ""
        if "." in filename:
            name, ext = filename.rsplit(".", 1)
            ext = "." + ext
            max_name = 255 - len(ext)
            filename = name[:max_name] + ext
        else:
            filename = filename[:255]
    return filename


def _is_safe_download_path(download_dir: str, target_path: str) -> bool:
    """Check if target_path is inside download_dir (no path traversal)."""
    try:
        download_dir = os.path.abspath(download_dir)
        target_path = os.path.abspath(target_path)
        return os.path.commonpath([download_dir]) == os.path.commonpath([download_dir, target_path])
    except (ValueError, OSError):
        return False


def _safe_download_path(download_dir: str, filename: str) -> str:
    """Construct a sanitized download path and verify it stays inside download_dir."""
    sanitized = _sanitize_filename(filename)
    full_path = os.path.join(download_dir, sanitized)
    if not _is_safe_download_path(download_dir, full_path):
        raise ValueError(f"Path traversal blocked: {filename}")
    return full_path


def _get_default_launch_args(port: int) -> List[str]:
    """Get default launch args for the browser runtime serve mode."""
    return ["serve", "--port", str(port)]


def _build_launch_args(port: int, extra_args: str = "") -> List[str]:
    """Build complete launch args, merging defaults with extra runtime args."""
    args = _get_default_launch_args(port)
    if extra_args:
        extra = shlex.split(extra_args)
        for arg in extra:
            if arg and arg not in args:
                args.append(arg)
    return args


_element_ref_map: Dict[str, Dict[str, Any]] = {}
_ref_counter: int = 0


def _reset_ref_map() -> None:
    """Reset the element ref map (for testing)."""
    global _element_ref_map, _ref_counter
    _element_ref_map = {}
    _ref_counter = 0


def _build_ref() -> str:
    """Build a new element ref like @e1, @e2, etc."""
    global _ref_counter
    _ref_counter += 1
    return f"@e{_ref_counter}"


def _store_element(ref: str, element_data: Dict[str, Any]) -> None:
    """Store element data in ref map."""
    _element_ref_map[ref] = element_data


def _resolve_ref(ref_or_selector: str) -> str:
    """Resolve @eN ref to selector, or return raw selector if not a ref."""
    if ref_or_selector.startswith("@e") and ref_or_selector in _element_ref_map:
        elem = _element_ref_map[ref_or_selector]
        return elem.get("selector", ref_or_selector)
    return ref_or_selector


def _build_elements_from_dom_snapshot(raw_elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach stable @eN refs to DOM snapshot items returned by browser JS."""
    elements: List[Dict[str, Any]] = []
    for item in raw_elements:
        if not isinstance(item, dict):
            continue

        selector = str(item.get("selector") or "").strip()
        role = str(item.get("role") or "").strip()
        name = str(item.get("name") or "").strip()
        if not selector or not (role or name):
            continue

        ref = _build_ref()
        elem_data = {"ref": ref, "role": role, "name": name, "selector": selector}
        elements.append(elem_data)
        _store_element(ref, elem_data)
    return elements


mcp = FastMCP("ostwin-chrome-devtools", log_level="CRITICAL")

_browser_process: Optional[subprocess.Popen] = None
_playwright: Any = None
_cdp_client: Any = None
_page: Any = None


def _is_chrome_devtools_cdp_endpoint(version_info: Dict[str, Any]) -> bool:
    """Return true when /json/version identifies the managed browser runtime."""
    fields = (
        version_info.get("Browser"),
        version_info.get("Product"),
        version_info.get("User-Agent"),
        version_info.get("userAgent"),
    )
    return any(
        marker in str(value).lower()
        for value in fields
        if value
        for marker in ("chrome devtools", "obscura")
    )


def _adapter_started_browser_alive() -> bool:
    """Return true when this adapter started the current browser process."""
    return _browser_process is not None and _browser_process.poll() is None


async def _ensure_browser() -> dict:
    """Ensure browser is running and connected. Returns status dict."""
    global _playwright, _cdp_client, _page

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {"running": False, "port": CHROME_DEVTOOLS_PORT, "error": "playwright not installed"}

    if _page is not None:
        try:
            await _page.evaluate("1")
            return {"running": True, "port": CHROME_DEVTOOLS_PORT}
        except Exception:
            if _cdp_client is not None:
                try:
                    await _cdp_client.close()
                except Exception:
                    pass
            if _playwright is not None:
                try:
                    await _playwright.stop()
                except Exception:
                    pass
            _page = None
            _cdp_client = None
            _playwright = None

    try:
        import httpx
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"http://localhost:{CHROME_DEVTOOLS_PORT}/json/version")
            if resp.status_code == 200:
                data = resp.json()
                if not _is_chrome_devtools_cdp_endpoint(data) and not _adapter_started_browser_alive():
                    return {
                        "running": False,
                        "port": CHROME_DEVTOOLS_PORT,
                        "error": "Existing CDP endpoint is not Chrome DevTools managed",
                    }
                ws_url = data.get("webSocketDebuggerUrl")
                if ws_url:
                    _playwright = await async_playwright().start()
                    _cdp_client = await _playwright.chromium.connect_over_cdp(ws_url)
                    contexts = _cdp_client.contexts
                    if contexts:
                        pages = contexts[0].pages
                        _page = pages[0] if pages else await contexts[0].new_page()
                    else:
                        ctx = await _cdp_client.new_context()
                        _page = await ctx.new_page()
                    return {"running": True, "port": CHROME_DEVTOOLS_PORT}
    except Exception:
        pass

    return {"running": False, "port": CHROME_DEVTOOLS_PORT}


async def _start_browser() -> dict:
    """Start the Chrome DevTools browser runtime process."""
    global _browser_process

    status = await _ensure_browser()
    if status.get("running"):
        return status
    if status.get("error"):
        return status

    browser_exe = shutil.which(CHROME_DEVTOOLS_BIN) or CHROME_DEVTOOLS_BIN
    try:
        args = _build_launch_args(CHROME_DEVTOOLS_PORT, CHROME_DEVTOOLS_ARGS)
    except ValueError as e:
        return {"running": False, "error": f"Invalid CHROME_DEVTOOLS_ARGS: {e}"}
    full_cmd = [browser_exe] + args

    try:
        popen_kwargs = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "stdin": subprocess.DEVNULL,
        }
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        _browser_process = subprocess.Popen(
            full_cmd,
            **popen_kwargs,
        )
    except FileNotFoundError:
        return {"running": False, "error": f"Chrome DevTools runtime binary not found: {browser_exe}"}
    except Exception as e:
        return {"running": False, "error": str(e)}

    for _ in range(30):
        await asyncio.sleep(0.5)
        status = await _ensure_browser()
        if status.get("running"):
            return status

    if _browser_process is not None:
        try:
            _browser_process.terminate()
            _browser_process.wait(timeout=5)
        except Exception:
            try:
                _browser_process.kill()
            except Exception:
                pass
        _browser_process = None

    return {"running": False, "error": "Browser failed to start within timeout"}


@mcp.tool()
async def browser_health() -> str:
    """Check browser connection health.

    Returns JSON with 'running' boolean and optional 'error' or 'port'.
    """
    status = await _ensure_browser()
    return json.dumps(status)


@mcp.tool()
async def browser_open(
    url: Annotated[str, Field(description="URL to navigate to")],
    wait_until: Annotated[str, Field(description="Wait condition: load | domcontentloaded | networkidle")] = "load",
) -> str:
    """Open URL in browser, starting browser if needed.

    Returns JSON with 'success' boolean and 'url' or 'error'.
    """
    status = await _ensure_browser()
    if not status.get("running"):
        start_result = await _start_browser()
        if not start_result.get("running"):
            return json.dumps(start_result)

    if _page is None:
        return json.dumps({"success": False, "error": "No page available"})

    try:
        await _page.goto(url, wait_until=wait_until, timeout=30000)
        return json.dumps({"success": True, "url": url, "title": await _page.title()})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@mcp.tool()
async def browser_snapshot() -> str:
    """Capture a DOM-based page snapshot with deterministic element refs.

    Returns JSON like:
    { "url": "...", "title": "...", "elements": [{ "ref": "@e1", "role": "...", "name": "...", "selector": "..." }] }
    """
    if _page is None:
        return json.dumps({"error": "No page open"})

    try:
        _reset_ref_map()
        raw_elements = await _page.eval_on_selector_all(
            INTERACTIVE_SELECTOR,
            DOM_SNAPSHOT_SCRIPT,
        )
        elements = _build_elements_from_dom_snapshot(raw_elements)
        return json.dumps({
            "url": _page.url,
            "title": await _page.title(),
            "elements": elements
        }, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def browser_click(
    selector: Annotated[str, Field(description="CSS selector or @eN ref from browser_snapshot")],
    timeout: Annotated[int, Field(description="Timeout in ms (default: 5000)")] = 5000,
) -> str:
    """Click element matching selector or ref.

    Returns JSON with 'success' boolean and 'selector' or 'error'.
    """
    if _page is None:
        return json.dumps({"success": False, "error": "No page open"})

    resolved = _resolve_ref(selector)
    try:
        await _page.click(resolved, timeout=timeout)
        return json.dumps({"success": True, "selector": selector, "resolved": resolved})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e), "selector": selector})


@mcp.tool()
async def browser_fill(
    selector: Annotated[str, Field(description="CSS selector or @eN ref for input element")],
    value: Annotated[str, Field(description="Value to fill")],
    clear: Annotated[bool, Field(description="Clear field before filling (default: true)")] = True,
) -> str:
    """Fill text into input field.

    Returns JSON with 'success' boolean and 'selector' or 'error'.
    """
    if _page is None:
        return json.dumps({"success": False, "error": "No page open"})

    resolved = _resolve_ref(selector)
    try:
        if clear:
            await _page.fill(resolved, value)
        else:
            await _page.type(resolved, value)
        return json.dumps({"success": True, "selector": selector, "resolved": resolved, "filled": True})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e), "selector": selector})


@mcp.tool()
async def browser_press(
    key: Annotated[str, Field(description="Key to press (e.g., Enter, Tab, ArrowDown)")],
) -> str:
    """Press a keyboard key.

    Returns JSON with 'success' boolean and 'key' or 'error'.
    """
    if _page is None:
        return json.dumps({"success": False, "error": "No page open"})

    try:
        await _page.keyboard.press(key)
        return json.dumps({"success": True, "key": key})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@mcp.tool()
async def browser_screenshot(
    path: Annotated[str, Field(description="Filename for screenshot (will be sanitized)")] = "screenshot.png",
    full_page: Annotated[bool, Field(description="Capture full page (default: false)")] = False,
) -> str:
    """Capture screenshot of current page.

    Uses CDP Page.captureScreenshot directly for Chrome DevTools runtime compatibility.
    Falls back to Playwright helper for other CDP backends.
    Returns JSON with 'success', 'path', and a short base64 'data_preview' or 'error'.
    """
    if _page is None:
        return json.dumps({"success": False, "error": "No page open"})

    download_dir = _resolve_download_dir()
    try:
        safe_path = _safe_download_path(download_dir, path)
    except ValueError as e:
        return json.dumps({"success": False, "error": str(e)})

    try:
        if full_page:
            await _page.screenshot(path=safe_path, full_page=True)
            with open(safe_path, "rb") as f:
                data_preview = base64.b64encode(f.read()).decode("utf-8")[:100] + "..."
            return json.dumps({"success": True, "path": safe_path, "data_preview": data_preview})
        cdp = await _page.context.new_cdp_session(_page)
        fmt = "png" if safe_path.endswith(".png") else "jpeg"
        result = await cdp.send("Page.captureScreenshot", {"format": fmt, "quality": 80} if fmt == "jpeg" else {"format": fmt})
        await cdp.detach()
        import base64 as _b64
        img_bytes = _b64.b64decode(result["data"])
        with open(safe_path, "wb") as f:
            f.write(img_bytes)
        data_preview = result["data"][:100] + "..."
        return json.dumps({"success": True, "path": safe_path, "data_preview": data_preview})
    except Exception as e:
        if full_page:
            return json.dumps({"success": False, "error": f"Full-page screenshot failed: {e}"})
        try:
            await _page.screenshot(path=safe_path, full_page=False)
            with open(safe_path, "rb") as f:
                data_preview = base64.b64encode(f.read()).decode("utf-8")[:100] + "..."
            return json.dumps({"success": True, "path": safe_path, "data_preview": data_preview})
        except Exception as e2:
            return json.dumps({"success": False, "error": f"CDP screenshot failed: {e}; Playwright fallback failed: {e2}"})


@mcp.tool()
async def browser_click_and_download(
    selector: Annotated[str, Field(description="CSS selector or @eN ref for download trigger")],
    expected_filename: Annotated[str, Field(description="Expected download filename (will be sanitized)")] = "",
    timeout: Annotated[int, Field(description="Download timeout in ms (default: 30000)")] = 30000,
) -> str:
    """Click element and wait for download to complete.

    Downloads are saved to OSTWIN_BROWSER_DOWNLOAD_DIR.
    Returns JSON with 'success', 'path', 'filename' or 'error'.
    """
    if _page is None:
        return json.dumps({"success": False, "error": "No page open"})

    download_dir = _resolve_download_dir()
    resolved = _resolve_ref(selector)

    try:
        async with _page.expect_download(timeout=timeout) as download_info:
            await _page.click(resolved)
        download = await download_info.value

        suggested = download.suggested_filename
        if not suggested:
            suggested = expected_filename or "download"

        safe_filename = _sanitize_filename(suggested)
        safe_path = os.path.join(download_dir, safe_filename)

        if not _is_safe_download_path(download_dir, safe_path):
            return json.dumps({"success": False, "error": f"Path traversal blocked: {suggested}"})

        await download.save_as(safe_path)
        return json.dumps({"success": True, "path": safe_path, "filename": safe_filename, "selector": selector, "resolved": resolved})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e), "selector": selector})


@mcp.tool()
async def browser_close() -> str:
    """Close browser and clean up.

    Returns JSON with 'success' boolean.
    """
    global _browser_process, _playwright, _cdp_client, _page

    if _cdp_client is not None:
        try:
            await _cdp_client.close()
        except Exception:
            pass
    _page = None
    _cdp_client = None

    if _playwright is not None:
        try:
            await _playwright.stop()
        except Exception:
            pass
    _playwright = None

    if _browser_process is not None:
        try:
            _browser_process.terminate()
            _browser_process.wait(timeout=5)
        except Exception:
            try:
                _browser_process.kill()
            except Exception:
                pass
        _browser_process = None

    return json.dumps({"success": True})


if __name__ == "__main__":
    mcp.run(transport="stdio")
