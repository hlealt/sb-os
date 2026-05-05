// Investment dashboard — Histórico view.
// Reads raw ledger CSVs (orders, proventos, balcao, crypto) and renders a
// unified, filterable, paginated transaction history. Uses PapaParse (already
// loaded for the expense dashboard).
//
// This view is the only one that bypasses portfolio.json — raw transactions
// are not aggregated into the portfolio output. CSVs are kept fresh by the
// accountant workflow downstream of update_ledgers.py.

const INV_HIST_LEDGERS = [
  { id: 'orders',    file: './ledgers/investimentos/orders.csv',    label: 'Ordens'     },
  { id: 'proventos', file: './ledgers/investimentos/proventos.csv', label: 'Proventos'  },
  { id: 'balcao',    file: './ledgers/investimentos/balcao.csv',    label: 'Balcão'     },
  { id: 'crypto',    file: './ledgers/investimentos/crypto.csv',    label: 'Crypto'     },
];

const INV_HIST_BROKER_LABELS = {
  safra: 'Safra', clear: 'Clear', xp: 'XP', avenue: 'Avenue',
  bipa: 'Bipa', binance: 'Binance', mercado_bitcoin: 'Mercado Bitcoin',
  warren: 'Warren', mercado_pago: 'Mercado Pago', guide: 'Guide',
};

let invHistTxs = null;          // loaded transaction array (cached)
let invHistFilters = { ledger: 'all', broker: 'all', search: '', dateFrom: '', dateTo: '' };
let invHistSortState = { col: 'date', dir: 'desc' };
let invHistPage = 1;
const INV_HIST_PAGE_SIZE = 50;

async function invHistRender(container) {
  if (invHistTxs == null) {
    container.innerHTML = `<div class="loading"><div class="loading-spinner"></div><br>Carregando histórico…</div>`;
    try {
      invHistTxs = await invHistLoadAll();
    } catch (e) {
      container.innerHTML = `<div class="loading" style="color:var(--red)">Erro ao carregar ledgers: ${e.message}</div>`;
      return;
    }
  }

  const filtered = invHistApplyFilters(invHistTxs);
  const sorted   = invHistSortRows(filtered.slice());
  const totalPages = Math.max(1, Math.ceil(sorted.length / INV_HIST_PAGE_SIZE));
  if (invHistPage > totalPages) invHistPage = totalPages;
  const pageRows = sorted.slice((invHistPage - 1) * INV_HIST_PAGE_SIZE, invHistPage * INV_HIST_PAGE_SIZE);

  container.innerHTML = [
    invHistFilterBar(invHistTxs),
    invHistSummary(filtered, sorted),
    invHistTable(pageRows),
    invHistPager(totalPages, sorted.length),
  ].join('');

  invHistWireInteractions(container);
}

async function invHistLoadAll() {
  if (typeof Papa === 'undefined') throw new Error('PapaParse não disponível');
  const all = [];
  for (const cfg of INV_HIST_LEDGERS) {
    const text = await fetch(`${cfg.file}?v=${Date.now()}`).then(r => {
      if (!r.ok) throw new Error(`${cfg.file} → HTTP ${r.status}`);
      return r.text();
    });
    const parsed = Papa.parse(text, { header: true, skipEmptyLines: true, dynamicTyping: false });
    parsed.data.forEach(row => {
      const tx = invHistNormalize(cfg.id, row);
      if (tx) all.push(tx);
    });
  }
  return all;
}

