---
version: "1.0"
last_updated: "2026-05-27"
---

# Sources Manifest

Public registry of finance sources supported by this module. Every source listed here has a working parser under `../../scripts/`. When a user adds a source not listed here, `sb-bookkeeper` dispatches `tool-builder` to build it and then `doc-maintainer` to add it here — compounding the registry for all users.

**Path constants:**
```
SCRIPTS_DIR  = 3-resources/tools/sb-os/finance/scripts
SHARED_DIR   = {SCRIPTS_DIR}/shared
INV_DIR      = {SCRIPTS_DIR}/investimentos
```

---

## Per-Entry Schema

Each source entry carries these fields:

| Field | Description |
|-------|-------------|
| `id` | Stable snake_case identifier. Referenced by `.user/finance/bookkeeper/config/sources.yaml`. |
| `name` | Human-readable source name (pt-BR). |
| `scope` | `expenses` / `investments` / `both` |
| `input_format` | One or more of: `csv`, `pdf`, `ofx`, `manual` |
| `download_instructions` | Step-by-step export instructions for the user (pt-BR). |
| `extraction_instructions` | How to extract/convert the file if needed (e.g., PDF password). Omit if not applicable. |
| `parser_entry_point` | Path to the parser script under `SCRIPTS_DIR`. |
| `dry_run` | `true` if the parser ships a `--dry-run` mode. |
| `last_validated` | Date the parser was last verified against a real export. ISO 8601. |

---

## Expense Sources

### bradesco_extrato

| Field | Value |
|-------|-------|
| id | `bradesco_extrato` |
| name | Bradesco — Extrato Conta Corrente |
| scope | expenses |
| input_format | csv |
| download_instructions | App Bradesco → Extrato → Exportar CSV → salvar como `extrato-bradesco.csv` |
| extraction_instructions | — |
| parser_entry_point | `{SHARED_DIR}/parsers/bradesco_extrato.py` |
| dry_run | true |
| last_validated | 2026-05-27 |

---

### santander_extrato

| Field | Value |
|-------|-------|
| id | `santander_extrato` |
| name | Santander — Extrato Conta Corrente |
| scope | expenses |
| input_format | pdf |
| download_instructions | Internet Banking Santander → Extrato → Exportar PDF → salvar como `extrato-santander.pdf` |
| extraction_instructions | — |
| parser_entry_point | `{SHARED_DIR}/parsers/santander_extrato.py` |
| dry_run | true |
| last_validated | 2026-05-27 |

---

### santander_fatura

| Field | Value |
|-------|-------|
| id | `santander_fatura` |
| name | Santander — Fatura Cartão Visa |
| scope | expenses |
| input_format | pdf |
| download_instructions | Email ou app Santander → Fatura → Baixar PDF → salvar como `fatura-santander.pdf` |
| extraction_instructions | Senha do PDF: CPF completo (só dígitos, sem pontos ou traço) |
| parser_entry_point | `{SHARED_DIR}/parsers/santander_fatura.py` |
| dry_run | true |
| last_validated | 2026-05-27 |

---

### mp_extrato

| Field | Value |
|-------|-------|
| id | `mp_extrato` |
| name | Mercado Pago — Extrato Conta |
| scope | expenses |
| input_format | csv |
| download_instructions | App Mercado Pago → Atividades → Exportar → CSV → salvar como `extrato-mercado-pago.csv` |
| extraction_instructions | — |
| parser_entry_point | `{SHARED_DIR}/parsers/mp_extrato.py` |
| dry_run | true |
| last_validated | 2026-05-27 |

---

### mp_fatura

| Field | Value |
|-------|-------|
| id | `mp_fatura` |
| name | Mercado Pago — Fatura Cartão |
| scope | expenses |
| input_format | pdf |
| download_instructions | Email Mercado Pago → Fatura do mês → PDF em anexo → salvar como `fatura-mercado-pago.pdf` |
| extraction_instructions | Senha do PDF: primeiros 5 dígitos do CPF |
| parser_entry_point | `{SHARED_DIR}/parsers/mp_fatura.py` |
| dry_run | true |
| last_validated | 2026-05-27 |

---

### wise_extrato

| Field | Value |
|-------|-------|
| id | `wise_extrato` |
| name | Wise — Extrato Multi-Moeda |
| scope | expenses |
| input_format | csv |
| download_instructions | Wise.com → Statements → selecionar moeda → Export → CSV → salvar como `wise/extrato-wise-{MOEDA}.csv` (um arquivo por moeda) |
| extraction_instructions | — |
| parser_entry_point | `{SHARED_DIR}/parsers/wise_extrato.py` |
| dry_run | true |
| last_validated | 2026-05-27 |

---

### manual_cash

| Field | Value |
|-------|-------|
| id | `manual_cash` |
| name | Gastos em Dinheiro — Entrada Manual |
| scope | expenses |
| input_format | manual |
| download_instructions | Inserido manualmente durante o fechamento (Step 5, Section 2). Não requer arquivo. |
| extraction_instructions | — |
| parser_entry_point | — (entrada manual via Step 5 do gastos workflow) |
| dry_run | false |
| last_validated | 2026-05-27 |

