// Investment dashboard — Bolsa view.
// Pure renderer: reads state from inv-data.js. No fetch, no computation.
// Loaded after shared.js and inv-data.js.

const INV_BOLSA_PERIODS = [
  { key: '1d',  label: '1d' },
  { key: '30d', label: '30d' },
  { key: '90d', label: '90d' },
  { key: '180d', label: '180d' },
  { key: '365d', label: '365d' },
  { key: 'ytd', label: 'YTD' }
];

// Asset types that can never be fractional on B3.
const INV_BOLSA_INTEGER_TYPES = new Set(['acao', 'opcao', 'direito_subscricao', 'bdr']);

let invBolsaSortState = { col: 'current_value', dir: 'desc' };
let invBolsaBrokerFilter = 'all';
let invBolsaCurrencyView = 'native'; // 'native' | 'brl' — affects table only
let invBolsaSectionsOpen = { positions: true, sector: true };

// Fields that swap between native and BRL when the currency-view toggle changes.
const INV_BOLSA_BRL_FIELDS = {
  cost_basis: 'cost_basis_brl',
  current_value: 'current_value_brl',
  pnl_absolute: 'pnl_absolute_brl',
  total_dividends: 'total_dividends_brl'
};

function invBolsaRender(container) {
  const portfolio = invGetPortfolio();
  if (!portfolio) {
    const err = invGetLoadError() || 'Execute calculate.py para gerar dados.';
    container.innerHTML = `<div class="loading" style="color:var(--red)">${err}</div>`;
    return;
  }

  const all = invPositionsByMethod('price');
  if (all.length === 0) {
    container.innerHTML = `<div class="loading">Nenhuma posição em bolsa encontrada.</div>`;
    return;
  }

  const brokers = [...new Set(all.map(p => p.broker).filter(Boolean))].sort();
  if (invBolsaBrokerFilter !== 'all' && !brokers.includes(invBolsaBrokerFilter)) {
    invBolsaBrokerFilter = 'all';
  }
  const positions = invBolsaBrokerFilter === 'all'
    ? all
    : all.filter(p => p.broker === invBolsaBrokerFilter);

  const sorted = invBolsaSort(positions, invBolsaSortState.col, invBolsaSortState.dir);

  container.innerHTML = [
    invBolsaFilterBar(brokers, all.length, positions.length),
    invBolsaSummaryCards(positions),
    invBolsaCollapsible('positions', 'Posições em bolsa', invBolsaPositionsTable(sorted)),
    invBolsaCollapsible('sector', 'Resumo por setor', invBolsaSectorSummary(positions))
  ].join('');

  invBolsaAttachBrokerHandler(container);
  invBolsaAttachCurrencyHandler(container);
  invBolsaAttachRefreshHandler(container);
  invBolsaAttachSortHandlers(container);
  invBolsaAttachCollapsibleHandlers(container);
}

// --- Filter bar: broker filter + currency view toggle ---

