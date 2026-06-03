# Dashboard Financeiro

Dashboard HTML interativo para visualização e análise de gastos mensais. Arquivo único, self-contained, sem build step.

## Arquitetura

O dashboard é **totalmente dinâmico** — alimentado por CSVs gerados pelo workflow de fechamento financeiro (`.user/finance/bookkeeper/ledgers/fechamento/{YYYY-MM}/transactions.csv`).

### Estrutura de arquivos

```
finance system (post-p1-11 layout):
3-resources/tools/sb-os/finance/dashboard/    ← HTML/JS/CSS shipped via sb-os
.user/finance/dashboard.html                  ← entry HTML (rendered pelo install.py; destino configurável — finance_dashboard_html_path no sb-os.json)
.user/finance/bookkeeper/{ledgers,config}/    ← personal data
├── dashboard/                                  (logical view — files below ship from sb-os/finance/dashboard/)
│       ├── styles.css                     ← design system compartilhado
│       ├── shared.js                      ← utilitários, componentes, privacidade
│       ├── expenses.js                    ← lógica page-specific (abas mensais, evolução, filtros)
│       ├── inv-data.js                    ← data layer de investimentos (portfolio.json, snapshots)
│       ├── inv-carteira.js                ← view Carteira (alocações, TIR, cut date, indicadores)
│       ├── inv-bolsa.js                   ← view Bolsa (posições, variações, setor)
│       ├── inv-balcao.js                  ← view Balcão (RF + Fundos)
│       ├── inv-crypto.js                  ← view Crypto
│       ├── inv-proventos.js               ← view Proventos
│       ├── inv-historico.js               ← view Histórico (lê CSVs via PapaParse)
│       └── investments.js                 ← router thin de investimentos
├── ledgers/
│   ├── fechamento/                        ← CSVs categorizados mensais + months.json
│   └── investimentos/                     ← portfolio.json + snapshots.json + ledgers CSV
└── config/
    └── categories.json                    ← shared with bookkeeper (reimbursement_mappings)
```

- `shared.js` define globals usados por qualquer dashboard: constantes (cores, bancos), formatação, multi-select, collapsible, privacidade, estado global (`allData`, `charts`).
- `expenses.js` contém toda a lógica específica do dashboard de gastos: carregamento de dados, renderização de abas, filtros, paginação, evolução.
- `inv-data.js` é o data layer do dashboard de investimentos: carrega `portfolio.json` e `snapshots.json`, expõe `invLoadPortfolio()`, `invLoadSnapshots()`, `invGetPortfolio()`, `invGetSnapshots()`, `invGetCurrentSnapshot()`, `invGetLoadError()`, `invGetLiveCutDate()`. Renderizador puro — sem parsing de CSV, sem chamadas a APIs. `invLiveCutDate` é cacheado na primeira carga de `'current'` para que o label `Atual (DD/MM/YYYY)` no dropdown permaneça estável quando o usuário seleciona um snapshot histórico — caso contrário o label refletiria o `meta.cut_date` do portfolio carregado e mudaria a cada troca.
- `inv-carteira.js` renderiza a view Carteira: cards resumo (valor total, custo, P&L, TIR, posições — `count = positions.length` para incluir RF/funds que sempre carregam `quantity=0`), três donuts de alocação lado a lado — **por classe**, **por instituição** e **por moeda** (R$ / US$ / Crypto, tudo convertido em BRL — Crypto é separada de R$ porque é classe de ativo distinta apesar do `portfolio.json` cotar cripto em BRL nativo; bucket por position: `asset_class === 'crypto'` → Crypto, senão `currency === 'USD'` → US$ usando `current_value_brl`, senão R$ usando `current_value_brl ?? current_value`. Computado em JS no `invCurrencyAllocationDataset` porque `summary.allocation_by_currency` do calculate.py só conhece BRL/USD e não isola cripto). Cada donut tem (a) legenda em branco via `generateLabels` — `fontColor: '#ffffff'` é forçado por-item porque o `labels.color` default é ignorado quando `generateLabels` retorna items custom no Chart.js v4 — e (b) datalabels externos via `chartjs-plugin-datalabels` com `anchor: 'end'`, `align: 'end'`, offset 6px mostrando valor compacto em BRL — `R$ Xk` milhares, `R$ X,Xm` milhões, `R$ X` < mil — ao redor de TODAS as fatias (sem threshold de % — fatias pequenas como cripto sub-5% precisam aparecer); `layout.padding` 28/32px reserva espaço externo para os labels não clipparem nas bordas; canvas em 300px de altura; o plugin é registrado por-chart via `plugins: [ChartDataLabels]` no construtor para não vazar nas barras das outras views. Grid `repeat(auto-fit,minmax(280px,1fr))` mantém os 3 lado a lado em desktop e empilha em telas estreitas. As antigas tabelas "Posições por instituição" e "Alocação por moeda" foram removidas — os donuts são suficientes. Restantes: indicadores de mercado, seletor de cut date (dropdown populado via `snapshots.json`). Indicadores de mercado: cada card lê `value` + `change_1d` (ratio fracionário, ex.: `-0.005` = `-0,50%`); valor é formatado por chave (`IBOVESPA` inteiro com separador de milhar, `SP500` 2 decimais, `USD_BRL` 4 decimais, `BTC_BRL` prefixo `R$` inteiro), change é colorido verde/vermelho.
- `inv-bolsa.js` renderiza a view Bolsa (filtra `valuation_method === 'price'` — listed equities, ETFs, FIIs, BDRs, opções, direitos de subscrição):
  - **Filtro de corretora** (topo esquerdo): dropdown com `Todas as corretoras` + uma opção por `broker` distinto presente nas posições. Aplica a TUDO abaixo — cards resumo, tabela de posições e resumo por setor. Estado do filtro é mantido em módulo (`invBolsaBrokerFilter`) e re-aplicado a cada render (inclui trocas de snapshot).
  - **Toggle de moeda da tabela** (topo direito): `Original (USD/BRL)` (default) vs `Tudo em BRL`. Afeta APENAS as tabelas (posições e resumo por setor); cards de resumo permanecem sempre em BRL porque agregam entre moedas — somar USD com BRL sem normalizar não tem significado. Em `Original`, posições Avenue renderizam `US$` e B3 renderizam `R$`. Em `Tudo em BRL`, todos os valores de Valor / Custo / P&L / Proventos usam `*_brl` e renderizam `R$`. `Preço` e `PM` sempre ficam na moeda nativa (preço unitário — USD para Avenue mesmo no modo BRL, já que é assim que o broker cota). Ordenação da tabela respeita o modo — ordenar por Valor no modo BRL ordena por `current_value_brl`. Estado em `invBolsaCurrencyView`.
  - **Cards resumo** (valor, custo, P&L, proventos, tickers): agregam em BRL a partir de `current_value`/`cost_basis`/`pnl_absolute`/`total_dividends` das posições filtradas.
  - **Tabela de posições** (colapsável, aberta por default): qty / preço / PM / valor / P&L / retorno % / proventos / YoC LT / YoC TTM / 1ª compra + variações 1d/30d/90d/180d/365d/YTD (via `price_changes`) + indicador de fonte (dot verde api, cinza snapshot, âmbar snapshot >60d, vermelho missing). Colunas sortáveis — default `current_value` desc. YoC (Yield on Cost) é computado em `calculate.py` a partir de `total_dividends / cost_basis` (LT = lifetime) e `total_dividends_ttm / cost_basis` (TTM = trailing 12 months). Funciona sem preços ao vivo — depende apenas dos ledgers `orders.csv` e `proventos.csv`.
  - **Resumo por setor** (colapsável, aberto por default): renderizado DEPOIS da tabela de posições. Agrega valor / % carteira bolsa / P&L por `sector`.
  - **Formatação de moeda por posição**: colunas monetárias (Preço, PM, Valor, P&L, Proventos) usam `p.currency`. Posições com `currency: "USD"` (Avenue) renderizam como `US$ 1.135,43`; posições `BRL` usam `R$`. Cards resumo e resumo por setor continuam em BRL (agregados).
  - **Formatação de quantidade**: posições com `type ∈ {acao, opcao, direito_subscricao, bdr}` E `currency: BRL` são renderizadas como inteiros (`Math.round`) — B3 não permite frações desses tipos. Demais (ETFs Avenue, fundos, crypto) usam até 4 casas decimais com trailing zeros removidos. Esta é uma correção de display; o dado em `portfolio.json` pode carregar ruído decimal de razões de eventos corporativos (ex.: AMOB3 34.000109 da cisão VAMO3→AMOB3 ratio 1.151363666).
  - **Estado de colapso** é mantido em módulo (`invBolsaSectionsOpen`) — a preferência do usuário sobrevive re-renders da mesma sessão.