---

## Expense Sources — Historical Only

These sources have working parsers but are used only for backfill (past-period imports). They are NOT used for new monthly closes.

### nubank_fatura

| Field | Value |
|-------|-------|
| id | `nubank_fatura` |
| name | Nubank — Fatura Cartão |
| scope | expenses |
| input_format | pdf |
| download_instructions | App Nubank → Fatura → Baixar PDF (ou email) → salvar como `fatura-nubank.pdf` |
| extraction_instructions | — |
| parser_entry_point | `{SHARED_DIR}/parsers/nubank_fatura.py` |
| dry_run | true |
| last_validated | 2026-05-27 |
| note | historical_only — não usar em fechamentos novos |

---

### xp_fatura

| Field | Value |
|-------|-------|
| id | `xp_fatura` |
| name | XP — Fatura Cartão |
| scope | expenses |
| input_format | csv |
| download_instructions | App XP → Cartão → Fatura → Exportar CSV → salvar como `fatura-xp.csv` |
| extraction_instructions | — |
| parser_entry_point | `{SHARED_DIR}/parsers/xp_fatura.py` |
| dry_run | true |
| last_validated | 2026-05-27 |
| note | historical_only — não usar em fechamentos novos |

---

## Investment Sources

### safra

| Field | Value |
|-------|-------|
| id | `safra` |
| name | Banco Safra / Safra Corretora |
| scope | investments |
| input_format | pdf, csv |
| download_instructions | Portal Safra → Relatórios → exportar extrato de movimentações (PDF) e posição (CSV) conforme instruções em `3-resources/tools/prompts/safra-extrair-movimentacoes.md` |
| extraction_instructions | Ver prompts específicos por tipo de ativo (RF, fundos, títulos) no diretório `3-resources/tools/prompts/` |
| parser_entry_point | `{INV_DIR}/parsers/safra_*.py` (múltiplos parsers por tipo de ativo: `safra_titulos.py`, `safra_fundos.py`, `safra_rf_movimentacoes.py`, `safra_fundos_movimentacoes.py`) |
| dry_run | true |
| last_validated | 2026-05-27 |

---

### b3

| Field | Value |
|-------|-------|
| id | `b3` |
| name | B3 — Bolsa Brasileira (via Safra Corretora) |
| scope | investments |
| input_format | pdf, csv |
| download_instructions | Extratos de movimentações de ações e fundos de investimento via portal Safra |
| extraction_instructions | Coberto pelos parsers Safra para renda variável |
| parser_entry_point | `{INV_DIR}/parsers/b3_parser.py` (run via `{INV_DIR}/run_b3.py`) |
| dry_run | true |
| last_validated | 2026-05-27 |

---

### avenue

| Field | Value |
|-------|-------|
| id | `avenue` |
| name | Avenue Securities |
| scope | investments |
| input_format | csv |
| download_instructions | Avenue.us → Activity → Export CSV → salvar na pasta de investimentos do mês |
| extraction_instructions | — |
| parser_entry_point | `{INV_DIR}/parsers/avenue.py` (trades) + `{INV_DIR}/parsers/avenue_fx.py` (fx) |
| dry_run | true |
| last_validated | 2026-05-27 |

---

### mercado_bitcoin

| Field | Value |
|-------|-------|
| id | `mercado_bitcoin` |
| name | Mercado Bitcoin |
| scope | investments |
| input_format | csv |
| download_instructions | Mercado Bitcoin → Extratos → Exportar CSV → salvar na pasta de investimentos do mês |
| extraction_instructions | — |
| parser_entry_point | `{INV_DIR}/parsers/mercado_bitcoin.py` |
| dry_run | true |
| last_validated | 2026-05-27 |

---

### bipa

| Field | Value |
|-------|-------|
| id | `bipa` |
| name | Bipa |
| scope | investments |
| input_format | csv |
| download_instructions | Bipa → Relatórios → Exportar CSV → salvar na pasta de investimentos do mês |
| extraction_instructions | — |
| parser_entry_point | `{INV_DIR}/parsers/bipa.py` |
| dry_run | true |
| last_validated | 2026-05-27 |

---

### funds

| Field | Value |
|-------|-------|
| id | `funds` |
| name | Fundos de Investimento (via Safra) |
| scope | investments |
| input_format | pdf, csv |
| download_instructions | Extratos de fundos via portal Safra — cobertura inclui fundos de renda fixa, multimercado e fundos imobiliários |
| extraction_instructions | Ver prompts específicos em `3-resources/tools/prompts/` |
| parser_entry_point | `{INV_DIR}/parsers/safra_fundos.py` + `{INV_DIR}/parsers/safra_fundos_movimentacoes.py` |
| dry_run | true |
| last_validated | 2026-05-27 |

---

## Append Convention

When a new source is validated by `tool-builder` and `doc-maintainer`, append a new section here under the appropriate category (Expense Sources / Investment Sources) following the per-entry schema above. One section per source. `last_validated` = date of the first successful dry-run against a real export. Do NOT edit existing entries without bumping `last_updated` in the frontmatter.