function invHistNormalize(ledger, row) {
  const date = row.date || '';
  if (!date) return null;
  const broker = (row.broker || row.exchange || '').toString().toLowerCase();
  const source = row.source || '';

  if (ledger === 'orders') {
    const qty = Number(row.quantity || 0);
    const total = Number(row.total || 0);
    const side = row.side === 'C' ? 'compra' : row.side === 'V' ? 'venda' : (row.side || '');
    const signedValue = row.side === 'C' ? -total : row.side === 'V' ? total : total;
    return {
      ledger, date, broker, source,
      operation: side,
      asset: row.ticker || '',
      asset_class: row.asset_type || '',
      quantity: qty,
      currency: row.currency || 'BRL',
      value_native: signedValue,
      detail: `${row.market || ''}${row.price ? ` @ ${row.currency || 'BRL'} ${Number(row.price).toLocaleString('pt-BR', { maximumFractionDigits: 4 })}` : ''}`.trim(),
    };
  }
  if (ledger === 'proventos') {
    const net = Number(row.net_value || row.gross_value || 0);
    return {
      ledger, date, broker, source,
      operation: row.type || '',
      asset: row.ticker || '',
      asset_class: '',
      quantity: Number(row.quantity || 0),
      currency: row.currency || 'BRL',
      value_native: net,
      detail: row.value_per_unit ? `${row.currency || 'BRL'} ${Number(row.value_per_unit).toLocaleString('pt-BR', { maximumFractionDigits: 6 })}/un` : '',
    };
  }
  if (ledger === 'balcao') {
    return {
      ledger, date, broker, source,
      operation: row.operation || '',
      asset: row.product_id || '',
      asset_class: row.product_type || '',
      quantity: Number(row.quantity || 0),
      currency: 'BRL',
      value_native: Number(row.amount || 0),
      detail: '',
    };
  }
  if (ledger === 'crypto') {
    const op = row.operation || '';
    const buyQty = Number(row.buy_quantity || 0);
    const sellQty = Number(row.sell_quantity || 0);
    // For BRL→crypto buys, value_native is the BRL spent (negative).
    // For crypto→BRL sells, value_native is BRL received (positive).
    let asset, qty, value;
    if (row.sell_asset === 'BRL') { asset = row.buy_asset; qty = buyQty; value = -sellQty; }
    else if (row.buy_asset === 'BRL') { asset = row.sell_asset; qty = sellQty; value = buyQty; }
    else { asset = row.buy_asset || row.sell_asset; qty = buyQty || sellQty; value = 0; }
    return {
      ledger, date, broker, source,
      operation: op,
      asset,
      asset_class: 'crypto',
      quantity: qty,
      currency: 'BRL',
      value_native: value,
      detail: row.price_brl ? `R$ ${Number(row.price_brl).toLocaleString('pt-BR', { maximumFractionDigits: 2 })}/un` : '',
    };
  }
  return null;
}

function invHistApplyFilters(txs) {
  const { ledger, broker, search, dateFrom, dateTo } = invHistFilters;
  const q = search.trim().toLowerCase();
  return txs.filter(t => {
    if (ledger !== 'all' && t.ledger !== ledger) return false;
    if (broker !== 'all' && t.broker !== broker) return false;
    if (dateFrom && t.date < dateFrom) return false;
    if (dateTo   && t.date > dateTo)   return false;
    if (q && !`${t.asset} ${t.operation} ${t.broker} ${t.source}`.toLowerCase().includes(q)) return false;
    return true;
  });
}

