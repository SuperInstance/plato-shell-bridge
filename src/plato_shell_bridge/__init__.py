"""
plato-shell-bridge
~~~~~~~~~~~~~~~~~
Dynamic tool loader for PLATO shells.

Example::
    >>> from plato_shell_bridge import PlatoShell
    >>> shell = PlatoShell("agent-shell")
    >>> handle = shell.load_tool("my-tool")
    >>> shell.list_tools()
    ['my-tool']
"""

__version__ = "0.1.0"

import json
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Literal


class PlatoShellBridgeError(Exception):
    """Base exception for all plato-shell-bridge errors."""
    pass


class ShellNotFoundError(PlatoShellBridgeError):
    """Raised when a shell cannot be found or reached."""
    pass


class ToolNotFoundError(PlatoShellBridgeError):
    """Raised when a tool is not found in the registry."""
    pass


class ToolLoadError(PlatoShellBridgeError):
    """Raised when a tool fails to load."""
    pass


class ShellBusyError(PlatoShellBridgeError):
    """Raised when a shell is busy and cannot accept new tools."""
    pass


class DiscoveryError(PlatoShellBridgeError):
    """Raised when shell discovery fails."""
    pass


@dataclass
class ToolHandle:
    """Opaque handle to a loaded tool."""
    name: str
    version: str
    module_path: str
    commands: list[str]
    shell_id: str

    def is_alive(self) -> bool:
        """Check if tool is still responsive."""
        return True


@dataclass
class ShellInfo:
    """Metadata about a PLATO shell."""
    name: str
    host: str
    port: int
    status: Literal["online", "offline", "busy"]
    loaded_tools: list[str]
    capabilities: list[str]
    version: str


class PlatoShell:
    """Interface to a PLATO shell instance."""

    def __init__(self, shell_name: str, host: str = "localhost", port: int = 8847):
        """
        Args:
            shell_name: Name of the shell to connect to (e.g., "agent-shell", "oracle1-shell")
            host: PLATO FM host (default localhost)
            port: PLATO FM port (default 8847)
        """
        self.shell_name = shell_name
        self.host = host
        self.port = port
        self._fm_url = f"http://{host}:{port}"
        self._loaded_tools: list[str] = []

    def load_tool(self, tool_name: str, config: dict | None = None) -> ToolHandle:
        """
        Dynamically load a tool into this shell.

        Args:
            tool_name: Name of the tool to load
            config: Optional configuration dict for the tool

        Returns:
            ToolHandle: Opaque handle for the loaded tool

        Raises:
            ShellNotFoundError: Shell does not exist
            ToolNotFoundError: Tool not registered in FM
            ToolLoadError: Tool failed to load
        """
        if not self.ping():
            raise ShellNotFoundError(f"Shell '{self.shell_name}' not found or unreachable")

        try:
            url = f"{self._fm_url}/tools/load"
            data = json.dumps({
                "tool_name": tool_name,
                "shell_name": self.shell_name,
                "config": config or {}
            }).encode("utf-8")

            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/json")

            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8"))

            if not result.get("success", False):
                raise ToolLoadError(f"Failed to load tool '{tool_name}': {result.get('error', 'Unknown error')}")

            handle = ToolHandle(
                name=tool_name,
                version=result.get("version", "0.1.0"),
                module_path=result.get("module_path", f"tools.{tool_name}"),
                commands=result.get("commands", []),
                shell_id=self.shell_name
            )

            if tool_name not in self._loaded_tools:
                self._loaded_tools.append(tool_name)

            return handle

        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ToolNotFoundError(f"Tool '{tool_name}' not found in FM registry")
            raise ToolLoadError(f"HTTP error loading tool '{tool_name}': {e.code} {e.reason}")
        except urllib.error.URLError as e:
            raise ShellNotFoundError(f"Cannot reach FM at {self._fm_url}: {e.reason}")
        except json.JSONDecodeError as e:
            raise ToolLoadError(f"Invalid response from FM: {e}")

    def unload_tool(self, tool_name: str) -> None:
        """Unload a tool from this shell."""
        if tool_name not in self._loaded_tools:
            return

        try:
            url = f"{self._fm_url}/tools/unload"
            data = json.dumps({
                "tool_name": tool_name,
                "shell_name": self.shell_name
            }).encode("utf-8")

            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/json")

            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8"))

            if result.get("success", False) and tool_name in self._loaded_tools:
                self._loaded_tools.remove(tool_name)

        except (urllib.error.URLError, json.JSONDecodeError):
            pass

    def list_tools(self) -> list[str]:
        """List currently loaded tools in this shell."""
        return self._loaded_tools.copy()

    def get_shell_info(self) -> ShellInfo:
        """Get metadata about this shell."""
        try:
            url = f"{self._fm_url}/shells/{self.shell_name}"
            with urllib.request.urlopen(url, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))

            return ShellInfo(
                name=data.get("name", self.shell_name),
                host=self.host,
                port=self.port,
                status=data.get("status", "online"),
                loaded_tools=data.get("loaded_tools", []),
                capabilities=data.get("capabilities", []),
                version=data.get("version", "0.1.0")
            )

        except urllib.error.URLError as e:
            raise ShellNotFoundError(f"Cannot reach shell '{self.shell_name}': {e.reason}")
        except json.JSONDecodeError as e:
            raise PlatoShellBridgeError(f"Invalid response from FM: {e}")

    def ping(self) -> bool:
        """Check shell connectivity."""
        try:
            url = f"{self._fm_url}/shells/{self.shell_name}/status"
            with urllib.request.urlopen(url, timeout=5) as response:
                return response.status == 200
        except (urllib.error.URLError, urllib.error.HTTPError):
            return False


