"""Base parser interface for bank statement/invoice parsers."""

from abc import ABC, abstractmethod
from pathlib import Path


class BaseParser(ABC):
    """Abstract base class for all bank parsers.

    Each parser converts a bank-specific file (CSV or PDF) into a list of
    normalized transaction dicts with the following keys:
        date, description, amount, balance, bank, source_type,
        currency, original_ref, installment_current, installment_total
    """

    bank_id: str = ""
    source_type: str = ""  # "extrato" or "fatura"

    @abstractmethod
    def parse(self, filepath: Path, password: str | None = None) -> list[dict]:
        """Parse a bank file and return normalized transactions.

        Args:
            filepath: Path to the source file (CSV or PDF).
            password: Optional password for encrypted PDFs.

        Returns:
            List of dicts, each representing one transaction.
        """
        ...

    def extract_total(self, filepath: Path, password: str | None = None) -> float | None:
        """Extract the fatura total ("Total a pagar") from a PDF invoice.

        Only applicable to fatura-type parsers. Returns None for extratos
        or if the total cannot be found.
        """
        return None

    def _make_row(
        self,
        date_str: str,
        description: str,
        amount: float,
        balance: float | str = "",
        currency: str = "BRL",
        original_ref: str = "",
        installment_current: int | None = None,
        installment_total: int | None = None,
        original_amount: float | str = "",
        exchange_rate: float | str = "",
    ) -> dict:
        """Create a normalized transaction dict."""
        return {
            "date": date_str,
            "description": description,
            "amount": amount,
            "balance": balance,
            "bank": self.bank_id,
            "source_type": self.source_type,
            "currency": currency,
            "original_ref": original_ref,
            "installment_current": installment_current if installment_current else "",
            "installment_total": installment_total if installment_total else "",
            "original_amount": original_amount,
            "exchange_rate": exchange_rate,
        }
