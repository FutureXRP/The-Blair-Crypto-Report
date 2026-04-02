/**
 * The Blair Report — app.js v3.0
 *
 * Compatible with live repo data shapes:
 *   data/headlines.json  → {x_breaking, breaking, day, week, month,
 *                           clusters, trending, generated_at}
 *   data/prices.json     → {prices:[...], gainers:[...], losers:[...]}
 *   data/sentiment.json  → {score, label, bullish, bearish, neutral, history:[...]}
 *   data/regulation.json → [{title, link, source, published_at, agency,
 *                             sentiment, coins}]
 *
 * Uses Fuse.js (loaded in <head>) for fuzzy search — same library as original.
 */
(async function () {

  // ── CONFIG ───────────────────────────────────────────────────────────────
  const REFRESH_MS  = 120_000;
  const MARKET_ROWS = 12;
  const STABLES = new Set([
    'USDT','USDC','BUSD','DAI','TUSD','USDP','FRAX','USDE','USDS','PYUSD',
    'RLUSD','USDY','USYC','BUIDL','USDG','USDF','USD1','EUTBL','GHO',
    'SUSDE','BSC-USD','FDUSD','USDTB','USD0','USDAI','JST',
  ]);

  // ── STATE ────────────────────────────────────────────────────────────────
  let allArticles     = [];
  let allPricesData   = { prices: [], gainers: [], losers: [] };
  let regItems        = [];
  let activePanel     = 'news';
  let activeBucket    = 'all';
  let activeRegAgency = 'all';
  let searchQuery     = '';
  let currentCoin     = null;
  let fuseInstance    = null;

  // ── HELPERS ──────────────────────────────────────────────────────────────
  async function loadJSON(path) {
    const r = await fetch(path + '?v=' + Date.now());
    if (!r.ok) throw new Error(r.status + ' ' + path);
    return r.json();
  }

  function esc(s) {
    return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function fmtAgo(iso) {
    try {
      const d = Math.max(0, Date.now() - new Date(iso).getTime());
      const m = Math.floor(d / 60000);
      if (m < 1)  return 'just now';
      if (m < 60) return m + 'm ago';
      const h = Math.floor(m / 60);
      if (h < 24) return h + 'h ago';
      return Math.floor(h / 24) + 'd ago';
    } catch { return ''; }
  }

  function fmtPrice(p) {
    const n = Number(p);
    if (isNaN(n)) return '—';
    if (n >= 1000) return '$' + n.toLocaleString('en-US', {maximumFractionDigits: 0});
    if (n >= 1)    return '$' + n.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    if (n >= 0.01) return '$' + n.toFixed(4);
    if (n > 0)     return '$' + n.toExponential(3);
    return '—';
  }

  function fmtChg(c) {
    if (typeof c !== 'number') return '—';
    return (c >= 0 ? '+' : '') + c.toFixed(2) + '%';
  }

  const SRC_COLOR = {
    'coindesk.com':        '#f5c842',
    'cointelegraph.com':   '#2563eb',
    'theblock.co':         '#e8432d',
    'decrypt.co':          '#22c55e',
    'blockworks.co':       '#8b5cf6',
    'thedefiant.io':       '#f97316',
    'bitcoinmagazine.com': '#f59e0b',
    'bankless.com':        '#60a5fa',
    'messari.io':          '#a78bfa',
    'sec.gov':             '#60a5fa',
    'federalreserve.gov':  '#22c55e',
    'cftc.gov':            '#a78bfa',
    'bis.org':             '#f87171',
    'beincrypto.com':      '#f5c842',
    'ambcrypto.com':       '#e8432d',
    'newsbtc.com':         '#f97316',
    'bitcoinist.com':      '#a78bfa',
  };
  function dotColor(src) {
    for (const [k, v] of Object.entries(SRC_COLOR)) {
      if (src && src.includes(k)) return v;
    }
    return 'var(--accent)';
  }

  function sentClass(s) {
    if (s === 'bullish') return 'sent-bullish';
    if (s === 'bearish') return 'sent-bearish';
    return 'sent-neutral';
  }
  function sentLabel(s) {
    if (s === 'bullish') return '▲ bullish';
    if (s === 'bearish') return '▼ bearish';
    return '● neutral';
  }

  function agencyClass(agency) {
    const map = {
      'SEC':'agency-sec','CFTC':'agency-cftc','Fed':'agency-fed',
      'Treasury':'agency-treasury','Congress':'agency-congress',
      'BIS':'agency-bis','IMF':'agency-imf','EU':'agency-eu',
    };
    return map[agency] || 'agency-default';
  }

  // ── FUSE.JS INIT ─────────────────────────────────────────────────────────
  function initFuse(articles) {
    if (!window.Fuse) { console.warn('Fuse.js not loaded'); return; }
    fuseInstance = new Fuse(articles, {
      keys: ['title', 'source', 'ntitle'],
      threshold: 0.4,
      includeScore: true,
      ignoreLocation: true,
    });
  }

  // ── ARTICLE HTML ─────────────────────────────────────────────────────────
  function articleHTML(item, index) {
    const num   = String(index + 1).padStart(2, '0');
    const color = dotColor(item.source || '');
    const src   = esc((item.source || '').replace('www.',''));
    const coins = (item.coins || []).slice(0, 3);
    const sent  = item.sentiment || 'neutral';
    const coinTags = coins.map(c =>
      `<span class="coin-tag" data-coin="${esc(c)}">${esc(c)}</span>`
    ).join('');

    return `<li>
      <a class="article-item" href="${esc(item.link || '#')}" target="_blank" rel="noopener noreferrer">
        <div class="art-num">${num}</div>
        <div class="art-body">
          <div class="art-meta">
            <span class="art-dot" style="background:${color}"></span>
            <span class="art-src">${src}</span>
            <span class="art-sent ${sentClass(sent)}">${sentLabel(sent)}</span>
            <span class="art-time">${fmtAgo(item.published_at)}</span>
          </div>
          <div class="art-title">${esc(item.title || '')}</div>
          ${coins.length ? `<div class="art-coins">${coinTags}</div>` : ''}
        </div>
      </a>
    </li>`;
  }

  function renderBucket(id, items) {
    const ul  = document.getElementById(id);
    const cnt = document.getElementById('count-' + id);
    if (!ul) return;
    if (!items || !items.length) {
      ul.innerHTML = '<li class="empty">No headlines.</li>';
      if (cnt) cnt.textContent = '';
      return;
    }
    ul.innerHTML = items.map((it, i) => articleHTML(it, i)).join('');
    if (cnt) cnt.textContent = items.length + ' stories';
  }

  // ── CLUSTERS ─────────────────────────────────────────────────────────────
  function clusterBadge(count) {
    if (count >= 6) return `<span class="cluster-badge cb-hot">${count} sources</span>`;
    if (count >= 3) return `<span class="cluster-badge cb-warm">${count} sources</span>`;
    return `<span class="cluster-badge cb-cool">${count} sources</span>`;
  }

  function renderClusters(clusters) {
    const el  = document.getElementById('cluster-list');
    const cnt = document.getElementById('cluster-count');
    if (!el) return;
    if (!clusters || !clusters.length) {
      el.innerHTML = '<div class="empty">No trending story clusters yet.</div>';
      if (cnt) cnt.textContent = '';
      return;
    }
    if (cnt) cnt.textContent = clusters.length + ' stories';
    el.innerHTML = clusters.map((c, i) => {
      const coins    = (c.coins || []).slice(0, 4);
      const coinTags = coins.map(co =>
        `<span class="coin-tag" data-coin="${esc(co)}">${esc(co)}</span>`
      ).join('');
      const subItems = (c.members || []).slice(0, 6).map(m => `
        <a class="sub-article" href="${esc(m.link||'#')}" target="_blank" rel="noopener noreferrer">
          <span class="sub-dot"></span>
          <span class="sub-title">${esc(m.title||'')}</span>
          <span class="sub-src">${esc((m.source||'').replace('www.',''))}</span>
        </a>`).join('');
      const sources = (c.sources || []).slice(0, 4).map(s => s.replace('www.','')).join(', ');
      return `<div class="cluster-card" data-cid="${i}">
        <div class="cluster-top">
          ${clusterBadge(c.count)}
          <div class="cluster-title">${esc(c.title||'')}</div>
        </div>
        ${c.summary ? `<div class="cluster-summary">${esc(c.summary)}</div>` : ''}
        <div class="cluster-meta">
          ${coinTags}
          <span class="sent-tag ${sentClass(c.sentiment)}">${sentLabel(c.sentiment)}</span>
          <span class="src-count">${esc(sources)}</span>
        </div>
        <div class="cluster-sources">${subItems}</div>
      </div>`;
    }).join('');

    el.querySelectorAll('.cluster-card').forEach(card => {
      card.addEventListener('click', e => {
        if (e.target.tagName === 'A' || e.target.classList.contains('coin-tag')) return;
        card.classList.toggle('expanded');
      });
    });
  }

  // ── REGULATION ───────────────────────────────────────────────────────────
  function renderRegulation(items, agency) {
    const el  = document.getElementById('reg-list');
    const cnt = document.getElementById('reg-count');
    if (!el) return;
    const filtered = agency === 'all' ? items : items.filter(i => i.agency === agency);
    if (cnt) cnt.textContent = filtered.length + ' items';
    if (!filtered.length) { el.innerHTML = '<div class="empty">No regulation items.</div>'; return; }
    el.innerHTML = filtered.map(item => {
      const coins = (item.coins || []).slice(0, 3)
        .map(c => `<span class="coin-tag" data-coin="${esc(c)}">${esc(c)}</span>`).join('');
      return `<a class="reg-item" href="${esc(item.link||'#')}" target="_blank" rel="noopener noreferrer">
        <div class="reg-agency-col">
          <span class="reg-agency ${agencyClass(item.agency)}">${esc(item.agency||'?')}</span>
          <span class="reg-time">${fmtAgo(item.published_at)}</span>
        </div>
        <div>
          <div class="reg-title">${esc(item.title||'')}</div>
          <div class="reg-meta">
            <span class="reg-src">${esc((item.source||'').replace('www.',''))}</span>
            <span class="sent-tag ${sentClass(item.sentiment)}">${sentLabel(item.sentiment)}</span>
            ${coins}
          </div>
        </div>
      </a>`;
    }).join('');
  }

  // ── COIN PAGE ─────────────────────────────────────────────────────────────
  function showCoinPage(symbol) {
    currentCoin = symbol.toUpperCase();
    const prices = allPricesData.prices || [];
    const coin   = prices.find(p => (p.symbol||'').toUpperCase() === currentCoin);

    document.getElementById('coin-sym').textContent   = currentCoin;
    document.getElementById('coin-price').textContent = coin ? fmtPrice(coin.price) : '—';
    const chgEl = document.getElementById('coin-change');
    if (coin && typeof coin.change24h === 'number') {
      chgEl.textContent = fmtChg(coin.change24h);
      chgEl.className   = 'coin-change ' + (coin.change24h >= 0 ? 'pos' : 'neg');
    } else {
      chgEl.textContent = '—'; chgEl.className = 'coin-change';
    }

    const statsEl = document.getElementById('coin-stats');
    if (coin) {
      statsEl.innerHTML = `
        <div class="stat-card"><div class="stat-label">Rank</div><div class="stat-value">#${coin.rank||'—'}</div></div>
        <div class="stat-card"><div class="stat-label">24H Change</div><div class="stat-value ${coin.change24h>=0?'pos':'neg'}">${fmtChg(coin.change24h)}</div></div>
        <div class="stat-card"><div class="stat-label">Price</div><div class="stat-value">${fmtPrice(coin.price)}</div></div>
        <div class="stat-card"><div class="stat-label">Market Cap</div><div class="stat-value">—</div></div>`;
    } else { statsEl.innerHTML = ''; }

    const coinNews = allArticles.filter(a =>
      (a.coins||[]).includes(currentCoin) ||
      (a.title||'').toLowerCase().includes(symbol.toLowerCase())
    ).slice(0, 20);

    const newsEl = document.getElementById('coin-news-list');
    newsEl.innerHTML = coinNews.length
      ? coinNews.map((it, i) => articleHTML(it, i)).join('')
      : `<li class="empty">No recent headlines for ${esc(currentCoin)}.</li>`;

    showPanel('coin');
  }

  // ── PANEL SWITCHING ──────────────────────────────────────────────────────
  function showPanel(name) {
    activePanel = name;
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    const t = document.getElementById(name === 'coin' ? 'coin-panel' : 'panel-' + name);
    if (t) t.classList.add('active');
    if (name !== 'coin') {
      document.querySelectorAll('.tab').forEach(t =>
        t.classList.toggle('active', t.dataset.panel === name && !t.dataset.bucket)
      );
    }
  }

  function applyBucketFilter(bucket) {
    activeBucket = bucket;
    const hotSection = document.getElementById('hot-stories-section');
    if (hotSection) hotSection.style.display = bucket === 'all' ? 'block' : 'none';
    ['breaking','day','week','month'].forEach(b => {
      const s = document.getElementById('bucket-' + b);
      if (s) s.classList.toggle('hidden', bucket !== 'all' && bucket !== b);
    });
    document.querySelectorAll('.tab[data-bucket]').forEach(t =>
      t.classList.toggle('active', t.dataset.bucket === bucket)
    );
  }

  // ── SEARCH (Fuse.js) ─────────────────────────────────────────────────────
  function runSearch(q) {
    searchQuery = q.trim().toLowerCase();
    const searchTab = document.getElementById('search-tab');

    if (!searchQuery) {
      if (searchTab) searchTab.style.display = 'none';
      showPanel('news');
      applyBucketFilter(activeBucket);
      return;
    }

    if (searchTab) searchTab.style.display = 'flex';
    showPanel('search');

    let results;
    if (fuseInstance) {
      results = fuseInstance.search(searchQuery).map(r => r.item);
    } else {
      // Fallback: simple includes
      results = allArticles.filter(it => {
        const hay = ((it.title||'') + ' ' + (it.source||'') + ' ' + (it.coins||[]).join(' ')).toLowerCase();
        return hay.includes(searchQuery);
      });
    }

    const ul    = document.getElementById('search-list');
    const cnt   = document.getElementById('search-count');
    const noRes = document.getElementById('no-results');

    if (!results.length) {
      ul.innerHTML = '';
      noRes.style.display = 'block';
      if (cnt) cnt.textContent = '0 results';
    } else {
      noRes.style.display = 'none';
      ul.innerHTML = results.map((it, i) => articleHTML(it, i)).join('');
      if (cnt) cnt.textContent = results.length + ' result' + (results.length !== 1 ? 's' : '');
    }
  }

  // ── TICKER ───────────────────────────────────────────────────────────────
  function buildTickerHTML(prices) {
    return prices.map(p => {
      const sym  = (p.symbol || '').toUpperCase();
      const rank = p.rank ? `<span class="t-rank">#${p.rank}</span>` : '';
      const chg  = typeof p.change24h === 'number' ? p.change24h : null;
      const cls  = chg === null ? '' : (chg >= 0 ? 't-up' : 't-dn');
      const chgStr = chg !== null ? `<span class="${cls}">${fmtChg(chg)}</span>` : '';
      return `<span class="ticker-item">${rank}<span class="t-sym">${esc(sym)}</span>${fmtPrice(p.price)}${chgStr}</span>`;
    }).join('');
  }

  function setupTicker(prices) {
    if (!prices.length) return;
    const html = buildTickerHTML(prices);
    const t1 = document.getElementById('t1');
    const t2 = document.getElementById('t2');
    if (t1) t1.innerHTML = html;
    if (t2) t2.innerHTML = html;
    requestAnimationFrame(() => {
      const w = (t1 && t1.scrollWidth) || 2000;
      document.getElementById('ticker').style.setProperty('--ticker-duration', Math.max(40, Math.round(w / 75)) + 's');
    });
  }

  // ── SIDEBAR: MARKET ───────────────────────────────────────────────────────
  function renderMarket(prices) {
    const tbody = document.getElementById('market-body');
    if (!tbody) return;
    tbody.innerHTML = prices.slice(0, MARKET_ROWS).map(p => {
      const chg = typeof p.change24h === 'number' ? p.change24h : null;
      const cls = chg === null ? '' : (chg >= 0 ? 'pos' : 'neg');
      return `<tr data-coin="${esc(p.symbol)}">
        <td>${esc((p.symbol||'').toUpperCase())}</td>
        <td>${fmtPrice(p.price)}</td>
        <td class="${cls}">${fmtChg(chg)}</td>
      </tr>`;
    }).join('');
    tbody.querySelectorAll('tr').forEach(row =>
      row.addEventListener('click', () => showCoinPage(row.dataset.coin))
    );
  }

  // ── SIDEBAR: GAINERS / LOSERS ─────────────────────────────────────────────
  // Uses pre-computed gainers/losers from prices.json (matching original behavior)
  function renderGainersLosers(pricesData) {
    function rowHTML(p, isGain) {
      const cls = isGain ? 'pos' : 'neg';
      return `<div class="gl-row" data-coin="${esc(p.symbol)}">
        <span class="gl-sym">${esc((p.symbol||'').toUpperCase())}</span>
        <span class="gl-price">${fmtPrice(p.price)}</span>
        <span class="gl-chg ${cls}">${fmtChg(p.change24h)}</span>
      </div>`;
    }
    const gEl = document.getElementById('gainers-list');
    const lEl = document.getElementById('losers-list');
    // Filter stables from both lists
    const gainers = (pricesData.gainers || []).filter(p => !STABLES.has((p.symbol||'').toUpperCase())).slice(0, 8);
    const losers  = (pricesData.losers  || []).filter(p => !STABLES.has((p.symbol||'').toUpperCase())).slice(0, 8);
    if (gEl) {
      gEl.innerHTML = gainers.map(p => rowHTML(p, true)).join('');
      gEl.querySelectorAll('.gl-row').forEach(r =>
        r.addEventListener('click', () => showCoinPage(r.dataset.coin))
      );
    }
    if (lEl) {
      lEl.innerHTML = losers.map(p => rowHTML(p, false)).join('');
      lEl.querySelectorAll('.gl-row').forEach(r =>
        r.addEventListener('click', () => showCoinPage(r.dataset.coin))
      );
    }
  }

  // ── SIDEBAR: TRENDING ─────────────────────────────────────────────────────
  function renderTrending(trending) {
    const el = document.getElementById('trending-list');
    if (!el) return;
    if (!trending || !trending.length) { el.innerHTML = '<div class="empty">No data yet.</div>'; return; }
    el.innerHTML = trending.map((t, i) => `
      <div class="trend-item">
        <span class="trend-rank">${i+1}</span>
        <span class="trend-tag" data-search="${esc(t.tag)}">${esc(t.tag)}</span>
        <div class="trend-bar"><div class="trend-fill" style="width:${t.pct||0}%"></div></div>
        <span class="trend-count">${t.count} mentions</span>
      </div>`).join('');
    el.querySelectorAll('.trend-tag').forEach(tag => {
      tag.addEventListener('click', () => {
        const inp = document.getElementById('search-input');
        if (inp) { inp.value = tag.dataset.search; runSearch(tag.dataset.search); }
      });
    });
  }

  // ── SIDEBAR: SENTIMENT ────────────────────────────────────────────────────
  function renderSentiment(data) {
    if (!data) return;
    const score = data.score || 0;
    const pct   = Math.round((score + 100) / 2);
    const elScore = document.getElementById('sent-score');
    const elLabel = document.getElementById('sent-label');
    const elFill  = document.getElementById('sent-fill');
    const elBull  = document.getElementById('s-bull');
    const elNeut  = document.getElementById('s-neut');
    const elBear  = document.getElementById('s-bear');
    if (elScore) elScore.textContent = score > 0 ? '+' + score : String(score);
    if (elLabel) elLabel.textContent = data.label || '—';
    if (elFill) {
      elFill.style.width      = pct + '%';
      elFill.style.background = score >= 20 ? 'var(--green)' : score >= -20 ? 'var(--accent)' : 'var(--red)';
    }
    if (elBull) elBull.textContent = (data.bullish || 0) + '%';
    if (elNeut) elNeut.textContent = (data.neutral || 0) + '%';
    if (elBear) elBear.textContent = (data.bearish || 0) + '%';

    const history = (data.history || []).slice(-14);
    if (history.length > 1) renderSparkline(history);
  }

  function renderSparkline(history) {
    const el = document.getElementById('sparkline');
    if (!el) return;
    const scores = history.map(h => h.score || 0);
    const min = Math.min(...scores), max = Math.max(...scores);
    const range = Math.max(max - min, 1);
    const W = 256, H = 30, pad = 3;
    const pts = scores.map((s, i) => [
      pad + (i / (scores.length - 1)) * (W - pad * 2),
      H - pad - ((s - min) / range) * (H - pad * 2),
    ]);
    const path = pts.map((p, i) => (i === 0 ? `M` : `L`) + p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
    const last  = pts[pts.length - 1];
    const lastS = scores[scores.length - 1];
    const dc    = lastS >= 20 ? '#22c55e' : lastS >= -20 ? '#f5c842' : '#e8432d';
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
      <path d="${path}" fill="none" stroke="var(--border2)" stroke-width="1.5"/>
      <circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="3" fill="${dc}"/>
    </svg>`;
  }

  // ── LAST UPDATED ──────────────────────────────────────────────────────────
  function setLastUpdated(iso) {
    const el = document.getElementById('lastUpdated');
    if (!el || !iso) return;
    try {
      const d = new Date(iso);
      el.textContent = d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}) +
                       ' · ' + d.toLocaleDateString([], {month:'short', day:'numeric'});
    } catch { el.textContent = ''; }
  }

  // ── DELEGATION: coin tags anywhere ───────────────────────────────────────
  document.addEventListener('click', e => {
    const tag = e.target.closest('.coin-tag');
    if (tag && tag.dataset.coin) {
      e.preventDefault(); e.stopPropagation();
      showCoinPage(tag.dataset.coin);
    }
  });

  // ── REGULATION FILTERS ────────────────────────────────────────────────────
  const regFiltersEl = document.getElementById('reg-filters');
  if (regFiltersEl) {
    regFiltersEl.addEventListener('click', e => {
      const btn = e.target.closest('.reg-filter');
      if (!btn) return;
      document.querySelectorAll('.reg-filter').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeRegAgency = btn.dataset.agency;
      renderRegulation(regItems, activeRegAgency);
    });
  }

  // ── NAV TABS ─────────────────────────────────────────────────────────────
  document.querySelectorAll('.tab[data-panel]').forEach(tab => {
    tab.addEventListener('click', () => {
      const panel  = tab.dataset.panel;
      const bucket = tab.dataset.bucket;
      if (panel === 'news' && bucket) {
        const inp = document.getElementById('search-input');
        if (inp && searchQuery) { inp.value = ''; runSearch(''); }
        showPanel('news');
        applyBucketFilter(bucket);
      } else {
        showPanel(panel);
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        if (panel === 'regulation') renderRegulation(regItems, activeRegAgency);
      }
    });
  });

  // Coin back button
  const coinBackEl = document.getElementById('coin-back');
  if (coinBackEl) {
    coinBackEl.addEventListener('click', () => {
      currentCoin = null;
      showPanel('news');
      applyBucketFilter(activeBucket);
    });
  }

  // ── SEARCH WIRING ─────────────────────────────────────────────────────────
  const searchInput = document.getElementById('search-input');
  const searchClear = document.getElementById('search-clear');
  let searchDebounce;

  if (searchInput) {
    searchInput.addEventListener('input', () => {
      clearTimeout(searchDebounce);
      searchDebounce = setTimeout(() => runSearch(searchInput.value), 200);
    });
    // Also support Enter key (preserved from original)
    searchInput.addEventListener('keypress', e => {
      if (e.key === 'Enter') runSearch(searchInput.value);
    });
  }
  if (searchClear) {
    searchClear.addEventListener('click', () => {
      if (searchInput) searchInput.value = '';
      runSearch('');
    });
  }
  // Escape to clear (preserved from original)
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && searchQuery) {
      if (searchInput) searchInput.value = '';
      runSearch('');
    }
  });

  // ── RESIZE ────────────────────────────────────────────────────────────────
  let resizeTimer;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => setupTicker(allPricesData.prices || []), 300);
  });

  // ── MAIN REFRESH ──────────────────────────────────────────────────────────
  async function refreshAll() {
    try {
      const [headlines, prices, sentiment, regulation] = await Promise.allSettled([
        loadJSON('data/headlines.json'),
        loadJSON('data/prices.json'),
        loadJSON('data/sentiment.json'),
        loadJSON('data/regulation.json'),
      ]);

      if (headlines.status === 'fulfilled') {
        const h = headlines.value;
        allArticles = [
          ...(h.x_breaking || []).map(a => ({...a, _bucket:'x_breaking'})),
          ...(h.breaking   || []).map(a => ({...a, _bucket:'breaking'})),
          ...(h.day        || []).map(a => ({...a, _bucket:'day'})),
          ...(h.week       || []).map(a => ({...a, _bucket:'week'})),
          ...(h.month      || []).map(a => ({...a, _bucket:'month'})),
        ];
        initFuse(allArticles);

        renderBucket('breaking', h.breaking || []);
        renderBucket('day',      h.day      || []);
        renderBucket('week',     h.week     || []);
        renderBucket('month',    h.month    || []);
        renderClusters(h.clusters || []);
        renderTrending(h.trending || []);
        setLastUpdated(h.generated_at);

        const brk   = (h.breaking || []).length;
        const badge = document.getElementById('breaking-badge');
        if (badge) { badge.textContent = brk; badge.style.display = brk > 0 ? 'inline' : 'none'; }

        const countEl = document.getElementById('article-count');
        if (countEl) countEl.textContent = allArticles.length + ' headlines';
      }

      if (prices.status === 'fulfilled') {
        // Live repo shape: {prices:[...], gainers:[...], losers:[...]}
        allPricesData = prices.value || { prices: [], gainers: [], losers: [] };
        setupTicker(allPricesData.prices || []);
        renderMarket(allPricesData.prices || []);
        renderGainersLosers(allPricesData);
        if (currentCoin) showCoinPage(currentCoin);
      }

      if (sentiment.status === 'fulfilled') {
        renderSentiment(sentiment.value);
      }

      if (regulation.status === 'fulfilled') {
        regItems = Array.isArray(regulation.value) ? regulation.value : [];
        if (activePanel === 'regulation') renderRegulation(regItems, activeRegAgency);
      }

      if (searchQuery) runSearch(searchQuery);

    } catch (e) {
      console.error('[Blair] Refresh error:', e);
    }
  }

  // ── BOOT ─────────────────────────────────────────────────────────────────
  const yearEl = document.getElementById('year');
  if (yearEl) yearEl.textContent = new Date().getFullYear();

  applyBucketFilter('all');
  await refreshAll();
  setInterval(refreshAll, REFRESH_MS);

})();
