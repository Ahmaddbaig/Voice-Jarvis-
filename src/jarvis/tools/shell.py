"""run_shell -- Tier 1 reversible tool. Uses PopenRegistry for abort support."""
import subprocess
import time

from jarvis.tools._registry import tool

# The PopenRegistry instance is set by assistant.py at startup
_popen_registry = None


def set_popen_registry(registry) -> None:
    """Called once at startup to inject the shared PopenRegistry."""
    global _popen_registry
    _popen_registry = registry


@tool(tier=1, description="Execute a shell command and return its output (4KB cap, 30s timeout).")
def run_shell(command: str) -> str:
    """Execute a shell command and return its output (4KB cap, 30s timeout).

    Args:
        command: The shell command to execute.
    """
    import uuid
    call_id = str(uuid.uuid4())

    proc = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    if _popen_registry is not None:
        _popen_registry.register(call_id, proc)
    try:
        stdout, stderr = proc.communicate(timeout=30)
        output = stdout or stderr or "(no output)"
        if len(output) > 4096:
            output = output[:4096] + f"\n...[truncated, was {len(stdout or '')+len(stderr or '')} bytes]"
        return output
    except subprocess.TimeoutExpired:
        proc.terminate()
        return "(command timed out after 30 seconds)"
    finally:
        if _popen_registry is not None:
            _popen_registry.unregister(call_id)
