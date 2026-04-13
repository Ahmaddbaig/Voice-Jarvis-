"""Tool registry — @tool decorator + pkgutil auto-discovery.

BRAIN-04: Adding a tool = dropping a file in jarvis/tools/.
"""
import importlib
import logging
import pkgutil
from pathlib import Path

from jarvis.tools._registry import (  # noqa: F401
    _REGISTRY,
    ToolDef,
    tool,
    discover_tools,
    all_schemas,
    call_tool,
    get_tier,
    set_turn_has_external_content,
    mark_external_content,
)

_logger = logging.getLogger(__name__)
_pkg_path = str(Path(__file__).parent)

# Auto-import all tool modules (skipping private _registry.py)
for _finder, _module_name, _is_pkg in pkgutil.iter_modules([_pkg_path]):
    if _module_name.startswith("_"):
        continue
    try:
        importlib.import_module(f"{__name__}.{_module_name}")
    except Exception as _exc:
        _logger.warning(f"Failed to load tool module '{_module_name}': {_exc}")
