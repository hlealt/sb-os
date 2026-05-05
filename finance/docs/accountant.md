# Fechamento Financeiro Mensal

Workflow automatizado de fechamento financeiro mensal para um Second Brain baseado em Obsidian. Processa extratos bancários e faturas de cartão de crédito (PDF/CSV), categoriza transações, e gera um relatório markdown — com revisão humana para itens não categorizados.

## Como funciona

O workflow é dividido em duas camadas: **scripts Python** (processamento de dados) e **agente Claude** (orquestração e interação humana).

```
Extratos/Faturas (PDF/CSV)
        │
        ▼
  ┌─────────────────┐     ┌──────────────┐     ┌──────────────┐
  │ Agente: pre-flight│ ──►│ normalize.py │ ──► │  Checkpoint  │
  │ (ID + rename)    │    │  (parsers)   │     │  (agente)    │
  └─────────────────┘    └──────────────┘     └──────────────┘
                               │                      │
                         CSVs normalizados             │
                                                       ▼
                                              ┌─────────────┐
                                              │categorize.py│
                                              └─────────────┘
                                                       │
                                                 CSV categorizado
                                                       │
                                                       ▼
                                           ┌────────────────────┐
                                           │  Revisão interativa │
                                           │     (agente)        │
                                           └────────────────────┘
                                                       │
                                                       ▼
                                           ┌────────────────────┐
                                           │  Relatório markdown │
                                           │     (agente)        │
                                           └────────────────────┘
```

### Por que dois scripts separados?

Bancos mudam formato de PDF sem aviso. O checkpoint do agente entre normalização e categorização detecta problemas de parser antes que dados corrompidos entrem na categorização. Se o output normalizado estiver errado, o agente para, avisa o usuário, e o parser pode ser ajustado sem re-categorizar tudo.

### Por que não um único script end-to-end?

A categorização depende de revisão humana para itens desconhecidos. O agente precisa interagir com o usuário entre os scripts. Um script único não permite esse ciclo de feedback.

---

## Estrutura de arquivos

O workflow segue o PARA method do Obsidian e distribui arquivos em três locais:

```
.user/workflows/accountant/   # WORKFLOW (permanent infrastructure)
├── accountant.md               # Workflow entry point (path vars, activation, rules)
├── gastos/
│   ├── step-01-preflight.md               # Pre-flight check and filename normalization
│   ├── step-02-normalize.md               # Run normalize.py
│   ├── step-03-validate.md                # Validation checkpoint
│   ├── step-04-categorize.md              # Run categorize.py
│   ├── step-05-review.md                  # Two-pass review queue + cash entries
│   ├── step-06-report.md                  # Generate markdown report
│   ├── step-07-recurring.md               # Update recurring payments
│   └── step-08-manifest.md                # Update dashboard manifest
├── scripts/
│   ├── normalize.py                       # Orquestrador: raw → CSVs normalizados
│   ├── categorize.py                      # CSVs normalizados → CSV categorizado
│   ├── utils.py                           # Normalização de datas/decimais, I/O CSV
│   ├── requirements.txt                   # pdfplumber, pikepdf
│   └── parsers/
│       ├── __init__.py                    # Registry (auto-discovery por bank_id)
│       ├── base.py                        # BaseParser (classe abstrata)
│       ├── bradesco_extrato.py            # CSV, delimitador ;, DD/MM/YYYY
│       ├── mp_extrato.py                  # CSV, delimitador ;, header duplo (RELEASE_DATE)
│       ├── wise_extrato.py                # CSV, delimitador ,, multi-moeda
│       ├── santander_extrato.py           # PDF, tabela com pdfplumber
│       ├── santander_fatura.py            # PDF protegido (CPF completo), split GUARANI
│       ├── mp_fatura.py                   # PDF protegido (5 primeiros CPF)
│       ├── nubank_fatura.py               # PDF, texto com regex
│       └── xp_fatura.py                   # CSV, delimitador ;, encoding utf-8-sig
└── templates/
    ├── banks-template.json                # Template open source (sem dados pessoais)
    └── categories-template.json           # Template open source (categorias vazias)

.user/workflows/accountant/                 # WORKFLOW DEFINITION + OPERATIONAL CONFIG
├── accountant.md                            # Top-level workflow
├── gastos/                                  # Gastos step files (.md)
├── investimentos/                           # Investimentos step files (.md) + tmp-processed/ scratch
├── config/banks.json                        # Bancos configurados + standard_filename
├── config/passwords.json                    # CPF e regras de derivação de senha
├── config/investment-sources.json           # Brokers/exchanges + status
├── config/suppliers.json                    # Supplier alias index
├── config/tags.json                         # Tags accepted/rejected
├── config/lot-splits.yaml                   # Lot-split overrides
└── data/assets.csv                          # Registro master de ativos

3-resources/tools/finance/                              # PIPELINE (code + data + docs co-located)
├── dashboard.html
├── scripts/
│   ├── dashboard/                           # Dashboard JS + CSS
│   ├── accountant/{shared,gastos,investimentos}/  # Python scripts
│   └── migrations/                          # One-shot migration scripts
├── config/
│   └── categories.json                      # Shared between accountant + dashboard
├── raw/                                     # RAW DATA per month
│   └── {YYYY-MM}/
│       ├── expenses/                        # Renamed bank exports (CSV/PDF)
│       └── investment/                      # Broker statements
├── ledgers/                                 # PROCESSED DATA
│   ├── expenses/{YYYY-MM}/                  # Output do normalize.py (per-month)
│   ├── fechamento/                          # Output do categorize.py (consumed by dashboard)
│   │   ├── months.json
│   │   └── {YYYY-MM}/transactions.csv
│   └── investimentos/                       # Consolidated investment ledgers
└── docs/                                    # accountant.md, expenses-data.md, financial-dashboard.md, architecture.md

2-areas/finance/                            # PERSONAL FINANCE RECORDS (vault content)
├── finance.md
├── finance-tasks.md
└── pagamentos-recorrentes.md                # Agenda de pagamentos fixos mensais

4-archives/finance/monthly-closings/         # Historical fechamento .md files (no longer produced)
```

