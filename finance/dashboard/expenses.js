// Dashboard Financeiro — page-specific logic.
// Depends on shared.js globals: CACHE_BUST, EXCLUDED_CATEGORIES, BANK_NAMES, COLOR_PALETTE,
// allData, charts, categoryColorMap, bankName, bankGroup, buildColorMap, catColor, formatBRL,
// formatMonth, catLabel, fullCatKey, toggleCollapse, createMultiSelect, getMultiSelectValues,
// updateMultiSelectChips, togglePrivacy, updateChartsPrivacy.

const MANIFEST_PATH = `./ledgers/fechamento/months.json${CACHE_BUST}`;
const DATA_PATH = (month) => `./ledgers/fechamento/${month}/transactions.csv${CACHE_BUST}`;
// categories.json is the authoritative source for reimbursement_mappings.
// Loading it at init avoids hardcoding the pattern list in JS (drift risk).
// The dashboard server serves from vault root; this path is resolved relative
// to dashboard.html (which lives at `3-resources/tools/finance/dashboard.html`).
const CATEGORIES_CONFIG_PATH = `./config/categories.json${CACHE_BUST}`;
const ROWS_PER_PAGE = 30;

// --- Date-axis toggle (Caixa | Competencia) ---
// Drives every aggregation in the gastos dashboard. Default = data_caixa
// (matches existing report convention). Persisted in localStorage under
// `expensesDateAxis`. The toggle is presentation-only — never mutates rows.
const DATE_AXIS_STORAGE_KEY = 'expensesDateAxis';
const VALID_DATE_AXES = new Set(['data_caixa', 'data_competencia']);
let expensesDateAxis = (() => {
  try {
    const stored = localStorage.getItem(DATE_AXIS_STORAGE_KEY);
    if (stored && VALID_DATE_AXES.has(stored)) return stored;
  } catch (_) { /* localStorage may be blocked — fall through to default */ }
  return 'data_caixa';
})();

function getActiveDateColumn() { return expensesDateAxis; }

function setDateAxis(axis) {
  if (!VALID_DATE_AXES.has(axis)) return;
  expensesDateAxis = axis;
  try { localStorage.setItem(DATE_AXIS_STORAGE_KEY, axis); } catch (_) { /* noop */ }
  rerenderForAxisChange();
}

// Bucket all loaded rows by the active date axis. Rows whose active-axis
// value is missing/empty are SKIPPED (no silent fallback to `date`).
// Rows whose active month is not in `_evoMonths` are also SKIPPED with a
// one-time console warning per (month, axis) — this is the conservative
// default for monthly-tab union; phase-5 backfill resolves it. See shape.md.
const _unknownMonthWarned = new Set();
function getMonthRows(month) {
  const axis = getActiveDateColumn();
  const knownMonths = window._evoMonths || Object.keys(allData);
  const knownSet = new Set(knownMonths);
  const out = [];
  Object.values(allData).forEach(monthRows => {
    monthRows.forEach(r => {
      const v = r[axis];
      if (!v || typeof v !== 'string' || v.length < 7) return; // skip rows lacking the axis column
      const rowMonth = v.slice(0, 7); // YYYY-MM
      if (!knownSet.has(rowMonth)) {
        const key = `${rowMonth}|${axis}`;
        if (!_unknownMonthWarned.has(key)) {
          _unknownMonthWarned.add(key);
          console.warn(`[expenses] row with ${axis}=${v} maps to month ${rowMonth} not in months.json — skipping. Backfill that month to include it.`);
        }
        return;
      }
      if (rowMonth === month) out.push(r);
    });
  });
  return out;
}

// --- Supplier rollup (T6) ---
// Render-time port of `lib.suppliers.rollup_outros` (Python). Mirrors the
// Python contract exactly:
//   - threshold default = 200.0 BRL
//   - window = fixed 92-day sliding window ending on `referenceDate` (inclusive)
//   - sums abs(amount) across ALL categories per supplier_canonical
//   - sum < threshold (strict) => 'Outros'; sum >= threshold => canonical
//   - empty/missing supplier_canonical => 'Outros'
//   - reads the row's date from the active axis column, falling back to legacy `date`
//     ONLY for legacy rows; this matches the Python behavior of preferring data_caixa
//     and falling back to `date` for rows without basis dates.
// 'Outros' is presentation-only and NEVER persisted (data-model §6 invariant 6).
const SUPPLIER_ROLLUP_THRESHOLD_BRL = 200.0;
const SUPPLIER_ROLLUP_WINDOW_DAYS = 92;
const SUPPLIER_OUTROS_LABEL = 'Outros';

function _parseISODate(s) {
  if (!s || typeof s !== 'string' || s.length < 10) return null;
  const y = Number(s.slice(0, 4));
  const m = Number(s.slice(5, 7));
  const d = Number(s.slice(8, 10));
  if (!y || !m || !d) return null;
  // Use UTC to avoid TZ drift across day boundaries.
  return new Date(Date.UTC(y, m - 1, d));
}

function _addDaysUTC(date, days) {
  const t = date.getTime() + days * 86400000;
  return new Date(t);
}

// Last day of month YYYY-MM as a Date (UTC).
function _lastDayOfMonthUTC(month) {
  if (!month || month.length < 7) return new Date();
  const y = Number(month.slice(0, 4));
  const m = Number(month.slice(5, 7));
  // day 0 of next month = last day of current month
  return new Date(Date.UTC(y, m, 0));
}

// Reference date for the rollup window for a given monthly tab (last day of
// the month) or for evolution view ("now").
function getReferenceDateForMonth(month) {
  if (!month || month === 'evolution') return new Date();
  return _lastDayOfMonthUTC(month);
}

// Compute the trailing-92-day supplier display map. Mirrors Python
// lib.suppliers.rollup_outros. Pass ALL loaded rows (the union across months)
// so the trailing window can pull from prior months that exist on disk.
//
// Returns a Map keyed by supplier_canonical -> display name (canonical or
// 'Outros'). Empty-key '' maps to 'Outros' if any input row has empty
// supplier_canonical. Suppliers seen in `rows` but with zero in-window
// activity are also mapped to 'Outros' (matches Python's defensive pass).
function computeSupplierDisplayMap(rows, referenceDate, threshold) {
  const thr = (typeof threshold === 'number') ? threshold : SUPPLIER_ROLLUP_THRESHOLD_BRL;
  const refDate = referenceDate instanceof Date ? referenceDate : new Date();
  const windowEnd = refDate;
  const windowStart = _addDaysUTC(windowEnd, -SUPPLIER_ROLLUP_WINDOW_DAYS);
  const axis = getActiveDateColumn();

  const sums = new Map();
  let sawEmpty = false;
  const seenSuppliers = new Set();

  for (const r of rows) {
    const sup = r.supplier_canonical || '';
    if (!sup) { sawEmpty = true; continue; }
    seenSuppliers.add(sup);
    // Active-axis date for window membership; fall back to legacy `date`
    // for rows without basis dates (parallels Python's data_caixa→date fallback).
    const d = _parseISODate(r[axis]) || _parseISODate(r.date);
    if (!d) continue;
    if (d.getTime() < windowStart.getTime() || d.getTime() > windowEnd.getTime()) continue;
    const amt = Number(r.amount) || 0;
    sums.set(sup, (sums.get(sup) || 0) + Math.abs(amt));
  }

  const mapping = new Map();
  for (const [sup, total] of sums.entries()) {
    mapping.set(sup, total >= thr ? sup : SUPPLIER_OUTROS_LABEL);
  }
  // Suppliers seen at all but with zero in-window activity → Outros.
  for (const sup of seenSuppliers) {
    if (!mapping.has(sup)) mapping.set(sup, SUPPLIER_OUTROS_LABEL);
  }
  if (sawEmpty) mapping.set('', SUPPLIER_OUTROS_LABEL);
  return mapping;
}

