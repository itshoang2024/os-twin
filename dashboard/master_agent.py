"""
Master Agent Model Configuration.

Routes all LLM calls through the OpenCode server using the opencode-ai SDK.
The OpenCode server manages provider selection, API keys, and model routing.

Key design:
- SessionRegistry maps conversation_id → OpenCode session_id (LRU-bounded,
  per-key locked to prevent duplicate session.create() on concurrent first hits)
- Each conversation (thread/plan) gets its own OpenCode session
- session.chat() sends a message and triggers an AI response
- session.messages() reads back the full message content (text + tool parts)
- session.delete() removes a session (used by /clear command)
- On the first send for a conversation, prior chat_history is replayed so
  OpenCode sees the full prior context
- A stale session (server lost it) is recovered transparently by recreating
  the session and replaying the request once
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opencode_ai import AsyncOpencode

from dashboard.llm_client import ChatMessage, LLMConfig, ToolCall

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.1-pro-preview"
# OpenCode-style provider ID. The old direct-LLM path used "google-vertex",
# but OpenCode's generated config and the persistence path emit short IDs
# ("google", "openai", "anthropic"). Sending "google-vertex" as providerID to
# /session/{id}/message on a fresh install would target a provider OpenCode
# doesn't know about until the user explicitly saved a model.
DEFAULT_PROVIDER = "google"

OPENCODE_BASE_URL = os.environ.get("OPENCODE_BASE_URL", "http://127.0.0.1:4096")
OPENCODE_SERVER_PASSWORD = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
OPENCODE_SERVER_USERNAME = os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")

MAX_SESSIONS = int(os.environ.get("OPENCODE_MAX_SESSIONS", "1000"))

# POST /session/{id}/message appends a new user turn server-side, so it is
# NOT idempotent — a retry on a transient transport error duplicates the
# message. We disable SDK auto-retries entirely and instead give the HTTP
# transport a generous read timeout so slow LLM completions don't trip the
# retry path in the first place. Stale-session recovery is handled
# explicitly in _opencode_chat / _opencode_command.
OPENCODE_HTTP_READ_TIMEOUT = float(os.environ.get("OPENCODE_HTTP_READ_TIMEOUT", "600.0"))
OPENCODE_HTTP_CONNECT_TIMEOUT = float(os.environ.get("OPENCODE_HTTP_CONNECT_TIMEOUT", "10.0"))


# ── Config ─────────────────────────────────────────────────────────────────


@dataclass
class MasterAgentConfig:
    model: str = DEFAULT_MODEL
    provider: str | None = DEFAULT_PROVIDER
    temperature: float | None = None
    max_tokens: int = 8192
    is_explicit: bool = False

    def to_llm_config(self) -> LLMConfig:
        return LLMConfig(max_tokens=self.max_tokens, temperature=self.temperature)


_master_config = MasterAgentConfig()


# Legacy direct-LLM provider IDs that OpenCode does not recognise. If one of
# these slips through (e.g. from a stale persisted runtime setting), we
# re-infer the OpenCode-style ID from the model name.
_LEGACY_PROVIDER_IDS: frozenset[str] = frozenset({"google-vertex", "google-genai", "google_gemini"})


def _infer_provider_for_model(model: str) -> str | None:
    model_lower = model.lower()
    if "gemini" in model_lower or model_lower.startswith("gemma"):
        return "google"
    if any(marker in model_lower for marker in ("gpt", "o1", "o3", "o4")):
        return "openai"
    if "claude" in model_lower:
        return "anthropic"
    return None


def normalize_master_model(
    model: str,
    provider: str | None = None,
) -> tuple[str, str | None]:
    model = (model or "").strip()
    provider = (provider or "").strip() or None

    if provider is None:
        if "/" in model:
            provider, model = model.split("/", 1)
        elif ":" in model:
            provider, model = model.split(":", 1)

    if provider is None and model:
        provider = _infer_provider_for_model(model)

    return model, provider


def format_master_model(model: str, provider: str | None = None) -> str:
    model, provider = normalize_master_model(model, provider)
    return f"{provider}/{model}" if provider else model


def is_master_model_explicit() -> bool:
    return _master_config.is_explicit


def get_master_model() -> str:
    return _master_config.model


def set_master_model(model: str, provider: str | None = None) -> None:
    model, provider = normalize_master_model(model, provider)
    _master_config.model = model
    _master_config.provider = provider
    _master_config.is_explicit = True
    _session_registry.clear()
    logger.info("[MASTER_AGENT] Model set to: %s (provider: %s)", model, provider)


def get_master_config() -> MasterAgentConfig:
    return MasterAgentConfig(
        model=_master_config.model,
        provider=_master_config.provider,
        temperature=_master_config.temperature,
        max_tokens=_master_config.max_tokens,
    )


def set_master_config(config: MasterAgentConfig) -> None:
    global _master_config
    _master_config = config
    _session_registry.clear()
    logger.info("[MASTER_AGENT] Config updated: model=%s, provider=%s", config.model, config.provider)


def load_persisted_master_model() -> None:
    """Re-hydrate the master-agent singleton from the persisted runtime setting.

    Reads ``runtime.master_agent_model`` from ``.agents/config.json`` via the
    shared :class:`SettingsResolver`.  When a non-empty value is found, it is
    funneled through :func:`set_master_model` so the existing ``provider/model``
    parsing logic stays the single source of truth.

    Safe to call on every dashboard startup -- a missing file, empty value,
    or transient read error simply leaves the singleton at its defaults.
    """
    try:
        from dashboard.lib.settings import get_settings_resolver

        resolver = get_settings_resolver()
        runtime = resolver.get_master_settings().runtime
        persisted = (runtime.master_agent_model or "").strip()
    except Exception as exc:  # noqa: BLE001 - never block startup on config errors
        logger.warning("[MASTER_AGENT] Could not load persisted master model: %s", exc)
        return

    if not persisted:
        return

    set_master_model(persisted)
    logger.info("[MASTER_AGENT] Restored persisted master model: %s", persisted)


def _resolve_model_provider(
    model: str | None = None,
    provider: str | None = None,
) -> tuple[str, str]:
    resolved_model = model or _master_config.model or DEFAULT_MODEL
    resolved_provider = provider if provider is not None else _master_config.provider
    resolved_model, resolved_provider = normalize_master_model(
        resolved_model,
        resolved_provider,
    )
    # This block might cause problems in the future, but it's a quick fix for the current issue.
    if resolved_provider in _LEGACY_PROVIDER_IDS:
        inferred = _infer_provider_for_model(resolved_model)
        if inferred:
            resolved_provider = inferred
    return (resolved_model, resolved_provider or DEFAULT_PROVIDER)


def get_model_and_provider() -> tuple[str, str]:
    return _resolve_model_provider()


# ── OpenCode client ───────────────────────────────────────────────────────


def _build_opencode_client() -> "AsyncOpencode":
    import httpx
    from opencode_ai import AsyncOpencode

    timeout = httpx.Timeout(
        OPENCODE_HTTP_READ_TIMEOUT,
        connect=OPENCODE_HTTP_CONNECT_TIMEOUT,
    )

    kwargs: dict = {
        "base_url": OPENCODE_BASE_URL,
        "max_retries": 0,
        "timeout": timeout,
    }
    if OPENCODE_SERVER_PASSWORD:
        kwargs["http_client"] = httpx.AsyncClient(
            auth=httpx.BasicAuth(OPENCODE_SERVER_USERNAME, OPENCODE_SERVER_PASSWORD),
            timeout=timeout,
        )
    logger.info(
        "[MASTER_AGENT] Building OpenCode client: base_url=%s read_timeout=%.1fs retries=0",
        OPENCODE_BASE_URL, OPENCODE_HTTP_READ_TIMEOUT,
    )
    return AsyncOpencode(**kwargs)


_opencode_client: "AsyncOpencode | None" = None


def get_opencode_client() -> "AsyncOpencode":
    global _opencode_client
    if _opencode_client is None:
        _opencode_client = _build_opencode_client()
    return _opencode_client


def reset_master_client() -> None:
    global _opencode_client
    _opencode_client = None
    _session_registry.clear()
    logger.info("[MASTER_AGENT] Client reset, will rebuild on next use")


# ── Session registry ──────────────────────────────────────────────────────


_SESSION_REGISTRY_FILE = os.path.join(os.path.expanduser("~"), ".ostwin", "session_registry.json")
_SESSION_REGISTRY_DEBOUNCE = 2.0


class _SessionRegistry:
    """Maps conversation_id → opencode_session_id with locking and LRU eviction.

    Per-conversation asyncio locks make get_or_create() race-free, so two
    concurrent first-hits for the same conversation_id share a single
    session.create() call instead of orphaning one server-side session.

    Mappings are persisted to ~/.ostwin/session_registry.json so they survive
    dashboard restarts.  When a mapping points to a session that no longer
    exists on the OpenCode server (e.g. server restart), get_or_create()
    transparently creates a new one.
    """

    def __init__(self, max_size: int = MAX_SESSIONS) -> None:
        self._sessions: OrderedDict[str, str] = OrderedDict()
        self._has_system_set: set[str] = set()
        self._locks: dict[str, asyncio.Lock] = {}
        self._max_size = max_size
        self._persist_timer: asyncio.TimerHandle | None = None
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        try:
            if not os.path.exists(_SESSION_REGISTRY_FILE):
                return
            with open(_SESSION_REGISTRY_FILE) as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
            for conv_id, sess_id in data.items():
                if isinstance(conv_id, str) and isinstance(sess_id, str):
                    self._sessions[conv_id] = sess_id
            if self._sessions:
                logger.info("[MASTER_AGENT] Restored %d session mapping(s) from disk", len(self._sessions))
        except Exception as exc:
            logger.warning("[MASTER_AGENT] Failed to load session registry: %s", exc)

    def _schedule_persist(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._persist_timer is not None:
            self._persist_timer.cancel()
        self._persist_timer = loop.call_later(_SESSION_REGISTRY_DEBOUNCE, self._flush_to_disk)

    def _flush_to_disk(self) -> None:
        self._persist_timer = None
        try:
            d = os.path.dirname(_SESSION_REGISTRY_FILE)
            if not os.path.exists(d):
                os.makedirs(d, exist_ok=True)
            tmp = _SESSION_REGISTRY_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(dict(self._sessions), f)
            os.replace(tmp, _SESSION_REGISTRY_FILE)
        except Exception as exc:
            logger.warning("[MASTER_AGENT] Failed to persist session registry: %s", exc)

    def _lock_for(self, conversation_id: str) -> asyncio.Lock:
        lock = self._locks.get(conversation_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[conversation_id] = lock
        return lock

    async def get_or_create(self, conversation_id: str) -> str:
        existing = self._sessions.get(conversation_id)
        if existing:
            if await self._session_still_exists(existing):
                self._sessions.move_to_end(conversation_id)
                return existing
            logger.warning(
                "[MASTER_AGENT] Stale mapping %s→%s; will recreate",
                conversation_id, existing,
            )
            self._sessions.pop(conversation_id, None)
            self._has_system_set.discard(conversation_id)

        async with self._lock_for(conversation_id):
            existing = self._sessions.get(conversation_id)
            if existing:
                if await self._session_still_exists(existing):
                    self._sessions.move_to_end(conversation_id)
                    return existing
                self._sessions.pop(conversation_id, None)
                self._has_system_set.discard(conversation_id)

            client = get_opencode_client()
            session = await client.session.create()
            self._sessions[conversation_id] = session.id
            self._sessions.move_to_end(conversation_id)
            self._evict_if_needed()
            self._schedule_persist()
            logger.info("[MASTER_AGENT] New session %s for conversation %s", session.id, conversation_id)
            return session.id

    async def _session_still_exists(self, session_id: str) -> bool:
        """Validate that an OpenCode session still exists server-side.

        The opencode-ai SDK has no ``client.session.get(id)`` method — the
        available endpoints scoped to an id are ``messages`` / ``abort`` /
        ``delete`` etc.  ``messages`` is the cheapest read-only probe: it
        GETs ``/session/{id}/message`` and raises ``NotFoundError`` (HTTP
        404) when the session is gone.

        Be conservative on transient failures (network blip, server restart
        mid-flight, auth hiccup): treat them as "still alive" rather than
        evicting and recreating, because ``_opencode_chat`` already has a
        one-shot recover-on-NotFound path on the actual POST. Falsely
        treating a session as stale here churns through fresh sessions on
        every turn and silently breaks conversation continuity (the bug
        that made every Telegram turn create a new session).
        """
        NotFoundError = _not_found_exc()
        try:
            client = get_opencode_client()
            await client.session.messages(session_id)
            return True
        except NotFoundError:
            return False
        except Exception as exc:
            logger.warning(
                "[MASTER_AGENT] session.messages(%s) failed transiently (%s); "
                "treating session as alive",
                session_id, exc,
            )
            return True

    def _evict_if_needed(self) -> None:
        while len(self._sessions) > self._max_size:
            evicted, _ = self._sessions.popitem(last=False)
            self._has_system_set.discard(evicted)
            self._locks.pop(evicted, None)
            self._schedule_persist()
            logger.info("[MASTER_AGENT] LRU evicted conversation %s", evicted)

    def get(self, conversation_id: str) -> str | None:
        return self._sessions.get(conversation_id)

    def remove(self, conversation_id: str) -> None:
        self._sessions.pop(conversation_id, None)
        self._has_system_set.discard(conversation_id)
        self._locks.pop(conversation_id, None)
        self._schedule_persist()

    def clear(self) -> None:
        self._sessions.clear()
        self._has_system_set.clear()
        self._locks.clear()
        self._schedule_persist()

    def mark_system_set(self, conversation_id: str) -> None:
        self._has_system_set.add(conversation_id)

    def has_system(self, conversation_id: str) -> bool:
        return conversation_id in self._has_system_set


_session_registry = _SessionRegistry()


# ── Session content reading ───────────────────────────────────────────────


def _get_obj_field(obj, key: str):
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _json_error_detail(raw: str) -> str:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if not isinstance(parsed, dict):
        return raw
    detail = (
        parsed.get("error_description")
        or parsed.get("message")
        or parsed.get("error")
    )
    code = parsed.get("error")
    if detail and code and code not in str(detail):
        return f"{code}: {detail}"
    return str(detail or raw)


def _format_opencode_error(error) -> str:
    """Convert OpenCode message ``info.error`` into user-visible text."""
    if not error:
        return ""
    name = _get_obj_field(error, "name") or _get_obj_field(error, "code") or "error"
    data = _get_obj_field(error, "data")
    detail = (
        _get_obj_field(data, "message")
        or _get_obj_field(error, "message")
        or _get_obj_field(data, "error")
        or str(error)
    )
    if isinstance(detail, str):
        detail = _json_error_detail(detail)
    return f"OpenCode error ({name}): {detail}"


async def read_session_text(session_id: str) -> str:
    """Read the latest assistant message text or provider error from a session."""
    client = get_opencode_client()
    messages = await client.session.messages(session_id)
    for item in reversed(messages):
        if item.info.role != "assistant":
            continue
        text_parts = [p.text for p in item.parts if p.type == "text" and p.text]
        text = "\n".join(text_parts)
        if text:
            return text
        error_text = _format_opencode_error(_get_obj_field(item.info, "error"))
        if error_text:
            return error_text
        return ""
    return ""


async def read_session_tool_parts(session_id: str) -> list[dict]:
    """Read OpenCode-registered tool calls from the latest assistant message."""
    client = get_opencode_client()
    messages = await client.session.messages(session_id)
    results: list[dict] = []
    for item in reversed(messages):
        if item.info.role != "assistant":
            continue
        for part in item.parts:
            if part.type == "tool":
                state = part.state
                entry: dict = {
                    "tool": part.tool,
                    "call_id": part.call_id,
                    "status": state.status,
                }
                if hasattr(state, "input"):
                    entry["input"] = state.input
                if hasattr(state, "output"):
                    entry["output"] = state.output
                results.append(entry)
        break
    return results


_TOOL_BLOCK_RE = re.compile(r"```tool\s*\n(.*?)```", re.DOTALL)


def parse_custom_tool_calls(text: str) -> list[ToolCall]:
    """Parse ```tool JSON``` blocks from assistant text."""
    tool_calls: list[ToolCall] = []
    for match in _TOOL_BLOCK_RE.finditer(text):
        raw = match.group(1).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        name = data.get("name", "")
        arguments = data.get("arguments", {})
        if not name:
            continue
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"raw": arguments}
        if not isinstance(arguments, dict):
            arguments = {}
        tool_calls.append(ToolCall(id=str(uuid.uuid4()), name=name, arguments=arguments))
    return tool_calls


def strip_tool_blocks(text: str) -> str:
    return _TOOL_BLOCK_RE.sub("", text).strip()


# ── Message → OpenCode parts conversion ───────────────────────────────────


_IMAGE_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    ".heic": "image/heic",
    ".heif": "image/heif",
}


def _guess_image_mime(url_or_path: str) -> str:
    lowered = (url_or_path or "").split("?", 1)[0].lower()
    for ext, mime in _IMAGE_MIME_BY_EXT.items():
        if lowered.endswith(ext):
            return mime
    return "image/png"


def _msg_to_parts(msg: ChatMessage) -> list[dict]:
    parts: list[dict] = []

    if msg.role == "tool":
        parts.append({"type": "text", "text": f"[Tool result: {msg.name}]\n{msg.content or ''}"})
        return parts

    if msg.role == "assistant":
        if msg.tool_calls:
            for tc in msg.tool_calls:
                parts.append({
                    "type": "text",
                    "text": f"[Calling tool: {tc.name}({json.dumps(tc.arguments)})]",
                })
        if msg.content:
            parts.append({"type": "text", "text": msg.content})
        return parts

    if msg.role == "user":
        if msg.images:
            for img_url in msg.images:
                # OpenCode FilePartInputParam requires {type, mime, url} at top level.
                parts.append({
                    "type": "file",
                    "mime": _guess_image_mime(img_url),
                    "url": img_url,
                })
        if msg.content:
            parts.append({"type": "text", "text": msg.content})
        return parts

    return parts


def _extract_system_prompt(messages: list[ChatMessage]) -> str | None:
    system_parts = [m.content for m in messages if m.role == "system" and m.content]
    return "\n\n".join(system_parts) if system_parts else None


def _extract_new_parts(messages: list[ChatMessage]) -> list[dict]:
    """Pick the parts that represent NEW content for an existing session.

    - Trailing tool-result messages → tool results
    - Otherwise → the last message (typically user)
    System messages are sent separately via the ``system`` param.
    """
    if not messages:
        return []

    new_parts: list[dict] = []

    i = len(messages) - 1
    tool_results: list[ChatMessage] = []
    while i >= 0 and messages[i].role == "tool":
        tool_results.insert(0, messages[i])
        i -= 1

    if tool_results:
        for tr in tool_results:
            new_parts.extend(_msg_to_parts(tr))
        return new_parts

    last = messages[-1]
    return _msg_to_parts(last)


def _extract_replay_parts(messages: list[ChatMessage]) -> list[dict]:
    """Build a single parts list that replays prior history into a new session.

    OpenCode's session.chat() only accepts a user-side parts list per call,
    so prior assistant turns are folded into the next user message as quoted
    context. The final user/tool message ends the parts so the assistant
    responds to it.
    """
    parts: list[dict] = []
    pending_assistant: list[str] = []
    for msg in messages:
        if msg.role == "system":
            continue
        if msg.role == "assistant":
            for fragment in _msg_to_parts(msg):
                if fragment.get("type") == "text" and fragment.get("text"):
                    pending_assistant.append(fragment["text"])
            continue
        if pending_assistant:
            parts.append({
                "type": "text",
                "text": "[Previous assistant turn]\n" + "\n\n".join(pending_assistant),
            })
            pending_assistant = []
        parts.extend(_msg_to_parts(msg))
    if pending_assistant:
        parts.append({"type": "text", "text": "\n\n".join(pending_assistant)})
    return parts


# ── Core chat primitive ───────────────────────────────────────────────────


def _not_found_exc() -> type[Exception]:
    """Resolve opencode_ai.NotFoundError lazily so the module imports cleanly
    even when the SDK isn't installed (e.g. unit-test environments).
    """
    try:
        from opencode_ai import NotFoundError  # type: ignore[import-not-found]

        return NotFoundError
    except Exception:
        class _MissingNotFound(Exception):  # never matches a real exception
            pass

        return _MissingNotFound


async def _opencode_chat(
    session_id: str,
    parts: list[dict],
    *,
    model_id: str | None = None,
    provider_id: str | None = None,
    system: str | None = None,
    conversation_id: str | None = None,
) -> str:
    """Send a chat message to an OpenCode session and return the assistant text.

    Bypasses ``client.session.chat()`` because the opencode-ai SDK
    (>=0.1.0a36) encodes the model as flat top-level ``modelID``/``providerID``
    fields, while the actual OpenCode server schema nests them under
    ``model: {providerID, modelID}`` and has ``additionalProperties: false``
    — so the flat shape is silently dropped and the server falls back to its
    default model.  We POST the correctly-shaped body directly through the
    SDK's underlying transport so auth/timeouts still apply.

    Recovers from a stale ``NotFoundError`` by recreating the session once.
    ``system`` is only sent on the first message per conversation (the
    OpenCode session keeps the system prompt server-side after that).
    """
    NotFoundError = _not_found_exc()

    client = get_opencode_client()
    m, p = _resolve_model_provider(model_id, provider_id)

    send_system = bool(
        system and conversation_id and not _session_registry.has_system(conversation_id)
    )

    def _body() -> dict:
        body: dict = {
            "parts": parts,
            "model": {"providerID": p, "modelID": m},
        }
        if send_system:
            body["system"] = system
        return body

    async def _post(sid: str):
        return await client.post(
            f"/session/{sid}/message",
            body=_body(),
            cast_to=object,
        )

    try:
        resp = await _post(session_id)
    except NotFoundError:
        if not conversation_id:
            raise
        logger.warning(
            "[MASTER_AGENT] Stale session %s for %s; recreating once",
            session_id, conversation_id,
        )
        _session_registry.remove(conversation_id)
        session_id = await _session_registry.get_or_create(conversation_id)
        resp = await _post(session_id)

    if send_system and conversation_id:
        _session_registry.mark_system_set(conversation_id)

    _log_post_response_error(resp, m, p)

    return await read_session_text(session_id)


async def _opencode_command(
    session_id: str,
    command: str,
    arguments: str,
    *,
    conversation_id: str | None = None,
    agent: str | None = None,
    model_id: str | None = None,
    provider_id: str | None = None,
) -> str:
    """Invoke an OpenCode slash command (POST /session/{id}/command).

    The server resolves ``command`` against ``.opencode/commands/<name>.md``,
    substitutes ``$ARGUMENTS`` / ``$1`` / ``$2`` from ``arguments``, runs
    ``!`` bash injections, and submits the rendered prompt to the configured
    agent — all server-side. Use this when the connector receives a literal
    slash command from a user; it avoids re-injecting the command's result
    into the session as a fake user message (which is what happened with the
    bot-side ``askAgent('Create a plan for: ...')`` wrapper).

    Recovers from a stale ``NotFoundError`` by recreating the session once.
    """
    NotFoundError = _not_found_exc()

    client = get_opencode_client()
    m, p = _resolve_model_provider(model_id, provider_id)

    def _body() -> dict:
        body: dict = {
            "command": command,
            "arguments": arguments,
            "model": f"{p}/{m}",
        }
        if agent:
            body["agent"] = agent
        return body

    async def _post(sid: str):
        return await client.post(
            f"/session/{sid}/command",
            body=_body(),
            cast_to=object,
        )

    try:
        resp = await _post(session_id)
    except NotFoundError:
        if not conversation_id:
            raise
        logger.warning(
            "[MASTER_AGENT] Stale session %s for %s; recreating once",
            session_id, conversation_id,
        )
        _session_registry.remove(conversation_id)
        session_id = await _session_registry.get_or_create(conversation_id)
        resp = await _post(session_id)

    _log_post_response_error(resp, m, p)

    return await read_session_text(session_id)


def _log_post_response_error(resp, model_id: str, provider_id: str) -> None:
    """Surface ``info.error`` from the POST response so model/key failures
    don't silently degrade to an empty completion.

    OpenCode returns HTTP 200 even when the upstream provider rejects the
    request (bad key, unknown model id, rate limit) — the failure lives in
    ``info.error`` of the response body.  Without this, callers see only an
    empty string from ``read_session_text`` and have no signal as to why.
    """
    info = resp.get("info") if isinstance(resp, dict) else getattr(resp, "info", None)
    if info is None:
        return
    error = info.get("error") if isinstance(info, dict) else getattr(info, "error", None)
    if not error:
        return
    logger.error(
        "[MASTER_AGENT] OpenCode rejected %s/%s: %s",
        provider_id, model_id, _format_opencode_error(error) or error,
    )


async def _prepare_request(
    conversation_id: str,
    messages: list[ChatMessage],
) -> tuple[str, list[dict], str | None]:
    """Resolve (session_id, parts, system_prompt) for a chat request.

    On first hit for a conversation, returns replay parts (full history).
    On subsequent hits, returns only the new parts.
    """
    pre_existing = _session_registry.get(conversation_id) is not None
    session_id = await _session_registry.get_or_create(conversation_id)
    system_prompt = _extract_system_prompt(messages)

    if pre_existing:
        parts = _extract_new_parts(messages)
    else:
        parts = _extract_replay_parts(messages)

    if not parts:
        parts = [{"type": "text", "text": "(continue)"}]
    return session_id, parts, system_prompt


async def master_chat(
    messages: list[ChatMessage],
    tools: list[dict] | None = None,
    tool_choice: str | None = None,
    conversation_id: str | None = None,
    model: str | None = None,
    provider: str | None = None,
) -> ChatMessage:
    conv_id = conversation_id or f"default-{uuid.uuid4()}"
    try:
        session_id, parts, system_prompt = await _prepare_request(conv_id, messages)
        text = await _opencode_chat(
            session_id, parts,
            model_id=model, provider_id=provider,
            system=system_prompt, conversation_id=conv_id,
        )
    except Exception as e:
        logger.error("[MASTER_AGENT] OpenCode chat failed: %s", e)
        return ChatMessage(role="assistant", content=f"[OpenCode error: {e}]")

    parsed_tools = parse_custom_tool_calls(text)
    clean_text = strip_tool_blocks(text)
    return ChatMessage(role="assistant", content=clean_text or None, tool_calls=parsed_tools)


# ── Real streaming via /global/event SSE ──────────────────────────────────


async def _stream_session_deltas(
    session_id: str,
    chat_coro,
) -> AsyncIterator[str]:
    """Yield text deltas for `session_id` while running `chat_coro` in parallel.

    Subscribes to OpenCode's global event stream and filters for
    ``message.part.updated`` events that target this session.  The OpenCode
    server emits each part's full cumulative text on every update, so deltas
    are computed against the prior length per part_id.  Stops on
    ``session.idle``/``session.error``/``session.deleted`` for the session,
    or when ``chat_coro`` completes.

    On any streaming failure the consumer is expected to fall back to a
    post-hoc ``read_session_text``.
    """
    client = get_opencode_client()
    stream = await client.event.list()
    chat_task = asyncio.create_task(chat_coro)
    last_text_by_part: dict[str, str] = {}

    def _matches_session(obj) -> bool:
        sid = getattr(obj, "sessionID", None) or getattr(obj, "session_id", None)
        if sid is None:
            inner = getattr(obj, "info", None)
            if inner is not None:
                sid = getattr(inner, "id", None)
        return sid == session_id

    try:
        async for event in stream:
            etype = getattr(event, "type", None)
            payload = getattr(event, "properties", event)

            if etype == "message.part.updated":
                part = getattr(payload, "part", None)
                if part is None or not _matches_session(part):
                    pass  # may be flat shape — handled by hasattr below
                if part is None:
                    continue
                if getattr(part, "type", None) != "text":
                    continue
                if not _matches_session(part):
                    continue
                full = getattr(part, "text", "") or ""
                pid = getattr(part, "id", "") or ""
                prev = last_text_by_part.get(pid, "")
                if full == prev:
                    continue
                if full.startswith(prev):
                    yield full[len(prev):]
                else:
                    yield full
                last_text_by_part[pid] = full
            elif etype in ("session.idle", "session.error"):
                if _matches_session(payload):
                    break
            elif etype == "session.deleted":
                info = getattr(payload, "info", None)
                if info is not None and getattr(info, "id", None) == session_id:
                    break

            if chat_task.done():
                break
    finally:
        if not chat_task.done():
            try:
                await chat_task
            except Exception:
                pass
        try:
            await stream.close()
        except Exception:
            pass

    if chat_task.done() and chat_task.exception():
        raise chat_task.exception()


async def master_chat_stream(
    messages: list[ChatMessage],
    tools: list[dict] | None = None,
    tool_choice: str | None = None,
    conversation_id: str | None = None,
    model: str | None = None,
    provider: str | None = None,
) -> AsyncIterator[str | ToolCall]:
    conv_id = conversation_id or f"default-{uuid.uuid4()}"

    try:
        session_id, parts, system_prompt = await _prepare_request(conv_id, messages)
    except Exception as e:
        logger.error("[MASTER_AGENT] OpenCode stream prep failed: %s", e)
        yield f"[OpenCode error: {e}]"
        return

    chat_coro = _opencode_chat(
        session_id, parts,
        model_id=model, provider_id=provider,
        system=system_prompt, conversation_id=conv_id,
    )

    streamed_any = False
    accumulated: list[str] = []
    try:
        async for delta in _stream_session_deltas(session_id, chat_coro):
            streamed_any = True
            accumulated.append(delta)
            # Tool blocks are emitted as plain text; downstream callers strip them.
            yield delta
    except Exception as e:
        logger.error("[MASTER_AGENT] OpenCode streaming failed: %s", e)
        # Fall back to post-hoc read if streaming dies mid-flight.
        try:
            text = await read_session_text(session_id)
            for tc in parse_custom_tool_calls(text):
                yield tc
            return
        except Exception as fe:
            yield f"[OpenCode error: {fe}]"
            return

    if not streamed_any:
        # The chat finished but no events were observed (older server / non-streaming
        # provider). Read the final assistant text once and yield it as a single chunk.
        try:
            text = await read_session_text(session_id)
            clean = strip_tool_blocks(text)
            if clean:
                yield clean
            for tc in parse_custom_tool_calls(text):
                yield tc
            return
        except Exception as e:
            yield f"[OpenCode error: {e}]"
            return

    # Parse tool blocks from the full streamed text once.
    full_text = "".join(accumulated)
    for tc in parse_custom_tool_calls(full_text):
        yield tc


async def master_complete(
    prompt: str,
    system_prompt: str | None = None,
    conversation_id: str | None = None,
) -> str:
    messages = []
    if system_prompt:
        messages.append(ChatMessage(role="system", content=system_prompt))
    messages.append(ChatMessage(role="user", content=prompt))
    response = await master_chat(messages, conversation_id=conversation_id)
    return response.content or ""


# ── LLMClient-compatible shim ─────────────────────────────────────────────


class _OpenCodeLLMClient:
    """LLMClient-compatible adapter backed by OpenCode.

    Each instance binds a model+provider+conversation; model/provider are
    threaded per-call into _opencode_chat so concurrent clients on
    different models do not race a shared global.
    """

    def __init__(
        self,
        model: str = "",
        provider: str | None = None,
        config: LLMConfig | None = None,
        conversation_id: str | None = None,
    ):
        self.model = model or _master_config.model
        self.provider = provider or _master_config.provider
        self.config = config or LLMConfig()
        self.conversation_id = conversation_id or str(uuid.uuid4())

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
    ) -> ChatMessage:
        return await master_chat(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            conversation_id=self.conversation_id,
            model=self.model,
            provider=self.provider,
        )

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
    ) -> AsyncIterator[str | ToolCall]:
        async for chunk in master_chat_stream(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            conversation_id=self.conversation_id,
            model=self.model,
            provider=self.provider,
        ):
            yield chunk


def get_master_client(conversation_id: str | None = None) -> _OpenCodeLLMClient:
    return _OpenCodeLLMClient(
        model=_master_config.model,
        provider=_master_config.provider,
        config=_master_config.to_llm_config(),
        conversation_id=conversation_id,
    )


def create_client_for_model(
    model: str,
    provider: str | None = None,
    conversation_id: str | None = None,
) -> _OpenCodeLLMClient:
    model, provider = normalize_master_model(model, provider)
    return _OpenCodeLLMClient(model=model, provider=provider, conversation_id=conversation_id)


async def end_conversation(conversation_id: str) -> None:
    """Delete the OpenCode session for a conversation and forget it locally."""
    session_id = _session_registry.get(conversation_id)
    if session_id:
        client = get_opencode_client()
        try:
            await client.session.delete(session_id)
        except Exception as e:
            logger.warning("[MASTER_AGENT] Failed to delete session %s: %s", session_id, e)
    _session_registry.remove(conversation_id)
    logger.info("[MASTER_AGENT] Ended conversation: %s", conversation_id)
