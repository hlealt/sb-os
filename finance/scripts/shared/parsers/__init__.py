"""Parser registry — auto-discovers all parser modules."""

import sys
from pathlib import Path
from importlib import import_module

# Ensure scripts/ directory is on Python path so parsers can `from utils import ...`
_scripts_dir = str(Path(__file__).parent.parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from .base import BaseParser

_PARSERS: dict[str, BaseParser] = {}


def _discover_parsers():
    """Import all parser modules in this package and register them."""
    package_dir = Path(__file__).parent
    for py_file in package_dir.glob("*.py"):
        if py_file.name.startswith("_") or py_file.name == "base.py":
            continue
        module_name = f".{py_file.stem}"
        module = import_module(module_name, package=__package__)
        # Look for a class that inherits from BaseParser
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, BaseParser)
                and attr is not BaseParser
                and hasattr(attr, "bank_id")
                and attr.bank_id
            ):
                _PARSERS[attr.bank_id] = attr()


def get_parser(bank_id: str) -> BaseParser:
    """Get a parser instance by bank ID."""
    if not _PARSERS:
        _discover_parsers()
    parser = _PARSERS.get(bank_id)
    if not parser:
        raise ValueError(
            f"No parser found for bank_id '{bank_id}'. "
            f"Available: {list(_PARSERS.keys())}"
        )
    return parser


def list_parsers() -> list[str]:
    """List all available parser bank IDs."""
    if not _PARSERS:
        _discover_parsers()
    return list(_PARSERS.keys())
