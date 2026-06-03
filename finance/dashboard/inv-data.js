// Investment data layer — loads portfolio.json and manages snapshots.
// Loaded after shared.js. Pure data, no rendering.
// Data paths are vault-root-absolute via FIN_DATA_BASE (shared.js) — the
// entry HTML's install location is configurable, so nothing resolves
// relative to the page.

const INV_DATA_DIR = `${FIN_DATA_BASE}/ledgers/investimentos`;
const INV_CURRENT_FILE = 'portfolio.json';
const INV_SNAPSHOTS_MANIFEST = 'snapshots.json';

// Module state (read by view modules)
let invPortfolio = null;            // current loaded portfolio.json
let invSnapshots = [];              // [{ date, file, label }, ...]
let invCurrentSnapshot = 'current'; // 'current' or 'YYYY-MM-DD'
let invLoadError = null;            // last load error (string) or null
let invLiveCutDate = null;          // cut_date of the live portfolio.json (cached on first 'current' load)

// --- Loaders ---

async function invLoadSnapshots() {
  try {
    const res = await fetch(`${INV_DATA_DIR}/${INV_SNAPSHOTS_MANIFEST}${CACHE_BUST}`);
    if (!res.ok) { invSnapshots = []; return; }
    const raw = await res.json();
    invSnapshots = invNormalizeSnapshots(raw);
  } catch (e) {
    invSnapshots = [];
  }
}

function invNormalizeSnapshots(raw) {
  // Accepts PRD schema { snapshots: [{date,file,label}], current } OR array of dates.
  if (Array.isArray(raw)) {
    return raw.map(d => ({
      date: d,
      file: `portfolio-${d}.json`,
      label: invFormatBrDate(d)
    }));
  }
  if (raw && Array.isArray(raw.snapshots)) {
    return raw.snapshots.map(s => ({
      date: s.date,
      file: s.file || `portfolio-${s.date}.json`,
      label: s.label || invFormatBrDate(s.date)
    }));
  }
  return [];
}

function invFormatBrDate(iso) {
  if (!iso) return '';
  const [y, m, d] = iso.split('-');
  return `${d}/${m}/${y}`;
}

async function invLoadPortfolio(which) {
  // which: 'current' or an ISO date string present in invSnapshots
  invLoadError = null;
  invPortfolio = null;
  invCurrentSnapshot = which || 'current';
  const file = invResolvePortfolioFile(invCurrentSnapshot);
  try {
    const res = await fetch(`${INV_DATA_DIR}/${file}${CACHE_BUST}`);
    if (!res.ok) {
      invLoadError = `Arquivo não encontrado: ${file}. Execute calculate.py para gerar dados.`;
      return null;
    }
    invPortfolio = await res.json();
    if (which === 'current' || !which) {
      invLiveCutDate = invPortfolio?.meta?.cut_date || invLiveCutDate;
    }
    return invPortfolio;
  } catch (e) {
    invLoadError = `Erro ao carregar ${file}: ${e.message}`;
    return null;
  }
}

function invResolvePortfolioFile(which) {
  if (!which || which === 'current') return INV_CURRENT_FILE;
  const match = invSnapshots.find(s => s.date === which);
  return match ? match.file : INV_CURRENT_FILE;
}

function invGetPortfolio() { return invPortfolio; }
function invGetSnapshots() { return invSnapshots; }
function invGetCurrentSnapshot() { return invCurrentSnapshot; }
function invGetLoadError() { return invLoadError; }
function invGetLiveCutDate() { return invLiveCutDate; }

// --- Position helpers (used by view modules) ---

function invPositionsByClass(cls) {
  if (!invPortfolio || !Array.isArray(invPortfolio.positions)) return [];
  return invPortfolio.positions.filter(p => p.asset_class === cls);
}

// Filters positions by valuation_method ('price' | 'balcao' | 'crypto').
// Decoupled from asset_class: a non-DI fund has asset_class='variable_income'
// but valuation_method='balcao', so views that render balcão-style data filter
// by method, not class.
function invPositionsByMethod(method) {
  if (!invPortfolio || !Array.isArray(invPortfolio.positions)) return [];
  return invPortfolio.positions.filter(p => p.valuation_method === method);
}

function invPriceSourceDot(position) {
  // Returns { color, label } for the UX indicator.
  const src = position.price_source;
  if (src === 'api') {
    const d = position.price_date ? invFormatBrDate(position.price_date) : null;
    return { color: 'var(--green)', label: d ? `Cotação ${d}` : 'Cotação' };
  }
  if (src === 'snapshot') {
    const age = position.snapshot_age_days;
    if (typeof age === 'number' && age > 60) {
      return { color: 'var(--amber, #F59E0B)', label: `Saldo desatualizado (${invFormatBrDate(position.valuation_date || position.price_date)})` };
    }
    return { color: 'var(--text-muted)', label: `Saldo em ${invFormatBrDate(position.valuation_date || position.price_date)}` };
  }
  if (src === 'missing') {
    return { color: 'var(--red)', label: 'Sem valoração' };
  }
  return { color: 'var(--text-muted)', label: '—' };
}
