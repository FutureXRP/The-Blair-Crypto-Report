(async function () {
  const year = document.getElementById('year');
  if (year) year.textContent = new Date().getFullYear();
  // --- helpers ---
  async function loadJSON(path) {
    const res = await fetch(path + '?v=' + Date.now());
    if (!res.ok) throw new Error('Failed to load ' + path);
    return res.json();
  }
  function fmtTimeAgo(dateStr) {
    try {
      const d = new Date(dateStr);
      const delta = Math.max(0, Date.now() - d.getTime());
      const mins = Math.floor(delta / 60000);
      if (mins < 1) return 'just now';
      if (mins < 60) return mins + 'm ago';
      const hrs = Math.floor(mins / 60);
      if (hrs < 24) return hrs + 'h ago';
      const days = Math.floor(hrs / 24);
      return days + 'd ago';
    } catch { return ''; }
  }
  function renderList(id, items) {
    const el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = '';
    for (const it of (items || [])) {
      const li = document.createElement('li');
      const a = document.createElement('a');
      a.href = it.link; a.target = '_blank'; a.rel = 'noopener';
      a.textContent = it.title;
      const meta = document.createElement('span');
      meta.className = 'meta';
      const src = it.source ? ` • ${it.source}` : '';
      meta.textContent = `${fmtTimeAgo(it.published_at)}${src}`;
      li.appendChild(a); li.appendChild(meta);
      el.appendChild(li);
    }
  }
  function setupTicker(prices) {
    const wrap = document.querySelector('.ticker-wrap');
    const tick = document.getElementById('ticker');
    if (!wrap || !tick) return;
    tick.innerHTML = '';
    if (!Array.isArray(prices) || !prices.length) return;
    const oneRun = document.createElement('div');
    oneRun.className = 'ticker-track';
    for (const p of prices) {
      const span = document.createElement('span');
      const sym = (p.symbol || '').toUpperCase();
      const rank = p.rank ? `#${p.rank}` : '';
      const price = (p.price !== undefined) ? `$${Number(p.price).toLocaleString()}` : '';
      span.textContent = `${rank} ${sym} ${price}`;
      oneRun.appendChild(span);
    }
    const containerW = wrap.clientWidth || 800;
    let totalW = 0;
    while (totalW < containerW * 2) {
      const clone = oneRun.cloneNode(true);
      tick.appendChild(clone);
      totalW += clone.scrollWidth || containerW;
    }
    const speed = 100; // px/s
    const duration = Math.max(20, Math.round((totalW / speed)));
    tick.style.setProperty('--ticker-duration', duration + 's');
  }
  function renderMarkets(prices) {
    const tbody = document.getElementById('market-body');
    if (!tbody) return;
    tbody.innerHTML = '';
    for (const c of (prices || []).slice(0, 50)) {
      const tr = document.createElement('tr');
      const nameTd = document.createElement('td');
      nameTd.textContent = `${(c.symbol || '').toUpperCase()}`;
      const priceTd = document.createElement('td');
      priceTd.textContent = (c.price !== undefined) ? `$${Number(c.price).toLocaleString()}` : '';
      const changeTd = document.createElement('td');
      const change = c.change24h;
      if (typeof change === 'number') {
        changeTd.textContent = `${change.toFixed(2)}%`;
        changeTd.classList.add(change >= 0 ? 'positive' : 'negative');
      } else {
        changeTd.textContent = '—';
      }
      tr.append(nameTd, priceTd, changeTd);
      tbody.appendChild(tr);
    }
  }
  function setLastUpdated(iso) {
    const el = document.getElementById('lastUpdated');
    if (el && iso) {
      const d = new Date(iso);
      el.textContent = `Last updated ${d.toLocaleString()}`;
    }
  }
  async function refreshAll() {
    try {
      const [headlines, prices] = await Promise.all([
        loadJSON('data/headlines.json'),
        loadJSON('data/prices.json')
      ]);
      renderList('x_breaking', headlines.x_breaking || []);
      renderList('breaking', headlines.breaking || []);
      renderList('day', headlines.day || []);
      renderList('week', headlines.week || []);
      renderList('month', headlines.month || []);
      setupTicker(Array.isArray(prices) ? prices : []);
      renderMarkets(Array.isArray(prices) ? prices : []);
      setLastUpdated(headlines.generated_at);
    } catch (e) {
      console.error('Refresh failed:', e);
    }
  }
  // Initial load and ticker setup
  await refreshAll();
  // Auto-refresh every 2 minutes
  const REFRESH_MS = 120000;
  setInterval(refreshAll, REFRESH_MS);
  // Recompute ticker layout on resize
  window.addEventListener('resize', async () => {
    try {
      const prices = await loadJSON('data/prices.json');
      setupTicker(Array.isArray(prices) ? prices : []);
    } catch {}
  });
  // Force ticker recalc on load for mobile
  window.addEventListener('load', async () => {
    try {
      const prices = await loadJSON('data/prices.json');
      setupTicker(Array.isArray(prices) ? prices : []);
    } catch {}
  });
})();
