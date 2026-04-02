#!/usr/bin/env python3
"""
The Blair Report — build.py v3.0
Fully backward-compatible with existing repo structure.

Writes:
  data/headlines.json   {x_breaking, breaking, day, week, month,
                         clusters, trending, generated_at}
  data/prices.json      {prices:[...], gainers:[...], losers:[...]}
  data/sentiment.json   {score, label, bullish, bearish, neutral,
                         history:[...last 30 days]}
  data/regulation.json  [{title, link, source, published_at, agency,
                         sentiment, coins}]
  data/history/YYYY-MM-DD.json  (90-day rolling archive)
"""

import os, json, time, hashlib, sys, re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from collections import defaultdict, deque

import yaml
import feedparser
import requests

# ── PATHS ─────────────────────────────────────────────────────────────────────
ROOT     = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(ROOT, "data")
HIST_DIR = os.path.join(DATA_DIR, "history")
CONF     = os.path.join(ROOT, "config", "sources.yaml")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(HIST_DIR, exist_ok=True)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
X_BEARER_TOKEN    = os.environ.get("X_BEARER_TOKEN", "")

# ── UTILS ─────────────────────────────────────────────────────────────────────
def log(msg): print(msg, file=sys.stderr)
def now_utc(): return datetime.now(timezone.utc)

def safe_write_json(path, obj):
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        log(f"INFO: wrote {os.path.basename(path)}")
    except Exception as e:
        log(f"ERROR writing {path}: {e}")

