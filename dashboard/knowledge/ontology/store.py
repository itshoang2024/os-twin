"""Namespace-scoped ontology profile storage."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from dashboard.knowledge.namespace import NamespaceManager, NamespaceNotFoundError
from dashboard.knowledge.ontology.models import OntologyProfile, OntologyUnit


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

    def unit_path(self, namespace: str) -> Path:
        """Return ``{knowledge_dir}/{namespace}/ontology/unit.json``."""
        return self.ontology_dir(namespace) / "unit.json"

    def _installed_pack_ids(self, namespace: str) -> list[str]:
        path = self.ontology_dir(namespace) / "packs_state.json"
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        packs = data.get("installed_packs") if isinstance(data, dict) else {}
        if not isinstance(packs, dict):
            return []
        return sorted(pid for pid, rec in packs.items() if isinstance(rec, dict) and rec.get("status", "installed") == "installed")

    def get_unit(self, namespace: str) -> OntologyUnit | None:
        """Load the ontology unit, synthesizing one for legacy profile-only namespaces."""
        if self._nm.get(namespace) is None:
            return None
        path = self.unit_path(namespace)
        if path.exists():
            with path.open("r", encoding="utf-8") as fh:
                unit = OntologyUnit.model_validate(json.load(fh))
            if unit.namespace != namespace:
                raise ValueError("Ontology unit namespace must match path namespace")
            return unit
        profile_path = self.profile_path(namespace)
        if not profile_path.exists():
            return None
        with profile_path.open("r", encoding="utf-8") as fh:
            profile = OntologyProfile.model_validate(json.load(fh))
        if profile.namespace != namespace:
            raise ValueError("Ontology profile namespace must match path namespace")
        return OntologyUnit(
            namespace=namespace,
            active_profile_id=profile.profile_id,
            installed_packs=self._installed_pack_ids(namespace),
        )

    def get(self, namespace: str) -> OntologyProfile | None:
        """Load the active profile, or ``None`` for legacy namespaces with no profile."""
        if self._nm.get(namespace) is None:
            return None
        unit = self.get_unit(namespace)
        path = self.profile_path(namespace)
        if not path.exists():
            if unit is not None and unit.active_profile_id is not None:
                raise ValueError("Ontology unit active_profile_id references a missing profile")
            return None
        with path.open("r", encoding="utf-8") as fh:
            profile = OntologyProfile.model_validate(json.load(fh))
        if profile.namespace != namespace:
            raise ValueError("Ontology profile namespace must match path namespace")
        if unit is not None:
            if unit.active_profile_id is None:
                return None
            if unit.active_profile_id != profile.profile_id:
                raise ValueError("Ontology unit active_profile_id does not match stored active profile")
        return profile

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
                unit = self.get_unit(namespace)
                unit_data = (
                    unit.model_dump(mode="json")
                    if unit is not None
                    else {"namespace": namespace, "active_profile_id": profile.profile_id}
                )
                unit_data.update(
                    {
                        "id": namespace,
                        "namespace": namespace,
                        "active_profile_id": profile.profile_id,
                        "installed_packs": self._installed_pack_ids(namespace),
                    }
                )
                self.write_unit(OntologyUnit.model_validate(unit_data))
            return profile

    def write_unit(self, unit: OntologyUnit) -> OntologyUnit:
        """Validate and atomically persist ``unit`` under its namespace."""
        namespace = unit.namespace
        if self._nm.get(namespace) is None:
            raise NamespaceNotFoundError(namespace)
        profile_path = self.profile_path(namespace)
        if profile_path.exists():
            with profile_path.open("r", encoding="utf-8") as fh:
                profile = OntologyProfile.model_validate(json.load(fh))
            if profile.namespace != namespace:
                raise ValueError("Ontology profile namespace must match unit namespace")
            if unit.active_profile_id is not None and unit.active_profile_id != profile.profile_id:
                raise ValueError("OntologyUnit.active_profile_id must reference an existing profile in the same namespace")
        target = self.unit_path(namespace)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".unit.", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(unit.model_dump(mode="json"), fh, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, target)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return unit

    def list_namespaces_with_profiles(self) -> list[str]:
        """Return namespace ids that currently have an ontology profile file."""
        return [meta.name for meta in self._nm.list() if self.profile_path(meta.name).exists()]
