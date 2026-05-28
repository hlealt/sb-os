// Investment dashboard — Crypto view.
// Pure renderer: reads valuation_method === 'crypto' positions from inv-data.js.
// Spec: position cards (qty, value BRL, cost, P&L) + BTC dominance.
// Loaded after shared.js, inv-data.js, inv-carteira.js.

// Investment broker label lookup — canonical map lives in shared.js (BROKER_LABELS).
// INV_CRYPTO_BROKER_LABELS removed; all callers below use invBrokerLabelShared().

let invCryptoSortState = { col: 'current_value', dir: 'desc' };

function invCryptoRender(container) {
  const portfolio = invGetPortfolio();
  if (!portfolio) {
    container.innerHTML = `<div class="loading" style="color:var(--red)">${invGetLoadError() || 'Sem dados'}</div>`;
    return;
  }

  const positions = (portfolio.positions || []).filter(p => p.valuation_method === 'crypto');

  if (positions.length === 0) {
    container.innerHTML = `<div class="loading" style="color:var(--text-muted)">Nenhuma posição cripto encontrada.</div>`;
    return;
  }

  container.innerHTML = [
    invCryptoSummaryCards(positions),
    invCryptoPositionsBlock(positions),
  ].join('');

  container.querySelectorAll('[data-crypto-sort]').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.cryptoSort;
      if (invCryptoSortState.col === col) {
        invCryptoSortState.dir = invCryptoSortState.dir === 'asc' ? 'desc' : 'asc';
      } else {
        invCryptoSortState.col = col;
        invCryptoSortState.dir = (col === 'name' || col === 'broker_label') ? 'asc' : 'desc';
      }
      invCryptoRender(container);
    });
  });
}

function invCryptoSummaryCards(positions) {
  const total = positions.reduce((s, p) => s + (p.current_value_brl ?? p.current_value ?? 0), 0);
  const cost  = positions.reduce((s, p) => s + (p.cost_basis_brl  ?? p.cost_basis  ?? 0), 0);
  const pnl   = total - cost;
  const pnlPct = cost > 0 ? pnl / cost : 0;

  const btcValue = positions
    .filter(p => p.id === 'BTC')
    .reduce((s, p) => s + (p.current_value_brl ?? p.current_value ?? 0), 0);
  const dominance = total > 0 ? btcValue / total : 0;

  return `
    <div class="cards">
      <div class="card">
        <div class="card-label">Valor cripto</div>
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
        <div class="card-label">BTC dominance</div>
        <div class="card-value">${invFormatPctValue(dominance)}</div>
        <div style="font-size:0.8rem;color:var(--text-muted);">${positions.length} ativo${positions.length === 1 ? '' : 's'}</div>
      </div>
    </div>
  `;
}

const INV_CRYPTO_COLUMNS = [
  { key: 'name',          label: 'Ativo',       align: 'left'  },
  { key: 'broker_label',  label: 'Exchange',    align: 'left'  },
  { key: 'quantity',      label: 'Qtd',         align: 'right' },
  { key: 'current_price', label: 'Preço',       align: 'right', privacy: true },
  { key: 'avg_cost',      label: 'PM',          align: 'right', privacy: true },
  { key: 'cost_basis',    label: 'Aplicado',    align: 'right', privacy: true },
  { key: 'current_value', label: 'Valor',       align: 'right', privacy: true },
  { key: 'pnl_absolute',  label: 'P&L',         align: 'right', privacy: true },
  { key: 'pnl_pct',       label: 'Retorno %',   align: 'right', privacy: true },
  { key: 'price_date',    label: 'Cotação',     align: 'left'  },
];

