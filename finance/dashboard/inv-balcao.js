// Investment dashboard — Balcão view (Renda Fixa + Fundos).
// Pure renderer: reads state from inv-data.js. No fetch, no computation.
// Loaded after shared.js, inv-data.js.
//
// Filters by valuation_method === 'balcao' (RF + funds, regardless of asset_class).
// Two sections render in sequence:
//   1. Renda Fixa — CRA/DEB/LCA/CDB/Tesouro etc. Includes cronograma de vencimentos.
//   2. Fundos — FIM/FIRF/FIA/FIDC/COE/DI. No maturity (open-ended cotas).
// Per-position breakdown comes from balcão ledger:
//   aplicado_total, juros_amort_total, resgates_total, impostos_total.
// pnl_absolute = current_value + net_flow when snapshot exists; null otherwise
// (rendered in "Sem valoração" bucket). retorno% = pnl / aplicado_total.

const INV_BALCAO_TYPE_LABELS = {
  // Funds
  fia_br: 'FIA BR',
  fia_usa: 'FIA USA',
  fim_br: 'FIM',
  firf_br: 'FIRF',
  fidc: 'FIDC',
  coe: 'COE',
  di: 'FIRF DI',
  // Fixed income
  cdb: 'CDB',
  cra: 'CRA',
  cri: 'CRI',
  deb: 'Debênture',
  lca: 'LCA',
  lci: 'LCI',
  lc: 'LC',
  tesouro: 'Tesouro',
  rf: 'Renda Fixa',
};

// Fund product types — drives the RF vs Funds split inside the Balcão view.
// All types here render in "Fundos"; everything else (cra/deb/lca/cdb/...) is
// RF tradicional. type='di' (FIRF DI) renders under Fundos because it's an
// open-ended cota even though it classifies as fixed_income for the donut.
const _INV_BALCAO_FUND_TYPES = new Set(['fia_br', 'fia_usa', 'fim_br', 'firf_br', 'fidc', 'coe', 'di']);

const INV_BALCAO_BROKER_LABELS = { safra: 'Safra', clear: 'Clear', xp: 'XP', avenue: 'Avenue', guide: 'Guide' };

let invBalcaoBrokerFilter = 'all';
let invBalcaoSort = { col: 'current_value', dir: 'desc' };
let invBalcaoSectionsOpen = { rf: true, fundos: true, missing: false };

const INV_BALCAO_RF_COLUMNS = [
  { key: 'name',              label: 'Produto',          align: 'left' },
  { key: 'type_label',        label: 'Tipo',             align: 'left' },
  { key: 'indexer_label',     label: 'Indexador',        align: 'left' },
  { key: 'application_date',  label: 'Aplicação',        align: 'left',  format: 'date' },
  { key: 'maturity_date',     label: 'Vencimento',       align: 'left',  format: 'date' },
  { key: 'broker_label',      label: 'Instituição',      align: 'left' },
  { key: 'aplicado_total',    label: 'Aplicado',         align: 'right', privacy: true, format: 'money' },
  { key: 'juros_amort_total', label: 'Juros + Amortiz.', align: 'right', privacy: true, format: 'money' },
  { key: 'current_value',     label: 'Valor',            align: 'right', privacy: true, format: 'money' },
  { key: 'pnl_absolute',      label: 'P&L',              align: 'right', privacy: true, format: 'pnl' },
  { key: 'pnl_pct',           label: 'Retorno %',        align: 'right', privacy: true, format: 'pct' },
  { key: 'irr',               label: 'TIR',              align: 'right', privacy: true, format: 'pct' },
  { key: 'price_date',        label: 'Valoração',        align: 'left',  format: 'date' },
];

const INV_BALCAO_FUNDS_COLUMNS = [
  { key: 'name',              label: 'Fundo',          align: 'left' },
  { key: 'type_label',        label: 'Tipo',           align: 'left' },
  { key: 'broker_label',      label: 'Instituição',    align: 'left' },
  { key: 'aplicado_total',    label: 'Aplicado',       align: 'right', privacy: true, format: 'money' },
  { key: 'resgates_total',    label: 'Resgates',       align: 'right', privacy: true, format: 'money' },
  { key: 'current_value',     label: 'Valor',          align: 'right', privacy: true, format: 'money' },
  { key: 'pnl_absolute',      label: 'P&L',            align: 'right', privacy: true, format: 'pnl' },
  { key: 'pnl_pct',           label: 'Retorno %',      align: 'right', privacy: true, format: 'pct' },
  { key: 'irr',               label: 'TIR',            align: 'right', privacy: true, format: 'pct' },
  { key: 'price_date',        label: 'Valoração',      align: 'left',  format: 'date' },
];

