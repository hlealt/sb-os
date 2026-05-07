"""Name map loader and resolver for investment parsers."""

import csv
from pathlib import Path


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "CLAUDE.md").exists() and (parent / ".user").is_dir():
            return parent
    raise RuntimeError(f"Vault root not found from {__file__}")


VAULT_ROOT = _find_vault_root()

# Default location of name_map.csv
DEFAULT_NAME_MAP_PATH = (
    VAULT_ROOT / ".user" / "finance" / "bookkeeper" / "ledgers" / "investimentos" / "name_map.csv"
)


class NameMapResolver:
    """Resolves raw values from source files to canonical values.

    Loads name_map.csv and provides lookup by (source, field, raw_value).
    """

    def __init__(self, filepath: Path = DEFAULT_NAME_MAP_PATH):
        self._filepath = filepath
        self._map: dict[tuple[str, str, str], dict] = {}
        self._load()

    def _load(self):
        """Load name_map.csv into memory."""
        if not self._filepath.exists():
            return
        with open(self._filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (
                    row['source'].strip(),
                    row['field'].strip(),
                    row['raw_value'].strip(),
                )
                self._map[key] = {
                    'canonical_value': row['canonical_value'].strip(),
                    'asset_type': row.get('asset_type', '').strip(),
                }

    def resolve(self, source: str, field: str, raw_value: str) -> dict | None:
        """Look up a raw value and return its canonical mapping.

        Args:
            source: Parser source_id (b3, safra, bipa, etc.)
            field: Column name in the source (produto, instituicao, etc.)
            raw_value: Exact value from the source file.

        Returns:
            Dict with 'canonical_value' and 'asset_type' if found, None otherwise.
        """
        return self._map.get((source, field, raw_value))

    def resolve_value(self, source: str, field: str, raw_value: str) -> str | None:
        """Convenience: return just the canonical_value, or None."""
        result = self.resolve(source, field, raw_value)
        return result['canonical_value'] if result else None

    def resolve_with_type(self, source: str, field: str, raw_value: str) -> tuple[str | None, str]:
        """Return (canonical_value, asset_type) tuple. Both empty string if not found."""
        result = self.resolve(source, field, raw_value)
        if result:
            return result['canonical_value'], result['asset_type']
        return None, ''

    @property
    def entry_count(self) -> int:
        return len(self._map)

    def add_entry(self, source: str, field: str, raw_value: str,
                  canonical_value: str, asset_type: str = ''):
        """Add a new mapping and persist to CSV."""
        # Lazy import to avoid loading audit at parser import time.
        import sys as _sys
        from pathlib import Path as _Path
        _shared_lib = _Path(__file__).resolve().parents[3] / "shared"
        if str(_shared_lib) not in _sys.path:
            _sys.path.insert(0, str(_shared_lib))
        from lib import audit  # noqa: E402

        key = (source, field, raw_value)
        self._map[key] = {
            'canonical_value': canonical_value,
            'asset_type': asset_type,
        }
        # Append to CSV
        with audit.track_write(
            self._filepath,
            materiality="medium",
            action="append",
            event_type="config_write",
            source_function="name_map.add_entry",
            trigger_context={"source": source, "field": field},
        ):
            with open(self._filepath, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([source, field, raw_value, canonical_value, asset_type])