### Por que essa separação?

| Local | Razão |
|---|---|
| `.user/workflows/accountant/` | Workflow definition + operational config (credentials, asset registry) — never open-sourced |
| `3-resources/tools/finance/` | Self-contained pipeline (scripts + data + docs co-located) |
| `2-areas/finance/` | Personal finance records consumed by the `home` dashboard (`3-resources/tools/obsidian-dashboards/home.md`) |
| `4-archives/finance/monthly-closings/` | Legacy fechamento reports (dashboard supersedes) |

---

## Bancos suportados

### Inventário

| Banco | bank_id | Tipo | Formato | standard_filename | Senha |
|---|---|---|---|---|---|
| Bradesco | `bradesco_extrato` | Extrato CC | CSV (`;`) | `extrato-bradesco.csv` | Não |
| Santander | `santander_extrato` | Extrato CC | PDF | `extrato-santander.pdf` | Não |
| Santander | `santander_fatura` | Fatura Visa | PDF | `fatura-santander.pdf` | CPF completo |
| Mercado Pago | `mp_extrato` | Extrato conta | CSV (`;`) | `extrato-mercado-pago.csv` | Não |
| Wise | `wise_extrato` | Extrato multi-moeda | CSV (`,`) | `wise/extrato-wise-{MOEDA}.csv` | Não |
| Mercado Pago | `mp_fatura` | Fatura cartão | PDF | `fatura-mercado-pago.pdf` | 5 primeiros CPF |
| Nubank | `nubank_fatura` | Fatura cartão | PDF | `fatura-nubank.pdf` | Não |
| XP | `xp_fatura` | Fatura cartão | CSV (`;`) | `fatura-xp.csv` | Não |

### Convenção de nomes de arquivos

Padrão: `{tipo}-{banco}.{ext}` — definido no campo `standard_filename` de cada banco em `banks.json`.

O usuário faz upload dos arquivos com o nome original do banco (que varia entre meses). O agente identifica cada arquivo no Passo 1 (pre-flight) e renomeia para o `standard_filename` antes de rodar o `normalize.py`. O script usa `identification.filename_exact` para localizar os arquivos já renomeados.

### Expectativa por banco

| Banco | Extrato esperado | Fatura esperada |
|---|---|---|
| Bradesco | Sim (CSV) | Não — só conta corrente |
| Santander | Sim (PDF) | Sim (PDF, senha) |
| Mercado Pago | Sim (CSV) | Sim (PDF, senha) |
| Wise | Sim (CSV, multi-moeda) | Não |
| Nubank | Não | Sim (PDF) — pode ter 0 transações |
| XP | Não | Sim (CSV) — pode não ter em meses sem uso |

### Formatos CSV dos bancos

| Banco | Delimitador | Data | Decimal | Peculiaridades |
|---|---|---|---|---|
| Bradesco | `;` | `DD/MM/YYYY` | `,` (pt-BR) | BOM UTF-8, primeira linha é info da conta |
| MP Extrato | `;` | `DD-MM-YYYY` | `,` (pt-BR) | Header duplo: linhas 1-3 = resumo (saldo inicial/final), linha 4+ = transações (`RELEASE_DATE;TRANSACTION_TYPE;...`) |
| Wise | `,` | `DD-MM-YYYY` | `.` (intl) | 24 colunas, um arquivo por moeda. Arquivos sem transações têm só header |
| XP Fatura | `;` | `DD/MM/YYYY` | `,` (pt-BR, com `R$` prefix) | BOM UTF-8 (usar `utf-8-sig`). Header: `Data;Estabelecimento;Portador;Valor;Parcela` |

