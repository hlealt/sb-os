"""Parser registry — auto-discovers all investment parser modules."""

import sys
from pathlib import Path
from importlib import import_module

# Ensure scripts/ directory is on Python path so parsers can import utils
_scripts_dir = str(Path(__file__).parent.parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from .base import InvestmentBaseParser, ParseResult, UnknownMapping, FlaggedOperation
from .name_map import NameMapResolver

_PARSERS: dict[str, InvestmentBaseParser] = {}


def _discover_parsers():
    """Import all parser modules in this package and register them."""
    package_dir = Path(__file__).parent
    for py_file in package_dir.glob("*.py"):
        if py_file.name.startswith("_") or py_file.name in ("base.py", "name_map.py"):
            continue
        module_name = f".{py_file.stem}"
        module = import_module(module_name, package=__package__)
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, InvestmentBaseParser)
                and attr is not InvestmentBaseParser
                and hasattr(attr, "source_id")
                and attr.source_id
            ):
                _PARSERS[attr.source_id] = attr()


def get_parser(source_id: str) -> InvestmentBaseParser:
    """Get a parser instance by source ID."""
    if not _PARSERS:
        _discover_parsers()
    parser = _PARSERS.get(source_id)
    if not parser:
        raise ValueError(
            f"No parser found for source_id '{source_id}'. "
            f"Available: {list(_PARSERS.keys())}"
        )
    return parser


def list_parsers() -> list[str]:
    """List all available parser source IDs."""
    if not _PARSERS:
        _discover_parsers()
    return list(_PARSERS.keys())
