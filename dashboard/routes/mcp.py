"""
MCP Extension Management API Routes.

Provides endpoints to install, list, remove, and sync MCP server extensions.
Delegates to mcp-extension.sh for actual operations.
"""

import json
import asyncio
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client

from dashboard.api_utils import AGENTS_DIR
from dashboard.auth import get_current_user

# Try to import vault and config_resolver from .agents/mcp
import sys
import os
MCP_MODULE_PATH = str(AGENTS_DIR / "mcp")
if MCP_MODULE_PATH not in sys.path:
    sys.path.append(MCP_MODULE_PATH)

try:
    from vault import get_vault
    from config_resolver import ConfigResolver
except ImportError:
    # Fallback if not in the right environment
    get_vault = None
    ConfigResolver = None

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

MCP_DIR = AGENTS_DIR / "mcp"
EXTENSIONS_FILE = MCP_DIR / "extensions.json"
CATALOG_FILE = MCP_DIR / "mcp-catalog.json"
BUILTIN_CONFIG_FILE = MCP_DIR / "mcp-builtin.json"
HOME_CONFIG_FILE = Path.home() / ".ostwin" / ".agents" / "mcp" / "config.json"
if not HOME_CONFIG_FILE.exists():
    _legacy = Path.home() / ".ostwin" / ".agents" / "mcp" / "mcp-config.json"
    if _legacy.exists():
        HOME_CONFIG_FILE = _legacy
DEPLOY_CONFIG_FILE = Path.home() / ".ostwin" / ".agents" / "mcp" / "mcp-config.json"
SCRIPT = MCP_DIR / "mcp-extension.sh"


class InstallRequest(BaseModel):
    """Request body for installing an MCP extension."""
    repo: Optional[str] = None   # Git URL (alternative to name)
    name: Optional[str] = None   # Package name from catalog, or override name for git URL
    branch: Optional[str] = None # Git branch


class McpServerConfig(BaseModel):
    name: str
    type: str  # 'local'/'remote' (OpenCode) or 'stdio'/'http' (legacy)
    # OpenCode format: command is an array; legacy: string + separate args
    command: Optional[Any] = None
    args: Optional[List[str]] = None  # Legacy: separate args list
    url: Optional[str] = None
    httpUrl: Optional[str] = None  # Legacy alias for url
    environment: Optional[Dict[str, str]] = None
    env: Optional[Dict[str, str]] = None  # Legacy alias for environment
    headers: Optional[Dict[str, str]] = None
    enabled: Optional[bool] = True
    timeout: Optional[int] = None
    store_in_vault: bool = False

    def normalize(self) -> "McpServerConfig":
        """Normalize legacy fields to OpenCode format in-place."""
        # Normalize type: stdio → local, http → remote
        if self.type == "stdio":
            self.type = "local"
        elif self.type == "http":
            self.type = "remote"
        # Normalize command: string + args → array
        if isinstance(self.command, str):
            cmd_parts = [self.command]
            if self.args:
                cmd_parts.extend(self.args)
            self.command = cmd_parts
            self.args = None
        # Normalize url: httpUrl → url
        if self.httpUrl and not self.url:
            self.url = self.httpUrl
            self.httpUrl = None
        # Normalize env: env → environment
        if self.env and not self.environment:
            self.environment = self.env
            self.env = None
        return self


class CredentialUpdate(BaseModel):
    value: str


def _read_json(path: Path) -> dict:
    """Read a JSON file, return empty dict if missing."""
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _get_servers(data: dict) -> dict:
    """Extract MCP servers dict, supporting both OpenCode 'mcp' and legacy 'mcpServers' keys."""
    return data.get("mcp", data.get("mcpServers", {}))


async def _run_script(args: list[str], timeout: int = 120) -> dict:
    """Run mcp-extension.sh with given args and return stdout/stderr/code."""
    cmd = ["bash", str(SCRIPT)] + args
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )
        return {
            "stdout": stdout.decode(),
            "stderr": stderr.decode(),
            "returncode": process.returncode,
        }
    except asyncio.TimeoutError:
        process.kill()
        return {
            "stdout": "",
            "stderr": "Command timed out",
            "returncode": -1,
        }