### Como adicionar um novo banco

1. Criar parser em `scripts/parsers/{bank_id}.py` herdando `BaseParser`
2. Implementar `parse(filepath, password) → list[dict]`
3. Definir `bank_id` e `source_type` como atributos de classe
4. Adicionar entrada em `.user/workflows/accountant/config/banks.json` com `id`, `standard_filename`, `identification`, `password_required`
5. O registry (`__init__.py`) descobre o novo parser automaticamente

---

## CSV schema (normalized + categorized)

**Authoritative reference:** [`./data-model.md`](./data-model.md). Do NOT duplicate column tables in this file — the data-model owns them.

Quick orientation only:

- **Normalized CSV** (parser output, 12 columns): identity + amount fields written by every parser. Producer: `normalize.py` via parser registry. Schema: data-model §1.1.
- **Categorized CSV** (categorize.py output, 19 columns total): the 12 normalized columns plus 7 categorized columns. Schema: data-model §1.2.
  - Retained categorized columns: `category`, `match_confidence`, `recurrence`.
  - **NEW columns** (post-redesign): `data_caixa` (immutable cash-flow date), `data_competencia` (analytical attribution date), `supplier_canonical` (normalized supplier name), `tags` (semicolon-separated cross-cutting tokens).
  - **DROPPED:** `subcategory` is no longer a stored column. Cross-cutting slicing is done via `tags` (multi-value); per-trip / per-context labels live in `tags.json` per data-model §4.

The categorized CSV is the contract between `categorize.py` (and the one-shot `backfill.py`) and the dashboard. Path: `3-resources/tools/finance/ledgers/fechamento/{YYYY-MM}/transactions.csv`.

### Classificação de recorrência

O `categorize.py` classifica cada transação como `recorrente` (despesa fixa/mensal) ou `pontual` (one-off). Configuração em `categories.json` → `recurrence_rules`:

| Regra | Prioridade | Descrição |
|---|---|---|
| Categorias excluídas | 1 | `intercontas`, `ignorar`, `a_identificar` → vazio |
| Vendor overrides | 2 | Match por substring na descrição → valor do override |
| Parcelamentos | 3 | Transações com `installment_total >= 2` → `pontual` |
| Category default | 4 | Valor padrão da categoria |

Categorias recorrentes por padrão: moradia, alimentacao, saude, esportes, assinaturas, dev-tools, seguros, receitas.

Categorias pontuais por padrão: festas, viagem, lazer, compras, presentes, casa, tecer, transporte, venda.

Durante a revisão interativa (Passo 5), quando o agente categoriza um novo vendor em uma categoria recorrente, deve perguntar ao usuário se é recorrente ou pontual. Se pontual, adicionar o vendor a `vendor_overrides`.

---

## Config files

### banks.json

Define quais bancos o usuário tem, como identificar seus arquivos (após rename), e qual parser usar.

```json
{
  "banks": [
    {
      "id": "bradesco_extrato",
      "name": "Bradesco — Extrato Conta Corrente",
      "type": "extrato",
      "source_format": "csv",
      "download_hint": "App Bradesco > Extrato > Exportar CSV",
      "parser": "bradesco_extrato",
      "standard_filename": "extrato-bradesco.csv",
      "identification": { "filename_exact": "extrato-bradesco.csv" },
      "password_required": false
    }
  ]
}
```

O campo `identification` é usado pelo `normalize.py` para localizar arquivos após o rename. Suporta:
- `filename_exact` — nome exato (padrão para todos os bancos)
- `filename_startswith` — prefixo (usado por Wise: `extrato-wise-`)
- `subfolder` — subpasta (usado por Wise: `wise/`)

### passwords.json

Armazena o CPF uma única vez. `banks.json` referencia **regras** de derivação:

```json
{
  "cpf": "XXXXXXXXXXX",
  "rules": {
    "cpf_first_5": "Primeiros 5 dígitos do CPF",
    "cpf_full": "CPF completo sem pontuação"
  }
}
```

### categories.json

Definições de categoria + camadas auxiliares (value-based, recurrence, self-transfer, reimbursement). A camada de **vendor → categoria** vive em `suppliers.json` (post-Phase-6 merge — single layer).

