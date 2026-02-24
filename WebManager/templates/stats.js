async function loadStats() {
  const token = document.getElementById('token').value;
  if (!token) return;
  const res = await fetch('/api/stats', { headers: { 'X-Access-Token': token }});
  if (!res.ok) {
    if (res.status === 401) {
      try { localStorage.removeItem('mm_token'); } catch (_e) {}
      try { sessionStorage.setItem('mm_token_invalid', '1'); } catch (_e) {}
      const tokenRow = document.getElementById('tokenRow');
      const tokenHint = document.getElementById('tokenHint');
      if (tokenRow) tokenRow.classList.remove('hidden');
      if (tokenHint) tokenHint.classList.add('hidden');
    }
    return;
  }
  const data = await res.json();
  const req = data.request_count?.value ?? data.llm_request_count?.value ?? '0';
  const trades = data.trade_count?.value ?? '0';
  const pnl = data.pnl_unrealized?.value ?? '0';
  const positions = data.current_positions?.value ?? '[]';
  document.getElementById('statRequests').innerText = req;
  document.getElementById('statTrades').innerText = trades;
  document.getElementById('statPnl').innerText = pnl;
  document.getElementById('statPositions').innerText = formatPositions(positions);
  await loadLogs();
}

function formatPositions(raw) {
  if (!raw) return '暂无';
  if (Array.isArray(raw)) return raw.length ? raw.join('\n') : '暂无';
  const text = String(raw).trim();
  if (!text || text === '[]' || text === 'null') return '暂无';
  try {
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed)) return parsed.length ? parsed.join('\n') : '暂无';
  } catch (_e) {}
  return text;
}

const LOG_LANG_KEY = 'mm_log_lang';
let logLang = 'zh';

function setLogLangButton() {
  const btn = document.getElementById('logLangBtn');
  if (!btn) return;
  btn.textContent = logLang === 'zh' ? '日志：中文' : 'Logs: English';
}

function toggleLogLang() {
  logLang = logLang === 'zh' ? 'en' : 'zh';
  try { localStorage.setItem(LOG_LANG_KEY, logLang); } catch (_e) {}
  setLogLangButton();
  renderLogLists();
  persistLogLang();
}

let lastEvents = [];
let lastAlerts = [];

function translateLogLine(line) {
  if (logLang !== 'zh') return line;
  let output = line;
  const levelMap = {
    INFO: '信息',
    WARN: '警告',
    WARNING: '警告',
    ERROR: '错误',
    CRITICAL: '严重',
    DEBUG: '调试'
  };
  output = output.replace(/^(INFO|WARN|WARNING|ERROR|CRITICAL|DEBUG)\b/, (m) => levelMap[m] || m);
  output = output.replace('plan.created', '计划已创建');
  output = output.replace('plan.start', '计划开始');
  output = output.replace('plan.done', '计划完成');
  output = output.replace('plan.failed', '计划失败');
  output = output.replace('step.start:', '步骤开始:');
  output = output.replace('step.done:', '步骤完成:');
  output = output.replace('robot-error', '机器人错误');
  output = output.replace('request_count', '请求次数');
  output = output.replace('title=', '标题=');
  output = output.replace('inputs=', '输入=');
  output = output.replace('outputs=', '输出=');
  output = output.replace('observations=', '观察=');
  output = output.replace('decisions=', '决策=');
  output = output.replace('errors=', '错误=');
  output = output.replace('rationale=', '理由=');
  output = output.replace('stance=', '态度=');
  return output;
}

function renderLogList(targetId, lines, emptyText) {
  const container = document.getElementById(targetId);
  if (!container) return;
  container.innerHTML = '';
  if (!lines || lines.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'log-empty muted';
    empty.textContent = emptyText;
    container.appendChild(empty);
    return;
  }
  lines.forEach((line) => {
    const item = document.createElement('div');
    item.className = 'log-item';
    item.textContent = translateLogLine(line);
    container.appendChild(item);
  });
}

function renderLogLists() {
  renderLogList('eventList', lastEvents, '暂无事件');
  renderLogList('alertList', lastAlerts, '暂无告警');
}

async function loadLogs() {
  const token = document.getElementById('token').value;
  if (!token) return;
  const [eventsRes, alertsRes] = await Promise.all([
    fetch('/api/events?limit=50', { headers: { 'X-Access-Token': token }}),
    fetch('/api/alerts?limit=20', { headers: { 'X-Access-Token': token }})
  ]);
  if (!eventsRes.ok || !alertsRes.ok) {
    if (eventsRes.status === 401 || alertsRes.status === 401) {
      try { localStorage.removeItem('mm_token'); } catch (_e) {}
      try { sessionStorage.setItem('mm_token_invalid', '1'); } catch (_e) {}
      const tokenRow = document.getElementById('tokenRow');
      const tokenHint = document.getElementById('tokenHint');
      if (tokenRow) tokenRow.classList.remove('hidden');
      if (tokenHint) tokenHint.classList.add('hidden');
    }
    return;
  }
  const eventsData = await eventsRes.json().catch(() => ({}));
  const alertsData = await alertsRes.json().catch(() => ({}));
  lastEvents = Array.isArray(eventsData.events) ? eventsData.events : [];
  lastAlerts = Array.isArray(alertsData.alerts) ? alertsData.alerts : [];
  renderLogLists();
}

async function persistLogLang() {
  const token = document.getElementById('token').value;
  if (!token) return;
  try {
    await fetch('/api/ui', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Access-Token': token },
      body: JSON.stringify({ log_lang: logLang })
    });
  } catch (_e) {}
}

async function loadUiConfig() {
  const token = document.getElementById('token').value;
  if (!token) return;
  try {
    const res = await fetch('/api/ui', { headers: { 'X-Access-Token': token }});
    if (!res.ok) return;
    const data = await res.json().catch(() => ({}));
    if (data && (data.log_lang === 'zh' || data.log_lang === 'en')) {
      logLang = data.log_lang;
      try { localStorage.setItem(LOG_LANG_KEY, logLang); } catch (_e) {}
      setLogLangButton();
      renderLogLists();
    }
  } catch (_e) {}
}

window.addEventListener('DOMContentLoaded', () => {
  let blocked = false;
  try {
    blocked = sessionStorage.getItem('mm_token_invalid') === '1';
  } catch (_e) { blocked = false; }
  try {
    logLang = localStorage.getItem(LOG_LANG_KEY) || 'zh';
  } catch (_e) { logLang = 'zh'; }
  setLogLangButton();
  try {
    const saved = (localStorage.getItem('mm_token') || '').trim();
    if (saved) {
      const tokenInput = document.getElementById('token');
      tokenInput.value = saved;
      const tokenRow = document.getElementById('tokenRow');
      const tokenHint = document.getElementById('tokenHint');
      if (tokenRow) tokenRow.classList.add('hidden');
      if (tokenHint) tokenHint.classList.remove('hidden');
      if (!blocked) {
        loadUiConfig();
        loadStats();
        loadLogs();
      }
    }
  } catch (_e) {}
});
