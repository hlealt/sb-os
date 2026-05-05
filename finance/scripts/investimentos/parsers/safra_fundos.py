"""Safra internet banking fund CSV parser.

Parses the block-based Safra fund CSV into balcao.csv format.
Each fund is a block: header line, column headers, data rows, footer lines.
Also upserts assets.csv with fund metadata (name, type, cnpj, manager).

Fund header format:
  "Fundo: CODE - FUND NAMEGestor: MANAGER_NAMECNPJ  XX.XXX.XXX/XXXX-XX"
  or "Fundo: CODE - FUND NAMEGestor:CNPJ  XX.XXX.XXX/XXXX-XX"
"""

import csv
import re
from pathlib import Path

from .base import InvestmentBaseParser, ParseResult
from .name_map import NameMapResolver

_CNPJ_RE = re.compile(r'CNPJ\s+(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})')
_FUND_HEADER_RE = re.compile(r'^Fundo:\s*\w+\s*-\s*(.+?)(?:Gestor:\s*(.+?))?CNPJ', re.IGNORECASE)

# Operations that generate balcao entries
_BALCAO_OPS = {'Aplicação', 'Resgate', 'Amortização'}
# Operations to skip (informational only)
_SKIP_OPS = {'Saldo Anterior', 'Saldo Atual'}