function invCryptoPositionsBlock(positions) {
  const decorated = positions.map(p => ({
    ...p,
    broker_label: invBrokerLabelShared(p.broker),
  }));
  const rows = invCryptoSortRows(decorated);

  let html = `<div style="margin-top:24px;overflow-x:auto"><table class="inv-rf-table"><thead><tr>`;
  INV_CRYPTO_COLUMNS.forEach(col => {
    const arrow = invCryptoSortState.col === col.key ? (invCryptoSortState.dir === 'asc' ? ' ▲' : ' ▼') : '';
    html += `<th data-crypto-sort="${col.key}" style="cursor:pointer;text-align:${col.align};padding:8px 10px;border-bottom:1px solid var(--border);font-size:0.85rem;color:var(--text-muted);">${col.label}${arrow}</th>`;
  });
  html += `</tr></thead><tbody>`;
  rows.forEach(p => {
    html += `<tr>`;
    INV_CRYPTO_COLUMNS.forEach(col => {
      html += `<td style="text-align:${col.align};padding:8px 10px;border-bottom:1px solid var(--border-faint, var(--border));" class="${col.privacy ? 'privacy-hide' : ''}">${invCryptoFormatCell(p, col)}</td>`;
    });
    html += `</tr>`;
  });
  html += `</tbody></table></div>`;
  return html;
}

function invCryptoFormatCell(p, col) {
  if (col.key === 'name') {
    const dot = invPriceSourceDot(p);
    return `<span title="${dot.label}" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${dot.color};margin-right:6px;vertical-align:middle;"></span><strong>${p.name || p.id}</strong> <span style="font-size:0.75rem;color:var(--text-muted);">${p.id}</span>`;
  }
  if (col.key === 'price_date') {
    return p.price_date ? invFormatBrDate(p.price_date) : '—';
  }
  if (col.key === 'quantity') {
    return invCryptoFormatQty(p.quantity);
  }
  const v = col.key === 'current_value' ? (p.current_value_brl ?? p.current_value)
          : col.key === 'cost_basis'    ? (p.cost_basis_brl    ?? p.cost_basis)
          : col.key === 'pnl_absolute'  ? ((p.current_value_brl ?? p.current_value ?? 0) - (p.cost_basis_brl ?? p.cost_basis ?? 0))
          : col.key === 'pnl_pct'       ? (() => {
              const c = p.cost_basis_brl ?? p.cost_basis ?? 0;
              const v_ = p.current_value_brl ?? p.current_value ?? 0;
              return c > 0 ? (v_ - c) / c : null;
            })()
          : p[col.key];
  if (v == null || v === '') return '—';
  if (col.key === 'pnl_pct')      return invFormatPctValue(v);
  if (col.key === 'pnl_absolute') {
    const color = v >= 0 ? 'var(--green)' : 'var(--red)';
    return `<span style="color:${color}">${formatBRL(v)}</span>`;
  }
  if (col.key === 'current_price' || col.key === 'avg_cost') {
    // Per-unit quote: render BRL (current_price already in BRL for crypto positions in portfolio.json).
    return formatBRL(v);
  }
  if (col.key === 'current_value' || col.key === 'cost_basis') return formatBRL(v);
  return v;
}

function invCryptoFormatQty(v) {
  if (v == null) return '—';
  // Crypto is always fractional — up to 8 decimals, trim trailing zeros.
  const s = Number(v).toLocaleString('pt-BR', { maximumFractionDigits: 8 });
  return s;
}

function invCryptoSortRows(rows) {
  const { col, dir } = invCryptoSortState;
  const mult = dir === 'asc' ? 1 : -1;
  rows.sort((a, b) => {
    const va = invCryptoSortValue(a, col);
    const vb = invCryptoSortValue(b, col);
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    if (typeof va === 'string') return va.localeCompare(vb) * mult;
    return (va - vb) * mult;
  });
  return rows;
}

function invCryptoSortValue(p, col) {
  if (col === 'current_value') return p.current_value_brl ?? p.current_value;
  if (col === 'cost_basis')    return p.cost_basis_brl ?? p.cost_basis;
  if (col === 'pnl_absolute')  return (p.current_value_brl ?? p.current_value ?? 0) - (p.cost_basis_brl ?? p.cost_basis ?? 0);
  if (col === 'pnl_pct') {
    const c = p.cost_basis_brl ?? p.cost_basis ?? 0;
    const v = p.current_value_brl ?? p.current_value ?? 0;
    return c > 0 ? (v - c) / c : null;
  }
  return p[col];
}