const _INV_BALCAO_TEXT_COLS = new Set(['name', 'type_label', 'broker_label', 'price_date',
                                       'maturity_date', 'application_date', 'indexer_label']);

// IRR quality → tooltip copy. Drives the amber dot on the TIR cell.
// 'complete' renders no dot (clean number).
const _INV_BALCAO_IRR_QUALITY_TOOLTIPS = {
  seed_only:    'TIR baseada apenas no snapshot inicial (seed) — sem histórico de aplicações reais.',
  short_window: 'Janela < 90 dias entre o primeiro fluxo e a data de corte — TIR pode oscilar fortemente.',
  unverified:   'Aplicação única não auditada contra extratos históricos — possíveis lançamentos faltando.',
};

function invBalcaoRender(container) {
  const portfolio = invGetPortfolio();
  if (!portfolio) {
    container.innerHTML = `<div class="loading" style="color:var(--red)">${invGetLoadError() || 'Sem dados'}</div>`;
    return;
  }

  const positions = (portfolio.positions || [])
    .filter(p => p.valuation_method === 'balcao')
    .map(p => ({
      ...p,
      type_label: INV_BALCAO_TYPE_LABELS[p.type] || p.type || '—',
      broker_label: INV_BALCAO_BROKER_LABELS[p.broker] || p.broker || '—',
      indexer_label: invBalcaoFormatIndexer(p),
    }));

  const filtered = invBalcaoApplyFilters(positions);
  const isValued = p => p.price_source === 'snapshot' && p.current_value != null;
  const valuedRf    = filtered.filter(p => !_INV_BALCAO_FUND_TYPES.has(p.type) && isValued(p));
  const valuedFunds = filtered.filter(p =>  _INV_BALCAO_FUND_TYPES.has(p.type) && isValued(p));
  const missing     = filtered.filter(p => !isValued(p));

  container.innerHTML = [
    invBalcaoFilterBar(positions),
    invBalcaoSummaryCards([...valuedRf, ...valuedFunds], missing),
    invBalcaoRfSection(valuedRf),
    invBalcaoFundosSection(valuedFunds),
    invBalcaoMissingBlock(missing),
  ].join('');

  invBalcaoRenderMaturityChart(valuedRf);

  const brokerSel = container.querySelector('[data-balcao-broker]');
  if (brokerSel) brokerSel.addEventListener('change', e => {
    invBalcaoBrokerFilter = e.target.value;
    invBalcaoRender(container);
  });
  container.querySelectorAll('[data-balcao-sort]').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.balcaoSort;
      if (invBalcaoSort.col === col) {
        invBalcaoSort.dir = invBalcaoSort.dir === 'asc' ? 'desc' : 'asc';
      } else {
        invBalcaoSort.col = col;
        invBalcaoSort.dir = _INV_BALCAO_TEXT_COLS.has(col) ? 'asc' : 'desc';
      }
      invBalcaoRender(container);
    });
  });
  container.querySelectorAll('[data-balcao-section]').forEach(d => {
    d.addEventListener('toggle', () => {
      invBalcaoSectionsOpen[d.dataset.balcaoSection] = d.open;
    });
  });
}

function invBalcaoApplyFilters(positions) {
  return positions.filter(p => {
    if (invBalcaoBrokerFilter !== 'all' && p.broker !== invBalcaoBrokerFilter) return false;
    return true;
  });
}

function invBalcaoFilterBar(allPositions) {
  const brokers = ['all', ...Array.from(new Set(allPositions.map(p => p.broker).filter(Boolean))).sort()];
  const brokerOpts = brokers.map(b => {
    const label = b === 'all' ? 'Todas as instituições' : (INV_BALCAO_BROKER_LABELS[b] || b);
    return `<option value="${b}"${b === invBalcaoBrokerFilter ? ' selected' : ''}>${label}</option>`;
  }).join('');

  return `
    <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:16px;">
      <label style="font-size:0.85rem;color:var(--text-muted);">Instituição:
        <select data-balcao-broker style="margin-left:6px;padding:6px 10px;background:var(--surface);border:1px solid var(--border);border-radius:6px;color:var(--text);">${brokerOpts}</select>
      </label>
    </div>
  `;
}