- `inv-balcao.js` renderiza a view Balcão (cobre `valuation_method === 'balcao'` — RF tradicional + todos os fundos, incluindo FIRF DI). Consome o breakdown per-operação que `position_calculator.py` agrega do balcão ledger: `aplicado_total`, `juros_amort_total`, `resgates_total`, `impostos_total`, `net_flow` (signed). `pnl_absolute = current_value + net_flow` (identidade algébrica de current_value − aplicado + juros_amort + resgates − impostos); quando não há snapshot, `pnl_absolute = null` e a posição cai no bucket "Sem valoração". Metadados de RF (`issuer`, `indexer`, `rate`, `indexer_pct`, `application_date`, `maturity_date`) vêm de `assets.csv` via `calculate.py`. TIR per-asset é calculada via XIRR sobre os cash flows do balcão (`irr_calculator.compute_xirr`):
  - **Filter bar**: dropdown único de instituição (todas + uma por broker). A separação entre Renda Fixa e Fundos não é filtro — são sessões distintas (ver abaixo). Estado em módulo (`invBalcaoBrokerFilter`).
  - **Cards resumo** (Balcão = RF + Fundos consolidados): Valor Balcão, Aplicado, P&L (com cor + retorno %), contador `valoradas / total` com badge "X sem valoração".
  - **Sessão "Renda Fixa"** (colapsável, aberta por default): tabela com Produto, Tipo (`INV_BALCAO_TYPE_LABELS`), Indexador (`invBalcaoFormatIndexer` → `100% CDI`, `IPCA + 3,5%`, `PRÉ 14,35%`), Aplicação, Vencimento, Instituição, **Aplicado**, **Juros + Amortiz.**, Valor, P&L, Retorno %, **TIR**, Valoração. Colunas sortáveis — default `current_value` desc. Aplicação e Vencimento vêm de `assets.csv` via passthrough no `calculate.py`. Logo abaixo: **Cronograma de vencimentos** (bar chart `inv-bar-rf-maturity` registrado no `charts` global) e **Resumo por tipo** (agrega valor / % RF / P&L por `type`).
  - **Sessão "Fundos"** (colapsável, aberta por default): tabela com Fundo, Tipo, Instituição, Aplicado, Resgates, Valor, P&L, Retorno %, TIR, Valoração — sem Indexador/Vencimento (cotas abertas não têm). Logo abaixo: Resumo por tipo (FIM, FIRF, FIA…). Sort state é compartilhado com a tabela RF; `invBalcaoSortRows` ignora o sort silenciosamente quando a coluna ativa não existe na tabela atual.
  - **Sem valoração** (colapsável, fechado por default): bucket compartilhado RF + Fundos, agrupado por broker, mostra contagem + aplicado. Inclui hint para importar extrato mensal.
  - Posições com `price_source: 'missing'` são EXCLUÍDAS das sessões RF/Fundos e dos cards resumo — só aparecem no bucket "Sem valoração". Garante que aplicado/valor/P&L refletem capital efetivamente valorado.
  - **Estado de colapso** em módulo (`invBalcaoSectionsOpen`): `{ rf, fundos, missing }` — preferência sobrevive re-renders da mesma sessão.
