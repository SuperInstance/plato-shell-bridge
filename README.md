# plato-shell-bridge

The weapon rack — dynamic tool discovery, loading, and lifecycle management for PLATO shells. All Cocapn fleet tools reference this:

```python
from plato_shell_bridge import PlatoShell
shell = PlatoShell("agent-shell")
shell.load_tool("coordination-topology")
```

## Dependencies

none (standalone Python 3.10+)

## Installation

```bash
pip install plato-shell-bridge
```

Or from source:
```bash
git clone https://github.com/SuperInstance/plato-shell-bridge
cd plato-shell-bridge
pip install -e .
```

## API

```python
from plato_shell_bridge import PlatoShell, ToolHandle, discover_shells

# Load a tool into a shell
shell = PlatoShell("agent-shell")
handle = shell.load_tool("coordination-topology")
print(handle.commands)  # available methods

# Discover all PLATO shells on the network
shells = discover_shells(timeout=2)  # list of ShellInfo

# List loaded tools
loaded = shell.list_tools()

# Unload
shell.unload_tool("coordination-topology")
```

## License

MIT — Part of the Cocapn Fleet Intelligence System
