// Investment dashboard — Carteira view.
// Pure renderer: reads state from inv-data.js. No fetch, no computation.
// Loaded after shared.js and inv-data.js.

const INV_CLASS_LABELS = {
  variable_income: 'Renda Variável',
  fixed_income: 'Renda Fixa',
  crypto: 'Crypto',
  liquidity: 'Liquidez'
};

// Per-class IRR bucket labels (must match _irr_class_bucket() in calculate.py).
const INV_IRR_CLASS_LABELS = {
  rv_br:     'RV BR',
  rv_eua:    'RV EUA',
  rf_balcao: 'RF Balcão',
  fundos:    'Fundos',
  crypto:    'Crypto',
};
const _INV_IRR_CLASS_ORDER = ['rv_br', 'rv_eua', 'rf_balcao', 'fundos', 'crypto'];

const INV_BROKER_LABELS = {
  safra: 'Safra',
  avenue: 'Avenue',
  clear: 'Clear',
  xp: 'XP',
  bipa: 'Bipa',
  binance: 'Binance',
  mercado_bitcoin: 'Mercado Bitcoin',
  mercado_pago: 'Mercado Pago'
};

function invBrokerLabel(id) { return INV_BROKER_LABELS[id] || id; }
function invClassLabel(id) { return INV_CLASS_LABELS[id] || id; }

function invFormatPct(v) {
  if (v == null || isNaN(v)) return '—';
  return (v * 100).toFixed(2).replace('.', ',') + '%';
}

function invFormatPctValue(v) {
  // For IRR values already expressed as decimal (0.15 = 15%)
  if (v == null || isNaN(v)) return '—';
  const n = v * 100;
  return (n >= 0 ? '+' : '') + n.toFixed(2).replace('.', ',') + '%';
}

async function invRenderCarteira(container) {
  const portfolio = invGetPortfolio();
  if (!portfolio) {
    const err = invGetLoadError() || 'Execute calculate.py para gerar dados.';
    container.innerHTML = `<div class="loading" style="color:var(--red)">${err}</div>`;
    return;
  }

  const positions = Array.isArray(portfolio.positions) ? portfolio.positions : [];
  if (positions.length === 0) {
    container.innerHTML = `<div class="loading">Nenhuma posição encontrada para esta data.</div>`;
    return;
  }

  const summary = portfolio.summary || {};
  const meta = portfolio.meta || {};

  container.innerHTML = [
    invCarteiraHeader(portfolio),
    invCarteiraSummaryCards(summary, positions),
    invCarteiraIrrBreakdown(summary),
    invCarteiraRvEuaReturns(positions),
    invCarteiraAllocationSection(summary),
    invCarteiraMarketIndicators(meta)
  ].join('');

  // Instantiate charts after DOM is in place
  invRenderClassAllocationChart(summary);
  invRenderBrokerAllocationChart(summary);
  invRenderCurrencyAllocationChart(positions);

  if (document.body.classList.contains('privacy-mode')) {
    updateChartsPrivacy(true);
  }
}

// --- Header (cut date selector + freshness label) ---

function invCarteiraHeader(portfolio) {
  const snapshots = invGetSnapshots();
  const current = invGetCurrentSnapshot();
  const meta = portfolio.meta || {};
  const cutDate = meta.cut_date ? invFormatBrDate(meta.cut_date) : '—';
  const generated = meta.generated_at ? invFormatIsoToBr(meta.generated_at) : '—';
  const freshness = invFreshnessLabel(portfolio);

  // "Atual" label must always reflect the live portfolio's cut date — never the
  // currently-selected historical snapshot. Use the cached live cut date; fall
  // back to the loaded portfolio's cut date when no snapshot is selected yet.
  const liveDate = invGetLiveCutDate();
  const atualLabel = liveDate ? invFormatBrDate(liveDate) : (current === 'current' ? cutDate : '—');
  let options = `<option value="current"${current === 'current' ? ' selected' : ''}>Atual (${atualLabel})</option>`;
  snapshots.forEach(s => {
    options += `<option value="${s.date}"${current === s.date ? ' selected' : ''}>${s.label}</option>`;
  });

  return `
    <div class="inv-carteira-header" style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:16px;margin-bottom:20px;">
      <div>
        <div style="font-size:0.85rem;color:var(--text-muted);">Data de corte</div>
        <div style="font-size:1.4rem;font-weight:600;">${cutDate}</div>
        <div style="font-size:0.8rem;color:var(--text-muted);margin-top:4px;">${freshness}</div>
        <div style="font-size:0.75rem;color:var(--text-muted);margin-top:2px;">Gerado em ${generated}</div>
      </div>
      <div>
        <label style="display:block;font-size:0.85rem;color:var(--text-muted);margin-bottom:4px;">Snapshot</label>
        <select id="inv-cutdate-select" onchange="invOnCutDateChange(this.value)"
          style="padding:8px 12px;background:var(--surface);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:0.9rem;min-width:220px;">
          ${options}
        </select>
      </div>
    </div>
  `;
}

