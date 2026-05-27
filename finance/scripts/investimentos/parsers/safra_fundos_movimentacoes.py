"""Safra fund movimentacoes CSV parser (browser-extracted Histórico Mensal).

Consumes the 12-column CSV produced by the prompt
`safra-extrair-movimentacoes` (or the bootstrap variant). Covers fund
panels only (RF goes through `safra_rf_movimentacoes`).

Source schema:
    Mes, FundoNome, Gestor, CNPJ, DataLancamento, Lancamento,
    ValorBruto, ImpostosIncorridos, ImpostosPrevistos, ValorLiquido,
    ValorCota, QuantidadeCotas

Lançamento mapping:
    Saldo Atual       → balance_snapshots (date=DataLancamento, balance=ValorLiquido)
    Saldo Anterior    → balcao_seeds      (date=DataLancamento, amount=-ValorLiquido)
                        (only emitted when valores presentes; importer dedupes
                         seeds against earlier balcao history per product_id)
    Aplicação         → balcao            (op=aplicacao, amount=-ValorBruto)
    Resgate           → balcao            (op=resgate, amount=+ValorLiquido,
                                           irrf=ImpostosIncorridos)
    Pagamento de Juros→ balcao            (op=juros, amount=+ValorLiquido)
    Amortização*      → balcao            (op=amortizacao, amount=+ValorLiquido)
    Come-cotas        → balcao            (op=come_cotas, amount=-ImpostosIncorridos)
    All-"-" rows      → skipped silently  (cotização in flight; no value yet)
    Unknown lançamento→ flagged

Canonical product_id resolution:
    Fundos can change Safra-internal code mid-year while keeping the same
    CNPJ (e.g. `W39 - CLARITAS...` migrated to `D46 - CLARITAS...`).
    We resolve product_id from CNPJ via name_map (`safra_movimentacoes /
    fundo_cnpj / <cnpj>`). Fallback: slug-of-FundoNome with code prefix
    stripped (`W39 - CLARITAS VALOR FEEDER FIA*` → `claritas_valor_feeder_fia`).
"""

import csv
import re
import unicodedata
from pathlib import Path

from .base import FlaggedOperation, InvestmentBaseParser, ParseResult
from .name_map import NameMapResolver


_CODE_PREFIX_RE = re.compile(r'^[A-Z0-9]{2,4}\s*-\s*', re.IGNORECASE)
_TRAILING_AST_RE = re.compile(r'\*+$')


def _ascii_slug(s: str) -> str:
    """Lowercase ASCII slug, accents stripped."""
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-z0-9]+', '_', s.lower()).strip('_')


