let accessToken = '';
let autoLoginBlocked = false;
let state = {
  llm_providers: [],
  llm_timeout_sec: 30,
  trading_preferences: { timeframe: '15m', max_pairs: 2, max_timeframes: 2, margin_mode: 'isolated' },
  okx: { api_key: '', api_secret: '', passphrase: '', base_url: 'https://www.okx.com' }
};

function setStatus(message, type = '') {
  const status = document.getElementById('status');
  if (!status) return;
  status.classList.remove('ok', 'error', 'warn');
  if (type) status.classList.add(type);
  status.textContent = message;
}

function handleInvalidToken(message = 'Invalid token') {
  try { localStorage.removeItem('mm_token'); } catch (_e) {}
  try { sessionStorage.setItem('mm_token_invalid', '1'); } catch (_e) {}
  accessToken = '';
  const loginView = document.getElementById('loginView');
  const appView = document.getElementById('appView');
  if (appView) appView.classList.add('hidden');
  if (loginView) loginView.classList.remove('hidden');
  setStatus(message, 'error');
}

function login() {
  const token = document.getElementById('token').value.trim();
  if (!token) return;
  accessToken = token;
  try { sessionStorage.removeItem('mm_token_invalid'); } catch (_e) {}
  try { localStorage.setItem('mm_token', token); } catch (_e) {}
  document.getElementById('loginView').classList.add('hidden');
  document.getElementById('appView').classList.remove('hidden');
  closeProviderModal();
  setStatus('加载配置中...', 'warn');
  loadConfig();
}

function renderLLMList() {
  const list = document.getElementById('llmList');
  if (!list) return;
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
  const appView = document.getElementById('appView');
  const modal = document.getElementById('providerModal');
  if (!modal) return;
  if (appView.classList.contains('hidden')) return;
  modal.classList.remove('hidden');
}

function closeProviderModal() {
  const modal = document.getElementById('providerModal');
  if (!modal) return;
  modal.classList.add('hidden');
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
  const raw = document.getElementById('configRaw');
  if (!raw) return;
  raw.value = JSON.stringify(state, null, 2);
}

function syncFormToState() {
  const prefTimeframe = document.getElementById('prefTimeframe');
  const prefMaxPairs = document.getElementById('prefMaxPairs');
  const prefMaxTF = document.getElementById('prefMaxTF');
  const prefMarginMode = document.getElementById('prefMarginMode');
  const optMainstream = document.getElementById('optMainstream');
  const optAlt = document.getElementById('optAlt');
  const optScalp = document.getElementById('optScalp');
  const optIntraday = document.getElementById('optIntraday');
  const optSwing = document.getElementById('optSwing');
  const optSpot = document.getElementById('optSpot');
  const optDeriv = document.getElementById('optDeriv');

  if (prefTimeframe && prefMaxPairs && prefMaxTF && prefMarginMode) {
    state.trading_preferences = {
      timeframe: prefTimeframe.value || '15m',
      max_pairs: Number(prefMaxPairs.value || 2),
      max_timeframes: Number(prefMaxTF.value || 2),
      margin_mode: prefMarginMode.value || 'isolated',
      universe: {
        mainstream: !!optMainstream?.checked,
        alt: !!optAlt?.checked
      },
      horizon: {
        scalp: !!optScalp?.checked,
        intraday: !!optIntraday?.checked,
        swing: !!optSwing?.checked
      },
      market: {
        spot: !!optSpot?.checked,
        derivatives: !!optDeriv?.checked
      }
    };
  }

  const okxBaseUrl = document.getElementById('okxBaseUrl');
  const okxKey = document.getElementById('okxKey');
  const okxSecret = document.getElementById('okxSecret');
  const okxPass = document.getElementById('okxPass');
  const okxTradeMode = document.getElementById('okxTradeMode');
  const okxWeEnabled = document.getElementById('okxWeEnabled');

  if (okxBaseUrl && okxKey && okxSecret && okxPass && okxTradeMode) {
    state.okx = {
      base_url: okxBaseUrl.value || 'https://www.okx.com',
      api_key: okxKey.value || '',
      api_secret: okxSecret.value || '',
      passphrase: okxPass.value || '',
      trade_mode: okxTradeMode.value || 'real',
      we_enabled: !!okxWeEnabled?.checked
    };
  }

  const webPort = document.getElementById('webPort');
  if (webPort) {
    state.web_port = Number(webPort.value || 8088);
  }
}