- `inv-crypto.js` renderiza a view Crypto (filtra `valuation_method === 'crypto'`). Preços de cripto são denominados em BRL no `portfolio.json` (CoinGecko cota direto em BRL), então a view não tem toggle de moeda — tudo BRL nativo. **Posições crypto são divididas por (ticker, exchange)** — o mesmo ativo (ex. BTC) mantido em duas exchanges aparece como duas linhas distintas, uma por broker. `position_calculator.py` aplica normalização binária no exchange (`bipa` permanece `bipa`; `binance`, `mb` e qualquer outro valor mapeiam para `mercado_bitcoin`) e usa chave composta `f"{ticker}@{exchange}"` no dict interno. `Position.id` continua sendo o ticker bruto, então `calculate.py` dedupa por id antes de chamar o `price_fetcher` (uma cotação por ticker, aplicada a todas as posições com aquele id). `allocation_by_broker` recebe contribuição independente de cada par (ticker, exchange):
  - **Cards resumo**: Valor cripto, Aplicado, P&L (com cor + retorno %), BTC dominance (`current_value` agregado de positions com `id === 'BTC'` ÷ valor total cripto, em %).
  - **Tabela de posições**: Ativo (com indicador de fonte: dot verde api / cinza snapshot / âmbar snapshot >60d / vermelho missing — via `invPriceSourceDot`), Exchange (label PT-BR via `INV_CRYPTO_BROKER_LABELS`), Qtd (até 8 decimais, trim trailing zeros — cripto é sempre fracionária), Preço, PM, Aplicado, Valor, P&L (com cor), Retorno %, Cotação (`price_date`). Colunas sortáveis — default `current_value` desc.
  - Estado de ordenação em módulo (`invCryptoSortState`).
- `inv-proventos.js` renderiza a view Proventos. Consome `portfolio.income` (`monthly_totals: [{month, total, total_brl, by_type, by_type_brl}]` e `by_ticker: [{id, total, total_brl, currency}]`). Os campos `*_brl` são pré-computados em `calculate.py` usando o câmbio médio ponderado **do ticker no momento do dividendo** (via `fx_engine.process_provento`, conforme PRD §"Dividendos USD") — NÃO o câmbio spot. A view prefere `*_brl` quando presente; faz fallback para conversão spot apenas em snapshots legados sem esses campos:
  - **Cards resumo**: total recebido lifetime (soma de `by_ticker.total_brl`), últimos 12 meses (cauda de `monthly_totals` somando `total_brl`, com média/mês), número de ativos pagadores, melhor mês (compara `total_brl` para ranking cross-currency correto, label `MM/YYYY`).
  - **Stacked bar mensal por tipo** (Chart.js `inv-bar-prov-monthly`): uma série por tipo (`dividendo`, `jcp`, `juros`, `rendimento`, `fracao`, `bonificacao_dinheiro`), cores fixas via `INV_PROV_TYPE_COLORS`, ordem prioritária. Valores vêm de `by_type_brl`. Eixo Y formatado como BRL.
  - **Resumo por tipo** (colapsável, aberto): agrega `by_type_brl` de todos os meses em `monthly_totals`, com swatch de cor + label PT-BR + total + % do total. Ordenado por valor desc.
  - **Por ativo** (colapsável, aberto): tabela sortável com Ativo (nome resolvido via lookup em `positions[id]`, fallback para id), Classe (label PT-BR via `INV_PROV_CLASS_LABELS`), Instituição (label via `INV_PROV_BROKER_LABELS`), Total em BRL (vem direto de `total_brl` — FX ticker-ponderado; hint `(US$ X)` ao lado para tickers `currency='USD'`). Tickers sem position correspondente (RF redimida fora do recorte ativo, etc.) aparecem com `—` em Classe/Instituição mas com seu valor preservado. Default sort: `total_brl` desc.
  - Estado de ordenação em módulo (`invProvSortState`).
- `inv-historico.js` renderiza a view Histórico — **única view que bypassa `portfolio.json`**. Lê os 4 ledgers brutos (`orders.csv`, `proventos.csv`, `balcao.csv`, `crypto.csv`) via PapaParse (já carregado para o dashboard de despesas), normaliza linhas em uma estrutura unificada `{ledger, date, broker, operation, asset, asset_class, quantity, currency, value_native, detail, source}`, cacheia em módulo (`invHistTxs`) na primeira render. Justificativa: transações brutas não são agregadas em `portfolio.json` (que carrega só posições atuais e agregados de income); forçá-las em portfolio.json incharia o output para todas as outras views. CSVs ficam frescos via bookkeeper workflow downstream do `update_ledgers.py`.
  - **Filtros**: ledger (orders/proventos/balcao/crypto/all), instituição (todas + uma por broker), data de/até (date inputs), busca textual (asset/operação/broker/source). Estado em módulo (`invHistFilters`).
  - **Tabela paginada** (50/página): Data, Ledger (label PT-BR), Operação, Ativo, Instituição, Qtd, Valor (sinal — verde positivo, vermelho negativo, prefixo `R$` ou `US$`), Detalhe, Fonte. Sortable por qualquer coluna; default `date` desc. Pager fixo no rodapé (Anterior/Próxima + contador).
  - **Sinal de Valor**: orders compra → negativo (saída de caixa); orders venda → positivo. Proventos sempre positivos. Balcão `amount` já vem signed. Crypto: BRL→cripto = negativo; cripto→BRL = positivo.
  - **Search input**: re-render só dispara em Enter ou blur (não em cada keystroke) — evita perder foco do input.
  - Cache do array de transações invalida apenas em hard reload do dashboard (não há refresh button nesta view; CSVs atualizam offline).
- `investments.js` é o router: registra tabs (Carteira, Bolsa, Balcão, Crypto, Proventos, Histórico), delega ao view module correspondente. Cobre todas as 6 views agora — não há mais stubs. Tabs re-renderizam sempre ao trocar (garante que snapshot switches propagam para todas as views).
- Scripts carregam via `<script>` tags em ordem (shared primeiro, page-specific depois). Sem módulos, sem build step.