```json
{
  "categories": {
    "moradia": { "description": "Despesas fixas de moradia", "movable_hint": "movable" },
    "alimentacao": { "description": "Supermercados, restaurantes, delivery", "movable_hint": "non-movable" }
  },
  "value_based_mappings": [
    { "vendor": "PAGAMENTO DE CONTA ITAÚ UNIBANCO", "amount": 1639.36, "category": "saude", "label": "Plano de saude" }
  ],
  "recurrence_rules": {
    "default_by_category": { "moradia": "recorrente", "compras": "pontual" },
    "installments_override": "pontual",
    "vendor_overrides": { "AFETOS CLINICA": "pontual" }
  },
  "self_transfer_patterns": ["HENRIQUE LEAL TEIXEIRA"],
  "reimbursement_mappings": {
    "CARE PLUS": {"category": "saude", "subcategory": "reembolso"},
    "GUILHERME KENWORTHY": "receitas"
  }
}
```

**Lógica de matching** (em `categorize.py`):
1. Detecta transferências intercontas (mesma data, mesmo valor absoluto, bancos diferentes, sinais opostos)
2. Checa `self_transfer_patterns` → ignora transferências para si mesmo (exceto quando descrição também bate com um reimburser conhecido)
3. Checa `reimbursement_mappings` → marca reembolsos; subcategoria do dict-form vira tag
4. Checa `value_based_mappings` → vendor substring + valor absoluto dentro de margem ±5%
5. Resolve supplier via `suppliers.json` (alias longest-first, first-match-wins) → preenche `supplier_canonical`, `category` (de `default_category`), `tags` (de `default_tags`)
6. Sem match → `a_identificar` com `match_confidence: none`

**Subcategorias.** O conceito legado de "subcategoria" foi substituído por **tags** (multi-valor, semicolon-separated). `default_tags` no supplier carrega tags intrínsecas (ex: `reembolsavel`, `imoveis`, `desapego`). Tags de contexto de viagem (ex: `argentina-feb26`, `paraguai`) NÃO ficam em `default_tags` — são aplicadas por transação durante o mês da viagem.

**Value-based mappings** disambiguam vendors genéricos (ex: "PAGAMENTO DE CONTA ITAÚ UNIBANCO") que correspondem a despesas diferentes dependendo do valor:

| Campo | Descrição |
|---|---|
| `vendor` | Substring match (case-insensitive, accent-sensitive) |
| `amount` | Valor de referência (absoluto) |
| `category` | Categoria destino (string ou `{"category", "subcategory"}` — subcategoria vira tag) |
| `label` | Descrição humana (não usada pelo script) |

**Matching de vendor é case-insensitive mas NÃO é accent-insensitive.** Descrições com acentos (ex: "Cartão", "crédito", "Aplicação") precisam de alias separado no `suppliers.json` com os acentos corretos. `.upper()` preserva acentos: "crédito" → "CRÉDITO" ≠ "CREDITO".

### Wise e double-counting

Transações "WISE BRASIL CORRETORA" no extrato MP são conversões BRL→moeda estrangeira. A despesa real é capturada no extrato Wise (em USD/EUR/etc). O mapeamento WISE BRASIL CORRETORA MUST ser `ignorar` para evitar double-counting. Se o extrato Wise do mês não estiver disponível, o agente deve reclassificar manualmente a transação BRL como a despesa real.

### Categorias conhecidas

moradia, alimentacao, saude, esportes, transporte, festas, viagem, assinaturas, dev-tools, lazer, compras, casa, seguros, tecer, presentes, receitas, intercontas, a_identificar, ignorar, venda.

---

## Scripts Python

### normalize.py

```bash
python normalize.py <data_folder> <config_folder>
```

1. Lê `banks.json` e `passwords.json`
2. Infere range de datas do nome da pasta (ex: `2026-03` → fev 24 a abr 5)
3. Escaneia a pasta do mês e associa arquivos a bancos por `identification`
4. Para cada match, invoca o parser correspondente
5. Filtra transações fora do range de datas (remove parcelas futuras de faturas)
6. Para faturas (`type: fatura`), extrai o "Total a pagar" diretamente do PDF
7. Escreve CSVs normalizados em `{data_folder}/processed/`
8. Escreve `fatura_totals.json` com os totais extraídos

### categorize.py

```bash
python categorize.py <data_folder> <config_folder> [output_folder]
```

1. Lê todos os CSVs de `{data_folder}/processed/`
2. Carrega `categories.json`
3. Classifica cada transação (exact → partial → none)
4. Detecta parcelas via regex (`3/7`, `Parcela 3 de 7`, etc.)
5. Escreve `transactions.csv` em `output_folder` (default: `{data_folder}/categorized/`). O Passo 4 do agente passa `dashboard/data/fechamento/{YYYY-MM}/` como output_folder

### Dependências

```
pdfplumber>=0.11.0    # Extração de tabelas/texto de PDF
pikepdf>=9.0.0        # Decriptação de PDFs protegidos por senha
```

Sem pandas, sem tabula. Apenas standard library + essas duas.

---

