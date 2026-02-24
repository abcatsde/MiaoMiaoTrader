async function loadStats() {
  const token = document.getElementById('token').value;
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