function invHistFilterBar(allTxs) {
  const ledgerOpts = [['all', 'Todos os ledgers'], ...INV_HIST_LEDGERS.map(l => [l.id, l.label])]
    .map(([v, l]) => `<option value="${v}"${v === invHistFilters.ledger ? ' selected' : ''}>${l}</option>`).join('');
  const brokers = ['all', ...Array.from(new Set(allTxs.map(t => t.broker).filter(Boolean))).sort()];
  const brokerOpts = brokers.map(b => {
    const label = b === 'all' ? 'Todas as instituições' : (INV_HIST_BROKER_LABELS[b] || b);
    return `<option value="${b}"${b === invHistFilters.broker ? ' selected' : ''}>${label}</option>`;
  }).join('');

  return `
    <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:16px;">
      <label style="font-size:0.85rem;color:var(--text-muted);">Ledger:
        <select data-hist-ledger style="margin-left:6px;padding:6px 10px;background:var(--surface);border:1px solid var(--border);border-radius:6px;color:var(--text);">${ledgerOpts}</select>
      </label>
      <label style="font-size:0.85rem;color:var(--text-muted);">Instituição:
        <select data-hist-broker style="margin-left:6px;padding:6px 10px;background:var(--surface);border:1px solid var(--border);border-radius:6px;color:var(--text);">${brokerOpts}</select>
      </label>
      <label style="font-size:0.85rem;color:var(--text-muted);">De:
        <input data-hist-from type="date" value="${invHistFilters.dateFrom}" style="margin-left:6px;padding:6px 10px;background:var(--surface);border:1px solid var(--border);border-radius:6px;color:var(--text);">
      </label>
      <label style="font-size:0.85rem;color:var(--text-muted);">Até:
        <input data-hist-to type="date" value="${invHistFilters.dateTo}" style="margin-left:6px;padding:6px 10px;background:var(--surface);border:1px solid var(--border);border-radius:6px;color:var(--text);">
      </label>
      <label style="font-size:0.85rem;color:var(--text-muted);flex:1;min-width:200px;">Busca:
        <input data-hist-search type="text" placeholder="ticker, operação, fonte…" value="${invHistFilters.search.replace(/"/g, '&quot;')}" style="margin-left:6px;padding:6px 10px;background:var(--surface);border:1px solid var(--border);border-radius:6px;color:var(--text);width:100%;max-width:280px;">
      </label>
    </div>
  `;
}

function invHistSummary(filtered, sorted) {
  const count = filtered.length;
  return `<div style="font-size:0.85rem;color:var(--text-muted);margin-bottom:8px;">${count.toLocaleString('pt-BR')} transaç${count === 1 ? 'ão' : 'ões'} (de ${invHistTxs.length.toLocaleString('pt-BR')} totais)</div>`;
}

const INV_HIST_COLUMNS = [
  { key: 'date',        label: 'Data',        align: 'left'  },
  { key: 'ledger',      label: 'Ledger',      align: 'left'  },
  { key: 'operation',   label: 'Operação',    align: 'left'  },
  { key: 'asset',       label: 'Ativo',       align: 'left'  },
  { key: 'broker',      label: 'Instituição', align: 'left'  },
  { key: 'quantity',    label: 'Qtd',         align: 'right' },
  { key: 'value_native',label: 'Valor',       align: 'right', privacy: true },
  { key: 'detail',      label: 'Detalhe',     align: 'left'  },
  { key: 'source',      label: 'Fonte',       align: 'left'  },
];

function invHistTable(rows) {
  if (rows.length === 0) {
    return `<div style="color:var(--text-muted);padding:16px;">Nenhuma transação com os filtros atuais.</div>`;
  }
  let html = `<div style="overflow-x:auto"><table class="inv-rf-table"><thead><tr>`;
  INV_HIST_COLUMNS.forEach(col => {
    const arrow = invHistSortState.col === col.key ? (invHistSortState.dir === 'asc' ? ' ▲' : ' ▼') : '';
    html += `<th data-hist-sort="${col.key}" style="cursor:pointer;text-align:${col.align};padding:8px 10px;border-bottom:1px solid var(--border);font-size:0.85rem;color:var(--text-muted);">${col.label}${arrow}</th>`;
  });
  html += `</tr></thead><tbody>`;
  rows.forEach(t => {
    html += `<tr>`;
    INV_HIST_COLUMNS.forEach(col => {
      html += `<td style="text-align:${col.align};padding:6px 10px;border-bottom:1px solid var(--border-faint, var(--border));font-size:0.85rem;" class="${col.privacy ? 'privacy-hide' : ''}">${invHistFormatCell(t, col)}</td>`;
    });
    html += `</tr>`;
  });
  html += `</tbody></table></div>`;
  return html;
}

