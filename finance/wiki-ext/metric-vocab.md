# Metric Vocabulary — Finance Extension

Controlled vocabulary the `investor` extracts against. Segmented by entity kind. The `investor` extracts against THIS list — the user NEVER enumerates metrics per file. A new recurring metric is **proposed** by the agent for addition (governed growth, like new page types); start small, grow on evidence.

Feeds the `metric` and `unit` columns of the uniform long-format `## Financials` table (schema in `./section-menus.ext.md`). Names here are controlled identifiers — the investment lint rules (`./lint-rules.ext.md`) check against them exactly.

---

## Vocabulary by Entity Kind

### company / equity

`revenue, gross_profit, ebitda, ebit, net_income, gross_margin, ebitda_margin, net_margin, roic, roe, net_debt, net_debt_ebitda, fcf, capex`

Valuation point metrics (use `period_type: point`):

`market_cap, ev_ebitda, pe, dividend_yield`

### country / macro

`gdp_growth, inflation, policy_rate, unemployment, debt_gdp, fiscal_balance, current_account, fx_rate`

### asset — fixed income

`yield, duration, coupon, credit_rating, spread, price`

### sector

Comparative / aggregate metrics: `sector_revenue_growth, sector_margin`

Sectors mostly lean on member-company data. Additional sector metrics are proposed by the agent when recurring evidence warrants them.

---

## Allowed Sets

**units:** `BRL_mn, USD_mn, pct, pct_yoy, pct_mom, x, bps, years, rating, BRL, USD, index`

**period_type:** `annual, quarterly, monthly, ttm, point`

**method:** `xbrl, structured, llm, manual`

---

## Governance Rule

A metric NOT in this vocabulary MUST NOT be written to a `## Financials` table without prior addition here. Additions require an agent proposal (new name + entity kind + typical unit) approved by the user — the same governed-growth gate as new page types. Agents NEVER silently rename, abbreviate, or "improve" existing identifiers; lint checks enforce exact spelling.