function invBolsaFilterBar(brokers, totalCount, filteredCount) {
  const brokerOpts = ['<option value="all">Todas as corretoras</option>']
    .concat(brokers.map(b => {
      const sel = b === invBolsaBrokerFilter ? ' selected' : '';
      return `<option value="${b}"${sel}>${invBolsaBrokerLabel(b)}</option>`;
    }))
    .join('');
  const note = invBolsaBrokerFilter === 'all'
    ? `${totalCount} posições`
    : `${filteredCount} de ${totalCount} posições`;
  const selStyle = 'padding:6px 10px;border-radius:6px;border:1px solid var(--border);background:var(--bg);color:var(--text)';
  const btnStyle = 'padding:6px 12px;border-radius:6px;border:1px solid var(--border);background:var(--surface2);color:var(--text);cursor:pointer;font-size:0.85rem;display:inline-flex;align-items:center;gap:6px';
  const nativeSel = invBolsaCurrencyView === 'native' ? ' selected' : '';
  const brlSel = invBolsaCurrencyView === 'brl' ? ' selected' : '';
  return `
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;flex-wrap:wrap">
      <label style="font-size:0.85rem;color:var(--text-muted)">Corretora:</label>
      <select id="inv-bolsa-broker-filter" style="${selStyle}">${brokerOpts}</select>
      <span style="font-size:0.8rem;color:var(--text-muted)">${note}</span>
      <span style="flex:1"></span>
      <button id="inv-bolsa-refresh" style="${btnStyle}" title="Busca preços atuais via API (brapi/yfinance/CoinGecko) e regrava portfolio.json">
        <span id="inv-bolsa-refresh-icon">↻</span>
        <span id="inv-bolsa-refresh-label">Atualizar preços</span>
      </button>
      <label style="font-size:0.85rem;color:var(--text-muted)">Moeda (tabela):</label>
      <select id="inv-bolsa-currency-view" title="Afeta apenas as tabelas; os cards de resumo permanecem sempre em BRL" style="${selStyle}">
        <option value="native"${nativeSel}>Original (USD/BRL)</option>
        <option value="brl"${brlSel}>Tudo em BRL</option>
      </select>
    </div>
  `;
}

function invBolsaAttachRefreshHandler(container) {
  const btn = container.querySelector('#inv-bolsa-refresh');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    if (btn.disabled) return;
    const icon = btn.querySelector('#inv-bolsa-refresh-icon');
    const label = btn.querySelector('#inv-bolsa-refresh-label');
    btn.disabled = true;
    btn.style.opacity = '0.6';
    btn.style.cursor = 'wait';
    if (icon) icon.style.animation = 'spin 0.8s linear infinite';
    if (icon) icon.style.display = 'inline-block';
    if (label) label.textContent = 'Atualizando...';
    try {
      const res = await fetch('/api/refresh-prices', { method: 'POST' });
      const body = await res.json().catch(() => ({}));
      if (!res.ok || body.ok === false) {
        const msg = body.error || (body.stderr ? body.stderr.split('\n').slice(-3).join(' ') : `HTTP ${res.status}`);
        invBolsaToast(`Falha ao atualizar: ${msg}`, 'error');
        return;
      }
      await invLoadPortfolio(invGetCurrentSnapshot());
      invBolsaRender(container);
      invBolsaToast('Preços atualizados.', 'success');
    } catch (e) {
      invBolsaToast(`Erro: ${e.message}`, 'error');
    } finally {
      const btn2 = container.querySelector('#inv-bolsa-refresh');
      if (btn2) {
        btn2.disabled = false;
        btn2.style.opacity = '';
        btn2.style.cursor = 'pointer';
      }
    }
  });
}

function invBolsaToast(message, kind) {
  const existing = document.getElementById('inv-bolsa-toast');
  if (existing) existing.remove();
  const el = document.createElement('div');
  el.id = 'inv-bolsa-toast';
  const bg = kind === 'error' ? 'var(--red)' : (kind === 'success' ? 'var(--green)' : 'var(--surface2)');
  el.style.cssText = `position:fixed;right:20px;bottom:20px;z-index:9999;background:${bg};color:#fff;padding:10px 16px;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.3);font-size:0.9rem;max-width:420px`;
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => { el.style.transition = 'opacity 0.4s'; el.style.opacity = '0'; }, 3600);
  setTimeout(() => { el.remove(); }, 4200);
}

function invBolsaBrokerLabel(b) {
  if (!b) return '—';
  return b.charAt(0).toUpperCase() + b.slice(1);
}

function invBolsaAttachBrokerHandler(container) {
  const sel = container.querySelector('#inv-bolsa-broker-filter');
  if (!sel) return;
  sel.addEventListener('change', () => {
    invBolsaBrokerFilter = sel.value;
    invBolsaRender(container);
  });
}

function invBolsaAttachCurrencyHandler(container) {
  const sel = container.querySelector('#inv-bolsa-currency-view');
  if (!sel) return;
  sel.addEventListener('change', () => {
    invBolsaCurrencyView = sel.value;
    invBolsaRender(container);
  });
}