### Classificação de posições

Cada position no `portfolio.json` carrega 3 campos que governam display e cálculo:

| Campo | Origem | Uso |
|-------|--------|-----|
| `type` | `assets.csv` (column `type`) | Produto granular: `acao`, `etf`, `fii`, `bdr`, `opcao`, `direito_subscricao`, `cra`, `deb`, `lca`, `lci`, `cdb`, `tesouro`, `lc`, `cri`, `rf`, `fia_br`, `fia_usa`, `fim_br`, `firf_br`, `fidc`, `coe`, `di`, `crypto` |
| `valuation_method` | derivado do `type` em `position_calculator._resolve_valuation_method` | Qual VIEW renderiza a posição: `'price'` (Bolsa), `'balcao'` (Balcão), `'crypto'` (Crypto) |
| `asset_class` | `assets.csv` (column `asset_class`) | Donut "por classe" da Carteira: `'variable_income'`, `'fixed_income'`, `'crypto'` |

**Decoupling display vs classificação:** um fundo não-DI (ex.: FIM, FIA) tem `valuation_method='balcao'` (renderiza no Balcão, sessão Fundos) AND `asset_class='variable_income'` (donut da Carteira mostra na fatia RV). Já um fundo DI (`type='di'`) tem `valuation_method='balcao'` (também no Balcão) MAS `asset_class='fixed_income'` (donut mostra na fatia RF). Regra: **fundo DI = RF na carteira; demais fundos = RV na carteira; mas todos renderizam em Balcão**.

Mapeamento `type` → `valuation_method`:

| `valuation_method` | `type` membros |
|--------------------|----------------|
| `price` | `acao`, `fii`, `bdr`, `opcao`, `etf`, `stock_us`, `etf_us`, `direito_subscricao` |
| `balcao` | `cra`, `deb`, `lca`, `lci`, `cdb`, `cdb_mp`, `tesouro`, `lc`, `cri`, `rf`, `fia_br`, `fia_usa`, `fim_br`, `firf_br`, `fidc`, `coe`, `di` |
| `crypto` | `crypto` |

Mapeamento `type` → `asset_class` (mantido em `assets.csv`; classifier `_infer_class` é fallback para entries fora do CSV):

| `asset_class` | `type` membros |
|---------------|----------------|
| `variable_income` | listed types + non-DI funds (`fia_br`, `fia_usa`, `fim_br`, `firf_br`, `fidc`, `coe`) |
| `fixed_income` | RF tradicional (`cra`, `deb`, `lca`, `lci`, `cdb`, `tesouro`, `lc`, `cri`, `rf`) + DI puro (`di`) |
| `crypto` | `crypto` |

Identificação "FIRF DI" no cadastro: usa `type='di'` exclusivamente. Funds com `type='firf_br'` representam FIRF não-DI (crédito privado, longo prazo, etc.) e classificam como `variable_income`. A label "FIRF DI" no Balcão (sessão Fundos, coluna Tipo) é renderizada APENAS para `type='di'`; `firf_br` renderiza como "FIRF" sem o sufixo.

A sessão "Fundos" dentro do Balcão é separada da sessão "Renda Fixa" via `_INV_BALCAO_FUND_TYPES` em `inv-balcao.js`: `{fia_br, fia_usa, fim_br, firf_br, fidc, coe, di}`. Tudo fora desse set é RF tradicional. O split é por `type`, NÃO por `asset_class` — DI funds vão para Fundos no Balcão mesmo classificando como `fixed_income` no donut.

### Fluxo de dados

```
/.user/finance/bookkeeper/ledgers/fechamento/months.json     ← manifesto: array de meses disponíveis
/.user/finance/bookkeeper/ledgers/fechamento/{YYYY-MM}/
  transactions.csv                          ← 19 colunas (ver data-model.md §1.1+§1.2)
        │
        ▼
  dashboard.html                            ← fetch via HTTP (paths vault-root-absolute), parse com PapaParse
```

### Manifesto (`months.json`)

Array JSON simples: `["2026-02", "2026-03"]`. O dashboard cria uma aba "Evolucao" (primeira, ativa por padrão) + uma aba por mês. O workflow de fechamento financeiro (Passo 8) atualiza este arquivo automaticamente ao fechar cada mês.

### Caminhos vault-root-absolute

Todos os paths do dashboard são vault-root-absolute — o server serve a vault root como docroot e a localização do entry HTML é configurável (`finance_dashboard_html_path`), então nada resolve relativo à página:

| Classe | Base | Origem |
|--------|------|--------|
| Assets (CSS/JS) | `/{sb_os_path}/finance/dashboard/` | Substituída no render do template pelo `install.py` (`{{DASHBOARD_ASSET_BASE}}`) |
| Dados (ledgers/config) | `/.user/finance/bookkeeper/` | Constante `FIN_DATA_BASE` em `shared.js` (contrato fixo p1-3 — não configurável) |

### Dependências externas (CDN)

- **Chart.js 4.4.7** — gráficos (doughnut, bar horizontal, line, stacked bar)
- **PapaParse 5.4.1** — parse de CSV no browser

### Execução

Requer HTTP server (fetch API não funciona com `file://`). Servidor custom em `3-resources/tools/sb-os/finance/dashboard/dashboard-server.py` — estende `SimpleHTTPRequestHandler` servindo arquivos estáticos da vault root e expõe `POST /api/refresh-prices` que executa `calculate.py` e retorna JSON (`{ok, returncode, stdout, stderr}`). Timeout de 180s. Função PowerShell:

```powershell
function dashboard { Set-Location "$BRAIN"; Start-Process "http://localhost:8080/.user/finance/dashboard.html"; python "$BRAIN\3-resources\tools\sb-os\finance\dashboard\dashboard-server.py" 8080 }
```

`Ctrl+C` no terminal para parar o server.

### Botão "Atualizar preços" (Bolsa)