## Sistema de parsers

### Arquitetura

Cada parser é uma classe que herda de `BaseParser`:

```python
class BaseParser(ABC):
    bank_id: str = ""         # Deve bater com o id no banks.json
    source_type: str = ""     # "extrato" ou "fatura"

    @abstractmethod
    def parse(self, filepath: Path, password: str | None = None) -> list[dict]:
        ...
```

O registry (`parsers/__init__.py`) descobre parsers automaticamente: importa todos os `.py` no diretório, encontra classes que herdam de `BaseParser` com `bank_id` não-vazio, e registra por bank_id.

### Parsers CSV

Simples — lêem o arquivo com `csv.DictReader`, normalizam datas e decimais, retornam lista de dicts.

**Peculiaridades tratadas:**
- Bradesco: BOM UTF-8, linha de metadados antes do header, encoding variável (tenta utf-8-sig, latin-1, cp1252)
- MP Extrato: Header duplo (linhas 1-3 são resumo com saldo, pula pro header de transações na linha 4 `RELEASE_DATE;TRANSACTION_TYPE;...`)
- Wise: Decimais internacionais (ponto, não vírgula), multi-moeda, arquivos vazios (só header). **Non-BRL files use two-pass parsing:** Pass 1 collects exchange rates from TRANSFER (funding) rows; Pass 2 converts all amounts to BRL using the most recent rate, storing the original foreign amount in `original_amount` and the rate in `exchange_rate`
- XP Fatura: BOM UTF-8 (usar `utf-8-sig`), valores com prefixo `R$`, negação de amounts (positivo no CSV = despesa = negativo no normalizado)

### Parsers PDF

Usam `pdfplumber` para extração de tabela/texto e `pikepdf` para decriptação.

**Estratégia geral:**
1. Se protegido, decriptar com `pikepdf` → salvar temporário → deletar após processar
2. Extrair texto com `page.extract_text()`
3. Parsear linhas com regex
4. Post-processar: split de linhas mescladas, detecção de compras internacionais
5. Deduplicar

**Peculiaridades tratadas:**
- Santander extrato: tabela + texto fallback, colunas Data/Descrição/Docto/Crédito/Débito/Saldo
- Santander fatura:
  - **Linhas mescladas:** pdfplumber junta linhas adjacentes do PDF. O parser detecta padrões `DD/MM` no meio da descrição e separa em duas transações.
  - **Compras internacionais:** Descrição tem valor BRL embutido maior que o amount capturado → usa o embutido como amount real.
  - **GUARANI (Paraguai):** Transações com keyword `GUARANI` têm estrutura `VENDOR GUARANI_AMOUNT GUARANI BRL_AMOUNT IOF_AMOUNT`. O parser detecta "GUARANI" e usa os valores após a keyword (BRL) em vez dos anteriores (moeda estrangeira).
  - **IOF separado:** Linhas `IOF DESPESA NO EXTERIOR` são transações separadas (standalone ou splitadas da compra original).
- MP fatura: PDF protegido com 5 primeiros dígitos CPF, formato texto/tabela
- Nubank: texto semi-estruturado, datas `DD MMM` (meses em português), IOF como linhas separadas

---

## Menu de entrada e roteamento

A partir de 2026-04-26, `accountant.md` apresenta um menu na ativação:

```
Qual fluxo? [1] Gastos / [2] Investimentos / [3] Ambos
```

| Path | Primeiro passo | Descrição |
|------|---------------|-----------|
| `gastos` | `gastos/step-01-preflight.md` | Fluxo de fechamento de gastos (8 passos abaixo) |
| `investimentos` | `investimentos/step-01-preflight.md` | Fluxo de revisão mensal de investimentos (8 passos) |
| `ambos` | `gastos/step-01-preflight.md` → `investimentos/step-01-preflight.md` | Gastos completo (Passos 1-8) e em seguida Investimentos. O encadeamento ocorre no Passo 8 (`gastos/step-08-manifest.md`) que verifica `{PATH}=ambos` e roteia para o preflight de investimentos |

Path variables adicionais introduzidas: `GASTOS_WORKFLOW_DIR` (`{WORKFLOW_DIR}/gastos`), `INV_WORKFLOW_DIR`, `INV_SCRIPTS_DIR` (`3-resources/tools/finance/scripts/accountant/investimentos`), `INV_RAW_DIR` (`3-resources/tools/finance/raw/{MONTH}/investment`), `INV_LEDGER_DIR` (`3-resources/tools/finance/ledgers/investimentos`).

## Fluxo do agente — Gastos (8 passos)

O workflow usa arquitetura micro-file BMAD. Entry point em `.user/workflows/accountant/accountant.md`, passos individuais em `.user/workflows/accountant/step-{NN}-{id}.md`.

