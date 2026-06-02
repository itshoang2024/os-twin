"""Namespace-scoped ontology profile storage."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from dashboard.knowledge.namespace import NamespaceManager, NamespaceNotFoundError
from dashboard.knowledge.ontology.models import OntologyProfile


class OntologyProfileStore:
    """Read and atomically write the single active ontology profile per namespace."""

    def __init__(self, namespace_manager: NamespaceManager) -> None:
        self._nm = namespace_manager
        self._lock = threading.Lock()

    def ontology_dir(self, namespace: str) -> Path:
        """Return ``{knowledge_dir}/{namespace}/ontology``."""
        return self._nm.namespace_dir(namespace) / "ontology"

    def profile_path(self, namespace: str) -> Path:
        """Return ``{knowledge_dir}/{namespace}/ontology/profile.json``."""
        return self.ontology_dir(namespace) / "profile.json"

    def get(self, namespace: str) -> OntologyProfile | None:
        """Load the active profile, or ``None`` for legacy namespaces with no profile."""
        if self._nm.get(namespace) is None:
            return None
        path = self.profile_path(namespace)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as fh:
            return OntologyProfile.model_validate(json.load(fh))

    def write(self, profile: OntologyProfile, *, set_active: bool = True) -> OntologyProfile:
        """Validate and atomically persist ``profile`` under its namespace."""
        namespace = profile.namespace
        with self._lock:
            meta = self._nm.get(namespace)
            if meta is None:
                raise NamespaceNotFoundError(namespace)

            target = self.profile_path(namespace)
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(prefix=".profile.", suffix=".tmp", dir=str(target.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(profile.model_dump(mode="json"), fh, indent=2, sort_keys=True)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_path, target)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            if set_active:
                meta.ontology_profile_version = profile.version
                self._nm.write_manifest(namespace, meta)
            return profile

    def list_namespaces_with_profiles(self) -> list[str]:
        """Return namespace ids that currently have an ontology profile file."""
        return [meta.name for meta in self._nm.list() if self.profile_path(meta.name).exists()]