class SafraFundosMovimentacoesParser(InvestmentBaseParser):
    source_id = "safra_fundos_movimentacoes"

    def parse(self, filepath: Path, name_map: NameMapResolver = None) -> ParseResult:
        result = ParseResult()
        result.outputs = {
            'balcao': [],
            'balance_snapshots': [],
            'balcao_seeds': [],
            'assets': [],
        }

        rows = self._read_rows(filepath)
        # Track which CNPJs we've already emitted assets metadata for, to avoid
        # repeating one row per (CNPJ, monthly statement) pair.
        emitted_assets: set[str] = set()

        for line_no, row in enumerate(rows, start=2):  # +2 = header on line 1
            cnpj = (row.get('CNPJ') or '').strip()
            fundo_nome_raw = (row.get('FundoNome') or '').strip()
            gestor = (row.get('Gestor') or '').strip()
            lancamento = (row.get('Lancamento') or '').strip()
            data_lcto = self._parse_date(row.get('DataLancamento', ''))

            if not lancamento or not cnpj:
                continue

            valor_bruto = self._parse_ptbr(row.get('ValorBruto', ''))
            impostos_incorridos = self._parse_ptbr(row.get('ImpostosIncorridos', ''))
            valor_liquido = self._parse_ptbr(row.get('ValorLiquido', ''))
            quantidade_cotas = self._parse_ptbr(row.get('QuantidadeCotas', ''))

            fundo_nome = self._normalize_fund_name(fundo_nome_raw)
            canonical, mapped_type = self._resolve_id(name_map, cnpj, fundo_nome)
            # name_map's asset_type wins when set (handles edge cases like Trígono
            # where the FIA classification isn't inferable from the fund name).
            product_type = mapped_type or self._infer_type(fundo_nome)

            # Asset metadata — emit once per CNPJ in this file
            if cnpj not in emitted_assets:
                emitted_assets.add(cnpj)
                result.outputs['assets'].append({
                    'id': canonical,
                    'asset_class': 'funds',
                    'name': fundo_nome,
                    'type': product_type,
                    'sector': '',
                    'currency': 'BRL',
                    'current_broker': 'safra',
                    'active': 'true',
                    'cnpj': cnpj,
                    'manager': gestor,
                })

            # Saldo Atual → snapshot (skip empty rows)
            if lancamento == 'Saldo Atual':
                if data_lcto and valor_liquido > 0:
                    result.outputs['balance_snapshots'].append({
                        'date': data_lcto,
                        'product_id': canonical,
                        'balance': str(round(valor_liquido, 2)),
                        'source': 'safra_movimentacoes',
                    })
                continue

            # Saldo Anterior → seed (importer enforces "no prior history" before applying)
            if lancamento == 'Saldo Anterior':
                if data_lcto and valor_liquido > 0:
                    result.outputs['balcao_seeds'].append({
                        'date': data_lcto,
                        'operation': 'aplicacao',
                        'product_id': canonical,
                        'product_type': product_type,
                        'quantity': str(round(abs(quantidade_cotas), 8)),
                        'amount': str(round(-abs(valor_liquido), 2)),
                        'irrf': '0',
                        'iof': '0',
                        'broker': 'safra',
                        'source': 'safra_movimentacoes_seed',
                    })
                continue

            # Real cash-flow operations
            op_amount = self._map_operation(
                lancamento, valor_bruto, valor_liquido, impostos_incorridos
            )
            if op_amount is None:
                # Unknown lançamento — flag for the user
                result.flags.append(FlaggedOperation(
                    date=data_lcto,
                    operation=lancamento,
                    product=fundo_nome,
                    values={
                        'valor_bruto': valor_bruto,
                        'valor_liquido': valor_liquido,
                        'impostos': impostos_incorridos,
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
                'quantity': str(round(abs(quantidade_cotas), 8)),
                'amount': str(round(amount, 2)),
                'irrf': str(round(abs(irrf), 2)),
                'iof': '0',
                'broker': 'safra',
                'source': 'safra_movimentacoes',
            })

        return result

    # ---------------- helpers ----------------

    def _map_operation(
        self, lancamento: str, valor_bruto: float, valor_liquido: float,
        impostos: float,
    ) -> tuple[str, float, float] | None:
        """Return (operation, amount, irrf) or None if all values are empty/skip."""
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
            # No money flow but a tax debit; the tax reduces cota count over time.
            # Decision (a) from task spec: amount=-impostos so the loss shows up
            # in net_flow / impostos_total bucket; quantity stays the cota delta.
            if impostos <= 0:
                return None
            return ('come_cotas', -abs(impostos), abs(impostos))
        if lancamento == 'Entrada por transferência de Custódia':
            # Custody transfer in (e.g. Guide → Safra migration). NOT a real
            # cash flow — the original aplicação date lives in DataAplicacao
            # (RF only) or in safra_titulos seeds (already in balcao.csv).
            # Skip without flagging.
            return None
        return None

    def _normalize_fund_name(self, raw: str) -> str:
        """Strip Safra-internal code prefix (`W39 - `) and trailing `*`."""
        s = _CODE_PREFIX_RE.sub('', raw or '').strip()
        s = _TRAILING_AST_RE.sub('', s).strip()
        return s

    def _resolve_id(self, name_map, cnpj: str, fundo_nome: str) -> tuple[str, str]:
        """Resolve canonical product_id and asset_type from name_map.

        Returns (canonical_id, asset_type). asset_type is empty when the lookup
        falls back to slug auto-generation (caller should infer from name).

        Lookup order:
          1. safra / fundo_cnpj / <cnpj>     — most stable (Safra renames funds)
          2. safra / fundo / <fundo_nome>    — reuses entries from legacy parser
          3. ASCII slug fallback             — auto-generated, may need name_map
        """
        if name_map and cnpj:
            canonical, atype = name_map.resolve_with_type('safra', 'fundo_cnpj', cnpj)
            if canonical:
                return canonical, atype
        if name_map and fundo_nome:
            canonical, atype = name_map.resolve_with_type('safra', 'fundo', fundo_nome)
            if canonical:
                return canonical, atype
        return (_ascii_slug(fundo_nome) or 'unknown_fund', '')

    def _infer_type(self, fundo_nome: str) -> str:
        # Word-boundary matches — `'FIA' in 'CONFIANZA'` was a false positive.
        name = (fundo_nome or '').upper()
        if re.search(r'\bFIRF\b', name) or 'RF REF DI' in name or 'RF REFER' in name:
            return 'firf_br'
        if re.search(r'\bFIDC\b', name):
            return 'fidc'
        if re.search(r'\bFIA\b', name):
            return 'fia_br'
        if re.search(r'\bFIM\b', name):
            return 'fim_br'
        return 'fim_br'

    def _read_rows(self, filepath: Path) -> list[dict]:
        with open(filepath, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            return list(reader)

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