function invBalcaoSummaryCards(valued, missing) {
  const total = valued.reduce((s, p) => s + (p.current_value ?? 0), 0);
  const cost  = valued.reduce((s, p) => s + (p.aplicado_total ?? p.cost_basis ?? 0), 0);
  const pnl   = valued.reduce((s, p) => s + (p.pnl_absolute ?? 0), 0);
  const pnlPct = cost > 0 ? pnl / cost : 0;

  return `
    <div class="cards">
      <div class="card">
        <div class="card-label">Valor Balcão</div>
        <div class="card-value privacy-hide">${formatBRL(total)}</div>
      </div>
      <div class="card">
        <div class="card-label">Aplicado</div>
        <div class="card-value privacy-hide">${formatBRL(cost)}</div>
      </div>
      <div class="card">
        <div class="card-label">P&amp;L</div>
        <div class="card-value privacy-hide" style="color:${pnl >= 0 ? 'var(--green)' : 'var(--red)'}">${formatBRL(pnl)}</div>
        <div class="privacy-hide" style="font-size:0.8rem;color:var(--text-muted);">${invFormatPctValue(pnlPct)}</div>
      </div>
      <div class="card">
        <div class="card-label">Produtos</div>
        <div class="card-value">${valued.length} / ${valued.length + missing.length}</div>
        <div style="font-size:0.8rem;color:var(--text-muted);">${missing.length > 0 ? `${missing.length} sem valoração` : 'todos valorados'}</div>
      </div>
    </div>
  `;
}

function invBalcaoRfSection(valued) {
  const open = invBalcaoSectionsOpen.rf ? ' open' : '';
  return `
    <details data-balcao-section="rf"${open} style="margin-top:24px;">
      <summary style="cursor:pointer;font-size:1.15rem;font-weight:700;margin-bottom:8px;">Renda Fixa (${valued.length})</summary>
      ${invBalcaoTable(valued, INV_BALCAO_RF_COLUMNS)}
      ${invBalcaoMaturityTimelineHtml(valued)}
      ${invBalcaoTypeSummary(valued, 'RF')}
    </details>
  `;
}

function invBalcaoFundosSection(valued) {
  const open = invBalcaoSectionsOpen.fundos ? ' open' : '';
  return `
    <details data-balcao-section="fundos"${open} style="margin-top:24px;">
      <summary style="cursor:pointer;font-size:1.15rem;font-weight:700;margin-bottom:8px;">Fundos (${valued.length})</summary>
      ${invBalcaoTable(valued, INV_BALCAO_FUNDS_COLUMNS)}
      ${invBalcaoTypeSummary(valued, 'Fundos')}
    </details>
  `;
}

function invBalcaoTable(rows, columns) {
  if (rows.length === 0) {
    return `<div style="color:var(--text-muted);padding:16px;">Nenhuma posição valorada com os filtros atuais.</div>`;
  }
  const sorted = invBalcaoSortRows(rows.slice(), columns);
  let html = `<div style="overflow-x:auto"><table class="inv-rf-table"><thead><tr>`;
  columns.forEach(col => {
    const arrow = invBalcaoSort.col === col.key ? (invBalcaoSort.dir === 'asc' ? ' ▲' : ' ▼') : '';
    html += `<th data-balcao-sort="${col.key}" style="cursor:pointer;text-align:${col.align};padding:8px 10px;border-bottom:1px solid var(--border);font-size:0.85rem;color:var(--text-muted);">${col.label}${arrow}</th>`;
  });
  html += `</tr></thead><tbody>`;
  sorted.forEach(p => {
    html += `<tr>`;
    columns.forEach(col => {
      html += `<td style="text-align:${col.align};padding:8px 10px;border-bottom:1px solid var(--border-faint, var(--border));" class="${col.privacy ? 'privacy-hide' : ''}">${invBalcaoFormatCell(p, col)}</td>`;
    });
    html += `</tr>`;
  });
  html += `</tbody></table></div>`;
  return html;
}

function invBalcaoFormatCell(p, col) {
  if (col.key === 'name') {
    return `<strong style="display:block;">${p.name || p.id}</strong><span style="font-size:0.75rem;color:var(--text-muted);">${p.id}</span>`;
  }
  if (col.format === 'date') {
    const d = p[col.key];
    return d ? invFormatBrDate(d) : '—';
  }
  const v = p[col.key];
  if (v == null || v === '') return '—';
  if (col.format === 'money') return formatBRL(v);
  if (col.format === 'pct') {
    const txt = invFormatPctValue(v);
    if (col.key === 'irr' && p.irr_quality && p.irr_quality !== 'complete') {
      const tip = _INV_BALCAO_IRR_QUALITY_TOOLTIPS[p.irr_quality] || p.irr_quality;
      const dot = `<span title="${tip}" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--amber, #F59E0B);margin-right:6px;vertical-align:middle;cursor:help;"></span>`;
      return `${dot}${txt}`;
    }
    return txt;
  }
  if (col.format === 'pnl') {
    const color = v >= 0 ? 'var(--green)' : 'var(--red)';
    return `<span style="color:${color}">${formatBRL(v)}</span>`;
  }
  return v;
}

