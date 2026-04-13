"""Tool registry internals — @tool decorator, schema generation, dispatch.

BRAIN-04: @tool decorator with pkgutil auto-discovery.
BRAIN-05: JSON schemas from type hints + docstrings.
SAFE-01: Three-tier classification (0=read, 1=reversible, 2=destructive).
"""
from __future__ import annotations

import inspect
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Union, get_args, get_origin, get_type_hints, Literal

_logger = logging.getLogger(__name__)
_REGISTRY: dict[str, ToolDef] = {}

# ---------------------------------------------------------------------------
# SAFE-04: Per-turn quarantine flag (set by read tools, checked by call_tool)
# ---------------------------------------------------------------------------

_turn_has_external_content: bool = False


def set_turn_has_external_content(value: bool) -> None:
    """Reset (or set) the quarantine flag — called at the top of _turn_pipeline."""
    global _turn_has_external_content
    _turn_has_external_content = value


def mark_external_content() -> None:
    """Called by read tools (read_file, read_pdf, fetch_page, etc.) to flag this turn."""
    global _turn_has_external_content
    _turn_has_external_content = True


# ---------------------------------------------------------------------------
# SAFE-03: Tier 2 dry-run preview logger (actions.log, lazy-initialized)
# ---------------------------------------------------------------------------

_actions_logger: logging.Logger | None = None


def _get_actions_logger() -> logging.Logger:
    """Return (or create) the rotating actions logger at %LOCALAPPDATA%\\Jarvis\\actions.log."""
    global _actions_logger
    if _actions_logger is None:
        log_path = Path(os.environ.get("LOCALAPPDATA", "")) / "Jarvis" / "actions.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        _actions_logger = logging.getLogger("jarvis.actions")
        _actions_logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(
            str(log_path), maxBytes=1_000_000, backupCount=5, encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        if not any(isinstance(h, RotatingFileHandler) for h in _actions_logger.handlers):
            _actions_logger.addHandler(handler)
        _actions_logger.propagate = False
    return _actions_logger


@dataclass
class ToolDef:
    fn: Callable
    name: str
    description: str
    schema: dict
    tier: int  # 0=read, 1=reversible, 2=destructive


def tool(tier: int = 0, description: str | None = None):
    """Decorator to register a function as a tool.

    Usage:
        @tool(tier=0)
        def get_time() -> str:
            '''Return the current date and time.'''
            ...
    """
    def decorator(fn: Callable) -> Callable:
        name = fn.__name__
        desc = description or _extract_description(fn)
        schema = _schema_from_hints(fn)
        _REGISTRY[name] = ToolDef(fn=fn, name=name, description=desc, schema=schema, tier=tier)
        return fn
    return decorator


def discover_tools() -> dict[str, ToolDef]:
    """Return the registry (populated by pkgutil import in __init__.py)."""
    return dict(_REGISTRY)


def all_schemas() -> list[dict]:
    """Return JSON-compatible tool schemas for LLM providers.

    Format matches both OpenAI and Ollama tool parameter:
    [{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}]
    """
    schemas = []
    for name, td in _REGISTRY.items():
        schemas.append({
            "type": "function",
            "function": {
                "name": td.name,
                "description": td.description,
                "parameters": td.schema,
            },
        })
    return schemas


def call_tool(name: str, arguments: dict) -> str:
    """Execute a registered tool by name. Returns string result.

    Catches all exceptions and returns error strings — the turn pipeline
    never crashes from a tool failure.
    """
    td = _REGISTRY.get(name)
    if td is None:
        return f"[error] Unknown tool: {name}. Available: {', '.join(_REGISTRY.keys())}"

    # SAFE-04: Quarantine — block Tier 2 when external content was ingested this turn
    if td.tier == 2 and _turn_has_external_content:
        return "[blocked] Tier 2 tools are blocked after reading external content in this turn. Start a new turn to perform destructive actions."

    # SAFE-03: Dry-run preview for Tier 2 tools
    if td.tier == 2:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        args_summary = " ".join(f"{k}={v}" for k, v in arguments.items())
        _get_actions_logger().info(f"[{ts}] DRY-RUN {name} {args_summary}")

    try:
        result = td.fn(**arguments)
        # Ensure result is a string and capped at 4KB
        result_str = str(result) if result is not None else "(no output)"
        # Image data URLs (screenshots) must not be truncated — they're 50-200KB of base64
        if not result_str.startswith("data:image/") and len(result_str) > 4096:
            result_str = result_str[:4096] + f"\n...[truncated, was {len(str(result))} chars]"
        return result_str
    except Exception as exc:
        _logger.warning(f"Tool '{name}' raised: {exc}")
        return f"[error] Tool '{name}' failed: {exc}"


def get_tier(name: str) -> int:
    """Get the tier of a registered tool. Returns -1 if unknown."""
    td = _REGISTRY.get(name)
    return td.tier if td else -1


# ---------------------------------------------------------------------------
# Schema generation from type hints (BRAIN-05)
# ---------------------------------------------------------------------------

def _extract_description(fn: Callable) -> str:
    """First line of docstring."""
    doc = fn.__doc__ or ""
    return doc.strip().split("\n")[0]


def _extract_param_desc(fn: Callable, param_name: str) -> str | None:
    """Extract per-param description from docstring Args: section."""
    doc = fn.__doc__ or ""
    in_args = False
    for line in doc.split("\n"):
        stripped = line.strip()
        if stripped.lower().startswith("args:"):
            in_args = True
            continue
        if in_args:
            if stripped == "" or (not stripped.startswith(" ") and ":" not in stripped and stripped.endswith(":")):
                in_args = False
                continue
            if stripped.startswith(f"{param_name}:") or stripped.startswith(f"{param_name} "):
                # Extract description after the colon
                parts = stripped.split(":", 1)
                if len(parts) > 1:
                    return parts[1].strip()
    return None


def _schema_from_hints(fn: Callable) -> dict:
    """Convert type hints to JSON Schema 'parameters' object."""
    hints = get_type_hints(fn)
    hints.pop("return", None)
    sig = inspect.signature(fn)

    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue
        hint = hints.get(param_name, str)
        prop = _type_to_schema(hint)

        prop_desc = _extract_param_desc(fn, param_name)
        if prop_desc:
            prop["description"] = prop_desc

        properties[param_name] = prop

        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    return {"type": "object", "properties": properties, "required": required}


def _type_to_schema(hint) -> dict:
    """Map Python type hint to JSON Schema type."""
    origin = get_origin(hint)
    args = get_args(hint)

    # Handle Optional[X] (Union[X, None])
    if origin is Union:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _type_to_schema(non_none[0])

    # Handle Literal["a", "b", "c"]
    if origin is Literal:
        return {"type": "string", "enum": list(args)}

    # Handle list[X]
    if origin is list:
        item_schema = _type_to_schema(args[0]) if args else {"type": "string"}
        return {"type": "array", "items": item_schema}

    # Primitives
    TYPE_MAP = {str: "string", int: "integer", float: "number", bool: "boolean"}
    return {"type": TYPE_MAP.get(hint, "string")}