@router.get("/extensions")
async def list_extensions(user: dict = Depends(get_current_user)):
    """List all installed MCP extensions."""
    data = _read_json(EXTENSIONS_FILE)
    return {
        "extensions": data.get("extensions", []),
        "count": len(data.get("extensions", [])),
    }


def _mask_sensitive_config(config: dict) -> dict:
    """Return a copy of the MCP server config with env/header values masked."""
    import copy
    safe = copy.deepcopy(config)
    for section in ("environment", "headers"):
        if section in safe and isinstance(safe[section], dict):
            for k, v in safe[section].items():
                if isinstance(v, str) and not (v.startswith("${") or v.startswith("{env:")):
                    # Plaintext value — mask it (skip template references)
                    safe[section][k] = v[:4] + "****" if len(v) > 4 else "****"
    return safe


@router.get("/servers")
async def list_mcp_servers(user: dict = Depends(get_current_user)):
    """List all MCP servers from builtin and home config with credential status."""
    builtin = _get_servers(_read_json(BUILTIN_CONFIG_FILE))
    home = _get_servers(_read_json(HOME_CONFIG_FILE))

    merged = {}
    merged.update(builtin)
    merged.update(home)

    resolver = ConfigResolver() if ConfigResolver else None
    vault = get_vault() if get_vault else None

    servers = []
    for name, config in merged.items():
        is_builtin = name in builtin
        server_type = config.get("type", "remote" if "url" in config else "local")
        
        # Check credential status
        credential_status = "ok" # Default if no vault refs
        missing_keys = []
        if resolver:
            refs = resolver.extract_vault_refs(config)
            for s, k in refs:
                if vault and vault.get(s, k) is None:
                    missing_keys.append(f"{s}/{k}")
            
            if missing_keys:
                credential_status = "missing"

        servers.append({
            "name": name,
            "type": server_type,
            "status": "active", # Placeholder status
            "credential_status": credential_status,
            "missing_keys": missing_keys,
            "builtin": is_builtin,
            "config": _mask_sensitive_config(config)
        })

    return {"servers": servers}


@router.post("/servers")
async def add_mcp_server(server: McpServerConfig, user: dict = Depends(get_current_user)):
    """Add a new MCP server to home config."""
    server.normalize()  # Convert legacy stdio/http/env/args/httpUrl → OpenCode format

    data = _read_json(HOME_CONFIG_FILE)
    if "mcp" not in data:
        data["mcp"] = {}

    config = {"type": server.type}
    vault = get_vault() if get_vault else None

    def process_dict(d: Dict[str, str], prefix: str):
        processed = {}
        for k, v in d.items():
            if server.store_in_vault and vault:
                # Store in vault as {server_name}/{prefix}_{k}
                vault_key = f"{prefix}_{k}" if prefix else k
                vault.set(server.name, vault_key, v)
                processed[k] = f"${{vault:{server.name}/{vault_key}}}"
            else:
                processed[k] = v
        return processed

    if server.type == "remote":
        config["url"] = server.url
        if server.headers:
            config["headers"] = process_dict(server.headers, "HEADER")
    else:
        config["command"] = server.command
        if server.environment:
            config["environment"] = process_dict(server.environment, "")

    if server.enabled is not None:
        config["enabled"] = server.enabled
    if server.timeout is not None:
        config["timeout"] = server.timeout

    data["mcp"][server.name] = config
    
    # Ensure directory exists
    HOME_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    HOME_CONFIG_FILE.write_text(json.dumps(data, indent=2))

    return {"status": "success", "name": server.name}


