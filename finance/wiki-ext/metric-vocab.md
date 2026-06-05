# Metric Vocabulary — Finance Extension

Controlled vocabulary the `sb-investor` extracts against. Segmented by entity kind. The `sb-investor` extracts against THIS list — the user NEVER enumerates metrics per file. A new recurring metric is **proposed** by the agent for addition (governed growth, like new page types); start small, grow on evidence.

Feeds the `metric` and `unit` columns of the uniform long-format `## Financials` table (schema in `./section-menus.ext.md`). Names here are controlled identifiers — the investment lint rules (`./lint-rules.ext.md`) check against them exactly, and the `investment_financials_extract` write tool HARD-REJECTS off-vocabulary `metric`/`unit`/`period_type`/`method` values at write time.

---

## Vocabulary by Entity Kind

### company / equity

`revenue, gross_profit, ebitda, ebit, operating_income, net_income, gross_margin, ebitda_margin, operating_margin, net_margin, roic, roe, net_debt, net_debt_ebitda, fcf, operating_cash_flow, capex, rpo, crpo, subscription_revenue, subscription_support_revenue, cloud_revenue, data_center_revenue, data_cloud_ai_arr, cash_and_securities`

GAAP is the unqualified default — `operating_income`/`operating_margin` mean the GAAP figure; non-GAAP variants take the `_non_gaap` suffix (see Suffix Families). `data_cloud_ai_arr` is an operational-KPI-class identifier (admitted 2026-06-04, governed). `cash_and_securities` is a balance-sheet point figure (`period_type: point`).

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

## Suffix Families

A valid `metric` is a base identifier from the entity-kind's list above, OR a base identifier + exactly ONE of these suffixes. Stacking suffixes is FORBIDDEN (`revenue_guidance_growth_yoy` is invalid).

`_growth_yoy, _guidance, _non_gaap`

| Suffix | Meaning | Rules |
|--------|---------|-------|
| `_growth_yoy` | Stated year-over-year growth rate of the base metric | `unit: pct`. Only as printed in the source — never derived |
| `_guidance` | Company-guided (not actual) value of the base metric | Year-free (NEVER `revenue_fy26_guidance`); `period_end` = the guided period's close; `period_type` stays `annual`/`quarterly`. Re-guides across quarters = expected multi-rows, NOT conflicts |
| `_non_gaap` | Non-GAAP variant of the base metric | GAAP is the unqualified default — the bare base identifier means GAAP |

---

## Allowed Sets

**units:** `BRL_mn, USD_mn, pct, pct_yoy, pct_mom, x, bps, years, rating, BRL, USD, index`

**period_type:** `annual, quarterly, monthly, ttm, point`

**method:** `xbrl, structured, llm, manual`

| Method | Meaning |
|--------|---------|
| `xbrl` | Deterministically parsed by `investment_financials_extract` from a captured XBRL companyfacts artifact (lane 1) |
| `structured` | Deterministically parsed by `investment_financials_extract` from captured raw — a structured feed OR an agent-pointed, verbatim-verified anchor location (lane 2). The tool re-reads the number from the raw; a model never transcribes it |
| `llm` | Model-supplied value WITHOUT tool verification (lane 3 — exception, not norm). Rows feeding a `status: active` thesis route to the lint Fundamentals #2 spot-check queue |
| `manual` | User-entered by hand. Lint Fundamentals rules backstop vocabulary conformance |

---

## Governance Rule

A metric NOT in this vocabulary MUST NOT be written to a `## Financials` table without prior addition here. Additions require an agent proposal (new name + entity kind + typical unit) approved by the user — the same governed-growth gate as new page types; the extraction scan surfaces off-vocabulary finds as `PROPOSAL:` rows, never as writes. Agents NEVER silently rename, abbreviate, or "improve" existing identifiers; the `investment_financials_extract` tool hard-gates at write time and lint checks enforce exact spelling.
