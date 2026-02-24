async function loadStats() {
  const token = document.getElementById('token').value;
  if (!token) return;
  const res = await fetch('/api/stats', { headers: { 'X-Access-Token': token }});
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
  try {
    const saved = localStorage.getItem('mm_token');
    if (saved) {
      const tokenInput = document.getElementById('token');
      tokenInput.value = saved;
      const tokenRow = document.getElementById('tokenRow');
      const tokenHint = document.getElementById('tokenHint');
      if (tokenRow) tokenRow.classList.add('hidden');
      if (tokenHint) tokenHint.classList.remove('hidden');
      loadStats();
    }
  } catch (_e) {}
});
