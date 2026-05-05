"""Safra fixed income titles CSV parser.

Parses the "Títulos Renda Fixa - Emissão própria e de terceiros" export.
Each title has full metadata: indexer, rate, application date, maturity, current
value. This is significantly richer than fund statements — no synthetic seeds
needed because we know the real Data Aplicação.

Source schema (header row 2):
    Ativo, Emissor / Devedor, Indexador, Taxa, % Indexador,
    Data Aplicação, Vencimento/ Repactuação, Quantidade,
    Valor Aplicado (R$), Saldo Bruto (R$),
    IR Previsto (R$), IOF Previsto (R$), Saldo Líquido (R$),
    Status, Local Negociação

Outputs:
    - balance_snapshots: one row per title (Saldo Líquido as balance, today as date)
    - balcao_seeds: one row per title (Data Aplicação as date, -Valor Aplicado as amount).
      Real cost basis dates → seeds become honest cash flows for XIRR.
    - assets: one row per title (name, type, asset_class, issuer, indexer, rate,
      indexer_pct, application_date, maturity_date) — upserted into assets.csv,
      the master metadata registry. New RF columns coexist with empty values for
      non-RF rows.
"""

import csv
import re
from datetime import date
from pathlib import Path

from .base import InvestmentBaseParser, ParseResult
from .name_map import NameMapResolver


# "Ativo" header text → product_type enum
_ATIVO_TO_TYPE = [
    (re.compile(r'\bDeb', re.I), 'deb'),
    (re.compile(r'\bCRA\b', re.I), 'cra'),
    (re.compile(r'\bCRI\b', re.I), 'cri'),
    (re.compile(r'\bLCA\b|LETRA.*AGN', re.I), 'lca'),
    (re.compile(r'\bLCI\b', re.I), 'lci'),
    (re.compile(r'\bCDB\b', re.I), 'cdb'),
    (re.compile(r'\bLC\b', re.I), 'lc'),
    (re.compile(r'TESOURO|NTN|LFT|LTN', re.I), 'tesouro'),
    # "TCM CRAPRE" is a CRA variant
    (re.compile(r'CRAPRE', re.I), 'cra'),
]


