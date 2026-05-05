// Investment dashboard — thin router.
// Delegates to view modules. Data layer: inv-data.js. Views: inv-carteira.js (MVP v1).
// Loaded after shared.js, inv-data.js, inv-carteira.js.

const INV_TABS = [
  { id: 'carteira',        label: 'Carteira',       render: invRenderCarteira,  mvp: true },
  { id: 'bolsa',           label: 'Bolsa',          render: invBolsaRender,     mvp: true },
  { id: 'balcao',          label: 'Balcão',         render: invBalcaoRender,    mvp: true  },
  { id: 'crypto',          label: 'Crypto',         render: invCryptoRender,    mvp: true  },
  { id: 'proventos',       label: 'Proventos',      render: invProvRender,      mvp: true  },
  { id: 'historico',       label: 'Histórico',      render: invHistRender,      mvp: true  }
];

async function invInit() {
  const contentEl = document.getElementById('inv-content');
  contentEl.innerHTML = `<div class="loading"><div class="loading-spinner"></div><br>Carregando portfólio...</div>`;
  await invLoadSnapshots();
  await invLoadPortfolio('current');
  invRenderTabs();
}

function invRenderTabs() {
  const tabsEl = document.getElementById('inv-tabs');
  const contentEl = document.getElementById('inv-content');
  tabsEl.innerHTML = '';
  contentEl.innerHTML = '';

  INV_TABS.forEach((t, i) => {
    const btn = document.createElement('button');
    btn.className = 'tab' + (i === 0 ? ' active' : '');
    btn.textContent = t.label;
    btn.dataset.tabId = t.id;
    btn.onclick = () => invSwitchTab(t.id);
    tabsEl.appendChild(btn);

    const div = document.createElement('div');
    div.className = 'tab-content' + (i === 0 ? ' active' : '');
    div.id = 'tab-' + t.id;
    contentEl.appendChild(div);
  });

  // Render only the active tab on load
  const active = INV_TABS[0];
  active.render(document.getElementById('tab-' + active.id));
}

function invSwitchTab(id) {
  document.querySelectorAll('#inv-tabs .tab').forEach(t => t.classList.toggle('active', t.dataset.tabId === id));
  document.querySelectorAll('#inv-content .tab-content').forEach(t => t.classList.toggle('active', t.id === 'tab-' + id));
  const tab = INV_TABS.find(t => t.id === id);
  const el = document.getElementById('tab-' + id);
  // Always re-render on switch: cheap, and guarantees snapshot-switch propagates to every view
  if (tab && el) tab.render(el);
}

function invRenderStub(container) {
  container.innerHTML = `<div class="loading" style="color:var(--text-muted)">Em breve — esta view será implementada em uma unidade posterior do plano.</div>`;
}

// --- Init ---
invInit();