// --- Tags (multi-value, cross-cutting) ---
//
// JS port of `lib.tags.parse_tag_column` (Python). Mirrors the Python
// contract exactly: empty string → []; otherwise value.split(';') with no
// trimming. Filters empty segments (defensive — valid tokens never empty).
// Tag tokens are lowercase kebab-case ASCII per data-model §1.3 / §6 inv-7.
function parseTagColumn(value) {
  if (!value || typeof value !== 'string') return [];
  return value.split(';').filter(t => t.length > 0);
}

// Get a row's parsed tags (uses the cached `_tags` array set during load).
function rowTags(r) {
  return Array.isArray(r._tags) ? r._tags : parseTagColumn(r.tags || '');
}

// Resolve the display name for a single row given a precomputed display map.
function supplierDisplayName(row, displayMap) {
  const sup = row.supplier_canonical || '';
  if (displayMap.has(sup)) return displayMap.get(sup);
  // Defensive: any unseen value rolls up.
  return SUPPLIER_OUTROS_LABEL;
}

// --- Reimbursement netting (T4) ---
//
// Identification rule (mirrors categorize.py lines 152-155 exactly):
//   A row is a reimbursement IFF its amount > 0 AND its description (uppercased)
//   contains any pattern key from `reimbursement_mappings` in categories.json.
//
// `reimbursement_mappings` is fetched once at init() from
// `./config/categories.json` to avoid drift
// between Python source-of-truth and JS hardcoding. If the fetch fails (file
// missing, server cannot reach it), the dashboard falls back to no
// reimbursement netting (empty pattern list) and surfaces a console.warn —
// reimbursements then display as positive rows in their categories without
// being subtracted. This is the conservative-reversible default; a missing
// config never silently mis-categorizes.
//
// Netting semantics across visuals (per spec §T4 + shape.md Decisions):
//   - Doughnut, top-10, category table, supplier table, evolution line,
//     evolution stacked (recurrence + categories), comparativa table:
//     reimbursements SUBTRACT from the same row's category/supplier total.
//     The reimbursement row contributes its (positive) amount as a negative
//     to the expense aggregate, so a saude expense of -1000 + reimbursement
//     of +200 nets to 800.
//   - "Total Receitas" cards: reimbursements EXCLUDED — they are not income,
//     they are negative-expense.
//   - Transactions table: untouched. Each reimbursement row remains visible
//     with its original amount and category (gross recoverable per-row).
//
// Q12 invariant: `data_caixa` is never moved by netting. Active-axis routing
// happens through getMonthRows() upstream; netting math operates on the
// rows handed to each aggregation site.
let _reimbursementPatterns = []; // upper-cased substrings; populated at init.

function setReimbursementPatterns(patterns) {
  _reimbursementPatterns = (patterns || []).map(p => String(p).toUpperCase());
}

// Returns true iff the row is a reimbursement per the rule above.
function isReimbursement(row) {
  if (!row) return false;
  const amt = Number(row.amount) || 0;
  if (amt <= 0) return false;
  if (_reimbursementPatterns.length === 0) return false;
  const desc = String(row.description || '').toUpperCase();
  if (!desc) return false;
  for (const pat of _reimbursementPatterns) {
    if (pat && desc.indexOf(pat) !== -1) return true;
  }
  return false;
}

// Net amount for a group of rows: expenses (negative) accumulate normally;
// reimbursements ADD their positive amount to the negative total, making it
// less negative (i.e., reduce |expense|). Non-reimbursement positive rows
// (real income) are EXCLUDED from this sum (they are not expenses).
// Returns a NEGATIVE number for net expense (matches the existing
// convention used for expense aggregates that pass through formatBRL with a
// leading minus).
//
// Mathematical contract:
//   netAmount(rows) = sum(r.amount for r in rows if r.amount < 0)
//                   + sum(r.amount for r in rows if isReimbursement(r))
// Example:
//   [-1000 saude, +200 saude reimb] -> -1000 + 200 = -800. ✓
function netAmount(rows) {
  let s = 0;
  for (const r of rows) {
    const a = Number(r.amount) || 0;
    if (a < 0) {
      s += a;
    } else if (a > 0 && isReimbursement(r)) {
      s += a; // positive reimbursement reduces the negative expense total
    }
    // non-reimbursement positives (real income) are excluded
  }
  return s;
}

// Net absolute amount for an expense group (display-friendly positive).
// = -netAmount(rows). Convenient for code that holds expense totals as
// positive numbers (pie/bar/table sums).
function netAbsAmount(rows) {
  return -netAmount(rows);
}

// Net amount for a single category, given a row list pre-filtered to that
// category (or the full list when category-specific filtering is upstream).
// Identical contract to netAmount; named for readability at call sites.
function netAmountForGroup(rows) { return netAmount(rows); }

function rerenderForAxisChange() {
  // Determine active tab; re-render its content. Evolution is always rebuilt.
  const months = window._evoMonths || [];
  const activeTab = document.querySelector('.tab.active');
  const activeId = activeTab ? activeTab.dataset.month : 'evolution';

  // Destroy existing per-month charts (they'll be recreated on render).
  Object.keys(charts).forEach(key => {
    if (key.startsWith('pie-') || key.startsWith('bar-') || key.startsWith('evo-')) {
      charts[key].destroy();
      delete charts[key];
    }
  });

  // Re-render every monthly tab in place (state vars and DOM containers persist).
  months.forEach(m => {
    const div = document.getElementById('tab-' + m);
    if (div) renderMonthTab(m, div);
  });

  // Re-render evolution.
  const evoDiv = document.getElementById('tab-evolution');
  if (evoDiv) renderEvolutionTab(months, evoDiv);

  // Re-apply privacy state to freshly created charts.
  if (document.body.classList.contains('privacy-mode')) {
    updateChartsPrivacy(true);
  }
}