function invFormatIsoToBr(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const dd = String(d.getDate()).padStart(2, '0');
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const yyyy = d.getFullYear();
  const hh = String(d.getHours()).padStart(2, '0');
  const mi = String(d.getMinutes()).padStart(2, '0');
  return `${dd}/${mm}/${yyyy} ${hh}:${mi}`;
}

function invFreshnessLabel(portfolio) {
  const positions = portfolio.positions || [];
  const rv = positions.filter(p => p.valuation_method === 'price' && p.price_source === 'api');
  const rf = positions.filter(p => p.valuation_method === 'balcao');
  const latest = arr => {
    const dates = arr.map(p => p.price_date || p.valuation_date).filter(Boolean).sort();
    return dates.length ? invFormatBrDate(dates[dates.length - 1]) : null;
  };
  const parts = [];
  const rvDate = latest(rv);
  if (rvDate) parts.push(`RV: ${rvDate}`);
  const rfDate = latest(rf);
  if (rfDate) parts.push(`RF: último saldo ${rfDate}`);
  return parts.join(' · ') || 'Sem dados de frescor';
}

// --- Summary cards ---

function invCarteiraSummaryCards(summary, positions) {
  const total = summary.total_value ?? 0;
  const cost = summary.total_cost ?? 0;
  const pnl = summary.total_pnl ?? 0;
  const pnlPct = cost > 0 ? pnl / cost : 0;
  const irr = summary.irr?.total;
  // Count all positions emitted by calculate.py — RF/funds always carry quantity=0
  // (they're net_flow + snapshot driven), so filtering by quantity!=0 hides them.
  const count = positions.length;

  return `
    <div class="cards">
      <div class="card">
        <div class="card-label">Valor Total</div>
        <div class="card-value privacy-hide">${formatBRL(total)}</div>
      </div>
      <div class="card">
        <div class="card-label">Custo Total</div>
        <div class="card-value privacy-hide">${formatBRL(cost)}</div>
      </div>
      <div class="card">
        <div class="card-label">P&amp;L</div>
        <div class="card-value privacy-hide" style="color:${pnl >= 0 ? 'var(--green)' : 'var(--red)'}">${formatBRL(pnl)}</div>
        <div class="privacy-hide" style="font-size:0.8rem;color:var(--text-muted);">${invFormatPctValue(pnlPct)}</div>
      </div>
      <div class="card">
        <div class="card-label">TIR anualizada</div>
        <div class="card-value" style="color:${(irr ?? 0) >= 0 ? 'var(--green)' : 'var(--red)'}">${invFormatPctValue(irr)}</div>
      </div>
      <div class="card">
        <div class="card-label">Posições</div>
        <div class="card-value">${count}</div>
      </div>
    </div>
  `;
}

// --- Per-class IRR breakdown ---