// Display-currency and display-value for a money field, respecting toggle.
function invBolsaDisplayCurrency(p) {
  return invBolsaCurrencyView === 'brl' ? 'BRL' : p.currency;
}
function invBolsaDisplayValue(p, nativeKey) {
  if (invBolsaCurrencyView === 'brl' && INV_BOLSA_BRL_FIELDS[nativeKey]) {
    return p[INV_BOLSA_BRL_FIELDS[nativeKey]];
  }
  return p[nativeKey];
}

// --- Collapsible wrapper ---

function invBolsaCollapsible(key, title, innerHtml) {
  const open = invBolsaSectionsOpen[key] ? ' open' : '';
  return `
    <details class="inv-bolsa-collapsible" data-section="${key}"${open} style="margin-top:24px">
      <summary style="cursor:pointer;font-size:1.1rem;font-weight:600;padding:8px 0;user-select:none">${title}</summary>
      <div style="margin-top:12px">${innerHtml}</div>
    </details>
  `;
}

function invBolsaAttachCollapsibleHandlers(container) {
  container.querySelectorAll('details.inv-bolsa-collapsible').forEach(d => {
    d.addEventListener('toggle', () => {
      const key = d.dataset.section;
      if (key) invBolsaSectionsOpen[key] = d.open;
    });
  });
}

// --- Summary cards ---

function invBolsaSummaryCards(positions) {
  // Summary cards ALWAYS aggregate in BRL (sum *_brl fields). Cross-currency
  // sums are only meaningful with a normalized currency — the currency toggle
  // affects tables only, not cards.
  const total = positions.reduce((s, p) => s + (p.current_value_brl || 0), 0);
  const cost = positions.reduce((s, p) => s + (p.cost_basis_brl || 0), 0);
  const pnl = positions.reduce((s, p) => s + (p.pnl_absolute_brl || 0), 0);
  const dividends = positions.reduce((s, p) => s + (p.total_dividends_brl || 0), 0);
  const pnlPct = cost > 0 ? pnl / cost : 0;

  return `
    <div class="cards">
      <div class="card"><div class="card-label">Valor Bolsa</div><div class="card-value privacy-hide">${formatBRL(total)}</div></div>
      <div class="card"><div class="card-label">Custo</div><div class="card-value privacy-hide">${formatBRL(cost)}</div></div>
      <div class="card">
        <div class="card-label">P&amp;L</div>
        <div class="card-value privacy-hide" style="color:${pnl >= 0 ? 'var(--green)' : 'var(--red)'}">${formatBRL(pnl)}</div>
        <div class="privacy-hide" style="font-size:0.8rem;color:var(--text-muted);">${invFormatPctValue(pnlPct)}</div>
      </div>
      <div class="card"><div class="card-label">Proventos recebidos</div><div class="card-value privacy-hide">${formatBRL(dividends)}</div></div>
      <div class="card"><div class="card-label">Tickers</div><div class="card-value">${positions.length}</div></div>
    </div>
  `;
}

// --- Sector summary ---

function invBolsaSectorSummary(positions) {
  // Sector aggregation always in BRL (cross-currency sums require a common unit).
  const bySector = {};
  let totalValue = 0;
  positions.forEach(p => {
    const s = p.sector || '—';
    if (!bySector[s]) bySector[s] = { sector: s, value: 0, cost: 0, pnl: 0, count: 0 };
    bySector[s].value += p.current_value_brl || 0;
    bySector[s].cost += p.cost_basis_brl || 0;
    bySector[s].pnl += p.pnl_absolute_brl || 0;
    bySector[s].count += 1;
    totalValue += p.current_value_brl || 0;
  });
  const rows = Object.values(bySector).sort((a, b) => b.value - a.value);

  let html = `<table><thead><tr>
    <th>Setor</th>
    <th style="text-align:right">Tickers</th>
    <th style="text-align:right">Valor</th>
    <th style="text-align:right">% carteira bolsa</th>
    <th style="text-align:right">P&amp;L</th>
  </tr></thead><tbody>`;
  rows.forEach(r => {
    const pct = totalValue > 0 ? r.value / totalValue : 0;
    const color = r.pnl >= 0 ? 'var(--green)' : 'var(--red)';
    html += `<tr>
      <td>${r.sector}</td>
      <td style="text-align:right">${r.count}</td>
      <td class="privacy-hide" style="text-align:right">${formatBRL(r.value)}</td>
      <td style="text-align:right">${invFormatPct(pct)}</td>
      <td class="privacy-hide" style="text-align:right;color:${color}">${formatBRL(r.pnl)}</td>
    </tr>`;
  });
  html += `</tbody></table>`;
  return html;
}