async function init() {
  try {
    // Load categories.json for reimbursement_mappings (T4 netting). Failure
    // here is non-fatal — netting falls back to no-op and reimbursements
    // display as positive rows without subtraction.
    try {
      const cfgRes = await fetch(CATEGORIES_CONFIG_PATH);
      if (cfgRes.ok) {
        const cfg = await cfgRes.json();
        const reimb = cfg.reimbursement_mappings || {};
        setReimbursementPatterns(Object.keys(reimb));
      } else {
        console.warn('[expenses] categories.json fetch returned ' + cfgRes.status + ' — reimbursement netting disabled');
      }
    } catch (cfgErr) {
      console.warn('[expenses] categories.json load failed — reimbursement netting disabled:', cfgErr.message);
    }

    const res = await fetch(MANIFEST_PATH);
    const months = await res.json();
    months.sort();
    const promises = months.map(async (m) => {
      const csvRes = await fetch(DATA_PATH(m));
      const csvText = await csvRes.text();
      const parsed = Papa.parse(csvText, { header: true, skipEmptyLines: true, dynamicTyping: true });
      allData[m] = parsed.data.map(r => {
        const tagsRaw = String(r.tags || '');
        return {
          ...r,
          amount: parseFloat(r.amount) || 0,
          date: String(r.date || ''),
          data_caixa: String(r.data_caixa || ''),
          data_competencia: String(r.data_competencia || ''),
          category: String(r.category || ''),
          tags: tagsRaw,
          _tags: parseTagColumn(tagsRaw),
          bank: String(r.bank || ''),
          source_type: String(r.source_type || ''),
          description: String(r.description || ''),
          recurrence: String(r.recurrence || ''),
          supplier_canonical: String(r.supplier_canonical || '')
        };
      });
    });
    await Promise.all(promises);
    buildColorMap(allData);

    // Track the canonical month list for axis-aware row bucketing.
    window._evoMonths = months;

    // Sync the page-level date-axis dropdown with the loaded/persisted state.
    const axisSel = document.getElementById('date-axis-select');
    if (axisSel) axisSel.value = getActiveDateColumn();

    const tabsEl = document.getElementById('tabs');
    const contentEl = document.getElementById('content');
    contentEl.innerHTML = '';

    // Evolution tab (first, active by default)
    const evoBtn = document.createElement('button');
    evoBtn.className = 'tab active';
    evoBtn.textContent = 'Evolucao';
    evoBtn.onclick = () => switchTab('evolution');
    evoBtn.dataset.month = 'evolution';
    tabsEl.appendChild(evoBtn);

    const evoDiv = document.createElement('div');
    evoDiv.className = 'tab-content active';
    evoDiv.id = 'tab-evolution';
    contentEl.appendChild(evoDiv);
    renderEvolutionTab(months, evoDiv);

    months.forEach((m) => {
      const btn = document.createElement('button');
      btn.className = 'tab';
      btn.textContent = formatMonth(m);
      btn.onclick = () => switchTab(m);
      btn.dataset.month = m;
      tabsEl.appendChild(btn);

      const div = document.createElement('div');
      div.className = 'tab-content';
      div.id = 'tab-' + m;
      contentEl.appendChild(div);
      renderMonthTab(m, div);
    });

    // Apply privacy to charts on load (default is hidden)
    if (document.body.classList.contains('privacy-mode')) {
      updateChartsPrivacy(true);
    }

  } catch (e) {
    document.getElementById('content').innerHTML = `<div class="loading" style="color:var(--red)">Erro ao carregar dados: ${e.message}<br><br>Verifique se o arquivo esta sendo servido via HTTP (nao file://).<br>Use: <code>python -m http.server 8000</code></div>`;
  }
}

function switchTab(id) {
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.month === id));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.toggle('active', t.id === 'tab-' + id));
}