Na aba Bolsa, topo direito da filter bar. Ao clicar: POST `/api/refresh-prices` → server executa `calculate.py` (sem `--cut-date`, regrava `portfolio.json`) → frontend re-fetch `portfolio.json` e re-renderiza a view. Durante a chamada o botão fica desabilitado com spinner. Toast fixo no canto inferior direito (4s, verde/sucesso ou vermelho/erro). Reload respeita o snapshot atualmente selecionado — se o usuário está olhando um snapshot histórico, refetch é do `portfolio-YYYY-MM-DD.json` correspondente (que `calculate.py` não regenerou — só o `portfolio.json` atual). Em prática, usar refresh com cut date histórico selecionado recarrega o snapshot antigo sem mudança.

---

## Estrutura do dashboard

### Toggle de eixo temporal (topo direito)

Dropdown único `Caixa | Competência` no topo direito da página (lado a lado com os botões de modo e privacidade). Governa TODAS as agregações do dashboard de gastos: cards, doughnut, top-10, resumos por categoria/fornecedor/tag, evolução, comparativa, e a aba mensal em que cada transação aparece. Ver "Caixa vs Competência" abaixo para o comportamento completo.

### Abas mensais

Cada mês tem:

1. **Cards resumo** — Total Gastos (líquido de reembolsos — ver "Reembolsos: netting" abaixo), Total Receitas (exclui reembolsos), Categorias, Transacoes, Recorrente, Pontual
2. **Gráficos** (lado a lado)
   - Doughnut: gastos por categoria (líquido de reembolsos)
   - Bar horizontal: top 10 maiores gastos por **fornecedor** com rollup R$200 trailing-92-day para "Outros" (ver "Fornecedores: rollup" abaixo)
3. **Resumo por Categoria** — tabela com total, % do total, % recorrente, % pontual. Líquido de reembolsos. **Colapsável, fechado por padrão.**
4. **Resumo por Fornecedor** — tabela com fornecedor (canonical ou "Outros" via rollup), total, % do total. Líquido de reembolsos. **Colapsável, fechado por padrão.**
5. **Resumo por Tag** — tabela com tag, total, % recorrente, % pontual. Tags são uma dimensão CROSS-CUTTING (ver "Tags" abaixo) — uma transação com múltiplas tags contribui o valor inteiro para CADA tag, então a soma das linhas é INTENCIONALMENTE maior que a soma das transações. Disclaimer renderizado abaixo da tabela. Só aparece se o mês tiver pelo menos uma tag. **Colapsável, fechado por padrão.**
6. **Todas as Transacoes** — tabela completa com TODAS as transacoes do mês (incluindo não categorizadas, ignoradas, intercontas, reembolsos como linhas separadas com valor positivo). Colunas: Data, Descrição, Fornecedor (display name após rollup), Valor (gross — reembolso aparece como positivo), Categoria, **Tags** (multi-badge), Recorrência, Banco, Tipo. **Colapsável, aberto por padrão.**
   - Link para abrir o relatório `.md` do mês

### Aba Evolucao

1. **Filtros** — mesmos filtros da seção de transações das abas mensais (categoria, **tags**, banco, tipo, fluxo, recorrência, busca textual). Afetam todos os dados da aba: cards, gráficos e tabela comparativa. Multi-selects coletam valores únicos de TODOS os meses. Subtotais (gastos, receitas, transações) aparecem quando filtros estão ativos. Os subtotais de Gastos e Receitas são líquidos de reembolsos (T4).
2. **Cards** — total de gastos por mês (afetados por filtros, líquido de reembolsos)
3. **Linha** — evolucao total de gastos (eixo Y começa em zero). Líquido de reembolsos. **Colapsável.**
4. **Stacked bar (recorrência)** — recorrente vs pontual empilhados por mês. Líquido de reembolsos. **Colapsável.**
5. **Stacked bar (categorias)** — gastos por categoria empilhados (top 12 + "Outros"). Líquido de reembolsos. **Colapsável.**
6. **Tabela comparativa** — todas as categorias, valor por mês, variacao % entre últimos dois meses. Líquido de reembolsos. **Colapsável.**

---

## Filtros (abas mensais)

A tabela de transacoes tem 5 filtros + busca textual:

| Filtro | Tipo | Valores |
|--------|------|---------|
| Categoria | Multi-select com checkboxes + exclude button | Todas as categorias encontradas no CSV do mês. Botão `−` em cada opção seleciona todas EXCETO aquela (exclude mode) |
| Tags | Multi-select com checkboxes + exclude button | Todos os tokens de tag encontrados no CSV do mês (cross-cutting — ver "Tags"). **OR semantics:** uma linha passa o filtro se QUALQUER uma de suas tags estiver no conjunto selecionado. Substitui o antigo filtro de subcategoria |
| Banco | Multi-select com checkboxes + exclude button | Nomes amigáveis agrupados por instituição (Bradesco, Mercado Pago, Nubank, Santander, Wise). Selecionar "Mercado Pago" filtra `mp_extrato`, `mp_fatura` e `xp_extrato`. Mesmo comportamento de exclude |
| Tipo de transacao | Select simples | Extrato bancário (`extrato`) ou Fatura de cartão (`fatura`) |
| Fluxo | Select simples | Gastos e receitas / Somente gastos / Somente receitas |
| Recorrencia | Select simples | Todas / Recorrente / Pontual |
| Busca | Input texto | Texto livre na descricao |

Filtros são combináveis. A tabela é paginada (30 linhas/página) e ordenável por qualquer coluna (incluindo Fornecedor — usa o display name pós-rollup). Direção padrão ao clicar numa coluna pela primeira vez: `amount` inicia descendente (maior → menor); todas as outras colunas (texto, data) iniciam ascendente (A→Z, mais antigo → mais recente). Segundo clique inverte a direção. Indicadores visuais (▲/▼) aparecem via CSS `::after` no `<th>` ativo.

---

## Caixa vs Competência

Toggle único no topo direito da página (`Caixa | Competência`) governa todas as agregações do dashboard de gastos. Implementação em `expenses.js` via `getActiveDateColumn()` + `getMonthRows(month)`.