# Local registry for tool → shell assignments
_tool_registry: dict[str, str] = {}
_tool_metadata: dict[str, dict[str, Any]] = {}


def discover_shells(host: str = "localhost", port: int = 8847) -> list[ShellInfo]:
    """
    Discover all available PLATO shells via FM.

    Returns:
        List of ShellInfo objects for shells that respond to ping.

    Raises:
        DiscoveryError: If discovery fails to contact FM
    """
    try:
        url = f"http://{host}:{port}/room/fleet-registry/history"
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))

        shells: list[ShellInfo] = []
        for entry in data.get("shells", []):
            try:
                shell_info = ShellInfo(
                    name=entry["name"],
                    host=entry.get("host", host),
                    port=entry.get("port", 8847),
                    status=entry.get("status", "offline"),
                    loaded_tools=entry.get("loaded_tools", []),
                    capabilities=entry.get("capabilities", []),
                    version=entry.get("version", "0.1.0")
                )
                shells.append(shell_info)
            except KeyError:
                continue

        return shells

    except urllib.error.URLError as e:
        raise DiscoveryError(f"Cannot reach FM at {host}:{port}: {e.reason}")
    except json.JSONDecodeError as e:
        raise DiscoveryError(f"Invalid response from FM: {e}")


def get_default_shell() -> str:
    """
    Get the default shell name from environment or FM config.

    Returns:
        Shell name string (e.g., "agent-shell")
    """
    import os
    return os.environ.get("PLATO_DEFAULT_SHELL", "agent-shell")


def register_tool(name: str, shell_id: str) -> None:
    """
    Register a tool→shell assignment in the local registry.

    This is a local cache; the FM is the source of truth.

    Args:
        name: Tool name to register
        shell_id: Shell ID to assign tool to
    """
    _tool_registry[name] = shell_id
    if name not in _tool_metadata:
        _tool_metadata[name] = {}


def get_tool_shell(tool_name: str) -> str | None:
    """
    Look up which shell a tool is registered to.

    Args:
        tool_name: Name of the tool to look up

    Returns:
        Shell name or None if not registered.
    """
    return _tool_registry.get(tool_name)


def list_registered_tools() -> dict[str, str]:
    """
    Get all tool→shell registrations.

    Returns:
        Dict mapping tool_name → shell_name
    """
    return _tool_registry.copy()


__all__ = [
    "PlatoShell",
    "ShellInfo",
    "ToolHandle",
    "discover_shells",
    "get_default_shell",
    "register_tool",
    "get_tool_shell",
    "list_registered_tools",
    "PlatoShellBridgeError",
    "ShellNotFoundError",
    "ToolNotFoundError",
    "ToolLoadError",
    "ShellBusyError",
    "DiscoveryError",
]