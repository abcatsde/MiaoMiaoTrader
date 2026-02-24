let accessToken = '';
let state = {
  llm_providers: [],
  trading_preferences: { timeframe: '15m', max_pairs: 2, max_timeframes: 2, margin_mode: 'isolated' },
  okx: { api_key: '', api_secret: '', passphrase: '', base_url: 'https://www.okx.com' }
};

function login() {
  const token = document.getElementById('token').value.trim();
  if (!token) return;
  accessToken = token;
  document.getElementById('loginView').classList.add('hidden');
  document.getElementById('appView').classList.remove('hidden');
  loadConfig();
}

function renderLLMList() {
  const list = document.getElementById('llmList');
  list.innerHTML = '';
  state.llm_providers.forEach((p, idx) => {
    const item = document.createElement('div');
    item.className = 'llm-item';
    item.draggable = true;
    item.dataset.index = String(idx);
    item.innerHTML = `
      <div class="drag">☰</div>
      <input placeholder="name" value="${p.name || ''}" data-field="name" />
      <input placeholder="endpoint" value="${p.endpoint || ''}" data-field="endpoint" />
      <input placeholder="api_key" value="${p.api_key || ''}" data-field="api_key" />
      <input placeholder="model" value="${p.model || ''}" data-field="model" />
      <select data-field="enabled">
        <option value="true" ${p.enabled ? 'selected' : ''}>启用</option>
        <option value="false" ${!p.enabled ? 'selected' : ''}>停用</option>
      </select>
      <button class="btn btn-danger" onclick="removeProvider(${idx})">删</button>
    `;

    item.addEventListener('input', (e) => {
      const target = e.target;
      if (!target || !target.dataset.field) return;
      const field = target.dataset.field;
      if (field === 'enabled') {
        state.llm_providers[idx][field] = target.value === 'true';
      } else {
        state.llm_providers[idx][field] = target.value;
      }
      syncRaw();
    });

    item.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('text/plain', item.dataset.index);
    });
    item.addEventListener('dragover', (e) => e.preventDefault());
    item.addEventListener('drop', (e) => {
      e.preventDefault();
      const from = Number(e.dataTransfer.getData('text/plain'));
      const to = Number(item.dataset.index);
      if (Number.isNaN(from) || Number.isNaN(to) || from === to) return;
      const moved = state.llm_providers.splice(from, 1)[0];
      state.llm_providers.splice(to, 0, moved);
      renderLLMList();
      syncRaw();
    });

    list.appendChild(item);
  });
}

function openProviderModal() {
  document.getElementById('providerModal').classList.remove('hidden');
}

function closeProviderModal() {
  document.getElementById('providerModal').classList.add('hidden');
}

function saveProviderFromModal() {
  const name = document.getElementById('providerName').value.trim();
  const key = document.getElementById('providerKey').value.trim();
  const endpoint = document.getElementById('providerEndpoint').value.trim();
  const model = document.getElementById('providerModel').value.trim() || 'gpt-4o-mini';
  if (!name || !key || !endpoint) return;

  state.llm_providers.push({
    name,
    api_key: key,
    endpoint,
    model,
    enabled: true,
    weight: 1
  });
  renderLLMList();
  syncRaw();
  closeProviderModal();
}

function addEmptyProvider() {
  state.llm_providers.push({ name: '', endpoint: '', api_key: '', model: '', enabled: true, weight: 1 });
  renderLLMList();
  syncRaw();
}

function removeProvider(index) {
  state.llm_providers.splice(index, 1);
  renderLLMList();
  syncRaw();
}

function syncRaw() {
  document.getElementById('configRaw').value = JSON.stringify(state, null, 2);
}

function syncFormToState() {
  state.trading_preferences = {
    timeframe: document.getElementById('prefTimeframe').value || '15m',
    max_pairs: Number(document.getElementById('prefMaxPairs').value || 2),
    max_timeframes: Number(document.getElementById('prefMaxTF').value || 2),
    margin_mode: document.getElementById('prefMarginMode').value || 'isolated',
    universe: {
      mainstream: document.getElementById('optMainstream').checked,
      alt: document.getElementById('optAlt').checked
    },
    horizon: {
      scalp: document.getElementById('optScalp').checked,
      intraday: document.getElementById('optIntraday').checked,
      swing: document.getElementById('optSwing').checked
    },
    market: {
      spot: document.getElementById('optSpot').checked,
      derivatives: document.getElementById('optDeriv').checked
    }
  };
  state.okx = {
    base_url: document.getElementById('okxBaseUrl').value || 'https://www.okx.com',
    api_key: document.getElementById('okxKey').value || '',
    api_secret: document.getElementById('okxSecret').value || '',
    passphrase: document.getElementById('okxPass').value || '',
    trade_mode: document.getElementById('okxTradeMode').value || 'real',
    we_enabled: document.getElementById('okxWeEnabled').checked
  };
  state.web_port = Number(document.getElementById('webPort').value || 8088);
}

function syncStateToForm() {
  document.getElementById('prefTimeframe').value = state.trading_preferences?.timeframe || '15m';
  document.getElementById('prefMaxPairs').value = state.trading_preferences?.max_pairs ?? 2;
  document.getElementById('prefMaxTF').value = state.trading_preferences?.max_timeframes ?? 2;
  document.getElementById('prefMarginMode').value = state.trading_preferences?.margin_mode || 'isolated';
  document.getElementById('optMainstream').checked = !!state.trading_preferences?.universe?.mainstream;
  document.getElementById('optAlt').checked = !!state.trading_preferences?.universe?.alt;
  document.getElementById('optScalp').checked = !!state.trading_preferences?.horizon?.scalp;
  document.getElementById('optIntraday').checked = !!state.trading_preferences?.horizon?.intraday;
  document.getElementById('optSwing').checked = !!state.trading_preferences?.horizon?.swing;
  document.getElementById('optSpot').checked = !!state.trading_preferences?.market?.spot;
  document.getElementById('optDeriv').checked = !!state.trading_preferences?.market?.derivatives;
  document.getElementById('okxBaseUrl').value = state.okx?.base_url || 'https://www.okx.com';
  document.getElementById('okxKey').value = state.okx?.api_key || '';
  document.getElementById('okxSecret').value = state.okx?.api_secret || '';
  document.getElementById('okxPass').value = state.okx?.passphrase || '';
  document.getElementById('okxTradeMode').value = state.okx?.trade_mode || 'real';
  document.getElementById('okxWeEnabled').checked = !!state.okx?.we_enabled;
  document.getElementById('webPort').value = state.web_port ?? 8088;
  syncRaw();
  renderLLMList();
}

async function loadConfig() {
  const res = await fetch('/api/config', { headers: { 'X-Access-Token': accessToken }});
  const data = await res.json();
  state = data;
  syncStateToForm();
}

async function saveConfig() {
  syncFormToState();
  const res = await fetch('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Access-Token': accessToken },
    body: JSON.stringify(state)
  });
  const data = await res.json();
  alert(JSON.stringify(data));
}

async function restartApp() {
  const res = await fetch('/api/restart', {
    method: 'POST',
    headers: { 'X-Access-Token': accessToken }
  });
  const data = await res.json();
  alert(JSON.stringify(data));
}

window.addEventListener('DOMContentLoaded', () => {
  const raw = document.getElementById('configRaw');
  raw.addEventListener('input', (e) => {
    try {
      const parsed = JSON.parse(e.target.value);
      state = parsed;
      syncStateToForm();
    } catch (_e) {}
  });
});