@router.delete("/servers/{name}")
async def remove_mcp_server(name: str, user: dict = Depends(get_current_user)):
    """Remove an MCP server from home config."""
    data = _read_json(HOME_CONFIG_FILE)
    if "mcp" in data and name in data["mcp"]:
        del data["mcp"][name]
        HOME_CONFIG_FILE.write_text(json.dumps(data, indent=2))
        return {"status": "success"}

    raise HTTPException(status_code=404, detail=f"Server {name} not found in home config")


@router.post("/servers/{name}/test")
async def test_mcp_server(name: str, user: dict = Depends(get_current_user)):
    """Test connectivity to an MCP server by performing protocol handshake."""
    builtin = _get_servers(_read_json(BUILTIN_CONFIG_FILE))
    home = _get_servers(_read_json(HOME_CONFIG_FILE))
    config = home.get(name) or builtin.get(name)

    if not config:
        raise HTTPException(status_code=404, detail=f"Server {name} not found")

    resolver = ConfigResolver() if ConfigResolver else None
    if resolver:
        try:
            config = resolver.resolve_config(config)
        except Exception as e:
            return {"status": "error", "message": f"Config resolution failed: {e}"}

    async def _test_session(session: ClientSession) -> dict:
        """Initialize session, list tools, and return structured result."""
        init_result = await asyncio.wait_for(session.initialize(), timeout=10)
        server_info = getattr(init_result, "serverInfo", None) or {}
        server_name = getattr(server_info, "name", "unknown") if server_info else "unknown"
        server_version = getattr(server_info, "version", "unknown") if server_info else "unknown"

        # Fetch available tools
        tools_result = await asyncio.wait_for(session.list_tools(), timeout=10)
        tools_list = getattr(tools_result, "tools", []) if tools_result else []
        tool_summaries = [
            {"name": getattr(t, "name", str(t)), "description": getattr(t, "description", "")}
            for t in tools_list
        ]

        return {
            "status": "success",
            "message": f"Connected — {len(tool_summaries)} tools available",
            "server_name": server_name,
            "server_version": server_version,
            "tools_count": len(tool_summaries),
            "tools": tool_summaries,
        }

    try:
        if config.get("type") == "remote" or "url" in config:
            url = config["url"]
            headers = config.get("headers", {})
            async with sse_client(url, headers=headers) as (read, write):
                async with ClientSession(read, write) as session:
                    return await _test_session(session)
        else:
            import re
            import shutil

            def _resolve_env_placeholders(value: str) -> str:
                """Replace {env:VAR} with os.environ[VAR], leave unresolved as-is."""
                return re.sub(
                    r'\{env:(\w+)\}',
                    lambda m: os.environ.get(m.group(1), m.group(0)),
                    value,
                )

            command = config.get("command", [])
            # OpenCode format: command is an array
            if isinstance(command, list):
                command = [_resolve_env_placeholders(c) for c in command]
                executable = command[0] if command else ""
                cmd_args = command[1:] if len(command) > 1 else []
            else:
                # Legacy fallback: string command
                import shlex
                command = _resolve_env_placeholders(command)
                parts = shlex.split(command)
                executable = parts[0] if parts else command
                cmd_args = parts[1:] if len(parts) > 1 else []

            # Resolve executable via PATH
            full_command = shutil.which(executable) or executable

            # Resolve {env:VAR} in environment values too
            env_vars = {k: _resolve_env_placeholders(v) for k, v in config.get("environment", {}).items()}
            server_params = StdioServerParameters(
                command=full_command,
                args=cmd_args,
                env={**os.environ, **env_vars}
            )

            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    return await _test_session(session)
                    
    except asyncio.TimeoutError:
        return {"status": "error", "message": "Connection timed out after 10 seconds"}
    except Exception as e:
        return {"status": "error", "message": f"Connection failed: {str(e)}"}