// --- Positions table (with price variation) ---

const INV_BOLSA_COLUMNS = [
  { key: 'id',              label: 'Ticker',       align: 'left' },
  { key: 'quantity',        label: 'Qtd',          align: 'right', privacy: true,  format: 'qty' },
  { key: 'current_price',   label: 'Preço',        align: 'right', privacy: false, format: 'money' },
  { key: 'avg_cost',        label: 'PM',           align: 'right', privacy: true,  format: 'money' },
  { key: 'current_value',   label: 'Valor',        align: 'right', privacy: true,  format: 'money' },
  { key: 'pnl_absolute',    label: 'P&L',          align: 'right', privacy: true,  format: 'pnl' },
  { key: 'pnl_pct',         label: 'Retorno %',    align: 'right', privacy: true,  format: 'pct' },
  { key: 'total_dividends', label: 'Proventos',    align: 'right', privacy: true,  format: 'money' },
  { key: 'yoc_lifetime',    label: 'YoC LT',       align: 'right', privacy: false, format: 'pct' },
  { key: 'yoc_ttm',         label: 'YoC TTM',      align: 'right', privacy: false, format: 'pct' },
  { key: 'first_purchase',  label: '1ª compra',    align: 'left',  format: 'date' }
];

function invBolsaPositionsTable(rows) {
  let html = `<div style="overflow-x:auto"><table class="inv-bolsa-table"><thead><tr>`;
  INV_BOLSA_COLUMNS.forEach(col => {
    const arrow = invBolsaSortState.col === col.key ? (invBolsaSortState.dir === 'asc' ? ' ▲' : ' ▼') : '';
    html += `<th data-sort="${col.key}" style="cursor:pointer;text-align:${col.align}">${col.label}${arrow}</th>`;
  });
  INV_BOLSA_PERIODS.forEach(p => {
    html += `<th style="text-align:right">${p.label}</th>`;
  });
  html += `<th>Fonte</th></tr></thead><tbody>`;

  if (rows.length === 0) {
    html += `<tr><td colspan="${INV_BOLSA_COLUMNS.length + INV_BOLSA_PERIODS.length + 1}" style="text-align:center;color:var(--text-muted)">Nenhum dado</td></tr>`;
  }

  rows.forEach(p => {
    html += `<tr>`;
    INV_BOLSA_COLUMNS.forEach(col => {
      html += `<td style="text-align:${col.align}" class="${col.privacy ? 'privacy-hide' : ''}">${invBolsaFormatCell(p, col)}</td>`;
    });
    INV_BOLSA_PERIODS.forEach(per => {
      const v = p.price_changes ? p.price_changes[per.key] : null;
      html += `<td style="text-align:right">${invBolsaFormatChange(v)}</td>`;
    });
    const dot = invPriceSourceDot(p);
    html += `<td><span title="${dot.label}" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${dot.color};margin-right:6px;"></span>${dot.label}</td>`;
    html += `</tr>`;
  });

  html += `</tbody></table></div>`;
  return html;
}