def load_json_safe(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return None

# ── CONFIG ────────────────────────────────────────────────────────────────────
def load_cfg():
    try:
        with open(CONF, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
            if not isinstance(cfg, dict): raise ValueError
            return cfg
    except Exception as e:
        log(f"WARN: sources.yaml not loaded: {e}")
        return {
            "limits": {"per_category": 30},
            "sources": [
                {"name": "CoinDesk",      "url": "https://www.coindesk.com/arc/outboundfeeds/rss/"},
                {"name": "Cointelegraph", "url": "https://cointelegraph.com/rss"},
                {"name": "Decrypt",       "url": "https://decrypt.co/feed"},
            ]
        }

cfg        = load_cfg()
PER_BUCKET = int(cfg.get("limits", {}).get("per_category", 30))
SOURCES    = cfg.get("sources", []) or []
UA         = "BlairReportBot/3.0 (+https://theblairreport.com)"
HEADERS    = {"User-Agent": UA}

# ── COIN / TERM MAPS ──────────────────────────────────────────────────────────
COIN_MAP = {
    "bitcoin": "BTC", "btc": "BTC",
    "ethereum": "ETH", "eth": "ETH", "ether": "ETH",
    "xrp": "XRP", "ripple": "XRP",
    "solana": "SOL", "sol": "SOL",
    "cardano": "ADA", "ada": "ADA",
    "binance": "BNB", "bnb": "BNB",
    "dogecoin": "DOGE", "doge": "DOGE",
    "chainlink": "LINK", "link": "LINK",
    "polygon": "MATIC", "matic": "MATIC",
    "avalanche": "AVAX", "avax": "AVAX",
    "polkadot": "DOT", "dot": "DOT",
    "uniswap": "UNI", "uni": "UNI",
    "aave": "AAVE",
    "near": "NEAR",
    "cosmos": "ATOM", "atom": "ATOM",
    "litecoin": "LTC", "ltc": "LTC",
    "stellar": "XLM", "xlm": "XLM",
    "hedera": "HBAR", "hbar": "HBAR",
    "tron": "TRX", "trx": "TRX",
    "toncoin": "TON", "ton": "TON",
    "shiba": "SHIB", "shib": "SHIB",
    "pepe": "PEPE",
    "sui": "SUI",
    "aptos": "APT", "apt": "APT",
    "arbitrum": "ARB", "arb": "ARB",
    "optimism": "OP", "op": "OP",
    "flare": "FLR", "flr": "FLR",
    "songbird": "SGB", "sgb": "SGB",
    "xdc": "XDC", "xinfin": "XDC",
    "zebec": "ZBCN", "zbcn": "ZBCN",
    "ethena": "ENA", "ena": "ENA",
    "hyperliquid": "HYPE", "hype": "HYPE",
    "algorand": "ALGO", "algo": "ALGO",
    "sei": "SEI",
    "injective": "INJ", "inj": "INJ",
    "monero": "XMR", "xmr": "XMR",
    "kaspa": "KAS", "kas": "KAS",
}

REGULATION_AGENCIES = {
    "sec.gov": "SEC", "cftc.gov": "CFTC",
    "federalreserve.gov": "Fed", "treasury.gov": "Treasury",
    "bis.org": "BIS", "imf.org": "IMF",
    "worldbank.org": "World Bank", "ecb.europa.eu": "ECB",
    "esma.europa.eu": "ESMA",
}
REGULATION_TERMS = [
    "regulation", "regulatory", " sec ", "cftc", "compliance",
    "enforcement", "lawsuit", "ruling", "legislation", "bill ",
    "policy", "framework", "sanction", "ban ", "approved", "approval",
    "federal reserve", "treasury", "congress", "senate", "committee",
    "etf approval", "spot etf", "custody rule", "broker-dealer",
    "clarity act", "token taxonomy", "stablecoin act",
]

SENTIMENT_POSITIVE = [
    "surge", "rally", "breakout", "all-time high", "ath", "bull",
    "gain", "rise", "jump", "soar", "approval", "approved", "launch",
    "partnership", "upgrade", "milestone", "record", "adoption",
    "institutional", "etf approved", "bullish", "recovery", "rebound",
    "ceasefire", "positive", "growth", "expand",
]
SENTIMENT_NEGATIVE = [
    "crash", "plunge", "drop", "fell", "fall", "bear", "hack",
    "exploit", "rug", "scam", "fraud", "ban", "lawsuit", "sink",
    "collapse", "warning", "concern", "risk", "loss", "liquidat",
    "bankrupt", "down", "fear", "panic", "sell-off", "dump",
    "cyberattack", "stolen", "vanishes", "threat", "war",
]

# Reuse the exact same FOCUS_TERMS and WHITELIST_DOMAINS from existing build.py
FOCUS_TICKERS = {"xrp", "xdc", "xlm", "zbcn", "hbar", "link", "flr", "sgb"}
DYN_TICKERS = {
    "xrp","xdc","xlm","zbcn","hbar","link","flr","sgb",
    "btc","eth","sol","ada","bnb","ton","doge","trx","ltc","dot","matic","avax",
    "atom","near","algo","apt","sui","inj","stx","op","arb","fil","etc","uni","aave"
}
DYN_NAMES = {
    "ripple","xinfin","stellar","zebec","hedera","chainlink","flare","songbird",
    "bitcoin","ethereum","solana","cardano","binance","toncoin","dogecoin","tron",
    "litecoin","polkadot","polygon","avalanche","cosmos","near","algorand","aptos",
    "sui","injective","stacks","optimism","arbitrum","filecoin","ethereum classic",
    "uniswap","aave"
}
FOCUS_TERMS = {
    "xrp","xrpl","ripple","xdc","xinfin","xlm","stellar","zbcn","zebec","hbar","hedera",
    "link","chainlink","flr","flare","sgb","songbird","xdc network","zebec network",
    "r3","corda","cordapp","swift","iso 20022","dtcc","euroclear","clearstream",
    "t+1","nostro","vostro","securities depository","instant payments","rtgs",
    "sepa","fednow","cbdc","tokenization","tokenised","tokenized","rwa",
    "real world asset","real-world asset","crypto","cryptocurrency","blockchain",
    "onchain","web3","defi","l2","layer 2","stablecoin","usdc","usdt","etf",
    "spot etf","smart contract","wallet","custody","staking","dex","cex",
    "tokenomics","airdrop","interoperability"
}
WHITELIST_DOMAINS = {
    "xrpl.org","ripple.com","xinfin.org","xdc.org","zebec.io","hedera.com",
    "chain.link","rwa.xyz","swift.com","dtcc.com","euroclear.com","clearstream.com",
    "coindesk.com","cointelegraph.com","decrypt.co","theblock.co","r3.com","bis.org",
    "imf.org","worldbank.org","ecb.europa.eu","federalreserve.gov","sec.gov"
}

GOOD_WORDS = [
    'xrp','xrpl','ripple','xdc','xinfin','xlm','stellar','zbcn','zebec','hbar',
    'hedera','link','chainlink','flr','flare','sgb','songbird','swift','iso 20022',
    'dtcc','euroclear','clearstream','nostro','vostro','rtgs','securities depository',
    'tokenization','tokenized','tokenised','rwa','real-world asset','pilot','production',
    'integration','partnership','institution','bank','approval','listing','launch',
    'upgrade','framework','compliance','settlement','custody','treasury','testnet',
    'mainnet','etf','spot etf','onchain','defi','interoperability','regulation','ruling'
]
BAD_WORDS = [
    'to the moon','lambo','giveaway','airdrop scam','rug','pump and dump',
    '100x','1000x','thousandx','rocket','buy now','guaranteed profits'
]
SCORE_DROP_THRESHOLD = -1

# ── HELPERS ───────────────────────────────────────────────────────────────────
def host_of(u):
    try: return (urlparse(u).hostname or "").lower().replace("www.", "")
    except: return ""

def is_crypto_relevant(title, summary, link):
    try:
        t    = (title   or "").lower()
        s    = (summary or "").lower()
        blob = t + " " + s + " " + (link or "").lower()
        if re.search(r"\$([a-z0-9]{2,10})\b", t): return True
        words = set(re.findall(r"[a-z0-9]+", blob))
        if words & (DYN_TICKERS | FOCUS_TICKERS): return True
        for n in DYN_NAMES:
            if n in blob: return True
        for term in FOCUS_TERMS:
            if term in blob: return True
        if host_of(link) in WHITELIST_DOMAINS: return True
    except: pass
    return False

def score_text(title, summary):
    try:
        t = (title or '').lower(); s = (summary or '').lower()
        score = sum(2 for w in GOOD_WORDS if w in t or w in s)
        score -= sum(3 for w in BAD_WORDS if w in t or w in s)
        if (set(re.findall(r"[a-z0-9]+", t)) & FOCUS_TICKERS) or \
           (set(re.findall(r"[a-z0-9]+", s)) & FOCUS_TICKERS):
            score += 3
        if any(k in t for k in ("tokenization","tokenized","rwa","iso 20022",
                                 "swift","dtcc","euroclear","clearstream")):
            score += 2
        score += min(len(t) // 40, 3)
        return score
    except: return 0

def canonical_source(link, fallback):
    try: return (urlparse(link).hostname or "").lower().replace("www.", "") or fallback
    except: return fallback or ""

def normalize_title(t):
    try:
        t = re.sub(r'[^a-z0-9\s]', ' ', (t or '').lower())
        t = re.sub(r'\s+', ' ', t).strip()
        stop = {'the','a','an','to','of','for','on','in','and','with','by',
                'from','is','are','its','at','as'}
        return ' '.join(w for w in t.split() if w not in stop)
    except: return (t or '').lower().strip()

def diverse_pick(items, total_limit, per_source_cap=2):
    # Preserve existing behavior exactly
    buckets      = defaultdict(deque)
    count_by_src = defaultdict(int)
    for it in items:
        buckets[it['source']].append(it)
    sources = deque(sorted(buckets.keys()))
    chosen  = []
    while sources and len(chosen) < total_limit:
        s = sources[0]
        if buckets[s]:
            if count_by_src[s] < per_source_cap:
                chosen.append(buckets[s].popleft())
                count_by_src[s] += 1
                sources.rotate(-1)
            else:
                sources.popleft()
        else:
            sources.popleft()
    return chosen

def extract_coins(title):
    t = (title or "").lower()
    found = set()
    for term, sym in COIN_MAP.items():
        if re.search(r'\b' + re.escape(term) + r'\b', t):
            found.add(sym)
    for m in re.finditer(r'\$([A-Za-z]{2,6})\b', title or ""):
        sym = m.group(1).upper()
        if sym not in ("THE","AND","FOR","ALL","NEW","ITS"):
            found.add(sym)
    return sorted(found)

def sentiment_label(title, summary):
    blob = ((title or "") + " " + (summary or "")).lower()
    pos  = sum(1 for w in SENTIMENT_POSITIVE if w in blob)
    neg  = sum(1 for w in SENTIMENT_NEGATIVE if w in blob)
    if pos > neg: return "bullish"
    if neg > pos: return "bearish"
    return "neutral"

def is_regulation(title, source_host):
    if source_host in REGULATION_AGENCIES: return True
    t = (title or "").lower()
    return any(term in t for term in REGULATION_TERMS)

def agency_of(source_host, title):
    if source_host in REGULATION_AGENCIES:
        return REGULATION_AGENCIES[source_host]
    t = (title or "").lower()
    if "sec " in t or " sec " in t or "securities" in t: return "SEC"
    if "cftc" in t: return "CFTC"
    if "federal reserve" in t or "fed " in t: return "Fed"
    if "treasury" in t: return "Treasury"
    if "congress" in t or "senate" in t or "clarity act" in t: return "Congress"
    if "eu " in t or "europe" in t or "mica" in t: return "EU"
    return "Regulatory"

# ── X / TWITTER INTEGRATION (preserved from original) ────────────────────────
def fetch_x_breaking():
    """Fetch X posts — preserved from original build.py behavior."""
    if not X_BEARER_TOKEN:
        log("INFO: No X_BEARER_TOKEN — skipping X feed")
        return []
    try:
        import tweepy
        client = tweepy.Client(bearer_token=X_BEARER_TOKEN, wait_on_rate_limit=False)
        # Fetch recent crypto tweets from known accounts
        cfg_accounts = cfg.get("x_accounts", [])
        if not cfg_accounts:
            return []
        handles = [a.get("handle","") for a in cfg_accounts[:10] if a.get("handle")]
        if not handles:
            return []
        query = f"(from:{' OR from:'.join(handles)}) (crypto OR bitcoin OR ethereum OR XRP) -is:retweet lang:en"
        tweets = client.search_recent_tweets(
            query=query, max_results=10,
            tweet_fields=["created_at","author_id","text"],
        )
        results = []
        if tweets.data:
            for t in tweets.data:
                results.append({
                    "title":        t.text[:200],
                    "link":         f"https://twitter.com/i/web/status/{t.id}",
                    "published_at": t.created_at.isoformat() if t.created_at else now_utc().isoformat(),
                    "source":       "x.com",
                    "score":        5,
                    "ntitle":       normalize_title(t.text),
                })
        log(f"INFO: X feed returned {len(results)} posts")
        return results
    except Exception as e:
        log(f"WARN: X fetch failed: {e}")
        return []

# ── STORY CLUSTERING ──────────────────────────────────────────────────────────
def jaccard(s1, s2):
    a, b = set(s1.split()), set(s2.split())
    if not a and not b: return 0.0
    return len(a & b) / len(a | b)

def cluster_articles(articles, threshold=0.28):
    normed   = [normalize_title(a['title']) for a in articles]
    assigned = [-1] * len(articles)
    clusters = []
    for i in range(len(articles)):
        if assigned[i] != -1: continue
        cid = len(clusters)
        clusters.append([i])
        assigned[i] = cid
        for j in range(i + 1, len(articles)):
            if assigned[j] != -1: continue
            if jaccard(normed[i], normed[j]) >= threshold:
                clusters[cid].append(j)
                assigned[j] = cid
    result = []
    for cid, idxs in enumerate(clusters):
        members = [articles[i] for i in idxs]
        rep     = max(members, key=lambda x: x.get('score', 0))
        coins   = list(set(c for m in members for c in m.get('coins', [])))
        result.append({
            "id":           cid,
            "title":        rep['title'],
            "link":         rep['link'],
            "source":       rep['source'],
            "published_at": rep['published_at'],
            "sentiment":    rep.get('sentiment', 'neutral'),
            "coins":        coins,
            "sources":      list({m['source'] for m in members}),
            "count":        len(members),
            "members":      [{"title": m['title'], "link": m['link'],
                              "source": m['source'],
                              "published_at": m['published_at']}
                             for m in members],
        })
    result.sort(key=lambda c: (c['count'], c['published_at']), reverse=True)
    return result

# ── AI SUMMARIES ──────────────────────────────────────────────────────────────
def ai_summarize_clusters(clusters, max_clusters=10):
    if not ANTHROPIC_API_KEY:
        log("INFO: No ANTHROPIC_API_KEY — skipping AI summaries")
        return clusters
    top = [c for c in clusters if c['count'] >= 2][:max_clusters]
    if not top: return clusters

    stories_text = "\n".join(
        f"{i+1}. [{c['count']} sources] {c['title']}"
        for i, c in enumerate(top)
    )
    prompt = (
        f"You are the editor of The Blair Report, a crypto intelligence hub.\n"
        f"Below are {len(top)} trending story clusters. Write a sharp, factual "
        f"1-sentence summary (max 25 words) for each. No hype. No speculation.\n"
        f"Output ONLY a JSON array of strings in the same order.\n\n"
        f"Stories:\n{stories_text}\n\n"
        f"Respond with only a JSON array, e.g. [\"Summary 1.\", \"Summary 2.\", ...]"
    )
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      "claude-haiku-4-5-20251001",
                "max_tokens": 1024,
                "messages":   [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()["content"][0]["text"].strip()
        raw = re.sub(r'^```json\s*|^```\s*|```$', '', raw, flags=re.MULTILINE).strip()
        summaries = json.loads(raw)
        if isinstance(summaries, list):
            for i, c in enumerate(top):
                if i < len(summaries):
                    c['summary'] = summaries[i]
            log(f"INFO: AI summaries generated for {len(top)} clusters")
    except Exception as e:
        log(f"WARN: AI summarization failed: {e}")
    return clusters

# ── TRENDING TOPICS ───────────────────────────────────────────────────────────
def extract_trending(articles, top_n=8):
    coin_counts = defaultdict(int)
    term_counts = defaultdict(int)
    TRACK_TERMS = [
        "etf","defi","nft","cbdc","regulation","stablecoin","rwa","tokenization",
        "layer 2","bitcoin","ethereum","xrp","solana","quantum","ai","hack",
    ]
    for a in articles:
        for coin in a.get('coins', []):
            coin_counts[coin] += 1
        blob = (a.get('title', '') + ' ' + a.get('source', '')).lower()
        for term in TRACK_TERMS:
            if term in blob:
                term_counts[term] += 1

    trending = []
    for coin, cnt in sorted(coin_counts.items(), key=lambda x: -x[1])[:5]:
        trending.append({"tag": f"#{coin}", "count": cnt, "type": "coin"})
    for term, cnt in sorted(term_counts.items(), key=lambda x: -x[1])[:5]:
        if cnt >= 2:
            trending.append({"tag": f"#{term.replace(' ','')}".title(),
                             "count": cnt, "type": "topic"})
    trending.sort(key=lambda x: -x['count'])
    if trending:
        max_c = trending[0]['count']
        for t in trending:
            t['pct'] = round(100 * t['count'] / max_c)
    return trending[:top_n]

# ── SENTIMENT HISTORY ─────────────────────────────────────────────────────────
def compute_sentiment_snapshot(articles):
    counts = defaultdict(int)
    for a in articles:
        counts[a.get('sentiment', 'neutral')] += 1
    total       = max(sum(counts.values()), 1)
    bullish_pct = round(100 * counts['bullish'] / total)
    bearish_pct = round(100 * counts['bearish'] / total)
    neutral_pct = 100 - bullish_pct - bearish_pct
    score       = bullish_pct - bearish_pct

    if score >= 30:    label = "Greed"
    elif score >= 10:  label = "Optimistic"
    elif score >= -10: label = "Neutral"
    elif score >= -30: label = "Cautious"
    else:              label = "Fear"

    return {
        "score":         score,
        "label":         label,
        "bullish":       bullish_pct,
        "bearish":       bearish_pct,
        "neutral":       neutral_pct,
        "date":          now_utc().date().isoformat(),
        "article_count": total,
    }

def load_sentiment_history():
    path = os.path.join(DATA_DIR, "sentiment.json")
    data = load_json_safe(path)
    if data and isinstance(data.get('history'), list):
        return data['history']
    return []

# ── PRICES (CoinGecko — preserves existing shape exactly) ────────────────────
def fetch_prices():
    """
    Returns {prices:[...], gainers:[...], losers:[...]}
    Identical shape to what the existing build.py produces.
    """
    prices_api = (
        "https://api.coingecko.com/api/v3/coins/markets"
        "?vs_currency=usd&order=market_cap_desc"
        "&per_page=125&page=1&sparkline=false"
        "&price_change_percentage=24h"
    )
    try:
        r = requests.get(prices_api, headers={"User-Agent": UA}, timeout=25)
        r.raise_for_status()
        prices = r.json() or []
    except Exception as e:
        log(f"WARN: CoinGecko fetch failed: {e}")
        # Fall back to existing file
        existing = load_json_safe(os.path.join(DATA_DIR, "prices.json"))
        return existing if isinstance(existing, dict) else {"prices": [], "gainers": [], "losers": []}

    gainers = sorted(
        [p for p in prices if p.get('price_change_percentage_24h') is not None
         and p['price_change_percentage_24h'] > 0],
        key=lambda p: p['price_change_percentage_24h'], reverse=True
    )[:15]
    losers = sorted(
        [p for p in prices if p.get('price_change_percentage_24h') is not None
         and p['price_change_percentage_24h'] < 0],
        key=lambda p: p['price_change_percentage_24h']
    )[:15]

    def fmt(p):
        return {
            "symbol":    p['symbol'],
            "price":     p['current_price'],
            "change24h": p['price_change_percentage_24h'],
        }

    return {
        "prices": [
            {"rank": i + 1, "symbol": p['symbol'], "price": p['current_price'],
             "change24h": p['price_change_percentage_24h']}
            for i, p in enumerate(prices)
        ],
        "gainers": [fmt(p) for p in gainers],
        "losers":  [fmt(p) for p in losers],
    }

# ── INGEST FEEDS ──────────────────────────────────────────────────────────────
raw        = []
seen_links = set()
log(f"INFO: ingesting {len(SOURCES)} sources")

for i, src in enumerate(SOURCES, 1):
    name = src.get("name", "?")
    url  = src.get("url", "")
    if not url: continue
    log(f"INFO: [{i}/{len(SOURCES)}] {name}")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        d = feedparser.parse(resp.content)
    except Exception as ex:
        log(f"WARN: {name}: {ex}"); continue

    for e in (getattr(d, "entries", []) or [])[:150]:
        try:
            title   = (e.get("title")   or "").strip()
            link    = (e.get("link")    or "").strip()
            summary = (getattr(e, "summary", "") or "")
            if not title or not link: continue
            if not is_crypto_relevant(title, summary, link): continue
            sc = score_text(title, summary)
            if sc < SCORE_DROP_THRESHOLD: continue
            h = hashlib.sha1(link.encode()).hexdigest()
            if h in seen_links: continue
            seen_links.add(h)

            pub = None
            for k in ("published_parsed", "updated_parsed", "created_parsed"):
                v = getattr(e, k, None)
                if v:
                    try:
                        pub = datetime.fromtimestamp(time.mktime(v), tz=timezone.utc)
                        break
                    except: pass
            if not pub: pub = now_utc()

            src_host = canonical_source(link, name)
            coins    = extract_coins(title)
            sent     = sentiment_label(title, summary)
            is_reg   = is_regulation(title, src_host)
            agency   = agency_of(src_host, title) if is_reg else None

            raw.append({
                "title":         title,
                "link":          link,
                "published_at":  pub.isoformat(),
                "source":        src_host,
                "score":         sc,
                "ntitle":        normalize_title(title),
                # NEW fields — additive only, won't break existing app.js
                "coins":         coins,
                "sentiment":     sent,
                "is_regulation": is_reg,
                "agency":        agency,
            })
        except Exception as ex:
            log(f"WARN: entry ({name}): {ex}")

log(f"INFO: raw={len(raw)}")

# ── DEDUPE ────────────────────────────────────────────────────────────────────
seen    = set()
deduped = []
for it in sorted(raw, key=lambda x: (x["score"], x["published_at"]), reverse=True):
    key = (it["ntitle"][:60], it["source"])
    if key in seen: continue
    seen.add(key)
    deduped.append(it)
log(f"INFO: deduped={len(deduped)}")

# ── BUCKET BY AGE (same thresholds as original) ───────────────────────────────
now_dt  = now_utc()
buckets = {"breaking": [], "day": [], "week": [], "month": []}

def age_minutes(iso):
    try: return (now_dt - datetime.fromisoformat(iso)).total_seconds() / 60.0
    except: return 1e9

for it in deduped:
    m = age_minutes(it["published_at"])
    if   m <    60: buckets["breaking"].append(it)
    elif m <  1440: buckets["day"].append(it)
    elif m < 10080: buckets["week"].append(it)
    elif m < 43200: buckets["month"].append(it)

# Sort and pick — identical to original logic
for b in buckets:
    buckets[b].sort(key=lambda x: x['published_at'], reverse=True)
    buckets[b] = diverse_pick(buckets[b], PER_BUCKET)

log(f"INFO: breaking={len(buckets['breaking'])} day={len(buckets['day'])} "
    f"week={len(buckets['week'])} month={len(buckets['month'])}")

# ── X FEED ────────────────────────────────────────────────────────────────────
x_breaking = fetch_x_breaking()

# ── REGULATION FEED ───────────────────────────────────────────────────────────
regulation_items = [it for it in deduped if it.get("is_regulation")]
regulation_items.sort(key=lambda x: x["published_at"], reverse=True)
reg_out = [{
    "title":        it["title"],
    "link":         it["link"],
    "source":       it["source"],
    "published_at": it["published_at"],
    "agency":       it.get("agency", "Regulatory"),
    "sentiment":    it.get("sentiment", "neutral"),
    "coins":        it.get("coins", []),
} for it in regulation_items[:30]]

# ── CLUSTERING + AI SUMMARIES ─────────────────────────────────────────────────
all_recent   = buckets["breaking"] + buckets["day"]
clusters     = cluster_articles(all_recent, threshold=0.25)
hot_clusters = [c for c in clusters if c["count"] >= 2][:10]
hot_clusters = ai_summarize_clusters(hot_clusters)

# ── TRENDING ──────────────────────────────────────────────────────────────────
trending = extract_trending(deduped[:200])

# ── SENTIMENT ─────────────────────────────────────────────────────────────────
snapshot = compute_sentiment_snapshot(deduped)
history  = load_sentiment_history()
today    = snapshot["date"]
history  = [h for h in history if h.get("date") != today]
history.append(snapshot)
history  = history[-30:]
sentiment_out = {**snapshot, "history": history}

# ── ARCHIVE ───────────────────────────────────────────────────────────────────
archive_path  = os.path.join(HIST_DIR, today + ".json")
existing_arc  = load_json_safe(archive_path) or []
existing_links = {a.get("link") for a in existing_arc}
new_items = [
    {k: it[k] for k in ("title","link","source","published_at","coins",
                         "sentiment","is_regulation") if k in it}
    for it in deduped if it.get("link") not in existing_links
]
safe_write_json(archive_path, existing_arc + new_items)

# Prune archives older than 90 days
cutoff = (now_dt - timedelta(days=90)).date().isoformat()
for fname in os.listdir(HIST_DIR):
    if fname.endswith(".json") and fname[:10] < cutoff:
        try: os.remove(os.path.join(HIST_DIR, fname)); log(f"INFO: pruned {fname}")
        except: pass

# ── WRITE OUTPUTS ─────────────────────────────────────────────────────────────
headlines_out = {
    # Preserve exact existing keys so old app.js keeps working
    "x_breaking": x_breaking,
    "breaking":   buckets["breaking"],
    "day":        buckets["day"],
    "week":       buckets["week"],
    "month":      buckets["month"],
    # New keys — ignored by old app.js, used by new one
    "clusters":     hot_clusters,
    "trending":     trending,
    "generated_at": now_dt.isoformat(),
}

prices_out = fetch_prices()   # {prices:[...], gainers:[...], losers:[...]}

safe_write_json(os.path.join(DATA_DIR, "headlines.json"),  headlines_out)
safe_write_json(os.path.join(DATA_DIR, "prices.json"),     prices_out)
safe_write_json(os.path.join(DATA_DIR, "sentiment.json"),  sentiment_out)
safe_write_json(os.path.join(DATA_DIR, "regulation.json"), reg_out)

log("INFO: build v3.0 complete ✓")