@router.get("/servers/{name}/credentials")
async def list_server_credentials(name: str, user: dict = Depends(get_current_user)):
    """List credential key names for a server."""
    builtin = _get_servers(_read_json(BUILTIN_CONFIG_FILE))
    home = _get_servers(_read_json(HOME_CONFIG_FILE))
    config = home.get(name) or builtin.get(name)

    if not config:
        raise HTTPException(status_code=404, detail=f"Server {name} not found")

    resolver = ConfigResolver() if ConfigResolver else None
    if not resolver:
        return {"keys": []}

    refs = resolver.extract_vault_refs(config)
    # Filter refs that belong to this server (in vault terms)
    # The vault ref format is ${vault:vault_server_name/key}
    # Often vault_server_name matches name, but not always.
    
    keys = []
    for s, k in refs:
        keys.append({"vault_server": s, "key": k})

    return {"credentials": keys}


@router.put("/servers/{name}/credentials/{key:path}")
async def set_server_credential(
    name: str, 
    key: str, 
    update: CredentialUpdate, 
    user: dict = Depends(get_current_user)
):
    """Set a credential value in the vault."""
    vault = get_vault() if get_vault else None
    if not vault:
        raise HTTPException(status_code=500, detail="Vault not available")

    # If key contains /, split it into vault_server and actual key
    if "/" in key:
        vault_server, vault_key = key.split("/", 1)
    else:
        vault_server = name
        vault_key = key

    vault.set(vault_server, vault_key, update.value)
    return {"status": "success"}


@router.delete("/servers/{name}/credentials/{key:path}")
async def delete_server_credential(
    name: str, 
    key: str, 
    user: dict = Depends(get_current_user)
):
    """Delete a credential from the vault."""
    vault = get_vault() if get_vault else None
    if not vault:
        raise HTTPException(status_code=500, detail="Vault not available")

    # If key contains /, split it into vault_server and actual key
    if "/" in key:
        vault_server, vault_key = key.split("/", 1)
    else:
        vault_server = name
        vault_key = key

    vault.delete(vault_server, vault_key)
    return {"status": "success"}


def _compile_test_config() -> dict:
    """Compile a fully-resolved MCP config for opencode testing.

    Merges builtin -> deploy -> home configs, resolves all vault refs and
    {env:*} placeholders to literal values so opencode can connect to every
    server without relying on the parent process's environment.
    """
    import re
    import shutil

    builtin = _get_servers(_read_json(BUILTIN_CONFIG_FILE))
    deploy = _get_servers(
        _read_json(DEPLOY_CONFIG_FILE)
    ) if DEPLOY_CONFIG_FILE.exists() else {}
    home = _get_servers(_read_json(HOME_CONFIG_FILE))

    # Merge: builtin -> deploy -> home (each layer overrides the previous)
    merged: Dict[str, Any] = {}
    merged.update(builtin)
    merged.update(deploy)
    merged.update(home)

    if not merged:
        return {"$schema": "https://opencode.ai/config.json", "mcp": {}}

    install_dir = str(Path.home() / ".ostwin" / ".agents")
    env_lookup = {
        **os.environ,
        "AGENT_DIR": install_dir,
        "HOME": str(Path.home()),
        "PROJECT_DIR": str(Path.home() / ".ostwin"),
    }

    env_ref_pattern = re.compile(r'\{env:(\w+)\}')

    def resolve_env_refs(text: str) -> str:
        return env_ref_pattern.sub(
            lambda m: env_lookup.get(m.group(1), m.group(0)), text
        )

    python_abs = shutil.which('python') or shutil.which('python3') or 'python'
    resolver = ConfigResolver() if ConfigResolver else None

    resolved_mcp: Dict[str, Any] = {}
    for name, cfg in merged.items():
        # Resolve ${vault:server/key} refs to actual secret values
        if resolver:
            try:
                cfg = resolver.resolve_config(cfg)
            except Exception:
                pass  # Continue with unresolved config

        out: Dict[str, Any] = {}
        for key, val in cfg.items():
            if key == 'command' and isinstance(val, list):
                resolved_cmd = []
                for i, c in enumerate(val):
                    if isinstance(c, str):
                        c = resolve_env_refs(c)
                        if i == 0 and c in ('python', 'python3'):
                            c = python_abs
                    resolved_cmd.append(c)
                out[key] = resolved_cmd
            elif key in ('environment', 'headers') and isinstance(val, dict):
                cleaned = {}
                for k, v in val.items():
                    if isinstance(v, str):
                        v = resolve_env_refs(v)
                    cleaned[k] = v
                if cleaned:
                    out[key] = cleaned
            elif key == 'url' and isinstance(val, str):
                out[key] = resolve_env_refs(val)
            else:
                out[key] = val

        resolved_mcp[name] = out

    return {"$schema": "https://opencode.ai/config.json", "mcp": resolved_mcp}


