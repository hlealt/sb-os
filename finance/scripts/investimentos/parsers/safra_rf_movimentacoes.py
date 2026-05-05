"""Safra RF movimentacoes CSV parser (browser-extracted Histórico Mensal).

Consumes the 11-column CSV produced by the prompt
`safra-extrair-movimentacoes-v2`. Covers RF panels only (CRA, CRI, Debênture,
LCA, LCI, CDB non-automático, Tesouro). Fund panels go through
`safra_fundos_movimentacoes`.

Source schema:
    Mes, Titulo, Ativo, Emissor, DataAplicacao, DataVencimento,
    DataLancamento, Lancamento, ValorBruto, ImpostosIncorridos, ValorLiquido

Lançamento mapping (mirrors safra_fundos_movimentacoes):
    Saldo Atual                      → balance_snapshots
    Saldo Anterior                   → balcao_seeds
    Aplicação                        → balcao  (op=aplicacao)
    Resgate                          → balcao  (op=resgate)
    Pagamento de Juros               → balcao  (op=juros)
    Amortização*                     → balcao  (op=amortizacao)
    Come-cotas                       → balcao  (op=come_cotas)  [rare for RF]
    Entrada por transferência de Custódia → SKIP (not a real cash flow; original
                                          aplicação already covered by safra_titulos
                                          or DataAplicacao seed below)
    All-"-" rows                     → skip silently
    Unknown                          → flagged

Canonical product_id resolution:
    Composite raw_value = "ATIVO|EMISSOR|DATA_APLICACAO|DATA_VENCIMENTO" so two
    debêntures from the same issuer with different application/maturity dates
    get distinct ids. name_map override lookup:
    `safra_movimentacoes / titulo / <ativo>|<emissor>|<dt_apl>|<dt_venc>`.
    Fallback: type_indexer_issuer slug.

RF metadata emitted into assets.csv is intentionally lean (no indexer/rate —
this CSV doesn't carry those columns). The `safra_titulos` parser remains the
canonical source for indexer/rate enrichment; upsert preserves existing values
because non-empty fields don't get overwritten by empty ones.
"""

import csv
import re
import unicodedata
from pathlib import Path

from .base import FlaggedOperation, InvestmentBaseParser, ParseResult
from .name_map import NameMapResolver


def _ascii_slug(s: str) -> str:
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-z0-9]+', '_', s.lower()).strip('_')


_ATIVO_TO_TYPE = [
    (re.compile(r'\bDeb', re.I), 'deb'),
    (re.compile(r'\bCRA\b|CRAPRE', re.I), 'cra'),
    (re.compile(r'\bCRI\b', re.I), 'cri'),
    (re.compile(r'\bLCA\b|LETRA.*AGN', re.I), 'lca'),
    (re.compile(r'\bLCI\b', re.I), 'lci'),
    (re.compile(r'\bCDB\b', re.I), 'cdb'),
    (re.compile(r'TESOURO|NTN|LFT|LTN', re.I), 'tesouro'),
    (re.compile(r'\bLC\b', re.I), 'lc'),
]