| Passo | Arquivo | Objetivo | STOP? |
|---|---|---|---|
| 1 | `step-01-preflight.md` | Identifica arquivos, mapeia a bancos, renomeia para standard_filename | Sim |
| 2 | `step-02-normalize.md` | Executa normalize.py | Não |
| 3 | `step-03-validate.md` | Valida CSVs normalizados (colunas, datas, amounts) | Sim |
| 4 | `step-04-categorize.md` | Executa categorize.py | Não |
| 5 | `step-05-review.md` | Two-pass queue: Pass 1 (cat/supplier/tag unknowns) + cash + Pass 2 (boundary prompts) | Sim |
| 6 | `step-06-report.md` | Gera relatório markdown do fechamento | Sim |
| 7 | `step-07-recurring.md` | Atualiza pagamentos-recorrentes com totais de faturas (skip se retroativo) | Sim |
| 8 | `step-08-manifest.md` | Adiciona mês ao months.json do dashboard | Não (done) |

### Detalhes por passo

**Passo 1 — Pre-flight:** Lê `banks.json`, escaneia pasta do mês, identifica arquivos (nome, headers CSV, heurísticas PDF), apresenta mapeamento, pede atribuição manual para não identificados, renomeia para `standard_filename`.

**Passo 2 — Normalizar:** Executa `normalize.py`, reporta transações e fatura totals.

**Passo 3 — Validação:** Lê CSVs normalizados, valida 12 colunas, datas no range (±5 dias), amounts numéricos, row count razoável.

**Passo 4 — Categorizar:** Executa `categorize.py` (que importa de `lib/`). O script emite o CSV no novo schema (com `data_caixa`, `data_competencia`, `supplier_canonical`, `tags`) e imprime três blocos estruturados em stdout — `UNKNOWN CATEGORIES`, `UNKNOWN SUPPLIERS`, `UNKNOWN TAGS`. O agente reporta os três counts em PT-BR e prima a fila Pass 1 do step-05.

**Passo 5 — Two-pass review queue:** Workflow de duas passadas (spec T5):
- **Pass 1 — Resolução de desconhecidos.** Carrega `suppliers.json`, `tags.json` e `categories.json`; chama `lib.queue.build_pass_1_queue` que agrupa itens por `item_type` na ordem `category` → `supplier` → `tag`. O agente processa cada batch (5–7 itens), persistindo decisões nas três config dictionaries via `lib.queue.apply_pass_1_resolution`. Pass 1 fecha quando as três filas zeram.
- **Gastos em dinheiro:** entre Pass 1 e Pass 2, o agente captura despesas em dinheiro (linhas com `bank: manual`, `source_type: dinheiro`, `supplier_canonical: Cash`).
- **Pass 2 — Limites de mês.** Chama `lib.queue.build_pass_2_queue` que filtra apenas transações com `is_boundary_day(data_caixa) AND supplier.movable == true AND source_type != 'fatura'`. **Pré-condição (data-model §6 invariant 8):** Pass 2 só pode ser construído depois que Pass 1 fechou — `build_pass_2_queue` levanta `QueueOrderingError` se houver categoria/fornecedor não resolvido. O default em cada prompt é `keep` (data_competencia = data_caixa, skip-default Q13a). Apenas `data_competencia` é mutada — `data_caixa` permanece imutável.

**Passo 6 — Relatório:** Lê o CSV totalmente categorizado (read-only) e gera `{YYYY-MM}-fechamento-mensal.md` com eixo padrão = caixa (`data_caixa`). Aplica reimbursement netting (T4) nos resumos por categoria e fornecedor, e o rollup `Outros` (T6) em tempo de render via `lib.suppliers.rollup_outros` (janela trailing 92 dias, threshold R$200) — `"Outros"` NUNCA é gravado no CSV. Tags são parseadas via `lib.tags.parse_tag_column` (semicolon-separated) e agregadas em uma seção própria (uma transação com 2 tags conta para ambas).

**Passo 7 — Pagamentos recorrentes:** Skip se retroativo. Lê `fatura_totals.json`, calcula mês de pagamento (N+1 dia 10), atualiza `pagamentos-recorrentes.md`.

**Passo 8 — Manifesto:** Adiciona mês a `months.json`, ordena cronologicamente.

---

## lib/ — shared primitives

All five modules live under `3-resources/tools/finance/scripts/accountant/shared/lib/` and are MANDATORY shared infrastructure (spec T8). Both `categorize.py` (Phase 2) and the one-shot `backfill.py` (Phase 5) MUST import from these modules — duplication is forbidden. Functions are pure where possible (input → output, no I/O); side effects (file writes, prompts) live in callers. Full function signatures and contracts: [`./data-model.md`](./data-model.md) §5.