def _parse_opencode_mcp_list(output: str) -> List[Dict[str, Any]]:
    """Parse ``opencode mcp list`` output into structured server results.

    Handles the box-drawing / emoji format produced by the OpenCode CLI::

        ┌  MCP Servers
        │
        ●  ✓ channel connected
        │      python /path/to/server.py
        │
        ●  ✗ github-mcp failed
        │      Error message here
        │      https://api.example.com/mcp
        │
        └  8 server(s)
    """
    import re

    # Strip ANSI escape codes
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    clean = ansi_escape.sub('', output)

    servers: List[Dict[str, Any]] = []
    current_server: Optional[Dict[str, Any]] = None

    for line in clean.split('\n'):
        # Match connected: ✓ <name> connected
        match_ok = re.search(r'✓\s+(\S+)\s+connected', line)
        if match_ok:
            if current_server:
                servers.append(current_server)
            current_server = {
                "name": match_ok.group(1),
                "status": "connected",
                "message": "Connected",
                "details": [],
            }
            continue

        # Match failed: ✗ <name> failed
        match_fail = re.search(r'✗\s+(\S+)\s+failed', line)
        if match_fail:
            if current_server:
                servers.append(current_server)
            current_server = {
                "name": match_fail.group(1),
                "status": "failed",
                "message": "",
                "details": [],
            }
            continue

        # Collect detail lines (indented text after │)
        if current_server:
            detail_match = re.search(r'│\s{2,}(.+)', line)
            if detail_match:
                detail = detail_match.group(1).strip()
                if detail:
                    current_server["details"].append(detail)

    if current_server:
        servers.append(current_server)

    # Post-process: set message from first detail for failed servers,
    # set command from first detail for connected servers.
    for server in servers:
        if server["status"] == "failed" and server["details"]:
            server["message"] = server["details"][0]
        elif server["status"] == "connected" and server["details"]:
            server["command"] = server["details"][0]

    return servers


@router.post("/servers/test-all")
async def test_all_mcp_servers(user: dict = Depends(get_current_user)):
    """Test all MCP servers by compiling config to a temp dir and running
    ``opencode mcp list``.  The temp dir is always cleaned up afterward."""
    import shutil as _shutil

    test_dir = Path.home() / ".ostwin" / ".agents" / "mcp" / "test"
    opencode_dir = test_dir / ".opencode"
    opencode_file = opencode_dir / "opencode.json"

    try:
        # 1. Compile fully-resolved config
        config = _compile_test_config()
        if not config.get("mcp"):
            return {"servers": [], "total": 0, "connected": 0, "failed": 0}

        # 2. Write to temp directory
        opencode_dir.mkdir(parents=True, exist_ok=True)
        opencode_file.write_text(json.dumps(config, indent=2))

        # 3. Run opencode mcp list in the temp directory
        process = await asyncio.create_subprocess_exec(
            "opencode", "mcp", "list",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(test_dir),
            env={**os.environ, "OPENCODE_DISABLE_CLAUDE_CODE": "1"},
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=120
        )
        raw_output = stdout.decode()

        # 4. Parse results
        servers = _parse_opencode_mcp_list(raw_output)
        connected = sum(1 for s in servers if s["status"] == "connected")
        failed = sum(1 for s in servers if s["status"] == "failed")

        return {
            "servers": servers,
            "total": len(servers),
            "connected": connected,
            "failed": failed,
            "raw_output": raw_output,
        }
    except asyncio.TimeoutError:
        return {
            "servers": [], "total": 0, "connected": 0, "failed": 0,
            "error": "Test timed out after 120 seconds",
        }
    except FileNotFoundError:
        return {
            "servers": [], "total": 0, "connected": 0, "failed": 0,
            "error": "opencode CLI not found — install from https://opencode.ai",
        }
    except Exception as e:
        return {
            "servers": [], "total": 0, "connected": 0, "failed": 0,
            "error": str(e),
        }
    finally:
        # 5. Always clean up the temp directory
        if test_dir.exists():
            _shutil.rmtree(test_dir, ignore_errors=True)