function invBolsaFormatCell(p, col) {
  if (col.key === 'id') return `<strong>${p.id}</strong>${p.name ? `<div style="font-size:0.75rem;color:var(--text-muted)">${p.name}</div>` : ''}`;
  if (col.key === 'first_purchase') return p.first_purchase_date ? invFormatBrDate(p.first_purchase_date) : '—';
  if (p.price_source === 'missing' && (col.key === 'current_price' || col.key === 'current_value' || col.key === 'pnl_absolute' || col.key === 'pnl_pct')) return '—';
  // Resolve value + display currency based on currency-view toggle.
  const v = (col.format === 'money' || col.format === 'pnl') ? invBolsaDisplayValue(p, col.key) : p[col.key];
  const displayCcy = invBolsaDisplayCurrency(p);
  if (v == null || v === '') return '—';
  if ((col.key === 'yoc_lifetime' || col.key === 'yoc_ttm') && v === 0) return '—';
  // `current_price` and `avg_cost` are always native per-unit quantities.
  // `current_value`, `cost_basis`, `pnl_absolute`, `total_dividends` swap
  // between native and BRL depending on the toggle.
  if (col.format === 'money') {
    const ccy = (col.key === 'current_price' || col.key === 'avg_cost') ? p.currency : displayCcy;
    return invBolsaFormatMoney(v, ccy);
  }
  if (col.format === 'qty') return invBolsaFormatQty(v, p);
  if (col.format === 'pct') return invFormatPctValue(v);
  if (col.format === 'pnl') {
    const color = v >= 0 ? 'var(--green)' : 'var(--red)';
    return `<span style="color:${color}">${invBolsaFormatMoney(v, displayCcy)}</span>`;
  }
  return v;
}

function invBolsaFormatMoney(v, currency) {
  const n = typeof v === 'number' ? v : parseFloat(v) || 0;
  if (currency === 'USD') {
    const abs = Math.abs(n);
    const formatted = abs.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return (n < 0 ? '-' : '') + 'US$ ' + formatted;
  }
  return formatBRL(n);
}

function invBolsaFormatQty(v, p) {
  if (typeof v !== 'number') return v;
  if (INV_BOLSA_INTEGER_TYPES.has(p.type) && p.currency === 'BRL') {
    return Math.round(v).toLocaleString('pt-BR');
  }
  // Fractional-possible: trim trailing zeros, up to 4 decimals.
  const rounded = Math.round(v * 10000) / 10000;
  return rounded.toLocaleString('pt-BR', { maximumFractionDigits: 4 });
}

function invBolsaFormatChange(v) {
  if (v == null || isNaN(v)) return '<span style="color:var(--text-muted)">—</span>';
  const pct = v * 100;
  const color = pct >= 0 ? 'var(--green)' : 'var(--red)';
  const sign = pct >= 0 ? '+' : '';
  return `<span style="color:${color}">${sign}${pct.toFixed(2).replace('.', ',')}%</span>`;
}

// --- Sorting ---

function invBolsaSort(rows, col, dir) {
  const mult = dir === 'asc' ? 1 : -1;
  // When sorting a toggle-aware column in BRL view, compare BRL values.
  const resolveKey = (p) => {
    if (invBolsaCurrencyView === 'brl' && INV_BOLSA_BRL_FIELDS[col]) return INV_BOLSA_BRL_FIELDS[col];
    return col;
  };
  return [...rows].sort((a, b) => {
    const va = a[resolveKey(a)];
    const vb = b[resolveKey(b)];
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * mult;
    return String(va).localeCompare(String(vb)) * mult;
  });
}

function invBolsaAttachSortHandlers(container) {
  container.querySelectorAll('th[data-sort]').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.sort;
      if (invBolsaSortState.col === col) {
        invBolsaSortState.dir = invBolsaSortState.dir === 'asc' ? 'desc' : 'asc';
      } else {
        invBolsaSortState.col = col;
        invBolsaSortState.dir = (col === 'id' || col === 'first_purchase') ? 'asc' : 'desc';
      }
      invBolsaRender(container);
    });
  });
}
