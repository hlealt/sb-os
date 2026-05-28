// Investment dashboard — Proventos view.
// Pure renderer: reads portfolio.income from inv-data.js.
// Spec: monthly stacked bar chart by type, totals by type, totals by ticker.
// Loaded after shared.js, inv-data.js, inv-carteira.js.

const INV_PROV_TYPE_LABELS = {
  dividendo: 'Dividendos',
  jcp: 'JCP',
  juros: 'Juros (RF)',
  rendimento: 'Rendimentos (Fundos)',
  fracao: 'Frações',
  bonificacao_dinheiro: 'Bonificação',
};

const INV_PROV_TYPE_COLORS = {
  dividendo:  'rgba(34, 197, 94, 0.75)',
  jcp:        'rgba(59, 130, 246, 0.75)',
  juros:      'rgba(168, 85, 247, 0.75)',
  rendimento: 'rgba(245, 158, 11, 0.75)',
  fracao:     'rgba(148, 163, 184, 0.75)',
  bonificacao_dinheiro: 'rgba(236, 72, 153, 0.75)',
};

let invProvSortState = { col: 'total_brl', dir: 'desc' };

function invProvRender(container) {
  const portfolio = invGetPortfolio();
  if (!portfolio) {
    container.innerHTML = `<div class="loading" style="color:var(--red)">${invGetLoadError() || 'Sem dados'}</div>`;
    return;
  }
  const income = portfolio.income || { monthly_totals: [], by_ticker: [] };
  const monthly = (income.monthly_totals || []).slice().sort((a, b) => a.month.localeCompare(b.month));
  // Spot rate is fallback ONLY for legacy portfolio.json without total_brl —
  // calculate.py now emits BRL pre-computed at the dividend's ticker-weighted FX.
  const fxRate = portfolio.meta?.fx_rate_usd_brl || 1;

  if (monthly.length === 0 && (income.by_ticker || []).length === 0) {
    container.innerHTML = `<div class="loading" style="color:var(--text-muted)">Nenhum provento registrado.</div>`;
    return;
  }

  const positionsById = {};
  (portfolio.positions || []).forEach(p => { positionsById[p.id] = p; });

  const byTicker = (income.by_ticker || []).map(t => {
    const pos = positionsById[t.id];
    // Prefer pre-computed total_brl from FX engine; fall back to spot for
    // legacy data, then to native total as last resort.
    const totalBrl = t.total_brl ?? (t.currency === 'USD' ? (t.total || 0) * fxRate : (t.total || 0));
    return {
      ...t,
      name: pos?.name || t.id,
      asset_class: pos?.asset_class || '—',
      broker: pos?.broker || '—',
      total_brl: totalBrl,
    };
  });

  container.innerHTML = [
    invProvSummaryCards(monthly, byTicker),
    invProvMonthlyChartBlock(),
    invProvByTypeTable(monthly),
    invProvByTickerTable(byTicker),
  ].join('');

  invProvRenderMonthlyChart(monthly);

  container.querySelectorAll('[data-prov-sort]').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.provSort;
      if (invProvSortState.col === col) {
        invProvSortState.dir = invProvSortState.dir === 'asc' ? 'desc' : 'asc';
      } else {
        invProvSortState.col = col;
        invProvSortState.dir = (col === 'name' || col === 'id' || col === 'asset_class' || col === 'broker') ? 'asc' : 'desc';
      }
      invProvRender(container);
    });
  });
}

// Helper: month total in BRL — prefers FX-engine-computed total_brl, falls back
// to native total (which is cross-currency-mixed for legacy data — best effort).
function invMonthBrl(m) {
  return m.total_brl ?? m.total ?? 0;
}