@router.get("/catalog")
async def get_catalog(user: dict = Depends(get_current_user)):
    """Get the predefined MCP extension catalog."""
    data = _read_json(CATALOG_FILE)
    installed = _read_json(EXTENSIONS_FILE)
    installed_names = {e["name"] for e in installed.get("extensions", [])}

    packages = []
    for name, spec in data.get("packages", {}).items():
        packages.append({
            "name": name,
            "description": spec.get("description", ""),
            "repo": spec.get("repo", ""),
            "build_type": spec.get("build_type", ""),
            "branch": spec.get("branch", "main"),
            "installed": name in installed_names,
        })

    return {
        "catalog_version": data.get("catalog_version", ""),
        "packages": packages,
        "count": len(packages),
    }


@router.post("/extensions/install")
async def install_extension(req: InstallRequest, user: dict = Depends(get_current_user)):
    """Install an MCP extension by name (from catalog) or git URL."""
    if not SCRIPT.exists():
        raise HTTPException(status_code=500, detail="mcp-extension.sh not found")

    args = ["install"]

    if req.repo:
        # Git URL mode
        args.append(req.repo)
        if req.name:
            args.extend(["--name", req.name])
    elif req.name:
        # Catalog name mode
        args.append(req.name)
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either 'name' (catalog) or 'repo' (git URL)",
        )

    if req.branch:
        args.extend(["--branch", req.branch])

    result = await _run_script(args, timeout=300)

    if result["returncode"] != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Installation failed",
                "stdout": result["stdout"],
                "stderr": result["stderr"],
            },
        )

    # Return updated extensions list
    data = _read_json(EXTENSIONS_FILE)
    return {
        "status": "installed",
        "output": result["stdout"],
        "extensions": data.get("extensions", []),
    }


@router.delete("/extensions/{name}")
async def remove_extension(name: str, user: dict = Depends(get_current_user)):
    """Remove an installed MCP extension."""
    if not SCRIPT.exists():
        raise HTTPException(status_code=500, detail="mcp-extension.sh not found")

    result = await _run_script(["remove", name])

    if result["returncode"] != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "message": f"Failed to remove '{name}'",
                "stdout": result["stdout"],
                "stderr": result["stderr"],
            },
        )

    return {"status": "removed", "name": name, "output": result["stdout"]}


@router.post("/extensions/sync")
async def sync_config(user: dict = Depends(get_current_user)):
    """Force rebuild mcp-config.json from builtin + installed extensions."""
    if not SCRIPT.exists():
        raise HTTPException(status_code=500, detail="mcp-extension.sh not found")

    result = await _run_script(["sync"])

    # Merge builtin + home config to return the current state
    builtin = _get_servers(_read_json(BUILTIN_CONFIG_FILE))
    home = _get_servers(_read_json(HOME_CONFIG_FILE))
    merged = {"mcp": {**builtin, **home}}
    return {
        "status": "synced",
        "output": result["stdout"],
        "config": merged,
    }


@router.get("/config")
async def get_mcp_config(user: dict = Depends(get_current_user)):
    """Get the current merged mcp-config.json (builtin + home)."""
    builtin = _get_servers(_read_json(BUILTIN_CONFIG_FILE))
    home = _get_servers(_read_json(HOME_CONFIG_FILE))
    return {"mcp": {**builtin, **home}}