function invCarteiraIrrBreakdown(summary) {
  const perClass = summary.irr?.per_class || {};
  const buckets = _INV_IRR_CLASS_ORDER
    .map(k => ({ key: k, ...(perClass[k] || {}) }))
    .filter(b => b.irr != null || (b.terminal_value || 0) > 0);
  if (buckets.length === 0) return '';

  const cells = buckets.map(b => {
    const label = INV_IRR_CLASS_LABELS[b.key] || b.key;
    const rate = b.irr;
    const color = rate == null ? 'var(--text-muted)' : (rate >= 0 ? 'var(--green)' : 'var(--red)');
    const rateTxt = invFormatPctValue(rate);
    const value = b.terminal_value ? formatBRL(b.terminal_value) : '—';
    return `
      <div style="flex:1;min-width:120px;padding:10px 14px;border:1px solid var(--border);border-radius:8px;background:var(--surface);">
        <div style="font-size:0.78rem;color:var(--text-muted);">${label}</div>
        <div class="privacy-hide" style="font-size:1.05rem;font-weight:600;color:${color};margin-top:2px;">${rateTxt}</div>
        <div class="privacy-hide" style="font-size:0.72rem;color:var(--text-muted);margin-top:2px;">${value}</div>
      </div>
    `;
  }).join('');

  return `
    <div style="margin-top:16px;">
      <div style="font-size:0.85rem;color:var(--text-muted);margin-bottom:8px;">TIR por classe</div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">${cells}</div>
    </div>
  `;
}

// --- RV EUA returns decomposition roll-up (p3-6 / D11) ---
// Sums return_usd, return_fx_brl, return_total_brl across all USD positions
// that have the decomposition fields. Only shown when at least one position
// emits these fields (non-BRL, price not missing).

function invCarteiraRvEuaReturns(positions) {
  const usdPositions = positions.filter(
    p => p.currency === 'USD' && p.return_total_brl != null
  );
  if (usdPositions.length === 0) return '';

  const totRetUsd = usdPositions.reduce((s, p) => s + (p.return_usd || 0), 0);
  const totFxBrl  = usdPositions.reduce((s, p) => s + (p.return_fx_brl || 0), 0);
  const totAllIn  = usdPositions.reduce((s, p) => s + (p.return_total_brl || 0), 0);
  const count = usdPositions.length;

  function pnlCell(v, fmtFn) {
    const color = v >= 0 ? 'var(--green)' : 'var(--red)';
    return `<span class="privacy-hide" style="color:${color}">${fmtFn(v)}</span>`;
  }
  function fmtUsd(v) {
    const abs = Math.abs(v);
    const formatted = abs.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return (v < 0 ? '-' : '') + 'US$ ' + formatted;
  }

  return `
    <div style="margin-top:16px;">
      <div style="font-size:0.85rem;color:var(--text-muted);margin-bottom:8px;">Retorno RV EUA (${count} posições)</div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <div style="flex:1;min-width:120px;padding:10px 14px;border:1px solid var(--border);border-radius:8px;background:var(--surface);">
          <div style="font-size:0.78rem;color:var(--text-muted);">Ret. USD</div>
          <div style="font-size:1.05rem;font-weight:600;margin-top:2px;">${pnlCell(totRetUsd, fmtUsd)}</div>
        </div>
        <div style="flex:1;min-width:120px;padding:10px 14px;border:1px solid var(--border);border-radius:8px;background:var(--surface);">
          <div style="font-size:0.78rem;color:var(--text-muted);">FX</div>
          <div style="font-size:1.05rem;font-weight:600;margin-top:2px;">${pnlCell(totFxBrl, formatBRL)}</div>
        </div>
        <div style="flex:1;min-width:120px;padding:10px 14px;border:1px solid var(--border);border-radius:8px;background:var(--surface);">
          <div style="font-size:0.78rem;color:var(--text-muted);">BRL All-in</div>
          <div style="font-size:1.05rem;font-weight:600;margin-top:2px;">${pnlCell(totAllIn, formatBRL)}</div>
        </div>
      </div>
    </div>
  `;
}

// --- Allocation section (charts side by side) ---