class SafraFundosParser(InvestmentBaseParser):
    source_id = "safra_fundos"

    def parse(self, filepath: Path, name_map: NameMapResolver = None) -> ParseResult:
        result = ParseResult()
        result.outputs = {'balcao': [], 'balance_snapshots': [], 'balcao_seeds': [], 'assets': []}

        blocks = self._read_blocks(filepath)

        for fund_name, cnpj, manager, rows in blocks:
            # Resolve fund to canonical product_id
            canonical = None
            if name_map:
                canonical = name_map.resolve_value('safra', 'fundo', fund_name)

            if canonical is None:
                # Auto-generate product_id from fund name
                canonical = re.sub(r'[^a-z0-9]+', '_', fund_name.lower()).strip('_')

            # Emit assets metadata (upserted by import_balance_snapshots.py).
            # Fixes the "fund product_id shown instead of friendly name" bug —
            # populates `name`, plus fund-specific cnpj/manager.
            result.outputs['assets'].append({
                'id': canonical,
                'asset_class': 'funds',
                'name': fund_name,
                'type': self._infer_type(fund_name),
                'sector': '',
                'currency': 'BRL',
                'current_broker': 'safra',
                'active': 'true',
                'cnpj': cnpj,
                'manager': manager,
            })

            for row in rows:
                lancamento = row.get('Lançamentos', '').strip()
                if not lancamento:
                    continue

                # "Saldo Atual": latest valuation → balance snapshot.
                # Net value (after estimated taxes) is what the user can actually withdraw.
                if lancamento == 'Saldo Atual':
                    date = self._parse_date(row.get('Data', ''))
                    valor_liq = self._parse_ptbr(row.get('Valor Líquido (R$)', '0'))
                    if date and valor_liq:
                        result.outputs['balance_snapshots'].append({
                            'date': date,
                            'product_id': canonical,
                            'balance': str(round(valor_liq, 2)),
                            'source': 'safra_fundos',
                        })
                    continue

                # "Saldo Anterior": opening balance for the statement period. Emit a
                # synthetic balcao seed so funds with no prior history get a cost-basis
                # baseline. The importer applies seeds ONLY when the product has zero
                # existing balcao rows — recurring statements never re-seed a tracked fund.
                if lancamento == 'Saldo Anterior':
                    date = self._parse_date(row.get('Data', ''))
                    valor_liq = self._parse_ptbr(row.get('Valor Líquido (R$)', '0'))
                    cotas = self._parse_ptbr(row.get('Quantidade de cotas', '0'))
                    if date and valor_liq:
                        result.outputs['balcao_seeds'].append({
                            'date': date,
                            'operation': 'aplicacao',
                            'product_id': canonical,
                            'product_type': self._infer_type(fund_name),
                            'quantity': str(round(abs(cotas), 8)),
                            'amount': str(round(-abs(valor_liq), 2)),
                            'irrf': '0',
                            'iof': '0',
                            'broker': 'safra',
                            'source': 'safra_fundos_seed',
                        })
                    continue

                if lancamento in _SKIP_OPS:
                    continue

                if lancamento not in _BALCAO_OPS:
                    # Unknown operation — skip silently (footer text, etc.)
                    continue

                date = self._parse_date(row.get('Data', ''))
                valor_bruto = self._parse_ptbr(row.get('Valor bruto (R$)', '0'))
                impostos = self._parse_ptbr(row.get('Impostos Incorridos (R$)', '0'))
                valor_liq = self._parse_ptbr(row.get('Valor Líquido (R$)', '0'))
                cotas = self._parse_ptbr(row.get('Quantidade de cotas', '0'))

                if lancamento == 'Aplicação':
                    amount = -abs(valor_bruto)  # Money out
                    operation = 'aplicacao'
                elif lancamento == 'Resgate':
                    amount = abs(valor_liq)  # Money in (net of taxes)
                    operation = 'resgate'
                elif lancamento == 'Amortização':
                    amount = abs(valor_liq)
                    operation = 'amortizacao'
                else:
                    continue

                result.outputs['balcao'].append({
                    'date': date,
                    'operation': operation,
                    'product_id': canonical,
                    'product_type': self._infer_type(fund_name),
                    'quantity': str(round(abs(cotas), 8)),
                    'amount': str(round(amount, 2)),
                    'irrf': str(round(abs(impostos), 2)),
                    'iof': '0',
                    'broker': 'safra',
                    'source': 'safra_fundos',
                })

        return result

    def _read_blocks(self, filepath: Path) -> list[tuple[str, str, str, list[dict]]]:
        """Parse block-based CSV into list of (fund_name, cnpj, manager, rows)."""
        blocks = []
        current_fund = None
        current_cnpj = ''
        current_manager = ''
        current_rows = []
        current_headers = None

        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                # Detect fund header
                if line.startswith('Fundo:'):
                    # Save previous block
                    if current_fund and current_rows:
                        blocks.append((current_fund, current_cnpj,
                                       current_manager, current_rows))

                    # Parse fund header
                    current_fund = self._extract_fund_name(line)
                    cnpj_match = _CNPJ_RE.search(line)
                    current_cnpj = cnpj_match.group(1) if cnpj_match else ''
                    # Extract manager (between "Gestor:" and "CNPJ")
                    m = re.search(r'Gestor:\s*(.+?)CNPJ', line)
                    current_manager = m.group(1).strip() if m else ''
                    current_rows = []
                    current_headers = None
                    continue

                # Detect column headers
                if line.startswith('Data,'):
                    current_headers = [h.strip() for h in line.split(',')]
                    continue

                # Skip footer lines (multi-line text)
                if line.startswith('"') or line.startswith('em cotização'):
                    continue
                if 'em cotização' in line or 'andamento' in line:
                    continue

                # Data row
                if current_headers and ',' in line:
                    # Parse CSV row with the current headers
                    parsed = self._parse_csv_row(line, current_headers)
                    if parsed and parsed.get('Data'):
                        current_rows.append(parsed)

            # Save last block
            if current_fund and current_rows:
                blocks.append((current_fund, current_cnpj,
                               current_manager, current_rows))

        return blocks

    def _extract_fund_name(self, header_line: str) -> str:
        """Extract clean fund name from header line."""
        # Remove "Fundo: CODE - " prefix
        m = re.match(r'Fundo:\s*\w+\s*-\s*(.+?)(?:Gestor|CNPJ)', header_line)
        if m:
            return m.group(1).strip()
        # Fallback: everything between "Fundo:" and "Gestor"
        m = re.match(r'Fundo:\s*(.+?)(?:Gestor|CNPJ)', header_line)
        if m:
            return m.group(1).strip()
        return header_line

    def _parse_csv_row(self, line: str, headers: list[str]) -> dict | None:
        """Parse a single CSV data row, handling quoted values with commas."""
        try:
            reader = csv.reader([line])
            values = next(reader)
            if len(values) >= len(headers):
                return dict(zip(headers, values))
        except Exception:
            pass
        return None

    def _parse_date(self, date_str: str) -> str:
        """DD/MM/YYYY → YYYY-MM-DD."""
        if not date_str:
            return ''
        parts = date_str.strip().split('/')
        if len(parts) == 3:
            return f'{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}'
        return date_str

    def _parse_ptbr(self, val: str) -> float:
        """Parse PT-BR decimal format."""
        if not val or val.strip() in ('-', ''):
            return 0.0
        s = val.strip().strip('"')
        s = s.replace('.', '').replace(',', '.')
        try:
            return float(s)
        except (ValueError, TypeError):
            return 0.0

    def _infer_type(self, fund_name: str) -> str:
        """Infer product_type from fund name patterns."""
        name_upper = fund_name.upper()
        if 'FIA' in name_upper:
            return 'fia_br'
        if 'FIM' in name_upper:
            return 'fim_br'
        if 'FIRF' in name_upper or 'RF REF DI' in name_upper:
            return 'firf_br'
        if 'FIDC' in name_upper:
            return 'fidc'
        return 'fim_br'  # Default for Safra funds
