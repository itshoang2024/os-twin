"""Memory Pool — manages multiple AgenticMemorySystem instances.

Each unique ``persist_dir`` gets one slot in the pool.  Multiple MCP
sessions pointing at the same directory share the same slot.  A background
sweep thread kills slots that have been idle for longer than
``idle_timeout_s``.

Three-tier resource model:
  Tier 1: ML runtime   — loaded once on pool creation, never unloaded.
  Tier 2: Memory slot   — one AgenticMemorySystem per persist_dir, created
                          and destroyed by the pool.
  Tier 3: MCP session   — maps a session to a persist_dir.  The pool doesn't
                          track sessions directly; it uses ``last_activity``
                          timestamps from tool calls to decide when to kill.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from .pool_config import PoolConfig, load_pool_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MemorySlot — one per unique persist_dir
# ---------------------------------------------------------------------------
@dataclass
class MemorySlot:
    """Holds a single AgenticMemorySystem and its bookkeeping."""

    system: Any  # AgenticMemorySystem — typed as Any to avoid import at module level
    persist_dir: str
    created_at: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)
    sync_stop: threading.Event = field(default_factory=threading.Event)
    sync_thread: Optional[threading.Thread] = None
    log_handler: Optional[logging.Handler] = None


# ---------------------------------------------------------------------------
# MemoryPool
# ---------------------------------------------------------------------------
class MemoryPool:
    """Manages a pool of AgenticMemorySystem instances keyed by persist_dir.

    Parameters
    ----------
    config : PoolConfig | None
        Pool configuration.  Loaded from env / config.default.json when None.
    system_factory : callable | None
        Override for creating AgenticMemorySystem instances.  Called as
        ``factory(persist_dir=...)``.  Used by tests to inject doubles.
    ml_preloader : callable | None
        Override for the ML preload function.  Called once in a background
        thread at pool construction.  Used by tests to skip heavy imports.
    """

    def __init__(
        self,
        config: PoolConfig | None = None,
        system_factory: Callable[..., Any] | None = None,
        ml_preloader: Callable[[], None] | None = None,
    ):
        self._config = config or load_pool_config()
        self._system_factory = system_factory
        self._slots: Dict[str, MemorySlot] = {}
        self._lock = threading.Lock()
        self._ml_ready = threading.Event()
        self._sweep_stop = threading.Event()
        self._sweep_thread: Optional[threading.Thread] = None
        # Track eviction/cleanup threads so kill_all() can join them (F5)
        self._cleanup_threads: list[threading.Thread] = []
        self._cleanup_threads_lock = threading.Lock()

        # --- Tier 1: ML preload ---
        if self._config.ml_preload:
            preloader = ml_preloader or self._default_ml_preload
            t = threading.Thread(
                target=self._run_ml_preload,
                args=(preloader,),
                daemon=True,
                name="pool-ml-preload",
            )
            t.start()
        else:
            self._ml_ready.set()

        # --- Idle sweep ---
        if self._config.idle_timeout_s > 0:
            self._sweep_thread = threading.Thread(
                target=self._sweep_loop,
                daemon=True,
                name="pool-idle-sweep",
            )
            self._sweep_thread.start()

    # -- ML preload ------------------------------------------------------------

    @staticmethod
    def _default_ml_preload() -> None:
        """Import heavy ML libraries so subsequent slot creation is fast."""
        from dashboard.agentic_memory.memory_system import _ensure_ml_imports

        _ensure_ml_imports()

    def _run_ml_preload(self, preloader: Callable[[], None]) -> None:
        try:
            preloader()
            logger.info("ML preload complete")
        except Exception:
            logger.exception("ML preload failed — slots will import on demand")
        finally:
            self._ml_ready.set()

    # -- Path validation -------------------------------------------------------

    def _validate_persist_dir(self, persist_dir: str) -> str:
        """Canonicalize and optionally validate the persist_dir.

        Raises ValueError when the path is rejected.
        """
        canonical = os.path.realpath(persist_dir)
        allowed = self._config.allowed_paths
        if allowed is not None:
            if not any(canonical.startswith(os.path.realpath(p)) for p in allowed):
                raise ValueError(f"persist_dir '{canonical}' is not under any allowed path: {allowed}")
        return canonical

    # -- Slot creation ---------------------------------------------------------

    def _create_system(self, persist_dir: str) -> Any:
        """Create an AgenticMemorySystem instance for *persist_dir*."""
        if self._system_factory is not None:
            return self._system_factory(persist_dir=persist_dir)

        from dashboard.agentic_memory.config import load_config
        from dashboard.agentic_memory.memory_system import AgenticMemorySystem

        # Base config from config.default.json (evolution, search, sync defaults)
        cfg = load_config()

        # Override with MasterSettings.memory (what the user actually configures
        # in the dashboard Settings > Memory tab).  This is the source of truth
        # for llm_backend, llm_model, embedding_backend, embedding_model, etc.
        llm_backend = cfg.llm.backend
        llm_model = cfg.llm.model
        embed_backend = cfg.embedding.backend
        embed_model = cfg.embedding.model
        vector_backend = cfg.vector.backend
        try:
            from dashboard.lib.settings.resolver import get_settings_resolver

            mem = get_settings_resolver().get_master_settings().memory
            if mem:
                if getattr(mem, "llm_backend", ""):
                    llm_backend = mem.llm_backend
                if getattr(mem, "llm_model", ""):
                    llm_model = mem.llm_model
                if getattr(mem, "embedding_backend", ""):
                    embed_backend = mem.embedding_backend
                if getattr(mem, "embedding_model", ""):
                    embed_model = mem.embedding_model
                if getattr(mem, "vector_backend", ""):
                    vector_backend = mem.vector_backend
        except Exception:
            pass

        return AgenticMemorySystem(
            model_name=embed_model,
            embedding_backend=embed_backend,
            vector_backend=vector_backend,
            persist_dir=persist_dir,
            context_aware_analysis=cfg.evolution.context_aware,
            context_aware_tree=cfg.evolution.context_aware_tree,
            max_links=cfg.evolution.max_links,
            similarity_weight=cfg.search.similarity_weight,
            decay_half_life_days=cfg.search.decay_half_life_days,
            conflict_resolution=cfg.sync.conflict_resolution,
            llm_model=llm_model,
            llm_backend=llm_backend,
        )

    def _start_sync_thread(self, slot: MemorySlot) -> None:
        """Start a per-slot auto-sync background thread."""
        interval = self._config.sync_interval_s

        def _sync_loop() -> None:
            while not slot.sync_stop.is_set():
                slot.sync_stop.wait(interval)
                if slot.sync_stop.is_set():
                    break
                try:
                    result = slot.system.sync_to_disk()
                    logger.debug("Auto-sync [%s]: %s", slot.persist_dir, result)
                except Exception:
                    logger.exception("Auto-sync failed [%s]", slot.persist_dir)

        t = threading.Thread(
            target=_sync_loop,
            daemon=True,
            name=f"pool-sync-{os.path.basename(slot.persist_dir)}",
        )
        slot.sync_thread = t
        t.start()

    @staticmethod
    def _create_log_handler(persist_dir: str) -> logging.FileHandler:
        """Create a per-slot file log handler at <persist_dir>/memory.log."""
        os.makedirs(persist_dir, exist_ok=True)
        log_path = os.path.join(persist_dir, "memory.log")
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        handler.setLevel(logging.DEBUG)
        return handler

    def _create_slot(self, persist_dir: str) -> MemorySlot:
        """Create a new MemorySlot (must be called with ``_lock`` held)."""
        system = self._create_system(persist_dir)
        slot = MemorySlot(system=system, persist_dir=persist_dir)
        slot.log_handler = self._create_log_handler(persist_dir)
        # Attach the handler to memory loggers so per-slot log file gets entries.
        # Also ensure loggers accept INFO+ (default effective level is WARNING).
        for log_name in ("dashboard.agentic_memory", "dashboard.routes.memory_mcp"):
            lgr = logging.getLogger(log_name)
            lgr.addHandler(slot.log_handler)
            if lgr.level == logging.NOTSET or lgr.level > logging.DEBUG:
                lgr.setLevel(logging.DEBUG)
        self._start_sync_thread(slot)
        logger.info(
            "Created memory slot: %s (%d notes)",
            persist_dir,
            len(system.memories),
        )
        # Log full config at slot creation for debugging
        self._log_slot_config(slot)
        return slot

    @staticmethod
    def _log_slot_config(slot: MemorySlot) -> None:
        """Log the effective configuration for a memory slot."""
        s = slot.system
        logger.info("=== Memory Slot Config ===")
        logger.info("  persist_dir:          %s", slot.persist_dir)
        logger.info("  embedding_backend:    %s", getattr(s, "embedding_backend", "?"))
        logger.info("  embedding_model:      %s", getattr(s, "model_name", "?"))
        logger.info("  vector_backend:       %s", getattr(s, "vector_backend", "?"))
        logger.info("  llm_backend:          %s", getattr(s, "llm_backend", "?"))
        logger.info("  llm_model:            %s", getattr(s, "llm_model", "?"))
        logger.info("  context_aware:        %s", getattr(s, "context_aware_analysis", "?"))
        logger.info("  max_links:            %s", getattr(s, "max_links", "?"))
        logger.info("  similarity_weight:    %s", getattr(s, "similarity_weight", "?"))
        logger.info("  decay_half_life_days: %s", getattr(s, "decay_half_life_days", "?"))
        logger.info("  conflict_resolution:  %s", getattr(s, "conflict_resolution", "?"))
        logger.info("  notes_loaded:         %d", len(s.memories))
        logger.info("=========================")

    # -- Eviction --------------------------------------------------------------

    def evict(self, persist_dir: str) -> bool:
        """Evict a specific slot by persist_dir. Returns True if found and evicted."""
        canonical = os.path.realpath(persist_dir)
        with self._lock:
            slot = self._slots.pop(canonical, None)
            if slot is None:
                return False
        # Cleanup outside lock
        t = threading.Thread(
            target=self._cleanup_slot,
            args=(slot,),
            daemon=True,
            name=f"pool-evict-{os.path.basename(canonical)}",
        )
        with self._cleanup_threads_lock:
            self._cleanup_threads = [ct for ct in self._cleanup_threads if ct.is_alive()]
            self._cleanup_threads.append(t)
        t.start()
        return True

    def _evict_one(self) -> bool:
        """Evict one idle slot according to policy.  Returns True if evicted.

        Must be called with ``_lock`` held.  The actual kill (sync + thread
        stop) is deferred to *after* the lock is released by the caller.
        """
        policy = self._config.eviction_policy
        if policy == "none":
            return False

        candidates = list(self._slots.values())
        if not candidates:
            return False

        if policy == "oldest":
            victim = min(candidates, key=lambda s: s.created_at)
        else:  # lru
            victim = min(candidates, key=lambda s: s.last_activity)

        self._slots.pop(victim.persist_dir, None)
        # Schedule cleanup outside the lock; track the thread (F5)
        t = threading.Thread(
            target=self._cleanup_slot,
            args=(victim,),
            daemon=True,
            name=f"pool-evict-{os.path.basename(victim.persist_dir)}",
        )
        with self._cleanup_threads_lock:
            # Prune completed threads to avoid unbounded growth
            self._cleanup_threads = [ct for ct in self._cleanup_threads if ct.is_alive()]
            self._cleanup_threads.append(t)
        t.start()
        logger.info("Evicted slot (%s): %s", policy, victim.persist_dir)
        return True

    # -- Public API ------------------------------------------------------------

    def get_or_create(self, persist_dir: str) -> MemorySlot:
        """Get an existing slot or create one for *persist_dir*.

        Updates ``last_activity`` on every call.

        Raises
        ------
        ValueError
            If *persist_dir* is not under ``allowed_paths``.
        RuntimeError
            If the pool is full and eviction policy is ``none``.
        """
        canonical = self._validate_persist_dir(persist_dir)

        with self._lock:
            slot = self._slots.get(canonical)
            if slot is not None:
                slot.last_activity = time.monotonic()
                return slot

            # Need to create — check capacity
            if len(self._slots) >= self._config.max_instances:
                if not self._evict_one():
                    raise RuntimeError(
                        f"Memory pool is full ({self._config.max_instances} "
                        f"instances) and eviction policy is "
                        f"'{self._config.eviction_policy}'."
                    )

        # Wait for ML outside the lock
        if not self._ml_ready.wait(timeout=self._config.ml_ready_timeout_s):
            logger.warning(
                "ML preload not ready after %ds — creating slot anyway",
                self._config.ml_ready_timeout_s,
            )

        with self._lock:
            # Double-check: another thread may have created it while we waited
            slot = self._slots.get(canonical)
            if slot is not None:
                slot.last_activity = time.monotonic()
                return slot

            slot = self._create_slot(canonical)
            self._slots[canonical] = slot
            return slot

    def touch(self, persist_dir: str) -> None:
        """Update last_activity for a slot (call on every tool invocation)."""
        canonical = os.path.realpath(persist_dir)
        with self._lock:
            slot = self._slots.get(canonical)
            if slot is not None:
                slot.last_activity = time.monotonic()

    def kill_slot(self, persist_dir: str) -> bool:
        """Kill a specific slot: final sync, stop sync thread, remove.

        Returns True if the slot existed and was killed.
        """
        canonical = os.path.realpath(persist_dir)
        with self._lock:
            slot = self._slots.pop(canonical, None)
        if slot is None:
            return False
        self._cleanup_slot(slot)
        return True

    def _cleanup_slot(self, slot: MemorySlot) -> None:
        """Stop sync thread, run final sync with timeout, and release resources.

        Thread-safe.  The sync is capped at 30s to avoid indefinite blocking
        if disk I/O hangs (F6).  The retriever's close() is called to release
        any resources it holds (F1).
        """
        slot.sync_stop.set()
        if self._config.sync_on_kill:
            import concurrent.futures

            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(slot.system.sync_to_disk)
                    future.result(timeout=30)  # 30s max for final sync
                    logger.info("Final sync completed: %s", slot.persist_dir)
            except concurrent.futures.TimeoutError:
                logger.warning("Final sync timed out after 30s: %s", slot.persist_dir)
            except Exception:
                logger.exception("Final sync failed: %s", slot.persist_dir)
        # Release retriever resources (embedding model ref, handles)
        if hasattr(slot.system, "retriever") and hasattr(slot.system.retriever, "close"):
            try:
                slot.system.retriever.close()
            except Exception:
                logger.exception("Retriever close failed: %s", slot.persist_dir)
        # Flush and close per-slot log handler
        if slot.log_handler:
            try:
                slot.log_handler.flush()
                slot.log_handler.close()
            except Exception:
                pass
        logger.info("Killed memory slot: %s", slot.persist_dir)

    def kill_all(self) -> None:
        """Kill every slot and join cleanup threads.  Called on dashboard shutdown."""
        self._sweep_stop.set()
        with self._lock:
            dirs = list(self._slots.keys())
        for d in dirs:
            self.kill_slot(d)
        # Wait for any in-flight eviction/cleanup threads (F5)
        with self._cleanup_threads_lock:
            threads_to_join = list(self._cleanup_threads)
            self._cleanup_threads.clear()
        for t in threads_to_join:
            t.join(timeout=10)
            if t.is_alive():
                logger.warning("Cleanup thread %s did not finish in 10s", t.name)
        logger.info("All memory slots killed")

    def stats(self) -> dict:
        """Return pool status for the health endpoint."""
        now = time.monotonic()
        with self._lock:
            slots_info = []
            for slot in self._slots.values():
                slots_info.append(
                    {
                        "persist_dir": slot.persist_dir,
                        "notes_count": len(slot.system.memories),
                        "idle_seconds": round(now - slot.last_activity, 1),
                        "created_ago_s": round(now - slot.created_at, 1),
                        "sync_thread_alive": (slot.sync_thread is not None and slot.sync_thread.is_alive()),
                    }
                )
            return {
                "ml_ready": self._ml_ready.is_set(),
                "active_slots": len(self._slots),
                "slots": slots_info,
                "config": {
                    "idle_timeout_s": self._config.idle_timeout_s,
                    "max_instances": self._config.max_instances,
                    "eviction_policy": self._config.eviction_policy,
                    "sync_interval_s": self._config.sync_interval_s,
                },
            }

    @property
    def active_slots(self) -> int:
        with self._lock:
            return len(self._slots)

    # -- Idle sweep ------------------------------------------------------------

    def _sweep_loop(self) -> None:
        """Periodically check for and kill idle slots."""
        interval = self._config.sweep_interval_s
        timeout = self._config.idle_timeout_s
        while not self._sweep_stop.is_set():
            self._sweep_stop.wait(interval)
            if self._sweep_stop.is_set():
                break
            self._sweep_once(timeout)

    def _sweep_once(self, timeout: float) -> None:
        """Single sweep pass — kill slots idle for longer than *timeout*."""
        now = time.monotonic()
        to_kill: list[str] = []
        with self._lock:
            for persist_dir, slot in self._slots.items():
                if now - slot.last_activity > timeout:
                    to_kill.append(persist_dir)

        for persist_dir in to_kill:
            logger.info("Idle sweep killing: %s", persist_dir)
            self.kill_slot(persist_dir)