| Aspecto | Comportamento |
|---------|--------------|
| Default | `data_caixa` — alinhado com o relatório de fechamento (cash flow real) |
| Persistência | `localStorage` chave `expensesDateAxis`. Sobrevive entre sessões |
| Coluna ativa | `data_caixa` ou `data_competencia` — definidas em `data-model.md` §1.2 |
| Bucket mensal | Cada transação cai na aba `YYYY-MM` extraída do prefixo da coluna ativa (`row[axis].slice(0,7)`) |
| Mudança de eixo | Re-renderiza todas as abas em vigência (destrói os charts `pie-`, `bar-`, `evo-` e reconstrói); a estrutura de tabs permanece estável |
| Linhas sem coluna ativa | SKIPPED (sem fallback silencioso para `date`). `date` é audit-only por data-model §1.1 |

### União de meses sob competência

Sob `data_competencia`, a competência de uma transação pode mapear para um mês fora de `months.json` (ex.: parcela paga em maio com competência em janeiro, quando só fev/mar estão carregados). Comportamento conservador (decisão de p4-1):

| Caso | Ação |
|------|------|
| `data_competencia.slice(0,7)` está em `months.json` | Linha agregada normalmente |
| `data_competencia.slice(0,7)` NÃO está em `months.json` | Linha **SKIPPED** + `console.warn` único por par (mês, axis) |

Razão: as abas são construídas no init a partir de `months.json`; sintetizar abas dinâmicas forneceria uma visão assimétrica (CSV ausente para o mês não carregado). O backfill da Phase 5 popula meses históricos — depois disso o warning auto-resolve.

---

## Fornecedores: rollup R$200 trailing-92-day

A coluna armazenada `supplier_canonical` (data-model §1.2) carrega o nome canonical detectado por `suppliers.json` (ou string vazia se nenhum alias bateu). O dashboard aplica um rollup de presentation-time para "Outros" (T6 — porta JS de `lib.suppliers.rollup_outros`). Implementação: `computeSupplierDisplayMap(rows, referenceDate)` em `expenses.js`.

| Regra | Detalhe |
|-------|---------|
| Threshold | R$ 200,00 (`SUPPLIER_ROLLUP_THRESHOLD_BRL`). `>=` canonical; `<` "Outros" |
| Janela | Fixa de 92 dias terminando no `referenceDate` (último dia do mês para abas mensais; "agora" para Evolução) |
| Soma | `abs(amount)` somado por `supplier_canonical` ao longo da janela, através de TODAS as categorias |
| Recomputação | Por render — nunca cacheado entre trocas de eixo ou de mês |
| `supplier_canonical` vazio | Sempre rolla para "Outros" |
| "Outros" | NUNCA persistido — invariante hard de data-model §6 inv-6. Apenas presentation-time |

Aplicado em: tabela Top-10 (bar horizontal), Resumo por Fornecedor, e coluna Fornecedor da tabela de transações (com `title` no hover mostrando o canonical para linhas roladas). Linhas "Outros" são estilizadas com `var(--text-muted)` itálico.

---

## Tags: dimensão cross-cutting

Tags **substituem** `subcategory` em todo o dashboard exceto na coluna da tabela de transações (que renderiza tags como multi-badge). Origem: coluna `tags` do CSV (semicolon-separated, lowercase kebab-case ASCII — data-model §1.3 + §6 inv-7).

| Aspecto | Comportamento |
|---------|--------------|
| Parsing | `parseTagColumn(value)` em `expenses.js` — `value.split(';')`, remove tokens vazios. Cacheado em `r._tags` no load |
| Multi-valor | Uma transação tem 0..N tags. Exemplos: `""`, `"tennis"`, `"tennis;reembolsavel"` |
| Filtro | Multi-select com **OR semantics** — linha passa se QUALQUER tag selecionada estiver presente |
| Resumo por Tag | Dimensão cross-cutting — uma transação com N tags contribui o valor INTEIRO para CADA tag. Soma das linhas é intencionalmente > soma das transações (disclaimer visível abaixo da tabela) |
| Render na tabela | Cada tag é um `.cat-badge` independente (cor pela `catColor` da tag); coluna em branco quando a transação não tem tags |
| Cor | `catColor(tag)` reusa o mapa de cores compartilhado (paleta de 30 cores ordenada alfabeticamente sobre o conjunto unificado de categorias + tags) |

A coluna `subcategory` foi REMOVIDA do schema (data-model §1.2). O backfill da Phase 5 re-mapeia subcategorias históricas para tags.

---

## Reembolsos: netting (T4)

Reembolsos NÃO são receita — são despesa-negativa. O dashboard subtrai reembolsos do total da categoria/fornecedor/tag em todas as visualizações agregadas.

### Identificação

A coluna armazenada não tem flag `is_reimbursement` — a regra é replicada de `categorize.py` (linhas 152-155):

| Condição | Resultado |
|----------|-----------|
| `amount > 0` AND `description.toUpperCase()` contém um substring de qualquer chave de `reimbursement_mappings` | É reembolso |
| Caso contrário | Não é reembolso |

Os patterns vêm de `categories.json` — fetched UMA VEZ no `init()` via `CATEGORIES_CONFIG_PATH`, vault-root-absolute (`${FIN_DATA_BASE}/config/categories.json` → `/.user/finance/bookkeeper/config/categories.json`). Se o fetch falhar: graceful degradation — `_reimbursementPatterns = []`, `console.warn` emitido, netting vira no-op (reembolsos aparecem como linhas positivas sem subtrair). Decisão de p4-4 (Opção B — single source of truth).

### Onde aplica