| Module | Purpose |
|--------|---------|
| `lib/accrual.py` | Computes `data_caixa` (immutable cash-flow date) and `data_competencia` (analytical attribution date) for a transaction given context. Encodes the four canonical scenarios from the spec behavior matrix (CC single, CC installment collapsed to original purchase month, non-CC skip-default, reimbursement caixa-immutable). For CC fatura rows, `invoice_payment_date` is REQUIRED — raises if absent. |
| `lib/suppliers.py` | Two concerns: (1) DETECTION — alias-based `supplier_canonical` resolution from `suppliers.json` (longest-first, first-match-wins, case-insensitive, accent-sensitive); (2) ROLLUP — render-time `rollup_outros` helper that buckets low-volume suppliers into `Outros` over a trailing 3-month window (92-day fixed window, R$200 default threshold). The rollup is presentation-only — the storage layer NEVER holds `"Outros"` (data-model §6 invariant 6). |
| `lib/tags.py` | Tag governance per spec T7: `accept_tag`, `merge_tag`, `reject_tag`, `should_resurface` (re-surface threshold = `return_count` non-zero multiple of 3). Token validation via `is_valid_token` (regex `^[a-z0-9][a-z0-9-]*$` — lowercase kebab-case ASCII, no `;`). Provides `parse_tag_column` and `serialize_tag_column` for the semicolon-separated CSV column representation (data-model §1.3). |
| `lib/boundary.py` | Boundary-day detection per spec T5: `is_boundary_day(d)` returns true iff `d.day ∈ [1..5] ∪ [last_day_of_month-4 .. last_day_of_month]` (calendar.monthrange-aware). `needs_boundary_prompt(tx, supplier_movable, data_caixa)` returns true iff boundary-day AND `supplier.movable == true` AND `source_type != 'fatura'` (CC excluded — caixa already pinned to invoice payment date). |
| `lib/queue.py` | Two-pass review queue model: `build_pass_1_queue` groups unknowns by `item_type` (`category`, `supplier`, `tag`) for batched clearance (T2 ≤15s/item target). `build_pass_2_queue` is built ONLY after Pass 1 closes — raises `QueueOrderingError` if any transaction lacks resolved category/supplier. `apply_pass_1_resolution` and `apply_pass_2_resolution` are pure functions returning new transaction lists (never mutate inputs). `data_caixa` is NEVER mutated by Pass 2. |

## Config dictionaries

Three JSON files under `.user/workflows/accountant/config/` drive categorization, supplier identity, and tag governance. Schemas authoritative in [`./data-model.md`](./data-model.md) §2–§4.

| File | Purpose |
|------|---------|
| `config/categories.json` | Category taxonomy (display name + `description` + `movable_hint`) plus auxiliary layers: `value_based_mappings`, `recurrence_rules`, `self_transfer_patterns`, `reimbursement_mappings`. Per spec T1, each category carries a `movable_hint` (`movable` / `non-movable` / `mixed`) that drives the DEFAULT `movable` flag for new suppliers under that category and the Pass 2 boundary-prompt behavior (`mixed` always surfaces; `movable` and `non-movable` set defaults silently). `vendor_mappings` was removed in the Phase 6 single-layer merge — see Decision D20. Schema: expenses-data.md §2. |
| `config/suppliers.json` | Single source of truth for the supplier dimension (post-Phase-6 merge). Each entry: `canonical` (display name), `aliases` (substring patterns matched against `description.upper()`), `movable` (boolean — overrides category hint), `default_category` (REQUIRED — written to category column on a hit), `default_tags` (optional — auto-applied tags, must be vendor-intrinsic, NOT trip-context). Schema: expenses-data.md §3. |
| `config/tags.json` | NEW cross-cutting dictionary (spec T7). Two sections: `tags` (accepted tokens with `label`, `added`, `notes`) and `rejected` (append-only log with `token`, `date`, `reason`, `return_count`). Tokens MUST match `^[a-z0-9][a-z0-9-]*$`. Re-surface threshold = `return_count` non-zero multiple of 3. Schema: data-model §4. |

## Decisões de design