function invBalcaoSortRows(rows, columns) {
  const { col, dir } = invBalcaoSort;
  // Skip sort if the active column is not in this table's column set —
  // RF and Fundos share most columns, this guard avoids errors when sorting
  // by an RF-only column (e.g. indexer) inside the Fundos table.
  if (!columns.find(c => c.key === col)) return rows;
  const mult = dir === 'asc' ? 1 : -1;
  rows.sort((a, b) => {
    const va = a[col];
    const vb = b[col];
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    if (typeof va === 'string') return va.localeCompare(vb) * mult;
    return (va - vb) * mult;
  });
  return rows;
}

function invBalcaoTypeSummary(valued, sectionLabel) {
  if (valued.length === 0) return '';
  const groups = {};
  valued.forEach(p => {
    const k = p.type || '—';
    if (!groups[k]) groups[k] = { type: k, count: 0, value: 0, cost: 0 };
    groups[k].count += 1;
    groups[k].value += p.current_value ?? 0;
    groups[k].cost  += p.aplicado_total ?? p.cost_basis ?? 0;
  });
  const total = Object.values(groups).reduce((s, g) => s + g.value, 0);
  const rows = Object.values(groups)
    .map(g => ({ ...g, label: INV_BALCAO_TYPE_LABELS[g.type] || g.type, pnl: g.value - g.cost, pct: total > 0 ? g.value / total : 0 }))
    .sort((a, b) => b.value - a.value);
  let html = `<div style="margin-top:16px;">
    <div style="font-size:1rem;font-weight:600;margin-bottom:8px;color:var(--text-muted);">Resumo por tipo</div>
    <table class="inv-rf-table" style="width:100%;"><thead><tr>
      <th style="text-align:left;padding:8px 10px;color:var(--text-muted);font-size:0.85rem;">Tipo</th>
      <th style="text-align:right;padding:8px 10px;color:var(--text-muted);font-size:0.85rem;">Produtos</th>
      <th style="text-align:right;padding:8px 10px;color:var(--text-muted);font-size:0.85rem;">Valor</th>
      <th style="text-align:right;padding:8px 10px;color:var(--text-muted);font-size:0.85rem;">% ${sectionLabel}</th>
      <th style="text-align:right;padding:8px 10px;color:var(--text-muted);font-size:0.85rem;">P&L</th>
    </tr></thead><tbody>`;
  rows.forEach(g => {
    const pnlColor = g.pnl >= 0 ? 'var(--green)' : 'var(--red)';
    html += `<tr>
      <td style="padding:8px 10px;border-bottom:1px solid var(--border-faint, var(--border));">${g.label}</td>
      <td style="text-align:right;padding:8px 10px;border-bottom:1px solid var(--border-faint, var(--border));">${g.count}</td>
      <td class="privacy-hide" style="text-align:right;padding:8px 10px;border-bottom:1px solid var(--border-faint, var(--border));">${formatBRL(g.value)}</td>
      <td style="text-align:right;padding:8px 10px;border-bottom:1px solid var(--border-faint, var(--border));">${invFormatPctValue(g.pct)}</td>
      <td class="privacy-hide" style="text-align:right;padding:8px 10px;border-bottom:1px solid var(--border-faint, var(--border));color:${pnlColor};">${formatBRL(g.pnl)}</td>
    </tr>`;
  });
  html += `</tbody></table></div>`;
  return html;
}

function invBalcaoFormatIndexer(p) {
  // "100% CDI", "IPCA + 3,5%", "PRÉ 14,35%". Falls back to "—" for funds with no indexer.
  if (!p.indexer) return '—';
  const idx = p.indexer.toUpperCase();
  const rate = p.rate ? Number(p.rate) : null;
  const pct = p.indexer_pct != null ? Number(p.indexer_pct) : null;
  if (idx === 'PRE') {
    return rate ? `PRÉ ${rate.toLocaleString('pt-BR', { maximumFractionDigits: 2 })}%` : 'PRÉ';
  }
  if (pct === 100 && rate) return `${idx} + ${rate.toLocaleString('pt-BR', { maximumFractionDigits: 2 })}%`;
  if (pct && rate)         return `${pct}% ${idx} + ${rate.toLocaleString('pt-BR', { maximumFractionDigits: 2 })}%`;
  if (pct)                 return `${pct}% ${idx}`;
  if (rate)                return `${idx} + ${rate.toLocaleString('pt-BR', { maximumFractionDigits: 2 })}%`;
  return idx;
}

