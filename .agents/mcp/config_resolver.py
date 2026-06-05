import json
import re
import os
import shlex
import sys
from typing import Any, Dict, List, Tuple
from pathlib import Path

# Try to import vault from the same directory
try:
    from .vault import get_vault
except ImportError:
    # Fallback for standalone execution
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from vault import get_vault

# Regex to match ${vault:server/key}
VAULT_REF_PATTERN = re.compile(r"\$\{vault:([^/]+)/([^}]+)\}")


def _split_command_text(command: str) -> List[str]:
    """Split a shell-style command string into argv parts."""
    stripped = command.strip()
    if not stripped:
        return []
    try:
        return shlex.split(stripped)
    except ValueError:
        return stripped.split()


def _normalize_local_command(command: Any) -> Any:
    """Normalize local MCP command values to argv-style arrays."""
    if isinstance(command, str):
        return _split_command_text(command)
    if (
        isinstance(command, list)
        and len(command) == 1
        and isinstance(command[0], str)
    ):
        return _split_command_text(command[0])
    return command


class ConfigResolver:
    def __init__(self):
        self.vault = get_vault()

    def resolve_config(self, config_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively resolves vault references in a config dictionary."""
        return self._resolve_recursive(config_dict)

    def _resolve_recursive(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: self._resolve_recursive(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._resolve_recursive(v) for v in obj]
        elif isinstance(obj, str):
            match = VAULT_REF_PATTERN.search(obj)
            if match:
                server, key = match.groups()
                secret = self.vault.get(server, key)
                if secret is None:
                    raise ValueError(
                        f"Vault reference not found: ${{vault:{server}/{key}}}"
                    )
                # Replace the entire reference with the secret
                # Note: this only supports one reference per string for now
                return obj.replace(match.group(0), secret)
        return obj

    def has_unresolved_refs(self, config_dict: Dict[str, Any]) -> List[str]:
        """Returns a list of missing vault references as 'server/key' strings."""
        unresolved = []
        refs = self.extract_vault_refs(config_dict)
        for server, key in refs:
            if self.vault.get(server, key) is None:
                unresolved.append(f"{server}/{key}")
        return unresolved

    def extract_vault_refs(self, config_dict: Dict[str, Any]) -> List[Tuple[str, str]]:
        """Extracts all vault references found in the config dictionary."""
        refs = []
        self._extract_recursive(config_dict, refs)
        return sorted(list(set(refs)))

    def _extract_recursive(self, obj: Any, refs: List[Tuple[str, str]]):
        if isinstance(obj, dict):
            for v in obj.values():
                self._extract_recursive(v, refs)
        elif isinstance(obj, list):
            for v in obj:
                self._extract_recursive(v, refs)
        elif isinstance(obj, str):
            for match in VAULT_REF_PATTERN.finditer(obj):
                refs.append(match.groups())

    # Simple ${VAR} — no nested braces allowed in the name
    _SIMPLE_VAR = re.compile(r"\$\{([A-Za-z_]\w*)\}")
    # ${VAR:-default} where default has NO nested ${...} (already resolved by prior pass)
    _DEFAULT_VAR = re.compile(r"\$\{([A-Za-z_]\w*):-([^$}]*)\}")

    def compile_config(
        self,
        home_config: Dict[str, Any],
        builtin_config: Dict[str, Any],
        agent_dir: str = None,
        project_dir: str = None,
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        """
        Compiles home config + builtin config into project config.
        Resolves all ${VAR}, ${VAR:-default}, ${vault:server/key}, and {env:VAR} references.
        Uses OpenCode format: top-level "mcp" key, "type"/"command" array/"environment"/"url".
        Returns the compiled config and env var mapping.
        """
        # Merge configs (OpenCode format uses "mcp" as top-level key)
        # Also accept legacy "mcpServers" key to avoid silently dropping servers during upgrade
        compiled_config = {"mcp": {}}
        compiled_config["mcp"].update(
            builtin_config.get("mcp", builtin_config.get("mcpServers", {}))
        )
        compiled_config["mcp"].update(
            home_config.get("mcp", home_config.get("mcpServers", {}))
        )

        # Build known variable values for ${VAR} resolution
        home = os.path.expanduser("~")
        if agent_dir is None:
            agent_dir = os.path.join(home, ".ostwin")
        # project_dir parameter takes precedence over os.getcwd()
        # (callers pass --project-dir which becomes the project_dir kwarg)
        if project_dir is None:
            project_dir = os.getcwd()

        known_vars = {
            "HOME": home,
            "AGENT_DIR": agent_dir,
            "PROJECT_DIR": project_dir,
            "AGENT_OS_PROJECT_DIR": project_dir,
            "OSTWIN_PYTHON": os.path.join(agent_dir, ".venv", "bin", "python"),
        }
        # Also pull from actual environment for any other vars
        for k, v in os.environ.items():
            if k not in known_vars:
                known_vars[k] = v

        # Auto-load env vars from .env files so `ostwin init` can resolve
        # placeholders like {env:GOOGLE_API_KEY} without requiring the user
        # to export them in their shell. Search order (later wins):
        #   1. ~/.ostwin/.env (global ostwin secrets)
        #   2. <agent_dir>/.env (deploy-specific)
        #   3. <project_dir>/.env (project-specific)
        #   4. <agent_dir>/mcp/.env.mcp (MCP-specific)
        def _load_env_file(path):
            if not os.path.exists(path):
                return
            try:
                with open(path) as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, _, v = line.partition("=")
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k and k not in known_vars:
                            known_vars[k] = v
            except (OSError, IOError):
                pass

        _load_env_file(os.path.join(home, ".ostwin", ".env"))
        _load_env_file(os.path.join(agent_dir, ".env"))
        _load_env_file(os.path.join(project_dir, ".env"))
        _load_env_file(os.path.join(agent_dir, ".agents", "mcp", ".env.mcp"))

        # Also scan shell rc files for `export VAR=value` lines.
        # Useful for users who keep secrets in ~/.bashrc / ~/.zshrc instead of .env.
        _shell_export_re = re.compile(
            r"^\s*export\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)\s*$"
        )

        def _load_shell_rc(path):
            if not os.path.exists(path):
                return
            try:
                with open(path) as f:
                    for line in f:
                        m = _shell_export_re.match(line)
                        if not m:
                            continue
                        k = m.group(1)
                        v = m.group(2).strip().strip('"').strip("'")
                        # Strip inline comments
                        if " #" in v:
                            v = v.split(" #")[0].rstrip()
                        if k and k not in known_vars:
                            known_vars[k] = v
            except (OSError, IOError):
                pass

        for rc in (".bashrc", ".zshrc", ".profile", ".bash_profile"):
            _load_shell_rc(os.path.join(home, rc))

        env_vars = {}

        # OpenCode {env:VAR} pattern
        opencode_var = re.compile(r"\{env:(\w+)\}")

        def _resolve_bash_vars(s: str) -> str:
            """Resolve ${VAR}, ${VAR:-default}, and {env:VAR} patterns.
            Strategy: resolve innermost simple ${VAR} first, then ${VAR:-default} on next pass.
            Also handles OpenCode-style {env:VAR}."""
            for _ in range(5):  # max passes
                prev = s

                # Pass A: resolve simple ${VAR}
                def _replace_simple(m):
                    var_name = m.group(1)
                    value = known_vars.get(var_name)
                    if value is not None:
                        return value
                    return m.group(0)

                s = self._SIMPLE_VAR.sub(_replace_simple, s)

                # Pass B: resolve ${VAR:-default}
                def _replace_default(m):
                    var_name = m.group(1)
                    default = m.group(2)
                    value = known_vars.get(var_name)
                    if value is not None:
                        return value
                    return default

                s = self._DEFAULT_VAR.sub(_replace_default, s)

                # Pass C: resolve OpenCode {env:VAR}
                def _replace_opencode(m):
                    var_name = m.group(1)
                    value = known_vars.get(var_name)
                    if value is not None:
                        return value
                    return m.group(0)

                s = opencode_var.sub(_replace_opencode, s)
                if s == prev:
                    break
            return s

        def _compile_recursive(obj, server_name):
            if isinstance(obj, dict):
                return {k: _compile_recursive(v, server_name) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_compile_recursive(v, server_name) for v in obj]
            elif isinstance(obj, str):
                # 1. Resolve vault references first
                match = VAULT_REF_PATTERN.search(obj)
                if match:
                    server, key = match.groups()
                    secret = self.vault.get(server, key)
                    # ENV var naming convention: MCP_{SERVER}_{KEY}
                    # Use OpenCode {env:VAR} syntax for variable references
                    env_name = f"MCP_{server.upper()}_{key.upper()}".replace(
                        "-", "_"
                    ).replace(".", "_")
                    env_vars[env_name] = secret or ""
                    obj = obj.replace(match.group(0), f"{{env:{env_name}}}")

                # 2. Resolve ${VAR} and ${VAR:-default} patterns
                return _resolve_bash_vars(obj)
            return obj

        for name, server_cfg in compiled_config["mcp"].items():
            compiled_config["mcp"][name] = _compile_recursive(server_cfg, name)

        for name, server_cfg in compiled_config["mcp"].items():
            is_local = server_cfg.get("type") == "local" or (
                "command" in server_cfg and server_cfg.get("type") != "remote"
            )
            if is_local and "command" in server_cfg:
                server_cfg["command"] = _normalize_local_command(
                    server_cfg["command"]
                )

        # Resolve bare "python"/"python3" in command[0] to the ostwin venv path
        ostwin_python = known_vars.get("OSTWIN_PYTHON", "")
        if ostwin_python and os.path.isfile(ostwin_python):
            for name, server_cfg in compiled_config["mcp"].items():
                cmd = server_cfg.get("command")
                if (
                    isinstance(cmd, list)
                    and len(cmd) > 0
                    and cmd[0] in ("python", "python3")
                ):
                    cmd[0] = ostwin_python

        # Clean up + resolve relative paths in environment/env values
        _unresolved_re = re.compile(r"\$\{[^}]+\}|\{env:[^}]+\}")
        for name, server_cfg in compiled_config["mcp"].items():
            # Support both "environment" (OpenCode) and "env" (legacy)
            for env_key in ("environment", "env"):
                if env_key in server_cfg and isinstance(server_cfg[env_key], dict):
                    # Drop entries that still contain unresolved ${VAR} or {env:VAR} placeholders
                    server_cfg[env_key] = {
                        k: v
                        for k, v in server_cfg[env_key].items()
                        if not (isinstance(v, str) and _unresolved_re.search(v))
                    }
                    # Resolve relative paths to absolute project_dir
                    for k, v in server_cfg[env_key].items():
                        if (
                            isinstance(v, str)
                            and not os.path.isabs(v)
                            and (v == "." or v.startswith("./"))
                        ):
                            if v == ".":
                                server_cfg[env_key][k] = project_dir
                            else:
                                server_cfg[env_key][k] = os.path.join(
                                    project_dir, v[2:]
                                )

        return compiled_config, env_vars


if __name__ == "__main__":
    # Test script
    resolver = ConfigResolver()
    test_config = {
        "mcp": {
            "test": {
                "type": "local",
                "command": ["python", "-m", "server"],
                "environment": {"API_KEY": "${vault:test/API_KEY}", "OTHER": "plain"},
            }
        }
    }
    print("Extracting refs:", resolver.extract_vault_refs(test_config))
    print("Has unresolved:", resolver.has_unresolved_refs(test_config))

    # Try setting a value and resolving
    resolver.vault.set("test", "API_KEY", "secret-value")
    print("Resolved config:", resolver.resolve_config(test_config))
    resolver.vault.delete("test", "API_KEY")