| Local | Netting? |
|-------|----------|
| Card Total Gastos (abas mensais e Evolução) | Sim |
| Doughnut por categoria | Sim |
| Top-10 por fornecedor | Sim |
| Resumo por Categoria / Fornecedor / Tag | Sim |
| Linha de evolução total | Sim |
| Stacked bar (recorrência) | Sim |
| Stacked bar (categorias) | Sim |
| Tabela comparativa | Sim |
| Subtotais de filtros (Gastos / Saldo) | Sim |
| **Tabela "Todas as Transacoes"** | **NÃO** — gross visível por linha (reembolso aparece com valor positivo) |
| Card Total Receitas / subtotal Receitas | NÃO inclui reembolsos (`r.amount > 0 AND r.category === 'receitas' AND !isReimbursement(r)`) |

### Contrato matemático

`netAmount(rows) = sum(r.amount for r in rows if r.amount < 0) + sum(r.amount for r in rows if isReimbursement(r))`. Retorna número negativo (despesa líquida). Exemplo: `[-1000 saude, +200 saude reimb]` → `-800`. `netAbsAmount(rows) = -netAmount(rows)` para call-sites que carregam totais como positivos.

### Invariantes

| # | Invariante |
|---|------------|
| 1 | `data_caixa` JAMAIS é movido pelo netting — opera apenas em `amount` e `description` (Q12 hard) |
| 2 | Interação com eixo: netting opera nas linhas devolvidas por `getMonthRows()`, que já roteou via `getActiveDateColumn()`. Reembolso recebido em maio (caixa) com competência em março (override manual) → neta em maio sob caixa, em março sob competência. Sem código especial |
| 3 | Receita real (positiva, não-reembolso) é EXCLUÍDA do agregado de Gastos — pertence ao card de Receitas |

---

## Modo privacidade

Botão "Ocultar Valores" / "Mostrar Valores" no canto superior direito.

**Ativado por padrão** ao abrir a página.

Quando ativo:
- Valores monetários (cards, tabelas, coluna Valor) ficam com blur CSS
- Eixos de valor nos gráficos ficam ocultos (ticks.display = false)
- Tooltips dos gráficos ficam desabilitados
- Legenda do doughnut fica oculta

Quando ativo, os gráficos continuam visíveis (formas, cores, proporções) — apenas dados financeiros ficam ocultos. Categorias, nomes de vendors, datas, bancos e tipos permanecem legíveis.

---

## Categorias

A categoria é uma dimensão **single-value** (uma categoria por transação) — vem do campo `category` do CSV. **Tags substituem `subcategory`** como a dimensão multi-valor cross-cutting (ver "Tags" acima); a coluna `subcategory` foi removida do schema.

Categorias são descobertas dinamicamente dos CSVs — nenhuma lista hard-coded no dashboard. Cores vêm de uma paleta fixa de 30 cores, atribuídas por ordem alfabética do conjunto unificado de categorias + tags. A mesma categoria sempre recebe a mesma cor enquanto o conjunto não mudar. Se uma nova categoria/tag é adicionada no meio da lista alfabética, as cores subsequentes se deslocam.

Categorias `ignorar` e `intercontas` são excluídas dos cálculos de gastos (cards, gráficos, resumo) e do filtro "Somente receitas". Aparecem apenas na tabela completa de transacoes (sem filtro de fluxo ativo).

---

## Formato do CSV esperado

**Schema authority:** `3-resources/tools/sb-os/finance/docs/expenses-data.md` §1.1 (12 colunas normalizadas) + §1.2 (7 colunas categorizadas). 19 colunas no total, output de `categorize.py`. Esta seção NÃO duplica o contrato — consulte expenses-data.md para tipos, semântica e invariantes completos.

Colunas que o dashboard consome diretamente (resumo informal — data-model.md é autoritativo):

| Coluna | Uso no dashboard |
|--------|-----------------|
| `date` | Exibição na tabela e ordenação. **Audit-only** — NÃO é eixo de agregação (data-model §1.1) |
| `description` | Exibição, busca textual, labels, identificação de reembolsos |
| `amount` | Base de todos os cálculos (negativo = gasto; positivo = receita ou reembolso) |
| `bank` | Filtro por banco (mapeado para nome amigável), exibição na tabela |
| `source_type` | Filtro por tipo de transação |
| `category` | Filtro, doughnut, resumo por categoria, badges |
| `match_confidence` | Não usado no dashboard |
| `recurrence` | Filtro, cards resumo, coluna na tabela, stacked bar de evolução |
| **`data_caixa`** (NEW) | Eixo de agregação quando o toggle = "Caixa" (default). Imutável (data-model §6 inv-1) |
| **`data_competencia`** (NEW) | Eixo de agregação quando o toggle = "Competência" |
| **`supplier_canonical`** (NEW) | Resumo por Fornecedor, top-10 (com rollup R$200), coluna Fornecedor |
| **`tags`** (NEW, semicolon-separated) | Filtro multi-select OR, Resumo por Tag, multi-badge na tabela |

**Removidas do schema:** `subcategory` (substituída por `tags`).

Colunas presentes no CSV mas NÃO consumidas pelo dashboard: `balance`, `currency`, `original_ref`, `installment_current`, `installment_total`, `original_amount`, `exchange_rate`. Ver data-model.md §1.1 para detalhes.

---

## Mapeamento de bancos

O dashboard converte `bank_id` do CSV em nomes amigáveis agrupados por instituição. O filtro de banco e a coluna na tabela de transacoes mostram o nome amigável.

| bank_id (CSV) | Nome exibido |
|---------------|-------------|
| `bradesco_extrato` | Bradesco |
| `mp_extrato` | Mercado Pago |
| `mp_fatura` | Mercado Pago |
| `santander_extrato` | Santander |
| `santander_fatura` | Santander |
| `nubank_fatura` | Nubank |
| `wise_extrato` | Wise |
| `xp_fatura` | XP |
| `Cash` | Cash (fallback — not in BANK_NAMES, displayed as-is) |

Bank_ids não mapeados aparecem como estão (fallback para o valor original do CSV).

---

## Dados de fevereiro 2026

Fevereiro não passou pelo workflow automatizado (pré-data a criação do sistema). O CSV foi criado manualmente a partir do relatório markdown `2026-02.md`. Diferenças em relação aos meses automatizados:

