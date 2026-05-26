// Shared utilities, components, and state for financial dashboards.
// Loaded by dashboard.html — shared utilities for expenses and investments modes.
// No modules — all functions are globals.

const CACHE_BUST = `?v=${Date.now()}`;

const COLOR_PALETTE = [
  '#38BDF8', '#22C55E', '#2563EB', '#14B8A6', '#7C3AED',
  '#06B6D4', '#10B981', '#3B82F6', '#84CC16', '#0EA5E9',
  '#6D28D9', '#2DD4BF', '#16A34A', '#60A5FA', '#0891B2',
  '#A3E635', '#1D4ED8', '#34D399', '#4F46E5', '#0F766E',
  '#F59E0B', '#65A30D', '#0284C7', '#8B5CF6', '#059669',
  '#93C5FD', '#F97316', '#67E8F9', '#86EFAC', '#94A3B8'
];

const EXCLUDED_CATEGORIES = new Set(['ignorar', 'intercontas']);

const BANK_NAMES = {
  'bradesco_extrato': 'Bradesco',
  'mp_extrato': 'Mercado Pago',
  'mp_fatura': 'Mercado Pago',
  'santander_extrato': 'Santander',
  'santander_fatura': 'Santander',
  'nubank_fatura': 'Nubank',
  'wise_extrato': 'Wise',
  'xp_fatura': 'XP'
};

// Global state shared across page-specific scripts
let allData = {};
let charts = {};
let categoryColorMap = {};

// --- Utility functions ---

function bankName(bankId) { return BANK_NAMES[bankId] || bankId; }
function bankGroup(bankId) { return bankName(bankId); }

function buildColorMap(data) {
  const allValues = new Set();
  Object.values(data).flat().forEach(r => {
    if (r.category) allValues.add(r.category);
  });
  const sorted = [...allValues].sort();
  categoryColorMap = {};
  sorted.forEach((val, i) => { categoryColorMap[val] = COLOR_PALETTE[i % COLOR_PALETTE.length]; });
}

function catColor(cat) { return categoryColorMap[cat] || COLOR_PALETTE[0]; }

function formatBRL(v) {
  const n = typeof v === 'number' ? v : parseFloat(v) || 0;
  const abs = Math.abs(n);
  const formatted = abs.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return (n < 0 ? '-' : '') + 'R$ ' + formatted;
}

function formatMonth(m) {
  const [y, mm] = m.split('-');
  const names = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];
  return names[parseInt(mm)-1] + ' ' + y;
}

function catLabel(c, sub) {
  const fmt = s => (s || '').replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  if (c && c.includes(':')) return c.replace(':', ': ').replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  if (sub) return fmt(c) + ': ' + fmt(sub);
  return fmt(c);
}

function fullCatKey(r) {
  return r.category || 'a_identificar';
}

// --- Collapsible sections ---

function toggleCollapse(header) {
  const section = header.parentElement;
  const wasCollapsed = section.classList.contains('collapsed');
  section.classList.toggle('collapsed');
  if (wasCollapsed) {
    const canvases = section.querySelectorAll('canvas');
    if (canvases.length > 0) {
      setTimeout(() => {
        canvases.forEach(c => { if (charts[c.id]) charts[c.id].resize(); });
      }, 350);
    }
  }
}

// --- Multi-select dropdown component ---

