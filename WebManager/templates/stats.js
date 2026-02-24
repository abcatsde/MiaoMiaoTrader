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
  const req = data.request_count?.value ?? '0';
  const trades = data.trade_count?.value ?? '0';
  const pnl = data.pnl_unrealized?.value ?? '0';
  const positions = data.current_positions?.value ?? '[]';
  document.getElementById('statRequests').innerText = req;
  document.getElementById('statTrades').innerText = trades;
  document.getElementById('statPnl').innerText = pnl;
  document.getElementById('statPositions').innerText = positions;
}

window.addEventListener('DOMContentLoaded', () => {
  let blocked = false;
  try {
    blocked = sessionStorage.getItem('mm_token_invalid') === '1';
  } catch (_e) { blocked = false; }
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
        loadStats();
      }
    }
  } catch (_e) {}
});
