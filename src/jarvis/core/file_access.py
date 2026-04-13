"""Path allow/denylist enforcement for file tools.

SAFE-03/SAFE-04 prerequisite: every file tool calls ``check_file_access``
before any I/O.  The config file is re-read on every call (D-03) so users
can add project directories without restarting Jarvis.

Config location: ``%LOCALAPPDATA%\\Jarvis\\file_access.json``
"""
from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path


_CONFIG_PATH = Path(os.environ.get("LOCALAPPDATA", "")) / "Jarvis" / "file_access.json"

_DEFAULT_CONFIG: dict = {
    "allow": ["~/Desktop", "~/Downloads", "~/Documents", "~"],
    "deny": [
        "C:\\Windows",
        "C:\\Program Files",
        "C:\\Program Files (x86)",
        ".venv",
        ".git",
        "*.env",
        "*.pem",
        "*.key",
        "__pycache__",
    ],
}


def load_file_access_config() -> dict:
    """Read the JSON config.  Creates it with defaults on first run."""
    if not _CONFIG_PATH.exists():
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_PATH.write_text(json.dumps(_DEFAULT_CONFIG, indent=2), encoding="utf-8")
        return dict(_DEFAULT_CONFIG)
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


def _expand_path(p: str) -> Path:
    """Expand ``~`` to ``%USERPROFILE%`` and resolve to absolute."""
    return Path(p).expanduser().resolve()


def check_file_access(path: str | Path) -> None:
    """Validate *path* against the allow/denylist.

    Raises :class:`PermissionError` if the path is denied or not under any
    allowed directory.
    """
    resolved = Path(path).resolve()
    resolved_str = str(resolved)
    cfg = load_file_access_config()

    # --- Deny rules (checked first — deny takes priority per D-01) ---
    for entry in cfg.get("deny", []):
        if "*" in entry:
            # Glob pattern: match against the file name and every parent name
            for part in (resolved.name, *[p.name for p in resolved.parents]):
                if fnmatch.fnmatch(part, entry):
                    raise PermissionError(
                        f"Access denied: {path} — blocked by file access policy"
                    )
        else:
            # Substring match (case-insensitive on Windows)
            if entry.lower() in resolved_str.lower():
                raise PermissionError(
                    f"Access denied: {path} — blocked by file access policy"
                )

    # --- Allow rules ---
    allow_paths = [_expand_path(a) for a in cfg.get("allow", [])]
    for allowed in allow_paths:
        try:
            resolved.relative_to(allowed)
            return  # path is under an allowed directory
        except ValueError:
            continue

    raise PermissionError(
        f"Access denied: {path} — blocked by file access policy"
    )