function syncStateToForm() {
  const prefTimeframe = document.getElementById('prefTimeframe');
  const prefMaxPairs = document.getElementById('prefMaxPairs');
  const prefMaxTF = document.getElementById('prefMaxTF');
  const prefMarginMode = document.getElementById('prefMarginMode');
  const optMainstream = document.getElementById('optMainstream');
  const optAlt = document.getElementById('optAlt');
  const optScalp = document.getElementById('optScalp');
  const optIntraday = document.getElementById('optIntraday');
  const optSwing = document.getElementById('optSwing');
  const optSpot = document.getElementById('optSpot');
  const optDeriv = document.getElementById('optDeriv');

  if (prefTimeframe) prefTimeframe.value = state.trading_preferences?.timeframe || '15m';
  if (prefMaxPairs) prefMaxPairs.value = state.trading_preferences?.max_pairs ?? 2;
  if (prefMaxTF) prefMaxTF.value = state.trading_preferences?.max_timeframes ?? 2;
  if (prefMarginMode) prefMarginMode.value = state.trading_preferences?.margin_mode || 'isolated';
  if (optMainstream) optMainstream.checked = !!state.trading_preferences?.universe?.mainstream;
  if (optAlt) optAlt.checked = !!state.trading_preferences?.universe?.alt;
  if (optScalp) optScalp.checked = !!state.trading_preferences?.horizon?.scalp;
  if (optIntraday) optIntraday.checked = !!state.trading_preferences?.horizon?.intraday;
  if (optSwing) optSwing.checked = !!state.trading_preferences?.horizon?.swing;
  if (optSpot) optSpot.checked = !!state.trading_preferences?.market?.spot;
  if (optDeriv) optDeriv.checked = !!state.trading_preferences?.market?.derivatives;

  const okxBaseUrl = document.getElementById('okxBaseUrl');
  const okxKey = document.getElementById('okxKey');
  const okxSecret = document.getElementById('okxSecret');
  const okxPass = document.getElementById('okxPass');
  const okxTradeMode = document.getElementById('okxTradeMode');
  const okxWeEnabled = document.getElementById('okxWeEnabled');

  if (okxBaseUrl) okxBaseUrl.value = state.okx?.base_url || 'https://www.okx.com';
  if (okxKey) okxKey.value = state.okx?.api_key || '';
  if (okxSecret) okxSecret.value = state.okx?.api_secret || '';
  if (okxPass) okxPass.value = state.okx?.passphrase || '';
  if (okxTradeMode) okxTradeMode.value = state.okx?.trade_mode || 'real';
  if (okxWeEnabled) okxWeEnabled.checked = !!state.okx?.we_enabled;

  const webPort = document.getElementById('webPort');
  if (webPort) webPort.value = state.web_port ?? 8088;

  syncRaw();
  renderLLMList();
}

async function loadConfig() {
  try {
    const res = await fetch('/api/config', { headers: { 'X-Access-Token': accessToken }});
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      if (res.status === 401) return handleInvalidToken(err.detail || 'Invalid token');
      throw new Error(err.detail || `加载失败（${res.status}）`);
    }
    const data = await res.json();
    state = data;
    syncStateToForm();
    setStatus('已加载', 'ok');
  } catch (err) {
    setStatus(err.message || '加载失败', 'error');
  }
}

async function saveConfig() {
  try {
    syncFormToState();
    setStatus('保存中...', 'warn');
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Access-Token': accessToken },
      body: JSON.stringify(state)
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      if (res.status === 401) return handleInvalidToken(err.detail || 'Invalid token');
      throw new Error(err.detail || `保存失败（${res.status}）`);
    }
    setStatus('保存成功', 'ok');
  } catch (err) {
    setStatus(err.message || '保存失败', 'error');
  }
}

async function restartApp() {
  try {
    setStatus('正在发起重启...', 'warn');
    const res = await fetch('/api/restart', {
      method: 'POST',
      headers: { 'X-Access-Token': accessToken }
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      if (res.status === 401) return handleInvalidToken(err.detail || 'Invalid token');
      throw new Error(err.detail || `重启失败（${res.status}）`);
    }
    const data = await res.json().catch(() => ({}));
    setStatus(data.message || '已发起重启', 'ok');
  } catch (err) {
    setStatus(err.message || '重启失败', 'error');
  }
}

window.addEventListener('DOMContentLoaded', () => {
  closeProviderModal();
  const modal = document.getElementById('providerModal');
  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) closeProviderModal();
    });
  }
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeProviderModal();
  });
  try {
    autoLoginBlocked = sessionStorage.getItem('mm_token_invalid') === '1';
  } catch (_e) { autoLoginBlocked = false; }
  try {
    const saved = (localStorage.getItem('mm_token') || '').trim();
    if (saved) {
      const tokenInput = document.getElementById('token');
      tokenInput.value = saved;
      if (!autoLoginBlocked) {
        login();
      }
    }
  } catch (_e) {}
  const raw = document.getElementById('configRaw');
  if (raw) {
    raw.addEventListener('input', (e) => {
      try {
        const parsed = JSON.parse(e.target.value);
        state = parsed;
        syncStateToForm();
      } catch (_e) {}
    });
  }
});