function invCarteiraAllocationSection(summary) {
  return `
    <h3 style="margin:24px 0 12px;font-size:1.1rem;">Alocação</h3>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;">
      <div class="card" style="padding:16px;">
        <div class="card-label" style="margin-bottom:8px;">Por classe de ativo</div>
        <div style="position:relative;height:300px;"><canvas id="inv-pie-class"></canvas></div>
      </div>
      <div class="card" style="padding:16px;">
        <div class="card-label" style="margin-bottom:8px;">Por instituição</div>
        <div style="position:relative;height:300px;"><canvas id="inv-pie-broker"></canvas></div>
      </div>
      <div class="card" style="padding:16px;">
        <div class="card-label" style="margin-bottom:8px;">Por moeda</div>
        <div style="position:relative;height:300px;"><canvas id="inv-pie-currency"></canvas></div>
      </div>
    </div>
  `;
}

function invAllocationDataset(allocation, labelFn) {
  const entries = Object.entries(allocation || {})
    .filter(([, v]) => (v?.value || 0) > 0 || (v?.pct || 0) > 0)
    .sort((a, b) => (b[1]?.value || 0) - (a[1]?.value || 0));
  return {
    labels: entries.map(([k]) => labelFn(k)),
    values: entries.map(([, v]) => v.value || 0),
    pcts: entries.map(([, v]) => v.pct || 0)
  };
}

function invFormatBrlK(v) {
  // Compact BRL for legend labels: <1k = "R$ XXX", >=1k = "R$ Xk", >=1M = "R$ X,Xm".
  if (v == null || isNaN(v)) return '—';
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `R$ ${(v / 1_000_000).toFixed(1).replace('.', ',')}m`;
  if (abs >= 1_000) return `R$ ${Math.round(v / 1_000)}k`;
  return `R$ ${Math.round(v)}`;
}

function invPieOptions(data) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    // Reserve generous space around the donut so external datalabels don't clip
    // at the top/bottom edges of the card.
    layout: { padding: { top: 28, bottom: 28, left: 32, right: 32 } },
    plugins: {
      legend: {
        position: 'bottom',
        labels: {
          color: '#ffffff',
          font: { size: 11 },
          // fontColor must be set per-item; the labels.color default is ignored
          // when generateLabels returns custom items (Chart.js v4 quirk).
          generateLabels: (chart) => {
            const ds = chart.data.datasets[0];
            return chart.data.labels.map((label, i) => ({
              text: label,
              fillStyle: ds.backgroundColor[i],
              strokeStyle: ds.backgroundColor[i],
              fontColor: '#ffffff',
              lineWidth: 0,
              hidden: false,
              index: i
            }));
          }
        }
      },
      tooltip: {
        callbacks: {
          label: (ctx) => {
            const pct = data.pcts[ctx.dataIndex];
            return `${ctx.label}: ${formatBRL(ctx.parsed)} (${invFormatPct(pct)})`;
          }
        }
      },
      datalabels: {
        color: '#ffffff',
        anchor: 'end',
        align: 'end',
        offset: 6,
        clamp: true,
        font: { size: 11, weight: '600' },
        textAlign: 'center',
        formatter: (value) => invFormatBrlK(value)
      }
    }
  };
}

function invRenderClassAllocationChart(summary) {
  const data = invAllocationDataset(summary.allocation_by_class, invClassLabel);
  const ctx = document.getElementById('inv-pie-class');
  if (!ctx) return;
  if (charts['inv-pie-class']) charts['inv-pie-class'].destroy();
  if (data.values.length === 0) {
    ctx.parentElement.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted);">Sem dados</div>';
    return;
  }
  charts['inv-pie-class'] = new Chart(ctx, {
    type: 'doughnut',
    plugins: [ChartDataLabels],
    data: {
      labels: data.labels,
      datasets: [{ data: data.values, backgroundColor: COLOR_PALETTE.slice(0, data.values.length), borderWidth: 0 }]
    },
    options: invPieOptions(data)
  });
}

function invRenderBrokerAllocationChart(summary) {
  const data = invAllocationDataset(summary.allocation_by_broker, invBrokerLabel);
  const ctx = document.getElementById('inv-pie-broker');
  if (!ctx) return;
  if (charts['inv-pie-broker']) charts['inv-pie-broker'].destroy();
  if (data.values.length === 0) {
    ctx.parentElement.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted);">Sem dados</div>';
    return;
  }
  charts['inv-pie-broker'] = new Chart(ctx, {
    type: 'doughnut',
    plugins: [ChartDataLabels],
    data: {
      labels: data.labels,
      datasets: [{ data: data.values, backgroundColor: COLOR_PALETTE.slice(3, 3 + data.values.length), borderWidth: 0 }]
    },
    options: invPieOptions(data)
  });
}