class SafraRfMovimentacoesParser(InvestmentBaseParser):
    source_id = "safra_rf_movimentacoes"

    def parse(self, filepath: Path, name_map: NameMapResolver = None) -> ParseResult:
        result = ParseResult()
        result.outputs = {
            'balcao': [],
            'balance_snapshots': [],
            'balcao_seeds': [],
            'assets': [],
        }

        rows = self._read_rows(filepath)
        emitted_assets: set[str] = set()

        for line_no, row in enumerate(rows, start=2):
            ativo = (row.get('Ativo') or '').strip()
            emissor = (row.get('Emissor') or '').strip()
            data_aplicacao = self._parse_date(row.get('DataAplicacao', ''))
            data_vencimento = self._parse_date(row.get('DataVencimento', ''))
            data_lcto = self._parse_date(row.get('DataLancamento', ''))
            lancamento = (row.get('Lancamento') or '').strip()

            if not lancamento or not ativo or not emissor:
                continue

            valor_bruto = self._parse_ptbr(row.get('ValorBruto', ''))
            impostos = self._parse_ptbr(row.get('ImpostosIncorridos', ''))
            valor_liquido = self._parse_ptbr(row.get('ValorLiquido', ''))

            product_type = self._infer_type(ativo)
            canonical = self._resolve_id(
                name_map, ativo, emissor, data_aplicacao, data_vencimento, product_type
            )
            display_name = f'{ativo} {emissor}'.strip()

            if canonical not in emitted_assets:
                emitted_assets.add(canonical)
                # Lean metadata — indexer/rate left empty so safra_titulos values
                # are preserved by upsert_assets.
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
                    'application_date': data_aplicacao,
                    'maturity_date': data_vencimento,
                })

            if lancamento == 'Saldo Atual':
                if data_lcto and valor_liquido > 0:
                    result.outputs['balance_snapshots'].append({
                        'date': data_lcto,
                        'product_id': canonical,
                        'balance': str(round(valor_liquido, 2)),
                        'source': 'safra_movimentacoes',
                    })
                continue

            if lancamento == 'Saldo Anterior':
                if data_lcto and valor_liquido > 0:
                    result.outputs['balcao_seeds'].append({
                        'date': data_lcto,
                        'operation': 'aplicacao',
                        'product_id': canonical,
                        'product_type': product_type,
                        'quantity': '0',
                        'amount': str(round(-abs(valor_liquido), 2)),
                        'irrf': '0',
                        'iof': '0',
                        'broker': 'safra',
                        'source': 'safra_movimentacoes_seed',
                    })
                continue

            op_amount = self._map_operation(
                lancamento, valor_bruto, valor_liquido, impostos
            )
            if op_amount is None:
                # Skip silently for known-but-no-op lançamentos like custody transfer
                if lancamento in _SILENT_SKIP:
                    continue
                result.flags.append(FlaggedOperation(
                    date=data_lcto,
                    operation=lancamento,
                    product=display_name,
                    values={
                        'valor_bruto': valor_bruto,
                        'valor_liquido': valor_liquido,
                        'impostos': impostos,
                    },
                    reason=f'unknown lançamento type "{lancamento}"',
                    line_number=line_no,
                ))
                continue

            operation, amount, irrf = op_amount
            if not data_lcto:
                continue

            result.outputs['balcao'].append({
                'date': data_lcto,
                'operation': operation,
                'product_id': canonical,
                'product_type': product_type,
                'quantity': '0',  # RF CSV doesn't carry quantity
                'amount': str(round(amount, 2)),
                'irrf': str(round(abs(irrf), 2)),
                'iof': '0',
                'broker': 'safra',
                'source': 'safra_movimentacoes',
            })

        return result

    # ---------------- helpers ----------------

    def _map_operation(
        self, lancamento: str, valor_bruto: float, valor_liquido: float, impostos: float,
    ) -> tuple[str, float, float] | None:
        if lancamento == 'Aplicação':
            if valor_bruto <= 0:
                return None
            return ('aplicacao', -abs(valor_bruto), 0.0)
        if lancamento == 'Resgate':
            if valor_liquido <= 0:
                return None
            return ('resgate', abs(valor_liquido), abs(impostos))
        if lancamento == 'Pagamento de Juros':
            if valor_liquido <= 0:
                return None
            return ('juros', abs(valor_liquido), abs(impostos))
        if lancamento.startswith('Amortização'):
            if valor_liquido <= 0:
                return None
            return ('amortizacao', abs(valor_liquido), abs(impostos))
        if lancamento == 'Come-cotas':
            if impostos <= 0:
                return None
            return ('come_cotas', -abs(impostos), abs(impostos))
        return None

    def _resolve_id(self, name_map, ativo: str, emissor: str,
                    data_aplicacao: str, data_vencimento: str, product_type: str) -> str:
        composite = f'{ativo}|{emissor}|{data_aplicacao}|{data_vencimento}'
        if name_map:
            mapped = name_map.resolve_value('safra', 'titulo', composite)
            if mapped:
                return mapped
        # Fallback: type_indexer_issuer_year (DataAplicacao year disambiguates
        # tranches with same issuer/maturity but different application dates).
        issuer_slug = _ascii_slug(emissor)
        issuer_slug = re.sub(r'_(s_a|sa|s_l|ltda|industr)$', '', issuer_slug)
        if len(issuer_slug) > 28:
            issuer_slug = issuer_slug[:28].rstrip('_')
        indexador = ''
        m = re.search(r'(CDI|IPCA|PRE|SELIC)', ativo, re.I)
        if m:
            indexador = m.group(1).lower()
        parts = [product_type]
        if indexador:
            parts.append(indexador)
        parts.append(issuer_slug)
        if data_aplicacao and len(data_aplicacao) >= 4:
            parts.append(data_aplicacao[:4])
        if data_vencimento and len(data_vencimento) >= 4:
            parts.append(data_vencimento[:4])
        return '_'.join(p for p in parts if p)

    def _infer_type(self, ativo: str) -> str:
        for pattern, t in _ATIVO_TO_TYPE:
            if pattern.search(ativo):
                return t
        return 'rf'

    def _read_rows(self, filepath: Path) -> list[dict]:
        with open(filepath, 'r', encoding='utf-8-sig', newline='') as f:
            return list(csv.DictReader(f))

    def _parse_date(self, s: str) -> str:
        s = (s or '').strip()
        if not s or s == '-':
            return ''
        parts = s.split('/')
        if len(parts) == 3:
            return f'{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}'
        return ''

    def _parse_ptbr(self, val: str) -> float:
        if not val:
            return 0.0
        s = val.strip().strip('"')
        if not s or s == '-':
            return 0.0
        s = s.replace('.', '').replace(',', '.')
        try:
            return float(s)
        except (ValueError, TypeError):
            return 0.0


# Lançamentos that are known but produce no balcao row (silently skipped).
_SILENT_SKIP = {
    'Entrada por transferência de Custódia',
}