function createMultiSelect(id, allLabel, options, month, onChange) {
  const wrapper = document.createElement('div');
  wrapper.className = 'multi-select';
  wrapper.id = id;
  wrapper.dataset.allLabel = allLabel;
  wrapper.dataset.month = month || '';
  wrapper._onChange = onChange || null;
  const triggerChange = () => { if (wrapper._onChange) wrapper._onChange(); else filterTable(month); };
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'multi-select-btn';
  btn.textContent = allLabel;
  const dropdown = document.createElement('div');
  dropdown.className = 'multi-select-dropdown';
  options.forEach(opt => {
    const label = document.createElement('label');
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.value = opt.value;
    cb.dataset.label = opt.label;
    cb.addEventListener('change', () => {
      updateMultiSelectChips(wrapper);
      triggerChange();
    });
    label.appendChild(cb);
    label.appendChild(document.createTextNode(opt.label));
    const exBtn = document.createElement('button');
    exBtn.type = 'button';
    exBtn.className = 'exclude-btn';
    exBtn.title = 'Selecionar todas exceto esta';
    exBtn.textContent = '\u2212';
    exBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      wrapper.querySelectorAll('input[type="checkbox"]').forEach(c => {
        c.checked = (c.value !== opt.value);
      });
      updateMultiSelectChips(wrapper);
      triggerChange();
    });
    label.appendChild(exBtn);
    dropdown.appendChild(label);
  });
  dropdown.addEventListener('click', (e) => {
    e.stopPropagation();
  });
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    document.querySelectorAll('.multi-select-dropdown.open').forEach(d => { if (d !== dropdown) d.classList.remove('open'); });
    dropdown.classList.toggle('open');
  });
  const chips = document.createElement('div');
  chips.className = 'multi-select-chips';
  wrapper.appendChild(btn);
  wrapper.appendChild(dropdown);
  wrapper.appendChild(chips);
  return wrapper;
}

function getMultiSelectValues(id) {
  const el = document.getElementById(id);
  if (!el) return [];
  return [...el.querySelectorAll('input[type="checkbox"]:checked')].map(cb => cb.value);
}

function updateMultiSelectChips(wrapper) {
  const allLabel = wrapper.dataset.allLabel;
  const month = wrapper.dataset.month;
  const checked = [...wrapper.querySelectorAll('input[type="checkbox"]:checked')];
  const btn = wrapper.querySelector('.multi-select-btn');
  const chips = wrapper.querySelector('.multi-select-chips');
  if (checked.length === 0) {
    btn.textContent = allLabel;
    chips.innerHTML = '';
    return;
  }
  btn.textContent = checked.length + ' selecionada' + (checked.length > 1 ? 's' : '');
  chips.innerHTML = checked.map(cb => {
    return '<span class="filter-chip" data-value="' + cb.value + '">' + cb.dataset.label + '<span class="filter-chip-x">\u00d7</span></span>';
  }).join('');
  chips.querySelectorAll('.filter-chip').forEach(chip => {
    chip.addEventListener('click', (e) => {
      e.stopPropagation();
      const val = chip.dataset.value;
      const cb = wrapper.querySelector('input[type="checkbox"][value="' + val + '"]');
      if (cb) { cb.checked = false; }
      updateMultiSelectChips(wrapper);
      if (wrapper._onChange) wrapper._onChange(); else filterTable(month);
    });
  });
}

// Close multi-select dropdowns on click outside
document.addEventListener('click', () => {
  document.querySelectorAll('.multi-select-dropdown.open').forEach(d => d.classList.remove('open'));
});

// --- Privacy mode ---

function togglePrivacy(btn) {
  document.body.classList.toggle('privacy-mode');
  const active = document.body.classList.contains('privacy-mode');
  btn.classList.toggle('active', active);
  btn.textContent = active ? 'Mostrar Valores' : 'Ocultar Valores';
  updateChartsPrivacy(active);
}

function updateChartsPrivacy(hidden) {
  Object.keys(charts).forEach(key => {
    const chart = charts[key];
    chart.options.plugins.tooltip.enabled = !hidden;
    if (key.startsWith('bar-') || key.startsWith('inv-bar-')) {
      if (chart.options.scales && chart.options.scales.x) {
        if (!chart.options.scales.x.ticks) chart.options.scales.x.ticks = {};
        chart.options.scales.x.ticks.display = !hidden;
      }
    } else if (key === 'evo-line' || key === 'evo-stacked' || key === 'evo-recurrence' || key.startsWith('inv-line-')) {
      if (chart.options.scales && chart.options.scales.y) {
        if (!chart.options.scales.y.ticks) chart.options.scales.y.ticks = {};
        chart.options.scales.y.ticks.display = !hidden;
      }
    } else if (key.startsWith('inv-pie-')) {
      // Donut charts use chartjs-plugin-datalabels to render BRL amounts on slices.
      // Tooltip toggle alone leaves those visible; hide datalabels too.
      if (chart.options.plugins.datalabels) {
        chart.options.plugins.datalabels.display = !hidden;
      }
    }
    chart.update('none');
  });
}