// --- Currency allocation (R$ / US$ / Crypto, all in BRL) ---
// Bucket from positions (not summary.allocation_by_currency, which only has BRL/USD).
// Crypto carves out from BRL because crypto is its own asset class with distinct risk
// profile, even though prices are denominated in BRL in portfolio.json.

function invCurrencyAllocationDataset(positions) {
  const buckets = { 'R$': 0, 'US$': 0, 'Crypto': 0 };
  positions.forEach(p => {
    const value = p.current_value_brl ?? p.current_value ?? 0;
    if (value <= 0) return;
    if (p.asset_class === 'crypto') buckets['Crypto'] += value;
    else if (p.currency === 'USD') buckets['US$'] += value;
    else buckets['R$'] += value;
  });
  const total = buckets['R$'] + buckets['US$'] + buckets['Crypto'];
  const entries = Object.entries(buckets).filter(([, v]) => v > 0);
  return {
    labels: entries.map(([k]) => k),
    values: entries.map(([, v]) => v),
    pcts: entries.map(([, v]) => total > 0 ? v / total : 0)
  };
}

function invRenderCurrencyAllocationChart(positions) {
  const data = invCurrencyAllocationDataset(positions);
  const ctx = document.getElementById('inv-pie-currency');
  if (!ctx) return;
  if (charts['inv-pie-currency']) charts['inv-pie-currency'].destroy();
  if (data.values.length === 0) {
    ctx.parentElement.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted);">Sem dados</div>';
    return;
  }
  charts['inv-pie-currency'] = new Chart(ctx, {
    type: 'doughnut',
    plugins: [ChartDataLabels],
    data: {
      labels: data.labels,
      datasets: [{ data: data.values, backgroundColor: COLOR_PALETTE.slice(6, 6 + data.values.length), borderWidth: 0 }]
    },
    options: invPieOptions(data)
  });
}

// --- Market indicators ---

function invCarteiraMarketIndicators(meta) {
  const ind = meta.market_indicators || {};
  const keys = Object.keys(ind);
  let html = `<h3 style="margin:24px 0 12px;font-size:1.1rem;">Indicadores de mercado</h3>`;
  if (keys.length === 0) {
    html += `<div class="card" style="color:var(--text-muted)">Indicadores indisponíveis.</div>`;
    return html;
  }
  html += `<div class="cards">`;
  keys.forEach(k => {
    const v = ind[k];
    const raw = typeof v === 'object' ? v.value : v;
    // change_1d is the canonical key emitted by price_fetcher (already a fractional ratio).
    const change = typeof v === 'object' ? (v.change_1d ?? v.change_pct) : null;
    const value = invFormatIndicatorValue(k, raw);
    const changeHtml = change != null
      ? `<div style="font-size:0.8rem;color:${change >= 0 ? 'var(--green)' : 'var(--red)'}">${invFormatPctValue(change)}</div>`
      : '';
    html += `<div class="card"><div class="card-label">${k}</div><div class="card-value">${value}</div>${changeHtml}</div>`;
  });
  html += `</div>`;
  return html;
}

function invFormatIndicatorValue(key, v) {
  if (v == null || isNaN(v)) return '—';
  const n = Number(v);
  if (key === 'BTC_BRL') return 'R$ ' + Math.round(n).toLocaleString('pt-BR');
  if (key === 'USD_BRL') return n.toLocaleString('pt-BR', { minimumFractionDigits: 4, maximumFractionDigits: 4 });
  if (key === 'IBOVESPA') return Math.round(n).toLocaleString('pt-BR');
  return n.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// --- Cut date change handler ---

async function invOnCutDateChange(value) {
  const container = document.getElementById('tab-carteira');
  if (!container) return;
  container.innerHTML = `<div class="loading"><div class="loading-spinner"></div><br>Carregando ${value}...</div>`;
  await invLoadPortfolio(value);
  invRenderCarteira(container);
}
