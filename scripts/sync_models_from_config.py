"""One-off: make .agents/config.json the ground truth for role fields.

Reads selected fields from the project engine config (.agents/config.json)
and writes them back into the canonical sources the startup sync reads from,
in precedence order:

  1. project  .agents/roles/<name>/role.json
  2. global   ~/.ostwin/.agents/roles/<name>/role.json
  3. global   ~/.ostwin/.agents/roles/config.json (legacy list)

Layer 3 is merged last by RoleRepository.list_roles() and therefore wins,
so it must be updated for the change to survive a restart.

Synced fields (engine-config key -> role.json key / legacy-list key):
  default_model    -> model            / version
  timeout_seconds  -> timeout_seconds  / timeout_seconds

For timeout, role.json may carry the legacy alias "timeout"; it resolves only
when "timeout_seconds" is absent (store.py:318-320), so we set
"timeout_seconds" and keep any existing "timeout" alias in sync to avoid a
stale value confusing a human reader.

Run:  python scripts/sync_models_from_config.py            (dry run)
      python scripts/sync_models_from_config.py --apply    (write)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENGINE_CONFIG = PROJECT_ROOT / ".agents" / "config.json"
PROJECT_ROLES = PROJECT_ROOT / ".agents" / "roles"

OSTWIN_HOME = Path(os.environ.get("OSTWIN_HOME", str(Path.home() / ".ostwin")))
GLOBAL_ROLES = OSTWIN_HOME / ".agents" / "roles"
GLOBAL_LEGACY = GLOBAL_ROLES / "config.json"

# Top-level keys in engine config.json that are NOT roles.
NON_ROLE_KEYS = {
    "version", "project_name", "memory", "channel", "release",
    "runtime", "knowledge", "providers",
}

# (engine config.json key, role.json key, legacy-list key, role.json aliases)
FIELDS = [
    ("default_model", "model", "version", ()),
    ("timeout_seconds", "timeout_seconds", "timeout_seconds", ("timeout",)),
    ("instance_type", "instance_type", "instance_type", ()),
]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, data) -> None:
    # Preserve real UTF-8 (em-dashes etc.) instead of \uXXXX escapes.
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def effective(d: dict, key: str, aliases: tuple) -> object:
    """Current resolved value, honouring the same precedence as store.py."""
    for k in (key, *aliases):
        if d.get(k) is not None:
            return d.get(k)
    return None


def main() -> int:
    apply = "--apply" in sys.argv

    cfg = load(ENGINE_CONFIG)
    roles = {
        name: v
        for name, v in cfg.items()
        if isinstance(v, dict) and name not in NON_ROLE_KEYS
    }

    # targets[engine_key] = {role_name: value}
    targets = {
        ekey: {name: v[ekey] for name, v in roles.items() if ekey in v}
        for ekey, *_ in FIELDS
    }
    summary = ", ".join(f"{ekey}={len(t)}" for ekey, t in targets.items())
    print(f"Ground truth: {ENGINE_CONFIG}\n  {summary} role(s)\n")

    changes: list[tuple[str, str, str, str, str]] = []  # (layer, field, role, old, new)

    # Layers 1 & 2 — role.json files
    for layer, root in (("project", PROJECT_ROLES), ("global", GLOBAL_ROLES)):
        for ekey, rkey, _lkey, aliases in FIELDS:
            for name, val in targets[ekey].items():
                rj = root / name / "role.json"
                if not rj.exists():
                    continue
                d = load(rj)
                old = effective(d, rkey, aliases)
                if old != val:
                    changes.append((f"{layer} role.json", rkey, name, str(old), str(val)))
                    if apply:
                        d[rkey] = val
                        for alias in aliases:
                            if alias in d:
                                d[alias] = val
                        dump(rj, d)

    # Layer 3 — global legacy config.json list (wins at merge time)
    if GLOBAL_LEGACY.exists():
        legacy = load(GLOBAL_LEGACY)
        dirty = False
        for entry in legacy:
            name = entry.get("name")
            for ekey, _rkey, lkey, _aliases in FIELDS:
                if name in targets[ekey] and entry.get(lkey) != targets[ekey][name]:
                    changes.append((
                        "global config.json", lkey, name,
                        str(entry.get(lkey)), str(targets[ekey][name]),
                    ))
                    entry[lkey] = targets[ekey][name]
                    dirty = True
        if apply and dirty:
            dump(GLOBAL_LEGACY, legacy)

    # Report
    if not changes:
        print("Nothing to change — all sources already match config.json.")
        return 0

    rw = max(len(c[2]) for c in changes)
    fw = max(len(c[1]) for c in changes)
    for layer, field, role, old, new in changes:
        print(f"  [{layer:<20}] {field:<{fw}} {role:<{rw}}  {old}  ->  {new}")

    print(f"\n{len(changes)} field(s) {'updated' if apply else 'would change'}.")
    if not apply:
        print("Dry run. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