| # | Decisão | Razão |
|---|---|---|
| D1 | Dois scripts + checkpoint | Bancos mudam formato; checkpoint pega antes de corromper categorização |
| D2 | Script orquestrador + sub-parsers | Cada banco tem formato diferente; parsers são independentes e testáveis |
| D3 | Categories como JSON, não markdown | Script precisa ler; JSON é robusto para parsing programático |
| D4 | Senhas via regras, não literais | `banks.json` pode ser open source; CPF fica só no `passwords.json` |
| D5 | standard_filename + rename no pre-flight | Nomes de download variam entre meses; rename garante contrato estável com o script |
| D6 | Separação open source | Templates tracked, dados pessoais gitignored |
| D7 | Wise: só processa com transações | 3 de 4 moedas geralmente estão vazias |
| D8 | Faturas do mês N na pasta do mês N | Fatura com vencimento N+1 = consumo do mês N |
| D9 | Checklist de bancos no pre-flight | Garante que nenhum extrato/fatura foi esquecido |
| D10 | Parcelas no CSV categorizado | Sem isso o agente não sabe quais transações são parceladas |
| D11 | Splits só no relatório | Info de split não existe nos extratos — é regra de negócio |
| D12 | ~~Subcategorias no CSV~~ → tags multi-valor | Subcategoria substituída por `tags` (semicolon-separated, cross-cutting, multi-valor). Coluna `subcategory` removida do schema. Slicing por trip/contexto vive em `tags.json` |
| D13 | Passo 7 skip retroativo | Pagamentos recorrentes só fazem sentido para o mês corrente |
| D14 | Pipeline em `3-resources/tools/finance/` | Self-contained — scripts + data + docs co-located para minimizar drift entre código e estrutura |
| D15 | `lib/` shared primitives mandate (T8) | `categorize.py` e `backfill.py` (one-shot Phase 5) DEVEM importar dos mesmos módulos `lib/`. Drift entre os dois consumidores é proibido — primitive-sharing impede divergência e regressões silenciosas |
| D16 | Two-pass review queue (T5) | Pass 1 (cat/supplier/tag unknowns batched by item type) DEVE fechar antes de Pass 2 (boundary prompts). Boundary depende de `supplier.movable` resolvido em Pass 1 — `build_pass_2_queue` levanta `QueueOrderingError` se a ordem for violada, tornando misses silenciosos impossíveis por construção |
| D17 | Render-time supplier rollup (T6) | `Outros` é uma camada de apresentação computada via `lib.suppliers.rollup_outros` (janela trailing 92 dias, threshold R$200). NUNCA gravado no CSV — supplier_canonical na storage layer só carrega valores reais ou string vazia |
| D18 | Tag governance accept/merge/reject + 3-return re-surface (T7) | Cada token novo passa por critério de duas perguntas (slice análise? merge?); rejeições logadas em `rejected` com `return_count`. Token re-aparece quando `return_count` cruza múltiplo não-zero de 3, evitando drift sem perder retries legítimos |
| D19 | Schema split: `data_caixa` (imutável) + `data_competencia` (analítico) | Spec § "Invariant" + Q12. Caixa é verdade de fluxo de caixa (CC fatura row → invoice payment date, per-INVOICE não per-purchase; reembolso → received date, NUNCA move). Competência colapsa para o mês de compra original em parcelas de CC. Código que computa competência NUNCA muta caixa — invariante reforçado por contratos de função em `lib/accrual.py` |
| D20 | Single-layer supplier model (Phase 6 merge) | `vendor_mappings` foi removido de `categories.json`; sua função (vendor → categoria) foi absorvida por `suppliers.json` via `default_category`. Tags intrínsecas (ex: `reembolsavel`, `imoveis`) ganham campo `default_tags` no supplier. Tags de viagem permanecem por-transação. Single source elimina ambiguidade do `match_confidence` e remove edição em dois arquivos para mudar attribution de um vendor |

---

## Open source

O workflow foi desenhado para ser distribuível como parte de um Second Brain template.

**O que é template (tracked):** scripts, parsers, `*-template.json`, agent, design doc.

**O que é pessoal (gitignored):** `banks.json`, `passwords.json`, `categories.json`, pastas mensais `{YYYY-MM}/`.

Para usar: copiar `*-template.json` para `banks.json` e `categories.json` (sem o sufixo `-template`), preencher com dados pessoais, e rodar.

---

## Troubleshooting

| Problema | Causa provável | Solução |
|---|---|---|
| Parser não encontra arquivo | Arquivo não foi renomeado para standard_filename | Verificar Passo 1 (pre-flight rename) |
| PDF protegido não abre | CPF errado em `passwords.json` | Verificar CPF sem pontuação |
| Transações duplicadas | Parser de texto + tabela extraíram a mesma linha | Verificar deduplicação no parser |
| Datas fora do range | Parcelas futuras ou transações de borda | Normal para parcelas; agente deve avisar |
| Encoding errado (CSV) | BOM UTF-8 ou latin-1 | Usar `utf-8-sig` para BOM; parser tenta múltiplos encodings |
| Linhas juntadas (Santander fatura) | pdfplumber não separou linhas do PDF | Ajustar regex no parser |
| Valor em GUARANI parseado como BRL | Transação internacional sem keyword GUARANI | Verificar `_extract_transaction_a` no santander_fatura parser |
| XP fatura 0 transações | BOM no CSV, header key = `\ufeffData` | Usar encoding `utf-8-sig` no parser |