function renderMonthTab(month, container) {
  // Aggregation site: bucket rows by the active date axis (caixa | competencia).
  const rows = getMonthRows(month);
  // Expense pool for netted aggregations (T4): includes negative-amount rows
  // (excluding ignorar/intercontas) AND reimbursement rows (positive amount,
  // matched against reimbursement_mappings). Reimbursements net out from
  // their category/supplier in every visual below — only the transactions
  // table treats them as separate visible rows.
  const expenseRows = rows.filter(r => r.amount < 0 && !EXCLUDED_CATEGORIES.has(r.category));
  const reimbRows = rows.filter(r => isReimbursement(r) && !EXCLUDED_CATEGORIES.has(r.category));
  const expensesForNetting = expenseRows.concat(reimbRows);
  // Total Receitas card: real income only — explicitly EXCLUDES reimbursements.
  const income = rows.filter(r => r.amount > 0 && r.category === 'receitas' && !isReimbursement(r));
  // Total Gastos card: net of reimbursements per T4.
  const totalExp = netAmount(expensesForNetting);
  const totalInc = income.reduce((s, r) => s + r.amount, 0);
  const totalTx = rows.length;
  // Recurrence breakdown also nets reimbursements (they inherit the
  // recurrence label from categorize.py classify_recurrence; e.g., a CARE
  // PLUS reimbursement of a recurring health expense is recurrent).
  const recorrente = expensesForNetting.filter(r => r.recurrence === 'recorrente');
  const pontual = expensesForNetting.filter(r => r.recurrence === 'pontual');
  const totalRec = netAmount(recorrente);
  const totalPon = netAmount(pontual);

  // Category breakdown — netted: each row contributes |amount| if negative,
  // or -amount if reimbursement (which subtracts from the category total).
  const catMap = {};
  expensesForNetting.forEach(r => {
    const c = r.category || 'a_identificar';
    const contrib = r.amount < 0 ? Math.abs(r.amount) : -r.amount; // reimb subtracts
    catMap[c] = (catMap[c] || 0) + contrib;
  });
  // Drop categories that net to <= 0 (theoretically possible if reimbursements
  // exceed expenses in a category-month). Keeps the doughnut sane.
  const catEntries = Object.entries(catMap)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1]);
  const categories = catEntries.map(e => e[0]);
  const catValues = catEntries.map(e => e[1]);

  // Supplier display map (T6 — render-time R$200 trailing-92-day rollup).
  // Computed against ALL loaded rows so the trailing window can reach into
  // prior months. The map is recomputed per render — never cached across
  // axis or month switches.
  const allLoadedRows = Object.values(allData).flat();
  const referenceDate = getReferenceDateForMonth(month);
  const supplierDisplayMap = computeSupplierDisplayMap(allLoadedRows, referenceDate);
  // Stash for filterTable to consume on the same render cycle.
  window[`supplierMap_${month}`] = supplierDisplayMap;

  // Top-10: group netted expenses by supplier display name (canonical or
  // 'Outros'). Reimbursements subtract from their supplier's total per T4.
  const topByDisplay = {};
  expensesForNetting.forEach(r => {
    const dn = supplierDisplayName(r, supplierDisplayMap) || SUPPLIER_OUTROS_LABEL;
    const contrib = r.amount < 0 ? Math.abs(r.amount) : -r.amount;
    topByDisplay[dn] = (topByDisplay[dn] || 0) + contrib;
  });
  const topSupplierEntries = Object.entries(topByDisplay)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10);

  // Supplier breakdown for "Resumo por Fornecedor" (netted; uses display name).
  const supplierMap = {};
  expensesForNetting.forEach(r => {
    const dn = supplierDisplayName(r, supplierDisplayMap) || SUPPLIER_OUTROS_LABEL;
    const contrib = r.amount < 0 ? Math.abs(r.amount) : -r.amount;
    supplierMap[dn] = (supplierMap[dn] || 0) + contrib;
  });
  const supplierEntries = Object.entries(supplierMap)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1]);

  container.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
      <h2 style="font-size:1.2rem;font-weight:600;">${formatMonth(month)}</h2>
    </div>
    <div class="cards">
      <div class="card">
        <div class="card-label">Total Gastos</div>
        <div class="card-value expense privacy-hide">${formatBRL(totalExp)}</div>
      </div>
      <div class="card">
        <div class="card-label">Total Receitas</div>
        <div class="card-value income privacy-hide">${formatBRL(totalInc)}</div>
      </div>
      <div class="card">
        <div class="card-label">Categorias</div>
        <div class="card-value neutral">${catEntries.length}</div>
      </div>
      <div class="card">
        <div class="card-label">Transacoes</div>
        <div class="card-value neutral">${totalTx}</div>
      </div>
      <div class="card">
        <div class="card-label">Recorrente</div>
        <div class="card-value expense privacy-hide">${formatBRL(totalRec)}</div>
      </div>
      <div class="card">
        <div class="card-label">Pontual</div>
        <div class="card-value expense privacy-hide">${formatBRL(totalPon)}</div>
      </div>
    </div>
    <div class="chart-row">
      <div class="chart-box">
        <h3>Gastos por Categoria</h3>
        <canvas id="pie-${month}"></canvas>
      </div>
      <div class="chart-box">
        <h3>Top 10 Maiores Gastos</h3>
        <canvas id="bar-${month}"></canvas>
      </div>
    </div>
    <div class="chart-row">
      <div class="chart-box collapsible collapsed" style="grid-column: 1 / -1;">
        <div class="collapsible-header" onclick="toggleCollapse(this)">
          <span class="collapsible-arrow">&#9660;</span>
          <h3>Resumo por Categoria</h3>
        </div>
        <div class="collapsible-body" style="max-height:2000px;">
          <table class="delta-table" style="margin-top:16px;">
            <thead><tr><th>Categoria</th><th style="text-align:right">Total</th><th style="text-align:right">% do Total</th><th style="text-align:right">% Recorrente</th><th style="text-align:right">% Pontual</th></tr></thead>
            <tbody>${catEntries.map(([c, v]) => {
              const pct = ((v / Math.abs(totalExp)) * 100).toFixed(1);
              // Per-category netted recurrence split: include reimbursements in
              // the same category so the row total matches the doughnut/cards.
              const catRowsNetted = expensesForNetting.filter(r => r.category === c);
              const recRows = catRowsNetted.filter(r => r.recurrence === 'recorrente');
              const recAmt = recRows.reduce((s, r) => {
                return s + (r.amount < 0 ? Math.abs(r.amount) : -r.amount);
              }, 0);
              const recPct = v !== 0 ? ((recAmt / v) * 100).toFixed(0) : '0';
              const pontPct = v !== 0 ? (100 - parseFloat(recPct)).toFixed(0) : '0';
              return `<tr><td><span class="cat-badge" style="border-color:${catColor(c)}">${catLabel(c)}</span></td><td style="text-align:right" class="privacy-hide">${formatBRL(-v)}</td><td style="text-align:right">${pct}%</td><td style="text-align:right">${recPct}%</td><td style="text-align:right">${pontPct}%</td></tr>`;
            }).join('')}</tbody>
          </table>
        </div>
      </div>
    </div>
    <div class="chart-row">
      <div class="chart-box collapsible collapsed" style="grid-column: 1 / -1;">
        <div class="collapsible-header" onclick="toggleCollapse(this)">
          <span class="collapsible-arrow">&#9660;</span>
          <h3>Resumo por Fornecedor</h3>
        </div>
        <div class="collapsible-body" style="max-height:2000px;">
          <table class="delta-table" style="margin-top:16px;">
            <thead><tr><th>Fornecedor</th><th style="text-align:right">Total</th><th style="text-align:right">% do Total</th></tr></thead>
            <tbody>${supplierEntries.map(([name, v]) => {
              const pct = totalExp !== 0 ? ((v / Math.abs(totalExp)) * 100).toFixed(1) : '0.0';
              const isOutros = name === SUPPLIER_OUTROS_LABEL;
              const style = isOutros ? 'color:var(--text-muted);font-style:italic;' : '';
              return `<tr><td style="${style}">${name}</td><td style="text-align:right" class="privacy-hide">${formatBRL(-v)}</td><td style="text-align:right">${pct}%</td></tr>`;
            }).join('')}</tbody>
          </table>
        </div>
      </div>
    </div>
    ${(() => {
      // Resumo por Tag — aggregates across categories (cross-cutting dimension).
      // A transaction with N tags contributes its FULL amount to N rows; the
      // sum across rows is INTENTIONALLY > sum of transaction amounts. Tags
      // are not partition-disjoint with category. See data-model §1.3 / spec
      // "Tag model — DECIDED (Q7=b)".
      //
      // T4 netting interaction: reimbursement rows (positive amount, matched
      // against reimbursement_mappings) contribute as -amount to each of
      // their tags. Real income (non-reimbursement positives) keeps its
      // positive sign. The displayed sign reflects the net (negative = net
      // expense; positive = net income).
      const tagMap = {};
      rows.forEach(r => {
        const tags = rowTags(r);
        if (tags.length === 0) return;
        const contrib = isReimbursement(r) ? -r.amount : r.amount;
        tags.forEach(t => { tagMap[t] = (tagMap[t] || 0) + contrib; });
      });
      const tagEntries = Object.entries(tagMap).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
      if (tagEntries.length === 0) return '';
      const disclaimer = '<div style="font-size:0.78rem;color:var(--text-muted);margin-top:8px;">Tags são uma dimensão cross-cutting: uma transação com múltiplas tags contribui o valor inteiro para CADA tag. A soma das linhas é intencionalmente maior que a soma das transações. Reembolsos subtraem do total da tag (T4).</div>';
      return `<div class="chart-row"><div class="chart-box collapsible collapsed" style="grid-column: 1 / -1;">
        <div class="collapsible-header" onclick="toggleCollapse(this)">
          <span class="collapsible-arrow">&#9660;</span>
          <h3>Resumo por Tag</h3>
        </div>
        <div class="collapsible-body" style="max-height:2000px;">
          <table class="delta-table" style="margin-top:16px;">
            <thead><tr><th>Tag</th><th style="text-align:right">Total</th><th style="text-align:right">% Recorrente</th><th style="text-align:right">% Pontual</th></tr></thead>
            <tbody>${tagEntries.map(([tag, v]) => {
              const isIncome = v > 0;
              const color = isIncome ? 'var(--green)' : 'var(--red)';
              const displayAmt = formatBRL(Math.abs(v));
              const tagRows = rows.filter(r => rowTags(r).includes(tag));
              const recAmt = tagRows.filter(r => r.recurrence === 'recorrente').reduce((s, r) => {
                return s + (isReimbursement(r) ? -r.amount : r.amount);
              }, 0);
              const recPct = v !== 0 ? ((recAmt / v) * 100).toFixed(0) : '0';
              const pontPct = v !== 0 ? (100 - parseFloat(recPct)).toFixed(0) : '0';
              return '<tr><td><span class="cat-badge" style="border-color:' + catColor(tag) + '">' + tag + '</span></td><td style="text-align:right;color:' + color + '" class="privacy-hide">' + displayAmt + '</td><td style="text-align:right">' + recPct + '%</td><td style="text-align:right">' + pontPct + '%</td></tr>';
            }).join('')}</tbody>
          </table>
          ${disclaimer}
        </div>
      </div></div>`;
    })()}
    <div class="table-section collapsible" id="txsection-${month}">
      <div class="collapsible-header" onclick="toggleCollapse(this)">
        <span class="collapsible-arrow">&#9660;</span>
        <h3>Todas as Transacoes</h3>
      </div>
      <div class="collapsible-body" style="max-height:none;">
      <div class="table-controls" style="margin-top:16px;" id="controls-${month}">
        <select id="typefilter-${month}" onchange="filterTable('${month}')">
          <option value="">Todos os tipos</option>
          <option value="extrato">Extrato bancario</option>
          <option value="fatura">Fatura de cartao</option>
        </select>
        <select id="flowfilter-${month}" onchange="filterTable('${month}')">
          <option value="">Gastos e receitas</option>
          <option value="expense">Somente gastos</option>
          <option value="income">Somente receitas</option>
        </select>
        <select id="recfilter-${month}" onchange="filterTable('${month}')">
          <option value="">Todas as recorrencias</option>
          <option value="recorrente">Recorrente</option>
          <option value="pontual">Pontual</option>
        </select>
        <input type="text" id="search-${month}" placeholder="Buscar descricao..." oninput="filterTable('${month}')">
        <button class="clear-filters-btn hidden" id="clearfilters-${month}" onclick="clearFilters('${month}')">Limpar filtros</button>
      </div>
      <div class="filter-subtotals" id="subtotals-${month}"></div>
      <div class="tx-count" id="txcount-${month}"></div>
      <table>
        <thead>
          <tr>
            <th data-col="date" onclick="sortTable('${month}','date')">Data</th>
            <th data-col="description" onclick="sortTable('${month}','description')">Descricao</th>
            <th data-col="supplier_display" onclick="sortTable('${month}','supplier_display')">Fornecedor</th>
            <th data-col="amount" onclick="sortTable('${month}','amount')">Valor</th>
            <th data-col="category" onclick="sortTable('${month}','category')">Categoria</th>
            <th>Tags</th>
            <th data-col="recurrence" onclick="sortTable('${month}','recurrence')">Recorrencia</th>
            <th data-col="bank" onclick="sortTable('${month}','bank')">Banco</th>
            <th data-col="source_type" onclick="sortTable('${month}','source_type')">Tipo</th>
          </tr>
        </thead>
        <tbody id="txbody-${month}"></tbody>
      </table>
      <div class="pagination" id="pagination-${month}"></div>
      </div>
    </div>
  `;

  // Insert multi-select dropdowns into controls
  const controlsEl = document.getElementById(`controls-${month}`);
  const catOptions = [...new Set(rows.map(r => r.category).filter(Boolean))].sort().map(c => ({ value: c, label: catLabel(c) }));
  // Tag options = union of tag tokens across the active month's rows.
  const tagSet = new Set();
  rows.forEach(r => rowTags(r).forEach(t => tagSet.add(t)));
  const tagOptions = [...tagSet].sort().map(t => ({ value: t, label: t }));
  const bankOptions = [...new Set(rows.map(r => bankGroup(r.bank)).filter(Boolean))].sort().map(b => ({ value: b, label: b }));
  const catMS = createMultiSelect(`catfilter-${month}`, 'Todas as categorias', catOptions, month);
  const tagMS = createMultiSelect(`tagfilter-${month}`, 'Todas as tags', tagOptions, month);
  const bankMS = createMultiSelect(`bankfilter-${month}`, 'Todos os bancos', bankOptions, month);
  controlsEl.insertBefore(bankMS, controlsEl.firstChild);
  controlsEl.insertBefore(tagMS, controlsEl.firstChild);
  controlsEl.insertBefore(catMS, controlsEl.firstChild);

  // Pie chart
  const pieCtx = document.getElementById(`pie-${month}`).getContext('2d');
  charts[`pie-${month}`] = new Chart(pieCtx, {
    type: 'doughnut',
    data: {
      labels: categories.map(c => catLabel(c)),
      datasets: [{
        data: catValues,
        backgroundColor: categories.map(catColor),
        borderColor: 'transparent',
        borderWidth: 0
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { position: 'right', labels: { color: '#ffffff', font: { size: 11 }, padding: 8 } },
        tooltip: { callbacks: { label: (ctx) => `${ctx.label}: ${formatBRL(-ctx.parsed)}` } }
      }
    }
  });

  // Bar chart — top 10 by supplier display name (T6 rollup applied).
  const barCtx = document.getElementById(`bar-${month}`).getContext('2d');
  charts[`bar-${month}`] = new Chart(barCtx, {
    type: 'bar',
    data: {
      labels: topSupplierEntries.map(([name]) => name.substring(0, 30)),
      datasets: [{
        data: topSupplierEntries.map(([, v]) => v),
        backgroundColor: topSupplierEntries.map(([name]) => name === SUPPLIER_OUTROS_LABEL ? '#495057' : catColor(name)),
        borderRadius: 4
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (ctx) => `${ctx.label}: ${formatBRL(-ctx.parsed.x)}` } }
      },
      scales: {
        x: { ticks: { color: '#ffffff', callback: v => 'R$ ' + Number(v).toLocaleString('pt-BR') }, grid: { color: '#2e3345' } },
        y: { ticks: { color: '#ffffff', font: { size: 11 } }, grid: { display: false } }
      }
    }
  });

  // Init table state
  window[`tableState_${month}`] = { sort: { col: 'date', dir: 'asc' }, page: 0 };
  filterTable(month);
}

function getFilteredRows(month) {
  // Aggregation site: filter operates on axis-bucketed rows.
  const rows = getMonthRows(month);
  const catFilters = getMultiSelectValues(`catfilter-${month}`);
  const tagFilters = getMultiSelectValues(`tagfilter-${month}`);
  const bankFilters = getMultiSelectValues(`bankfilter-${month}`);
  const typeFilter = document.getElementById(`typefilter-${month}`).value;
  const flowFilter = document.getElementById(`flowfilter-${month}`).value;
  const recFilter = document.getElementById(`recfilter-${month}`).value;
  const search = document.getElementById(`search-${month}`).value.toLowerCase();
  return rows.filter(r => {
    if (catFilters.length > 0 && !catFilters.includes(r.category)) return false;
    // Tag filter — OR semantics: row matches if ANY of its tags is in the
    // selected set. Empty selection = no tag filter applied.
    if (tagFilters.length > 0) {
      const rt = rowTags(r);
      if (!rt.some(t => tagFilters.includes(t))) return false;
    }
    if (bankFilters.length > 0 && !bankFilters.includes(bankGroup(r.bank))) return false;
    if (typeFilter && r.source_type !== typeFilter) return false;
    if (flowFilter === 'expense' && r.amount >= 0) return false;
    if (flowFilter === 'income' && (r.amount <= 0 || EXCLUDED_CATEGORIES.has(r.category))) return false;
    if (recFilter && r.recurrence !== recFilter) return false;
    if (search && !r.description.toLowerCase().includes(search)) return false;
    return true;
  });
}

function sortTable(month, col) {
  const state = window[`tableState_${month}`];
  if (state.sort.col === col) {
    state.sort.dir = state.sort.dir === 'asc' ? 'desc' : 'asc';
  } else {
    const defaultDir = col === 'amount' ? 'desc' : 'asc';
    state.sort = { col, dir: defaultDir };
  }
  state.page = 0;
  filterTable(month);
}

function clearFilters(month) {
  document.getElementById(`typefilter-${month}`).selectedIndex = 0;
  document.getElementById(`flowfilter-${month}`).selectedIndex = 0;
  document.getElementById(`recfilter-${month}`).selectedIndex = 0;
  document.getElementById(`search-${month}`).value = '';
  [`catfilter-${month}`, `tagfilter-${month}`, `bankfilter-${month}`].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.querySelectorAll('input[type="checkbox"]').forEach(cb => { cb.checked = false; });
    updateMultiSelectChips(el);
  });
  window[`tableState_${month}`].page = 0;
  filterTable(month);
}

function isFiltered(month) {
  if (getMultiSelectValues(`catfilter-${month}`).length > 0) return true;
  if (getMultiSelectValues(`tagfilter-${month}`).length > 0) return true;
  if (getMultiSelectValues(`bankfilter-${month}`).length > 0) return true;
  if (document.getElementById(`typefilter-${month}`).value) return true;
  if (document.getElementById(`flowfilter-${month}`).value) return true;
  if (document.getElementById(`recfilter-${month}`).value) return true;
  if (document.getElementById(`search-${month}`).value.trim()) return true;
  return false;
}

function filterTable(month) {
  const state = window[`tableState_${month}`];
  let rows = getFilteredRows(month);
  const { col, dir } = state.sort;
  const filtered = isFiltered(month);

  const supplierMap = window[`supplierMap_${month}`] || new Map();
  rows.sort((a, b) => {
    let va, vb;
    if (col === 'supplier_display') {
      va = supplierDisplayName(a, supplierMap);
      vb = supplierDisplayName(b, supplierMap);
    } else {
      va = a[col]; vb = b[col];
    }
    if (col === 'amount') { va = parseFloat(va) || 0; vb = parseFloat(vb) || 0; }
    if (typeof va === 'string') va = va.toLowerCase();
    if (typeof vb === 'string') vb = vb.toLowerCase();
    if (va < vb) return dir === 'asc' ? -1 : 1;
    if (va > vb) return dir === 'asc' ? 1 : -1;
    return 0;
  });

  // Update sort indicators
  const section = document.getElementById(`txsection-${month}`);
  section.querySelectorAll('th').forEach(th => {
    th.classList.remove('sorted-asc', 'sorted-desc');
    if (th.dataset.col === col) th.classList.add(dir === 'asc' ? 'sorted-asc' : 'sorted-desc');
  });

  // Show/hide clear filters button
  const clearBtn = document.getElementById(`clearfilters-${month}`);
  if (clearBtn) clearBtn.classList.toggle('hidden', !filtered);

  // Subtotals — netted per T4: Gastos sum = negatives + reimbursement
  // positives (which algebraically reduce |expense|). Receitas = positive
  // non-reimbursement rows only. Saldo = Gastos + Receitas.
  const subtotalsEl = document.getElementById(`subtotals-${month}`);
  if (filtered) {
    const expenses = netAmount(rows.filter(r => r.amount < 0 || isReimbursement(r)));
    const income = rows.filter(r => r.amount > 0 && !isReimbursement(r))
      .reduce((s, r) => s + r.amount, 0);
    const net = expenses + income;
    subtotalsEl.innerHTML = `
      <div class="subtotal-item"><span class="subtotal-label">Gastos:</span><span class="subtotal-value privacy-hide" style="color:var(--red)">${formatBRL(expenses)}</span></div>
      <div class="subtotal-divider"></div>
      <div class="subtotal-item"><span class="subtotal-label">Receitas:</span><span class="subtotal-value privacy-hide" style="color:var(--green)">${formatBRL(income)}</span></div>
      <div class="subtotal-divider"></div>
      <div class="subtotal-item"><span class="subtotal-label">Saldo:</span><span class="subtotal-value privacy-hide" style="color:${net >= 0 ? 'var(--green)' : 'var(--red)'}">${formatBRL(net)}</span></div>
      <div class="subtotal-divider"></div>
      <div class="subtotal-item"><span class="subtotal-label">Transacoes:</span><span class="subtotal-value">${rows.length}</span></div>
    `;
    subtotalsEl.classList.add('active');
  } else {
    subtotalsEl.classList.remove('active');
  }

  const total = rows.length;
  const pages = Math.ceil(total / ROWS_PER_PAGE);
  if (state.page >= pages) state.page = Math.max(0, pages - 1);
  const start = state.page * ROWS_PER_PAGE;
  const pageRows = rows.slice(start, start + ROWS_PER_PAGE);

  document.getElementById(`txcount-${month}`).textContent = `${total} transacoes encontradas`;

  const tbody = document.getElementById(`txbody-${month}`);
  tbody.innerHTML = pageRows.map(r => {
    const amtClass = r.amount < 0 ? 'amount-neg' : 'amount-pos';
    // Tags column: render each tag as its own .cat-badge pill (reuses existing
    // badge styles). Empty cell = blank when row has zero tags.
    const tagBadges = rowTags(r).map(t =>
      `<span class="cat-badge" style="border-color:${catColor(t)}">${t}</span>`
    ).join(' ');
    const recBadge = r.recurrence ? `<span class="cat-badge" style="border-color:${r.recurrence === 'recorrente' ? 'var(--accent2)' : 'var(--orange)'}">${r.recurrence === 'recorrente' ? 'Rec' : 'Pont'}</span>` : '';
    const supDisplay = supplierDisplayName(r, supplierMap);
    const supTitle = (r.supplier_canonical && r.supplier_canonical !== supDisplay)
      ? ` title="canonical: ${r.supplier_canonical}"` : '';
    const supStyle = supDisplay === SUPPLIER_OUTROS_LABEL ? ' style="color:var(--text-muted);font-style:italic;"' : '';
    return `<tr>
      <td>${r.date}</td>
      <td>${r.description}</td>
      <td${supTitle}${supStyle}>${supDisplay}</td>
      <td class="${amtClass} privacy-hide">${formatBRL(r.amount)}</td>
      <td><span class="cat-badge" style="border-color:${catColor(r.category)}">${catLabel(r.category || '-')}</span></td>
      <td>${tagBadges}</td>
      <td>${recBadge}</td>
      <td>${bankName(r.bank) || '-'}</td>
      <td>${r.source_type || '-'}</td>
    </tr>`;
  }).join('');

  const pagEl = document.getElementById(`pagination-${month}`);
  if (pages > 1) {
    pagEl.innerHTML = `
      <button onclick="changePage('${month}',-1)" ${state.page === 0 ? 'disabled' : ''}>Anterior</button>
      <span>${state.page + 1} de ${pages}</span>
      <button onclick="changePage('${month}',1)" ${state.page >= pages - 1 ? 'disabled' : ''}>Proxima</button>
    `;
  } else {
    pagEl.innerHTML = '';
  }
}

function changePage(month, delta) {
  window[`tableState_${month}`].page += delta;
  filterTable(month);
}

function renderEvolutionTab(months, container) {
  if (months.length < 1) { container.innerHTML = '<div class="loading">Dados insuficientes para evolucao.</div>'; return; }
  window._evoMonths = months;

  // Collect filter options from the union of all loaded rows. Filter
  // dictionaries are axis-independent (categories, tags, banks
  // exist on the row regardless of which date column drives bucketing).
  const _allRows = Object.values(allData).flat();
  const allCatOptions = [...new Set(_allRows.map(r => r.category).filter(Boolean))].sort().map(c => ({ value: c, label: catLabel(c) }));
  // Tag options for Evolução = union of tag tokens across ALL loaded rows.
  const allTagSet = new Set();
  _allRows.forEach(r => rowTags(r).forEach(t => allTagSet.add(t)));
  const allTagOptions = [...allTagSet].sort().map(t => ({ value: t, label: t }));
  const allBankOptions = [...new Set(_allRows.map(r => bankGroup(r.bank)).filter(Boolean))].sort().map(b => ({ value: b, label: b }));

  container.innerHTML = `
    <div class="table-controls" id="evo-controls" style="margin-bottom:16px;">
      <select id="evo-typefilter" onchange="updateEvolutionView()">
        <option value="">Todos os tipos</option>
        <option value="extrato">Extrato bancario</option>
        <option value="fatura">Fatura de cartao</option>
      </select>
      <select id="evo-flowfilter" onchange="updateEvolutionView()">
        <option value="">Gastos e receitas</option>
        <option value="expense">Somente gastos</option>
        <option value="income">Somente receitas</option>
      </select>
      <select id="evo-recfilter" onchange="updateEvolutionView()">
        <option value="">Todas as recorrencias</option>
        <option value="recorrente">Recorrente</option>
        <option value="pontual">Pontual</option>
      </select>
      <input type="text" id="evo-search" placeholder="Buscar descricao..." oninput="updateEvolutionView()">
      <button class="clear-filters-btn hidden" id="evo-clearfilters" onclick="clearEvoFilters()">Limpar filtros</button>
    </div>
    <div class="filter-subtotals" id="evo-subtotals"></div>
    <div id="evo-data"></div>
  `;

  // Insert multi-select dropdowns
  const controlsEl = document.getElementById('evo-controls');
  const catMS = createMultiSelect('evo-catfilter', 'Todas as categorias', allCatOptions, null, updateEvolutionView);
  const tagMS = createMultiSelect('evo-tagfilter', 'Todas as tags', allTagOptions, null, updateEvolutionView);
  const bankMS = createMultiSelect('evo-bankfilter', 'Todos os bancos', allBankOptions, null, updateEvolutionView);
  controlsEl.insertBefore(bankMS, controlsEl.firstChild);
  controlsEl.insertBefore(tagMS, controlsEl.firstChild);
  controlsEl.insertBefore(catMS, controlsEl.firstChild);

  updateEvolutionView();
}

function getEvoFilteredData() {
  const months = window._evoMonths;
  const catFilters = getMultiSelectValues('evo-catfilter');
  const tagFilters = getMultiSelectValues('evo-tagfilter');
  const bankFilters = getMultiSelectValues('evo-bankfilter');
  const typeFilter = document.getElementById('evo-typefilter').value;
  const flowFilter = document.getElementById('evo-flowfilter').value;
  const recFilter = document.getElementById('evo-recfilter').value;
  const search = document.getElementById('evo-search').value.toLowerCase();
  const result = {};
  months.forEach(m => {
    // Aggregation site: each evolution-month bucket is sourced through
    // the active date axis, not the file-of-origin month.
    result[m] = getMonthRows(m).filter(r => {
      if (catFilters.length > 0 && !catFilters.includes(r.category)) return false;
      // Tag filter — OR semantics (matches per-month tab behavior).
      if (tagFilters.length > 0) {
        const rt = rowTags(r);
        if (!rt.some(t => tagFilters.includes(t))) return false;
      }
      if (bankFilters.length > 0 && !bankFilters.includes(bankGroup(r.bank))) return false;
      if (typeFilter && r.source_type !== typeFilter) return false;
      if (flowFilter === 'expense' && r.amount >= 0) return false;
      if (flowFilter === 'income' && (r.amount <= 0 || EXCLUDED_CATEGORIES.has(r.category))) return false;
      if (recFilter && r.recurrence !== recFilter) return false;
      if (search && !r.description.toLowerCase().includes(search)) return false;
      return true;
    });
  });
  return result;
}

function isEvoFiltered() {
  if (getMultiSelectValues('evo-catfilter').length > 0) return true;
  if (getMultiSelectValues('evo-tagfilter').length > 0) return true;
  if (getMultiSelectValues('evo-bankfilter').length > 0) return true;
  if (document.getElementById('evo-typefilter').value) return true;
  if (document.getElementById('evo-flowfilter').value) return true;
  if (document.getElementById('evo-recfilter').value) return true;
  if (document.getElementById('evo-search').value.trim()) return true;
  return false;
}

function clearEvoFilters() {
  document.getElementById('evo-typefilter').selectedIndex = 0;
  document.getElementById('evo-flowfilter').selectedIndex = 0;
  document.getElementById('evo-recfilter').selectedIndex = 0;
  document.getElementById('evo-search').value = '';
  ['evo-catfilter', 'evo-tagfilter', 'evo-bankfilter'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.querySelectorAll('input[type="checkbox"]').forEach(cb => { cb.checked = false; });
    updateMultiSelectChips(el);
  });
  updateEvolutionView();
}

function updateEvolutionView() {
  const months = window._evoMonths;
  const filteredData = getEvoFilteredData();
  const filtered = isEvoFiltered();

  // Destroy existing evo charts
  ['evo-line', 'evo-recurrence', 'evo-stacked'].forEach(key => {
    if (charts[key]) { charts[key].destroy(); delete charts[key]; }
  });

  // Show/hide clear filters button
  const clearBtn = document.getElementById('evo-clearfilters');
  if (clearBtn) clearBtn.classList.toggle('hidden', !filtered);

  // Compute totals from filtered data — netted per T4. Each month aggregates
  // negative-amount expense rows AND reimbursement rows; reimbursements
  // subtract from their category's total.
  const allCats = new Set();
  const monthCatTotals = {};
  const monthTotals = {};
  months.forEach(m => {
    monthCatTotals[m] = {};
    const monthRows = filteredData[m];
    const expensesNet = monthRows.filter(r =>
      (r.amount < 0 || isReimbursement(r)) && !EXCLUDED_CATEGORIES.has(r.category)
    );
    expensesNet.forEach(r => {
      const c = r.category || 'a_identificar';
      allCats.add(c);
      const contrib = r.amount < 0 ? Math.abs(r.amount) : -r.amount;
      monthCatTotals[m][c] = (monthCatTotals[m][c] || 0) + contrib;
    });
    monthTotals[m] = netAbsAmount(expensesNet);
  });

  const monthRecTotals = {};
  months.forEach(m => {
    const monthRows = filteredData[m];
    const expensesNet = monthRows.filter(r =>
      (r.amount < 0 || isReimbursement(r)) && !EXCLUDED_CATEGORIES.has(r.category)
    );
    const sumNetAbs = (subset) => subset.reduce((s, r) => {
      return s + (r.amount < 0 ? Math.abs(r.amount) : -r.amount);
    }, 0);
    monthRecTotals[m] = {
      recorrente: sumNetAbs(expensesNet.filter(r => r.recurrence === 'recorrente')),
      pontual: sumNetAbs(expensesNet.filter(r => r.recurrence === 'pontual'))
    };
  });

  const sortedCats = [...allCats].sort((a, b) => {
    const totalA = months.reduce((s, m) => s + (monthCatTotals[m][a] || 0), 0);
    const totalB = months.reduce((s, m) => s + (monthCatTotals[m][b] || 0), 0);
    return totalB - totalA;
  });

  // Subtotals when filtered — netted per T4. Total Receitas explicitly
  // EXCLUDES reimbursements (they are negative-expense, not income).
  const subtotalsEl = document.getElementById('evo-subtotals');
  if (filtered) {
    const totalExpAll = months.reduce((s, m) => {
      const expensesNet = filteredData[m].filter(r =>
        (r.amount < 0 || isReimbursement(r)) && !EXCLUDED_CATEGORIES.has(r.category)
      );
      return s + netAmount(expensesNet);
    }, 0);
    const totalIncAll = months.reduce((s, m) =>
      s + filteredData[m]
        .filter(r => r.amount > 0 && r.category === 'receitas' && !isReimbursement(r))
        .reduce((s2, r) => s2 + r.amount, 0)
    , 0);
    const totalTx = months.reduce((s, m) => s + filteredData[m].length, 0);
    subtotalsEl.innerHTML = `
      <div class="subtotal-item"><span class="subtotal-label">Total Gastos:</span><span class="subtotal-value privacy-hide" style="color:var(--red)">${formatBRL(totalExpAll)}</span></div>
      <div class="subtotal-divider"></div>
      <div class="subtotal-item"><span class="subtotal-label">Total Receitas:</span><span class="subtotal-value privacy-hide" style="color:var(--green)">${formatBRL(totalIncAll)}</span></div>
      <div class="subtotal-divider"></div>
      <div class="subtotal-item"><span class="subtotal-label">Transacoes:</span><span class="subtotal-value">${totalTx}</span></div>
    `;
    subtotalsEl.classList.add('active');
  } else {
    subtotalsEl.innerHTML = '';
    subtotalsEl.classList.remove('active');
  }

  // Preserve collapsed state before re-rendering
  const dataContainer = document.getElementById('evo-data');
  const collapsedState = [];
  dataContainer.querySelectorAll('.evo-chart-box.collapsible').forEach((el, i) => {
    collapsedState[i] = el.classList.contains('collapsed');
  });
  dataContainer.innerHTML = `
    <div class="cards" id="evo-cards">
      ${months.map(m => `
        <div class="card">
          <div class="card-label">${formatMonth(m)}</div>
          <div class="card-value expense privacy-hide">${formatBRL(-monthTotals[m])}</div>
        </div>
      `).join('')}
    </div>
    <div class="evo-chart-box collapsible">
      <div class="collapsible-header" onclick="toggleCollapse(this)">
        <span class="collapsible-arrow">&#9660;</span>
        <h3>Evolucao Total de Gastos</h3>
      </div>
      <div class="collapsible-body" style="max-height:2000px;">
        <canvas id="evo-line"></canvas>
      </div>
    </div>
    <div class="evo-chart-box collapsible">
      <div class="collapsible-header" onclick="toggleCollapse(this)">
        <span class="collapsible-arrow">&#9660;</span>
        <h3>Recorrente vs Pontual</h3>
      </div>
      <div class="collapsible-body" style="max-height:2000px;">
        <canvas id="evo-recurrence"></canvas>
      </div>
    </div>
    <div class="evo-chart-box collapsible">
      <div class="collapsible-header" onclick="toggleCollapse(this)">
        <span class="collapsible-arrow">&#9660;</span>
        <h3>Gastos por Categoria (Empilhado)</h3>
      </div>
      <div class="collapsible-body" style="max-height:2000px;">
        <canvas id="evo-stacked"></canvas>
      </div>
    </div>
    <div class="evo-chart-box collapsible">
      <div class="collapsible-header" onclick="toggleCollapse(this)">
        <span class="collapsible-arrow">&#9660;</span>
        <h3>Comparativo Mensal por Categoria</h3>
      </div>
      <div class="collapsible-body" style="max-height:2000px;">
        <table class="delta-table" style="margin-top:0;">
          <thead>
            <tr>
              <th>Categoria</th>
              ${months.map(m => `<th style="text-align:right">${formatMonth(m)}</th>`).join('')}
              ${months.length >= 2 ? '<th style="text-align:right">Variacao</th>' : ''}
            </tr>
          </thead>
          <tbody>
            ${sortedCats.map(c => {
              const vals = months.map(m => monthCatTotals[m][c] || 0);
              let deltaHtml = '';
              if (months.length >= 2) {
                const prev = vals[vals.length - 2];
                const curr = vals[vals.length - 1];
                if (prev === 0 && curr === 0) {
                  deltaHtml = '<td class="delta-zero" style="text-align:right">-</td>';
                } else if (prev === 0) {
                  deltaHtml = '<td class="delta-pos" style="text-align:right">Novo</td>';
                } else {
                  const pct = ((curr - prev) / prev * 100).toFixed(0);
                  const cls = pct > 0 ? 'delta-pos' : pct < 0 ? 'delta-neg' : 'delta-zero';
                  deltaHtml = `<td class="${cls}" style="text-align:right">${pct > 0 ? '+' : ''}${pct}%</td>`;
                }
              }
              return `<tr>
                <td><span class="cat-badge" style="border-color:${catColor(c)}">${catLabel(c)}</span></td>
                ${vals.map(v => `<td style="text-align:right" class="privacy-hide">${v > 0 ? formatBRL(-v) : '-'}</td>`).join('')}
                ${deltaHtml}
              </tr>`;
            }).join('')}
            <tr style="font-weight:700; border-top: 2px solid var(--border)">
              <td>Total</td>
              ${months.map(m => `<td style="text-align:right" class="privacy-hide">${formatBRL(-monthTotals[m])}</td>`).join('')}
              ${months.length >= 2 ? (() => {
                const prev = monthTotals[months[months.length-2]];
                const curr = monthTotals[months[months.length-1]];
                if (prev === 0) return '<td class="delta-zero" style="text-align:right">-</td>';
                const pct = ((curr - prev) / prev * 100).toFixed(0);
                const cls = pct > 0 ? 'delta-pos' : pct < 0 ? 'delta-neg' : 'delta-zero';
                return `<td class="${cls}" style="text-align:right">${pct > 0 ? '+' : ''}${pct}%</td>`;
              })() : ''}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `;

  // Restore collapsed state
  if (collapsedState.length > 0) {
    dataContainer.querySelectorAll('.evo-chart-box.collapsible').forEach((el, i) => {
      if (collapsedState[i]) el.classList.add('collapsed');
    });
  }

  // Line chart — total trend
  const lineCtx = document.getElementById('evo-line').getContext('2d');
  charts['evo-line'] = new Chart(lineCtx, {
    type: 'line',
    data: {
      labels: months.map(formatMonth),
      datasets: [{
        label: 'Total Gastos',
        data: months.map(m => monthTotals[m]),
        borderColor: '#ff6b6b',
        backgroundColor: 'rgba(255,107,107,0.1)',
        fill: true,
        tension: 0.3,
        pointRadius: 6,
        pointHoverRadius: 8
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => formatBRL(-ctx.parsed.y) } }
      },
      scales: {
        y: { beginAtZero: true, ticks: { color: '#ffffff', callback: v => 'R$ ' + (v/1000).toFixed(0) + 'k' }, grid: { color: '#2e3345' } },
        x: { ticks: { color: '#ffffff' }, grid: { display: false } }
      }
    }
  });

  // Recurrence stacked bar chart
  const recCtx = document.getElementById('evo-recurrence').getContext('2d');
  charts['evo-recurrence'] = new Chart(recCtx, {
    type: 'bar',
    data: {
      labels: months.map(formatMonth),
      datasets: [
        {
          label: 'Recorrente',
          data: months.map(m => monthRecTotals[m].recorrente),
          backgroundColor: '#4ecdc4',
          borderRadius: 2
        },
        {
          label: 'Pontual',
          data: months.map(m => monthRecTotals[m].pontual),
          backgroundColor: '#ffa94d',
          borderRadius: 2
        }
      ]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { position: 'bottom', labels: { color: '#ffffff', font: { size: 11 }, padding: 12 } },
        tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${formatBRL(-ctx.parsed.y)}` } }
      },
      scales: {
        x: { stacked: true, ticks: { color: '#ffffff' }, grid: { display: false } },
        y: { stacked: true, ticks: { color: '#ffffff', callback: v => 'R$ ' + (v/1000).toFixed(0) + 'k' }, grid: { color: '#2e3345' } }
      }
    }
  });

  // Stacked bar chart
  const stackedCtx = document.getElementById('evo-stacked').getContext('2d');
  const topCats = sortedCats.slice(0, 12);
  const otherCats = sortedCats.slice(12);
  const datasets = topCats.map(c => ({
    label: catLabel(c),
    data: months.map(m => monthCatTotals[m][c] || 0),
    backgroundColor: catColor(c),
    borderRadius: 2
  }));
  if (otherCats.length > 0) {
    datasets.push({
      label: 'Outros',
      data: months.map(m => otherCats.reduce((s, c) => s + (monthCatTotals[m][c] || 0), 0)),
      backgroundColor: '#495057',
      borderRadius: 2
    });
  }

  charts['evo-stacked'] = new Chart(stackedCtx, {
    type: 'bar',
    data: { labels: months.map(formatMonth), datasets },
    options: {
      responsive: true,
      plugins: {
        legend: { position: 'bottom', labels: { color: '#ffffff', font: { size: 11 }, padding: 12 } },
        tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${formatBRL(-ctx.parsed.y)}` } }
      },
      scales: {
        x: { stacked: true, ticks: { color: '#ffffff' }, grid: { display: false } },
        y: { stacked: true, ticks: { color: '#ffffff', callback: v => 'R$ ' + (v/1000).toFixed(0) + 'k' }, grid: { color: '#2e3345' } }
      }
    }
  });

  // Apply privacy to new charts if active
  if (document.body.classList.contains('privacy-mode')) {
    updateChartsPrivacy(true);
  }
}

init();