function invProvSummaryCards(monthly, byTicker) {
  const totalLifetime = byTicker.reduce((s, t) => s + (t.total_brl || 0), 0);
  // TTM = sum of last 12 monthly_totals (sorted ascending; take tail).
  const ttmMonths = monthly.slice(-12);
  const ttm = ttmMonths.reduce((s, m) => s + invMonthBrl(m), 0);
  const payers = byTicker.filter(t => (t.total_brl || 0) > 0).length;
  const bestMonth = monthly.reduce(
    (best, m) => (best == null || invMonthBrl(m) > invMonthBrl(best)) ? m : best,
    null,
  );

  return `
    <div class="cards">
      <div class="card">
        <div class="card-label">Total recebido (lifetime)</div>
        <div class="card-value privacy-hide">${formatBRL(totalLifetime)}</div>
      </div>
      <div class="card">
        <div class="card-label">Últimos 12 meses</div>
        <div class="card-value privacy-hide">${formatBRL(ttm)}</div>
        <div style="font-size:0.8rem;color:var(--text-muted);">média ${formatBRL(ttm / Math.max(ttmMonths.length, 1))}/mês</div>
      </div>
      <div class="card">
        <div class="card-label">Ativos pagadores</div>
        <div class="card-value">${payers}</div>
      </div>
      <div class="card">
        <div class="card-label">Melhor mês</div>
        <div class="card-value privacy-hide">${bestMonth ? formatBRL(invMonthBrl(bestMonth)) : '—'}</div>
        <div style="font-size:0.8rem;color:var(--text-muted);">${bestMonth ? invFormatBrMonth(bestMonth.month) : '—'}</div>
      </div>
    </div>
  `;
}

function invFormatBrMonth(ym) {
  // "2025-12" → "12/2025"
  if (!ym || ym.length < 7) return ym || '—';
  return `${ym.slice(5, 7)}/${ym.slice(0, 4)}`;
}

function invProvMonthlyChartBlock() {
  return `
    <div style="margin-top:24px;">
      <h3 style="font-size:1.1rem;margin-bottom:12px;">Proventos por mês</h3>
      <div class="card" style="padding:16px;">
        <canvas id="inv-bar-prov-monthly" style="max-height:280px;"></canvas>
      </div>
    </div>
  `;
}

function invProvRenderMonthlyChart(monthly) {
  const canvas = document.getElementById('inv-bar-prov-monthly');
  if (!canvas || typeof Chart === 'undefined' || monthly.length === 0) return;

  // Collect all type keys present across months. Prefer by_type_brl (FX-engine
  // converted) over by_type (native, may mix currencies).
  const types = Array.from(new Set(
    monthly.flatMap(m => Object.keys(m.by_type_brl || m.by_type || {}))
  ));
  // Stable order: dividendo, jcp, juros, rendimento, fracao, bonificacao_dinheiro, then others alpha.
  const PRIORITY = ['dividendo', 'jcp', 'juros', 'rendimento', 'fracao', 'bonificacao_dinheiro'];
  types.sort((a, b) => {
    const ia = PRIORITY.indexOf(a); const ib = PRIORITY.indexOf(b);
    if (ia >= 0 && ib >= 0) return ia - ib;
    if (ia >= 0) return -1;
    if (ib >= 0) return 1;
    return a.localeCompare(b);
  });

  const labels = monthly.map(m => invFormatBrMonth(m.month));
  const datasets = types.map(t => ({
    label: INV_PROV_TYPE_LABELS[t] || t,
    data: monthly.map(m => (m.by_type_brl || m.by_type || {})[t] || 0),
    backgroundColor: INV_PROV_TYPE_COLORS[t] || 'rgba(148, 163, 184, 0.75)',
    stack: 'income',
  }));

  if (charts['inv-bar-prov-monthly']) charts['inv-bar-prov-monthly'].destroy();
  charts['inv-bar-prov-monthly'] = new Chart(canvas.getContext('2d'), {
    type: 'bar',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom', labels: { color: '#ffffff' } } },
      scales: {
        x: { stacked: true, ticks: { color: '#ffffff' } },
        y: { stacked: true, beginAtZero: true, ticks: { color: '#ffffff', callback: v => formatBRL(v) } },
      },
    },
  });
}