class SafraTitulosParser(InvestmentBaseParser):
    source_id = "safra_titulos"

    def parse(self, filepath: Path, name_map: NameMapResolver = None) -> ParseResult:
        result = ParseResult()
        result.outputs = {
            'balcao': [],
            'balance_snapshots': [],
            'balcao_seeds': [],
            'assets': [],
        }

        # Statement date — the snapshots reflect "today" since the export has no
        # explicit valuation date column. Use today as a reasonable proxy.
        snapshot_date = date.today().isoformat()

        rows = self._read_data_rows(filepath)
        for row in rows:
            ativo = row.get('Ativo', '').strip()
            emissor = row.get('Emissor / Devedor', '').strip()
            if not ativo or not emissor or ativo.startswith('Aplicações do dia'):
                continue

            indexador = row.get('Indexador', '').strip()
            taxa = self._parse_ptbr(row.get('Taxa', '0'))
            indexador_pct = self._parse_ptbr(row.get('% Indexador', '0'))
            data_aplicacao = self._parse_date(row.get('Data Aplicação', ''))
            vencimento = self._parse_date(row.get('Vencimento/ Repactuação', ''))
            quantidade = self._parse_ptbr(row.get('Quantidade', '0'))
            valor_aplicado = self._parse_ptbr(row.get('Valor Aplicado (R$)', '0'))
            saldo_liquido = self._parse_ptbr(row.get('Saldo Líquido (R$)', '0'))

            if not data_aplicacao or valor_aplicado <= 0:
                continue

            product_type = self._infer_type(ativo)
            canonical = self._resolve_id(name_map, ativo, emissor, taxa, product_type)

            display_name = f"{ativo} {emissor}".strip()

            # Snapshot — current valuation
            if saldo_liquido > 0:
                result.outputs['balance_snapshots'].append({
                    'date': snapshot_date,
                    'product_id': canonical,
                    'balance': str(round(saldo_liquido, 2)),
                    'source': 'safra_titulos',
                })

            # Seed — real cost-basis aplicação (NOT synthetic; the Data Aplicação is genuine)
            result.outputs['balcao_seeds'].append({
                'date': data_aplicacao,
                'operation': 'aplicacao',
                'product_id': canonical,
                'product_type': product_type,
                'quantity': str(round(abs(quantidade), 8)),
                'amount': str(round(-abs(valor_aplicado), 2)),
                'irrf': '0',
                'iof': '0',
                'broker': 'safra',
                'source': 'safra_titulos_aplicacao',
            })

            # Metadata — upserted into assets.csv (the master registry).
            result.outputs['assets'].append({
                'id': canonical,
                'asset_class': 'fixed_income',
                'name': display_name,
                'type': product_type,
                'sector': '',
                'currency': 'BRL',
                'current_broker': 'safra',
                'active': 'true',
                'issuer': emissor,
                'indexer': indexador,
                'rate': str(taxa) if taxa else '',
                'indexer_pct': str(indexador_pct) if indexador_pct else '',
                'application_date': data_aplicacao,
                'maturity_date': vencimento,
            })

        return result

    def _read_data_rows(self, filepath: Path) -> list[dict]:
        """Skip the title row, use row 1 as header."""
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            lines = list(csv.reader(f))
        # Find header row — first row whose first cell is "Ativo"
        header_idx = None
        for i, r in enumerate(lines):
            if r and r[0].strip() == 'Ativo':
                header_idx = i
                break
        if header_idx is None:
            return []
        headers = [h.strip() for h in lines[header_idx]]
        rows = []
        for r in lines[header_idx + 1:]:
            if not r or not any(c.strip() for c in r):
                continue
            rows.append(dict(zip(headers, [c.strip() for c in r])))
        return rows

    def _resolve_id(self, name_map, ativo: str, emissor: str, taxa: float, product_type: str) -> str:
        """Resolve to canonical product_id.

        Composite raw_value = "ATIVO|EMISSOR|TAXA" so two debêntures from the same
        issuer at different rates get distinct ids. name_map can override.
        """
        composite = f"{ativo}|{emissor}|{taxa}"
        if name_map:
            mapped = name_map.resolve_value('safra_titulos', 'titulo', composite)
            if mapped:
                return mapped

        # Auto-generate: type_indexer_issuer[_rate-suffix]
        issuer_slug = re.sub(r'[^a-z0-9]+', '_', emissor.lower()).strip('_')
        issuer_slug = re.sub(r'_(s_a|sa|s_l|ltda|industr)$', '', issuer_slug)
        # Truncate excessively long issuer slugs
        if len(issuer_slug) > 28:
            issuer_slug = issuer_slug[:28].rstrip('_')

        indexador_slug = ''
        m = re.search(r'(CDI|IPCA|PRE|SELIC)', ativo, re.I)
        if m:
            indexador_slug = m.group(1).lower()

        parts = [product_type]
        if indexador_slug:
            parts.append(indexador_slug)
        parts.append(issuer_slug)
        base = '_'.join(parts)

        return f"{base}_{int(round(taxa * 100))}" if taxa else base

    def _infer_type(self, ativo: str) -> str:
        for pattern, t in _ATIVO_TO_TYPE:
            if pattern.search(ativo):
                return t
        return 'rf'

    def _parse_date(self, s: str) -> str:
        s = s.strip()
        if not s or s in ('-', ''):
            return ''
        parts = s.split('/')
        if len(parts) == 3:
            return f'{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}'
        return ''

    def _parse_ptbr(self, val: str) -> float:
        if not val or val.strip() in ('-', ''):
            return 0.0
        s = val.strip().strip('"')
        s = s.replace('.', '').replace(',', '.')
        try:
            return float(s)
        except (ValueError, TypeError):
            return 0.0
