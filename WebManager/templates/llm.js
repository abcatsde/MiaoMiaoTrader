let accessToken = '';
let state = {
  llm_providers: [],
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

function login() {
  const token = document.getElementById('token').value.trim();
  if (!token) return;
  accessToken = token;
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
  // 预留：若以后单独提供原始 JSON 编辑
}

function syncStateToForm() {
  renderLLMList();
}

async function loadConfig() {
  try {
    const res = await fetch('/api/config', { headers: { 'X-Access-Token': accessToken }});
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
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
    setStatus('保存中...', 'warn');
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Access-Token': accessToken },
      body: JSON.stringify(state)
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
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
    const saved = localStorage.getItem('mm_token');
    if (saved) {
      const tokenInput = document.getElementById('token');
      tokenInput.value = saved;
      login();
    }
  } catch (_e) {}
});