function invProvByTypeTable(monthly) {
  // Aggregate across all months in monthly_totals. Prefer by_type_brl (FX-engine
  // converted at ticker-weighted rate) over native by_type.
  const totals = {};
  monthly.forEach(m => {
    Object.entries(m.by_type_brl || m.by_type || {}).forEach(([k, v]) => {
      totals[k] = (totals[k] || 0) + (v || 0);
    });
  });
  const grand = Object.values(totals).reduce((s, v) => s + v, 0);
  if (grand === 0) return '';

  const rows = Object.entries(totals)
    .map(([k, v]) => ({ type: k, label: INV_PROV_TYPE_LABELS[k] || k, value: v, pct: grand > 0 ? v / grand : 0 }))
    .sort((a, b) => b.value - a.value);

  let html = `<details open style="margin-top:24px;">
    <summary style="cursor:pointer;font-size:1.1rem;font-weight:600;margin-bottom:8px;">Resumo por tipo (${monthly.length} meses)</summary>
    <table class="inv-rf-table" style="width:100%;"><thead><tr>
      <th style="text-align:left;padding:8px 10px;color:var(--text-muted);font-size:0.85rem;">Tipo</th>
      <th style="text-align:right;padding:8px 10px;color:var(--text-muted);font-size:0.85rem;">Total</th>
      <th style="text-align:right;padding:8px 10px;color:var(--text-muted);font-size:0.85rem;">%</th>
    </tr></thead><tbody>`;
  rows.forEach(r => {
    html += `<tr>
      <td style="padding:8px 10px;border-bottom:1px solid var(--border-faint, var(--border));">
        <span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:${INV_PROV_TYPE_COLORS[r.type] || 'var(--text-muted)'};margin-right:8px;vertical-align:middle;"></span>${r.label}
      </td>
      <td class="privacy-hide" style="text-align:right;padding:8px 10px;border-bottom:1px solid var(--border-faint, var(--border));">${formatBRL(r.value)}</td>
      <td style="text-align:right;padding:8px 10px;border-bottom:1px solid var(--border-faint, var(--border));">${invFormatPctValue(r.pct)}</td>
    </tr>`;
  });
  html += `</tbody></table></details>`;
  return html;
}

const INV_PROV_TICKER_COLUMNS = [
  { key: 'name',        label: 'Ativo',       align: 'left'  },
  { key: 'asset_class', label: 'Classe',      align: 'left'  },
  { key: 'broker',      label: 'Instituição', align: 'left'  },
  { key: 'total_brl',   label: 'Total (BRL)', align: 'right', privacy: true },
];

const INV_PROV_CLASS_LABELS = {
  variable_income: 'Renda Variável',
  fixed_income:    'Renda Fixa',
  crypto:          'Crypto',
};

// Investment broker label lookup — canonical map lives in shared.js (BROKER_LABELS).
// INV_PROV_BROKER_LABELS removed; all callers below use invBrokerLabelShared().

function invProvByTickerTable(byTicker) {
  if (byTicker.length === 0) return '';
  const rows = byTicker.slice().sort((a, b) => {
    const { col, dir } = invProvSortState;
    const mult = dir === 'asc' ? 1 : -1;
    const va = a[col]; const vb = b[col];
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    if (typeof va === 'string') return va.localeCompare(vb) * mult;
    return (va - vb) * mult;
  });

  let html = `<details open style="margin-top:24px;">
    <summary style="cursor:pointer;font-size:1.1rem;font-weight:600;margin-bottom:8px;">Por ativo (${byTicker.length})</summary>
    <div style="overflow-x:auto"><table class="inv-rf-table"><thead><tr>`;
  INV_PROV_TICKER_COLUMNS.forEach(col => {
    const arrow = invProvSortState.col === col.key ? (invProvSortState.dir === 'asc' ? ' ▲' : ' ▼') : '';
    html += `<th data-prov-sort="${col.key}" style="cursor:pointer;text-align:${col.align};padding:8px 10px;border-bottom:1px solid var(--border);font-size:0.85rem;color:var(--text-muted);">${col.label}${arrow}</th>`;
  });
  html += `</tr></thead><tbody>`;
  rows.forEach(t => {
    const classLabel = INV_PROV_CLASS_LABELS[t.asset_class] || t.asset_class || '—';
    const brokerLabel = invBrokerLabelShared(t.broker);
    const currencyHint = t.currency === 'USD' ? ` <span style="font-size:0.7rem;color:var(--text-muted);">(US$ ${Number(t.total).toLocaleString('pt-BR', { maximumFractionDigits: 2 })})</span>` : '';
    html += `<tr>
      <td style="padding:8px 10px;border-bottom:1px solid var(--border-faint, var(--border));">
        <strong>${t.name}</strong>${t.id !== t.name ? ` <span style="font-size:0.75rem;color:var(--text-muted);">${t.id}</span>` : ''}
      </td>
      <td style="padding:8px 10px;border-bottom:1px solid var(--border-faint, var(--border));">${classLabel}</td>
      <td style="padding:8px 10px;border-bottom:1px solid var(--border-faint, var(--border));">${brokerLabel}</td>
      <td class="privacy-hide" style="text-align:right;padding:8px 10px;border-bottom:1px solid var(--border-faint, var(--border));">${formatBRL(t.total_brl)}${currencyHint}</td>
    </tr>`;
  });
  html += `</tbody></table></div></details>`;
  return html;
}
