"""Avenue FX PDF parser.

Handles two PDF layouts:
- Format A — "Recibo de Câmbio" (Avenue's newer receipt, ~2024+)
- Format B — "Contrato de Câmbio" (BEXS Banco de Câmbio, historical ~2018–2023)

fx_rate = VET (Valor Efetivo Total) — the effective rate including spread + IOF,
which is the actual BRL-per-foreign-unit cost of the operation. brl_amount is
computed as foreign_amount × VET (NOT the printed "Valor em Moeda Nacional",
which excludes IOF). Schema is currently USD-only; non-USD currencies are
flagged and skipped pending a multi-currency schema migration.
"""

import re
from pathlib import Path

import pdfplumber

from .base import FlaggedOperation, InvestmentBaseParser, ParseResult


# Format B — "Contrato de Câmbio" (BEXS, historical)
# Header: "Tipo do Contrato | Evento | Número do Contrato de Câmbio | Data"
# Row:    "Venda            | Contratação | 251660280              | 28/10/2020"
_B_TIPO_DATE = re.compile(
    r'Tipo do Contrato\s+Evento\s+N[úu]mero do Contrato de C[âa]mbio\s+Data\s*\n'
    r'\s*(Venda|Compra)\s+\w+\s+\d+\s+(\d{2}/\d{2}/\d{4})',
    re.IGNORECASE,
)
# "Cód. da Moeda Estrangeira Valor em Moeda Estrangeira\nUSD 851,83 (..."
_B_FOREIGN = re.compile(
    r'Valor em Moeda Estrangeira\s*\n\s*([A-Z]{3})\s+([\d.,]+)',
)
# "Valor Efetivo Total (VET)* Descrição da Forma de Entrega ...\n5,869700000000000 65 - ..."
_B_VET = re.compile(
    r'Valor Efetivo Total\s*\(VET\)\*?\s+Descri[çc][ãa]o.*?\n\s*([\d.,]+)\b',
    re.DOTALL,
)

# Format A — "Recibo de Câmbio" (newer Avenue layout)
# Header: "Tipo de Contrato Evento Data\nVenda Contratação 13/03/2024"
_A_TIPO = re.compile(r'Tipo de Contrato\s+Evento\s+Data\s*\n\s*(Venda|Compra)', re.IGNORECASE)
_A_DATE = re.compile(r'(?:Venda|Compra)\s+\w+\s+(\d{2}/\d{2}/\d{4})')
# Amount: "US$ 5.807,02" or "U$ 2.954,43" (the "S" is sometimes lost in PDF extraction)
_A_USD = re.compile(r'U[S]?\$\s*([\d.,]+)')
# VET line: "Valor Efetivo Total (VET)* Descrição da Forma de Entrega ...\n5,0771 65-..."
_A_VET = re.compile(
    r'Valor Efetivo Total\s*\(VET\)\*?\s+Descri[çc][ãa]o.*?\n\s*([\d.,]+)\b',
    re.DOTALL,
)


class AvenueFXParser(InvestmentBaseParser):
    source_id = "avenue_fx"

    def parse(self, filepath: Path, name_map=None) -> ParseResult:
        result = ParseResult()
        result.outputs = {'avenue_fx': []}

        if filepath.is_dir():
            pdf_files = sorted(filepath.glob("*.pdf"))
        else:
            pdf_files = [filepath]

        for pdf_file in pdf_files:
            self._parse_pdf(pdf_file, result)

        return result

    def _parse_pdf(self, filepath: Path, result: ParseResult) -> None:
        try:
            with pdfplumber.open(filepath) as pdf:
                full_text = '\n'.join(page.extract_text() or '' for page in pdf.pages)
        except Exception as e:
            result.flags.append(FlaggedOperation(
                date='', operation='PDF_ERROR', product=filepath.name,
                values={'error': str(e)},
                reason=f'Failed to open PDF: {e}',
            ))
            return

        # Format B (historical BEXS) first — most likely for the historical archive
        m_b = _B_TIPO_DATE.search(full_text)
        if m_b:
            extracted = self._extract_format_b(full_text, m_b, filepath, result)
        else:
            extracted = self._extract_format_a(full_text, filepath, result)

        if not extracted:
            return

        tipo, date, currency, foreign_amount, vet = extracted

        if currency != 'USD':
            result.flags.append(FlaggedOperation(
                date=date, operation='NON_USD_CURRENCY',
                product=filepath.name,
                values={'currency': currency, 'amount': foreign_amount, 'vet': vet},
                reason=f'Non-USD currency {currency}: schema currently USD-only',
            ))
            return

        brl_amount = round(foreign_amount * vet, 2)

        # Venda (BEXS sells USD to client) → client BRL→USD → transfer_in to Avenue
        # Compra (BEXS buys USD from client) → client USD→BRL → transfer_out from Avenue
        operation = 'transfer_in' if tipo.lower() == 'venda' else 'transfer_out'

        result.outputs['avenue_fx'].append({
            'date': date,
            'operation': operation,
            'brl_amount': str(brl_amount),
            'usd_amount': str(round(foreign_amount, 2)),
            'fx_rate': str(round(vet, 6)),
            'source': 'avenue_fx',
        })

    def _extract_format_b(self, text: str, m_tipo_date, filepath: Path,
                          result: ParseResult):
        tipo = m_tipo_date.group(1)
        date = self._parse_date(m_tipo_date.group(2))

        m_foreign = _B_FOREIGN.search(text)
        m_vet = _B_VET.search(text)

        if not (m_foreign and m_vet):
            result.flags.append(FlaggedOperation(
                date=date, operation='INCOMPLETE_FX_B',
                product=filepath.name,
                values={'foreign_matched': bool(m_foreign), 'vet_matched': bool(m_vet)},
                reason='Format B (Contrato de Câmbio) detected but field extraction incomplete',
            ))
            return None

        currency = m_foreign.group(1)
        foreign_amount = self._parse_ptbr(m_foreign.group(2))
        vet = self._parse_ptbr(m_vet.group(1))
        return tipo, date, currency, foreign_amount, vet

    def _extract_format_a(self, text: str, filepath: Path, result: ParseResult):
        m_tipo = _A_TIPO.search(text)
        m_date = _A_DATE.search(text)
        m_usd = _A_USD.search(text)
        m_vet = _A_VET.search(text)

        if not all([m_tipo, m_date, m_usd, m_vet]):
            result.flags.append(FlaggedOperation(
                date='', operation='UNKNOWN_FORMAT',
                product=filepath.name,
                values={
                    'tipo': bool(m_tipo), 'date': bool(m_date),
                    'usd': bool(m_usd), 'vet': bool(m_vet),
                },
                reason='Could not match Contrato de Câmbio or Recibo de Câmbio format',
            ))
            return None

        return (
            m_tipo.group(1),
            self._parse_date(m_date.group(1)),
            'USD',
            self._parse_ptbr(m_usd.group(1)),
            self._parse_ptbr(m_vet.group(1)),
        )

    def _parse_date(self, date_str: str) -> str:
        """DD/MM/YYYY → YYYY-MM-DD."""
        parts = date_str.split('/')
        if len(parts) == 3:
            return f'{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}'
        return date_str

    def _parse_ptbr(self, val: str) -> float:
        """Parse PT-BR decimal: '5.807,02' → 5807.02; '5,847500000000000' → 5.8475."""
        if not val:
            return 0.0
        s = val.strip().replace('.', '').replace(',', '.')
        try:
            return float(s)
        except (ValueError, TypeError):
            return 0.0