- `bank` usa `mp_extrato` para transacoes do extrato Mercado Pago (bank_id que não existe nos parsers — apenas dados históricos)
- Parcelas sem data precisa usam `2026-02-28` como data aproximada
- Seção "Movimentacoes ignoradas" do markdown não foi incluída no CSV por falta de datas individuais
- Categoria `roupas` e `iof` existem apenas em fevereiro (março usa categorias diferentes para esses gastos)

---

## Decisões de design

| Decisão | Razão |
|---------|-------|
| Manifesto `months.json` em vez de scan de diretório | HTML via fetch não pode listar diretórios. Manifesto requer adicionar 1 linha por mês — o workflow faz isso automaticamente no Passo 8 |
| CDN para Chart.js e PapaParse | Sem build step. Funciona offline após primeiro load (cache do browser) |
| Multi-file split (shared.js + page-specific) | Permite reutilizar design system e componentes entre dashboards (financeiro, investimentos). Sem módulos — globals carregados via `<script>` em ordem |
| Dashboard de investimentos como renderizador puro | Lê `portfolio.json` gerado pelo `calculate.py` — nenhuma computação em JS, nenhuma chamada a API de preços. Toda agregação (alocação, TIR, P&L, price_changes) é pré-computada em Python. Dashboard só renderiza. |
| `inv-data.js` separado de views | Data layer isola fetch, cache-busting, normalização de `snapshots.json` (aceita schema PRD `{snapshots:[...]}` ou array simples de datas) e tratamento de erro. Views (`inv-carteira.js`, futuros `inv-bolsa.js` etc) consomem via getters — sem acoplamento de fetch. |
| Cut date via snapshots pré-gerados | Dropdown popula de `snapshots.json`. Ao trocar, `inv-data.js` carrega `portfolio-YYYY-MM-DD.json` correspondente e re-renderiza a view. Nenhuma recomputação em JS — `calculate.py --cut-date` é responsável pela geração. |
| Privacy mode estendido para `inv-*` prefixos | `updateChartsPrivacy` em shared.js trata `inv-bar-*` como `bar-*` (oculta ticks X) e `inv-line-*` como `evo-line` (oculta ticks Y). Para `inv-pie-*`, desabilita tooltip e os datalabels (BRL nas fatias) — formas e legendas continuam visíveis. `inv-carteira.js` reaplica `updateChartsPrivacy(true)` após render quando o body já está em `privacy-mode`, para que charts criados com a aba já oculta respeitem o estado. |
| Cache-busting nos fetches | `?v=${Date.now()}` nos paths de manifesto e CSV. Garante que o browser sempre busca dados frescos após edições nos CSVs |
| Privacidade por padrão | Usuário mostra o dashboard para outras pessoas — valores devem estar ocultos por padrão |
| Resumo colapsado, Transacoes expandido | O uso principal é inspecionar transacoes individuais (verificar categorizacoes). Resumo é secundário |
| Evolucao como aba padrão | Visão consolidada é o ponto de entrada natural — meses individuais são drill-down |
| Evolucao preserva estado colapsável nos filtros | Filtros re-renderizam dados sem reabrir seções que o usuário colapsou |
| Todas as transacoes visíveis | Incluindo ignorar/intercontas — permite ao usuário verificar se algo foi categorizado errado |
| Eixo Y começa em zero | Gráfico de evolucao não deve distorcer visualmente a diferença entre meses |
| Caixa/competência via dropdown único (sem novas páginas) | Toggle único no topo direito governa todas as agregações. Sem páginas/abas duplicadas. Persistido em `localStorage.expensesDateAxis`. Default = caixa (cash flow real, alinhado com fechamento) |
| Rollup de fornecedor "Outros" apenas em render-time | Coluna armazenada `supplier_canonical` JAMAIS contém "Outros" (data-model §6 inv-6). Threshold R$200 / janela trailing 92 dias é recomputado por render via `computeSupplierDisplayMap()`. Permite sliding-window analytics sem schema migration |
| Reembolsos: netting em todos os visuais; gross na tabela | Consistência > preservação de sinal (T4). Cards, doughnut, top-10, resumos, evolução, comparativa: NETTED. Tabela "Todas as Transacoes": gross visível por linha (linha de reembolso fica visível com valor positivo). Identificação via `reimbursement_mappings` de `categories.json` fetched no init — single source of truth com `categorize.py` |
| Tags substituem `subcategory` como dimensão cross-cutting | Subcategoria era um modelo hierárquico que não encaixava em casos reais (ex.: "tennis" cruza esportes e compras). Tags são multi-valor por linha, OR-semantics no filtro. Resumo por Tag soma intencionalmente > soma das transações (cross-cutting) — disclaimer renderizado na tabela |
| `data-model.md` é a única autoridade de schema | Esta documentação NUNCA duplica a tabela de colunas — referencia data-model.md §1.1/§1.2. Evita drift entre o consumer (dashboard) e o schema (categorize.py / lib/) |
| `valuation_method` desacoplado de `asset_class` | `asset_class` historicamente acoplava DUAS coisas — a fatia do donut na Carteira E o branch de cálculo no `_build_position_entry` (price-based vs balcão flows). Isso impedia classificar fundos não-DI como Renda Variável no donut sem quebrar o cálculo do Balcão. `valuation_method` (derivado do `type`) governa exclusivamente onde a posição renderiza e como é calculada; `asset_class` governa exclusivamente o agrupamento visual da Carteira. Resultado: fundo FIM aparece na fatia RV do donut mas continua renderizando no Balcão (com aplicado/juros/resgates) sem inconsistência. |
| Funds DI = `fixed_income`; outros funds = `variable_income` | Visão pessoal de risco do usuário: fundos DI puros (FIRF Referenciado DI / 100% CDI) replicam o CDI e são tratados como RF; FIM/FIA/FIRF Crédito/cambial/infra etc. carregam volatilidade não-RF e vão para RV. Detecção via `type='di'` no cadastro (`assets.csv`) — FIRF não-DI usa `type='firf_br'` e cai automaticamente em `variable_income`. |
