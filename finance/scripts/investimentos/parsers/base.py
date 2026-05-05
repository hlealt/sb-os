"""Base parser interface for investment data parsers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class UnknownMapping:
    """A value in the source file that has no name_map entry."""
    source: str       # Parser source_id (b3, safra, bipa, etc.)
    field: str        # Column name in the source (produto, instituicao, etc.)
    raw_value: str    # Exact value from the source file
    line_number: int = 0  # Line in the source file (for user reference)


@dataclass
class FlaggedOperation:
    """An operation that needs manual classification or research."""
    date: str
    operation: str    # Raw operation type from source
    product: str      # Product/asset name from source
    values: dict      # Relevant numeric values (qty, price, amount, etc.)
    reason: str       # Why it was flagged
    line_number: int = 0


@dataclass
class ParseResult:
    """Result of parsing an investment source file.

    Multi-output: a single source file can produce rows for multiple ledgers.
    For example, B3 produces orders, proventos, balcao, and corporate_actions.
    """
    outputs: dict[str, list[dict]] = field(default_factory=dict)
    unknowns: list[UnknownMapping] = field(default_factory=list)
    flags: list[FlaggedOperation] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return sum(len(rows) for rows in self.outputs.values())

    @property
    def has_unknowns(self) -> bool:
        return len(self.unknowns) > 0

    @property
    def has_flags(self) -> bool:
        return len(self.flags) > 0


class InvestmentBaseParser(ABC):
    """Abstract base class for all investment parsers.

    Each parser converts a source file (CSV, XLSX, or PDF) into normalized
    rows for one or more ledger CSVs, returning a ParseResult.
    """

    source_id: str = ""  # e.g. "b3", "bipa", "safra", "avenue"

    @abstractmethod
    def parse(self, filepath: Path, name_map=None) -> ParseResult:
        """Parse a source file and return normalized ledger rows.

        Args:
            filepath: Path to the source file.
            name_map: NameMapResolver instance for name normalization.

        Returns:
            ParseResult with outputs, unknowns, and flags.
        """
        ...