function invBalcaoMaturityTimelineHtml(valued) {
  const rows = valued.filter(p => p.maturity_date);
  if (rows.length === 0) return '';
  return `
    <div style="margin-top:16px;">
      <div style="font-size:1rem;font-weight:600;margin-bottom:8px;color:var(--text-muted);">Cronograma de vencimentos</div>
      <div class="card" style="padding:16px;">
        <canvas id="inv-bar-rf-maturity" style="max-height:240px;"></canvas>
      </div>
    </div>
  `;
}

function invBalcaoRenderMaturityChart(valued) {
  const canvas = document.getElementById('inv-bar-rf-maturity');
  if (!canvas || typeof Chart === 'undefined') return;
  const buckets = {};
  valued.forEach(p => {
    if (!p.maturity_date) return;
    const year = p.maturity_date.slice(0, 4);
    const v = p.current_value ?? 0;
    buckets[year] = (buckets[year] || 0) + v;
  });
  const years = Object.keys(buckets).sort();
  if (years.length === 0) return;
  if (charts['inv-bar-rf-maturity']) charts['inv-bar-rf-maturity'].destroy();
  charts['inv-bar-rf-maturity'] = new Chart(canvas.getContext('2d'), {
    type: 'bar',
    data: {
      labels: years,
      datasets: [{
        label: 'Valor a vencer (R$)',
        data: years.map(y => buckets[y]),
        backgroundColor: 'rgba(96, 165, 250, 0.6)',
        borderColor: 'rgba(96, 165, 250, 1)',
        borderWidth: 1,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, ticks: { color: '#ffffff', callback: v => formatBRL(v) } },
        x: { ticks: { color: '#ffffff' } }
      }
    }
  });
}

function invBalcaoMissingBlock(missing) {
  if (missing.length === 0) return '';
  const open = invBalcaoSectionsOpen.missing ? ' open' : '';
  const totalCost = missing.reduce((s, p) => s + (p.aplicado_total ?? p.cost_basis ?? 0), 0);
  const grouped = {};
  missing.forEach(p => {
    const k = p.broker || '—';
    if (!grouped[k]) grouped[k] = { broker: k, count: 0, cost: 0 };
    grouped[k].count += 1;
    grouped[k].cost += p.aplicado_total ?? p.cost_basis ?? 0;
  });
  let html = `<details data-balcao-section="missing"${open} style="margin-top:24px;">
    <summary style="cursor:pointer;font-size:1.1rem;font-weight:600;margin-bottom:8px;color:var(--amber, #F59E0B);">Sem valoração (${missing.length} produtos · aplicado ${formatBRL(totalCost)})</summary>
    <div style="color:var(--text-muted);font-size:0.9rem;margin-bottom:8px;">Posições sem snapshot recente em <code>balance-snapshots.csv</code>. Importar extrato mensal para valorá-las.</div>
    <table class="inv-rf-table" style="width:auto;"><thead><tr>
      <th style="text-align:left;padding:8px 10px;color:var(--text-muted);font-size:0.85rem;">Instituição</th>
      <th style="text-align:right;padding:8px 10px;color:var(--text-muted);font-size:0.85rem;">Produtos</th>
      <th style="text-align:right;padding:8px 10px;color:var(--text-muted);font-size:0.85rem;">Aplicado (último conhecido)</th>
    </tr></thead><tbody>`;
  Object.values(grouped).sort((a, b) => b.cost - a.cost).forEach(g => {
    const label = INV_BALCAO_BROKER_LABELS[g.broker] || g.broker;
    html += `<tr>
      <td style="padding:8px 10px;border-bottom:1px solid var(--border-faint, var(--border));">${label}</td>
      <td style="text-align:right;padding:8px 10px;border-bottom:1px solid var(--border-faint, var(--border));">${g.count}</td>
      <td class="privacy-hide" style="text-align:right;padding:8px 10px;border-bottom:1px solid var(--border-faint, var(--border));">${formatBRL(g.cost)}</td>
    </tr>`;
  });
  html += `</tbody></table></details>`;
  return html;
}