function invHistFormatCell(t, col) {
  const v = t[col.key];
  if (v == null || v === '') return '—';
  if (col.key === 'date')          return invFormatBrDate(v);
  if (col.key === 'ledger')        return INV_HIST_LEDGERS.find(l => l.id === v)?.label || v;
  if (col.key === 'broker')        return INV_HIST_BROKER_LABELS[v] || v;
  if (col.key === 'quantity')      return Number(v).toLocaleString('pt-BR', { maximumFractionDigits: 8 });
  if (col.key === 'value_native') {
    const num = Number(v);
    const color = num > 0 ? 'var(--green)' : num < 0 ? 'var(--red)' : 'var(--text-muted)';
    const cur = t.currency === 'USD' ? 'US$ ' : 'R$ ';
    return `<span style="color:${color}">${cur}${Math.abs(num).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>`;
  }
  return v;
}

function invHistSortRows(rows) {
  const { col, dir } = invHistSortState;
  const mult = dir === 'asc' ? 1 : -1;
  rows.sort((a, b) => {
    const va = a[col]; const vb = b[col];
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * mult;
    return String(va).localeCompare(String(vb)) * mult;
  });
  return rows;
}

function invHistPager(totalPages, totalRows) {
  if (totalPages <= 1) return '';
  const prev = invHistPage > 1 ? '' : 'disabled';
  const next = invHistPage < totalPages ? '' : 'disabled';
  return `
    <div style="display:flex;gap:8px;align-items:center;justify-content:center;margin-top:12px;">
      <button data-hist-page="prev" ${prev} style="padding:4px 12px;background:var(--surface);border:1px solid var(--border);border-radius:6px;color:var(--text);cursor:${prev ? 'not-allowed' : 'pointer'};opacity:${prev ? '0.4' : '1'}">‹ Anterior</button>
      <span style="font-size:0.85rem;color:var(--text-muted);">Página ${invHistPage} de ${totalPages}</span>
      <button data-hist-page="next" ${next} style="padding:4px 12px;background:var(--surface);border:1px solid var(--border);border-radius:6px;color:var(--text);cursor:${next ? 'not-allowed' : 'pointer'};opacity:${next ? '0.4' : '1'}">Próxima ›</button>
    </div>
  `;
}

function invHistWireInteractions(container) {
  const reset = () => { invHistPage = 1; invHistRender(container); };
  container.querySelector('[data-hist-ledger]')?.addEventListener('change', e => { invHistFilters.ledger = e.target.value; reset(); });
  container.querySelector('[data-hist-broker]')?.addEventListener('change', e => { invHistFilters.broker = e.target.value; reset(); });
  container.querySelector('[data-hist-from]')?.addEventListener('change',   e => { invHistFilters.dateFrom = e.target.value; reset(); });
  container.querySelector('[data-hist-to]')?.addEventListener('change',     e => { invHistFilters.dateTo   = e.target.value; reset(); });
  // Search: re-render only on Enter or blur to avoid losing input focus.
  const searchEl = container.querySelector('[data-hist-search]');
  if (searchEl) {
    searchEl.addEventListener('keydown', e => { if (e.key === 'Enter') { invHistFilters.search = e.target.value; reset(); }});
    searchEl.addEventListener('blur',    e => { if (invHistFilters.search !== e.target.value) { invHistFilters.search = e.target.value; reset(); }});
  }
  container.querySelectorAll('[data-hist-sort]').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.histSort;
      if (invHistSortState.col === col) {
        invHistSortState.dir = invHistSortState.dir === 'asc' ? 'desc' : 'asc';
      } else {
        invHistSortState.col = col;
        invHistSortState.dir = (col === 'date' || col === 'value_native' || col === 'quantity') ? 'desc' : 'asc';
      }
      invHistRender(container);
    });
  });
  container.querySelectorAll('[data-hist-page]').forEach(btn => {
    btn.addEventListener('click', () => {
      if (btn.disabled) return;
      invHistPage += btn.dataset.histPage === 'next' ? 1 : -1;
      invHistRender(container);
    });
  });
}
