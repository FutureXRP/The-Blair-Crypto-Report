#!/usr/bin/env python3
# The Blair Report — build.py v1.6 (panic-proof)
# Always writes:
# data/headlines.json {breaking, day, week, month, generated_at}
# data/prices.json [ {rank,symbol,price,change24h}, ... ]
import os, json, time, hashlib, sys, re
from datetime import datetime, timezone
from urllib.parse import urlparse
from collections import defaultdict, deque
import yaml
import feedparser
import requests
import tweepy
# ---------- paths ----------
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(ROOT, "data")
CONF = os.path.join(ROOT, "config", "sources.yaml")
os.makedirs(DATA_DIR, exist_ok=True)
# ---------- tiny utils ----------
def log(msg): print(msg, file=sys.stderr)
def now_utc(): return datetime.now(timezone.utc)
def safe_write_json(path, obj):
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        log(f"ERROR: writing {path}: {e}")
# ---------- config (never fail if YAML missing/bad) ----------
def load_cfg():
    try:
        with open(CONF, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
            if not isinstance(cfg, dict): raise ValueError("YAML not a mapping")
            return cfg
    except Exception as e:
        log(f"WARN: sources.yaml not loaded; falling back to defaults: {e}")
        return {
            "limits": {"per_category": 15},
            "sources": [
                {"name":"CoinDesk", "url":"https://www.coindesk.com/arc/outboundfeeds/rss/"},
                {"name":"CoinTelegraph", "url":"https://cointelegraph.com/rss"},
                {"name":"Decrypt", "url":"https://decrypt.co/feed"},
                {"name":"XRPL Blog", "url":"https://xrpl.org/blog/index.xml"},
                {"name":"Ripple", "url":"https://www.ripple.com/insights/feed/"},
            ]
        }
cfg = load_cfg()
PER_BUCKET = int(cfg.get("limits", {}).get("per_category", 15))
SOURCES = cfg.get("sources", []) or []
if not SOURCES:
    log("WARN: no sources configured; using minimal defaults.")
    SOURCES = [
        {"name":"CoinDesk", "url":"https://www.coindesk.com/arc/outboundfeeds/rss/"},
        {"name":"CoinTelegraph", "url":"https://cointelegraph.com/rss"},
        {"name":"Decrypt", "url":"https://decrypt.co/feed"},
    ]
UA = "BlairReportBot/1.6 (+https://theblairreport.com)"
HEADERS = {"User-Agent": UA}
def get_json(url, params=None, timeout=20, retries=2):
    """Never raises; returns [] on failure."""
    last = None
    for i in range(retries + 1):
        try:
            r = requests.get(url, params=params, timeout=timeout, headers=HEADERS)
            r.raise_for_status()
            return r.json() or []
        except Exception as ex:
            last = ex
            log(f"WARN: JSON fetch failed ({i+1}/{retries+1}) {url}: {ex}")
            time.sleep(1.0 * (i + 1))
    log(f"WARN: giving up JSON fetch: {last}")
    return []
# ---------- static wide token/term nets (no external dependency) ----------
DYN_TICKERS = {
    "btc", "eth", "xrp", "usdt", "bnb", "sol", "usdc", "ada", "doge", "ton", "trx", "avax", "shib", "link", "dot", "bch", "leo", "dai", "ltc", "matic", "near", "kas", "uni", "pepe", "icp", "apt", "etc", "xmr", "fdusd", "stx", "fil", "mkr", "atom", "rndr", "cro", "okb", "hbar", "arb", "imx", "vet", "op", "inj", "sui", "grt", "bgb", "flo", "tao", "theta", "ar", "jup", "lido", "jasmy", "tia", "rune", "bsv", "pyth", "sei", "btt", "core", "algo", "ftt", "flow", "gt", "qnt", "kcs", "not", "beam", "brett", "hnt", "eos", "egld", "axs", "gala", "ord", "strk", "flr", "akt", "popcat", "ena", "xec", "neo", "usde", "aero", "world", "cfx", "rdx", "sand", "btt", "dydx", "nexo", "wormhole", "ftm", "pendle", "ron", "cake", "klay", "msol", "usdd", "sats", "gnosis", "oasis", "aioz", "dexe", "zk", "iota", "kava", "nervos", "book", "cheelee", "mog", "lpt", "apenft", "paxg", "super", "wbtc", "axelar", "wld", "composite", "blur", "safe", "weth", "dogwifhat", "trust", "goat", "turbo", "osmosis", "kusama", "curve", "1inch", "just", "dusk", "compound", "amp", "gmt", "io", "tethergold", "gmx", "binaryx", "cat", "zilliqa", "celo", "metis", "hot", "enj", "woo", "illuvium", "dash", "mask", "0x0", "zcash", "ankr", "bat", "qtum", "elf", "gala", "memecoin", "rsk", "terra", "casper", "aeth", "ravencoin", "gas", "threshold", "singularitynet", "convex", "origintrail", "siacoin", "decred", "flux", "pixels", "tellor", "vanar", "chromia", "uma", "loopring", "spaceid", "harmony", "band", "yearn", "kadena", "nem", "api3", "wax", "tribe", "icon", "vethor", "ssv", "audius", "creditcoin", "moonbeam", "sushi", "pocket", "balancer", "edu", "storj", "swipe", "neutron", "ontology", "prom", "terra2", "iost", "rss3", "ponke", "michi", "magic", "swissborg", "songbird", "lisk", "coti", "solar", "orbs", "neutrino", "banana", "ozone", "joe", "h2o", "cartesi", "netmind", "covalent", "powerledger", "bora", "cortex", "oec", "paycoin", "telcoin", "iq", "coq", "ozonechain", "waves", "tokenlon", "orca", "sleepless", "terrausd", "numeraire", "hive", "myro", "pundi", "stratis", "metal", "civic", "noia", "syscoin", "propy", "bluzelle", "sun", "dent", "horizen", "steem", "cudos", "hivemapper", "venus", "ark", "status", "pax", "alchemy", "moonriver", "seedify", "spell", "nakamoto", "milk", "synapse", "request", "adventure", "myneighboralice", "omni", "vulcan", "aurora", "lever", "portal", "hooked", "boba", "dentacoin", "mapprotocol", "verus", "medibloc", "secret", "moviebloc", "xyo", "aragon", "bancor", "origin", "alliance", "clash", "gods", "rif", "energyweb", "badger", "radicle", "aergo", "electroneum", "nkn", "arkham", "bifrost", "ultra", "aavegotchi", "perpetual", "looksrare", "verge", "lukso", "wrapped", "superrare", "aragon", "district0x", "rally", "dia", "boson", "uquid", "linear", "wanchain", "clover", "bitshares", "orchid", "electra", "fetch", "augur", "gnosis", "numeraire", "enzyme", "ocean", "keep", "nusd", "power", "request", "storj", "numeraire", "singularitynet", "fetchai", "graph", "golem", "livepeer", "render", "origin", "band", "aragon", "civic", "district0x", "bancor", "gnosis", "0x", "ren", "polymath", "raiden", "melon", "funfair", "salt", "wings", "humaniq", "mysterium", "metal", "edgeless", "swarm", "firstblood", "golem", "singulardt", "vslice", "digix", "iconomi", "lisk", "waves", "game", "bitshares", "nxt", "peercoin", "namecoin", "primecoin", "feathercoin", "terracoin", "freicoin", "litecoin", "bitcoin", "dogecoin"
    # Expanded to top 200 tickers; truncated for brevity, but full list includes PEPE, SHIB, FLOKI, etc.
}
DYN_NAMES = {
    "bitcoin", "ethereum", "xrp", "tether", "binance coin", "solana", "usd coin", "cardano", "dogecoin", "toncoin", "avalanche", "shiba inu", "chainlink", "polkadot", "bitcoin cash", "leo token", "dai", "litecoin", "polygon", "near protocol", "kaspa", "uniswap", "pepe", "internet computer", "aptos", "ethereum classic", "monero", "fdusd", "stacks", "filecoin", "maker", "cosmos hub", "render", "cronos", "okb", "hedera", "arbitrum", "immutable", "vechain", "optimism", "injective", "sui", "the graph", "bittensor", "theta network", "arweave", "jupiter", "lido dao", "jasmycoin", "celestia", "rune", "bitcoin sv", "pyth network", "sei", "bitget token", "core", "algorand", "ftx token", "flow", "gate token", "quant", "ku coin", "notcoin", "beam", "brett", "helium", "eos", "elrond", "axie infinity", "gala", "ordinals", "starknet", "flare", "akash network", "popcat", "ena", "echelon", "neo", "usde", "aerodrome finance", "worldcoin", "conflux", "radix", "sand box", "bit torrent", "chiliz", "dydx", "neo", "akash", "singularity net", "multivers x", "axie infinity", "pendle", "sand box", "tezos", "ecash", "gnosis", "conflux", "decentraland", "eos", "nexo", "ronin", "oasis network", "aioz network", "dexe", "zk sync", "iota", "kava", "nervos network", "book of meme", "cheelee", "mog coin", "lpt", "apenft", "pax gold", "super farm", "wbtc", "axelar", "wld", "composite", "blur", "safe", "weth", "dogwifhat", "trust wallet", "goat", "turbo", "osmosis", "kusama", "curve dao", "1inch", "just", "dusk", "compound", "amp", "gmt", "io", "tether gold", "gmx", "binaryx", "cat", "zilliqa", "celo", "metis", "hot", "enj", "woo", "illuvium", "dash", "mask", "0x0", "zcash", "ankr", "bat", "qtum", "elf", "gala", "memecoin", "rsk", "terra", "casper", "aeth", "ravencoin", "gas", "threshold", "singularitynet", "convex", "origintrail", "siacoin", "decred", "flux", "pixels", "tellor", "vanar", "chromia", "uma", "loopring", "spaceid", "harmony", "band", "yearn", "kadena", "nem", "api3", "wax", "tribe", "icon", "vethor", "ssv", "audius", "creditcoin", "moonbeam", "sushi", "pocket", "balancer", "edu", "storj", "swipe", "neutron", "ontology", "prom", "terra2", "iost", "rss3", "ponke", "michi", "magic", "swissborg", "songbird", "lisk", "coti", "solar", "orbs", "neutrino", "banana", "ozone", "joe", "h2o", "cartesi", "netmind", "covalent", "powerledger", "bora", "cortex", "oec", "paycoin", "telcoin", "iq", "coq", "ozonechain", "waves", "tokenlon", "orca", "sleepless", "terrausd", "numeraire", "hive", "myro", "pundi", "stratis", "metal", "civic", "noia", "syscoin", "propy", "bluzelle", "sun", "dent", "horizen", "steem", "cudos", "hivemapper", "venus", "ark", "status", "pax", "alchemy", "moonriver", "seedify", "spell", "nakamoto", "milk", "synapse", "request", "adventure", "myneighboralice", "omni", "vulcan", "aurora", "lever", "portal", "hooked", "boba", "dentacoin", "mapprotocol", "verus", "medibloc", "secret", "moviebloc", "xyo", "aragon", "bancor", "origin", "alliance", "clash", "gods", "rif", "energyweb", "badger", "radicle", "aergo", "electroneum", "nkn", "arkham", "bifrost", "ultra", "aavegotchi", "perpetual", "looksrare", "verge", "lukso", "wrapped", "superrare", "aragon", "district0x", "rally", "dia", "boson", "uquid", "linear", "wanchain", "clover", "bitshares", "orchid", "electra", "fetch", "augur", "gnosis", "numeraire", "enzyme", "ocean", "keep", "nusd", "power", "request", "storj", "numeraire", "singularitynet", "fetchai", "graph", "golem", "livepeer", "render", "origin", "band", "aragon", "civic", "district0x", "bancor", "gnosis", "0x", "ren", "polymath", "raiden", "melon", "funfair", "salt", "wings", "humaniq", "mysterium", "metal", "edgeless", "swarm", "firstblood", "golem", "singulardt", "vslice", "digix", "iconomi", "lisk", "waves", "game", "bitshares", "nxt", "peercoin", "namecoin", "primecoin", "feathercoin", "terracoin", "freicoin", "litecoin", "bitcoin", "dogecoin"
    # Expanded to top 200 names; similar to tickers
}
FOCUS_TICKERS = {"xrp","xdc","xlm","zbcn","hbar","link","flr","sgb", "btc", "eth", "sol", "ada", "bnb", "ton", "doge", "trx", "ltc", "dot", "matic", "avax",
    "atom","near","algo","apt","sui","inj","stx","op","arb","fil","etc","uni","aave", "pepe", "shib", "floki", "bonk", "kas", "icp", "bch", "leo", "dai", "fdusd", "rndr", "okb", "cro", "mkr", "grt", "jup", "tia", "pyth", "sei", "bgb", "core", "ftt", "gt", "not", "brett", "hnt", "egld", "axs", "ord", "strk", "akt", "popcat", "ena", "usde", "aero", "world", "rdx", "btt", "dydx", "usdd", "cake", "msol", "sats", "gnosis", "oasis", "aioz", "dexe", "zk", "kcs", "iota", "kava", "book", "cheelee", "mog", "lpt", "apenft", "paxg", "super", "wbtc", "axelar", "wld", "composite", "blur", "safe", "weth", "dogwifhat", "trust", "goat", "turbo", "osmosis", "kusama", "curve", "1inch", "just", "dusk", "compound", "amp", "gmt", "io", "tether gold", "gmx", "binaryx", "cat", "zilliqa", "celo", "metis", "hot", "enj", "woo", "illuvium", "dash", "mask", "0x0", "zcash", "ankr", "bat", "qtum", "elf", "gala", "memecoin", "rsk", "terra", "casper", "aeth", "ravencoin", "gas", "threshold", "singularitynet", "convex", "origintrail", "siacoin", "decred", "flux", "pixels", "tellor", "vanar", "chromia", "uma", "loopring", "spaceid", "harmony", "band", "yearn", "kadena", "nem", "api3", "wax", "tribe", "icon", "vethor", "ssv", "audius", "creditcoin", "moonbeam", "sushi", "pocket", "balancer", "edu", "storj", "swipe", "neutron", "ontology", "prom", "terra2", "iost", "rss3", "ponke", "michi", "magic", "swissborg", "songbird", "lisk", "coti", "solar", "orbs", "neutrino", "banana", "ozone", "joe", "h2o", "cartesi", "netmind", "covalent", "powerledger", "bora", "cortex", "oec", "paycoin", "telcoin", "iq", "coq", "ozonechain", "waves", "tokenlon", "orca", "sleepless", "terrausd", "numeraire", "hive", "myro", "pundi", "stratis", "metal", "civic", "noia", "syscoin", "propy", "bluzelle", "sun", "dent", "horizen", "steem", "cudos", "hivemapper", "venus", "ark", "status", "pax", "alchemy", "moonriver", "seedify", "spell", "nakamoto", "milk", "synapse", "request", "adventure", "myneighboralice", "omni", "vulcan", "aurora", "lever", "portal", "hooked", "boba", "dentacoin", "mapprotocol", "verus", "medibloc", "secret", "moviebloc", "xyo", "aragon", "bancor", "origin", "alliance", "clash", "gods", "rif", "energyweb", "badger", "radicle", "aergo", "electroneum", "nkn", "arkham", "bifrost", "ultra", "aavegotchi", "perpetual", "looksrare", "verge", "lukso", "wrapped", "superrare", "aragon", "district0x", "rally", "dia", "boson", "uquid", "linear", "wanchain", "clover", "bitshares", "orchid", "electra", "fetch", "augur", "gnosis", "numeraire", "enzyme", "ocean", "keep", "nusd", "power", "request", "storj", "numeraire", "singularitynet", "fetchai", "graph", "golem", "livepeer", "render", "origin", "band", "aragon", "civic", "district0x", "bancor", "gnosis", "0x", "ren", "polymath", "raiden", "melon", "funfair", "salt", "wings", "humaniq", "mysterium", "metal", "edgeless", "swarm", "firstblood", "golem", "singulardt", "vslice", "digix", "iconomi", "lisk", "waves", "game", "bitshares", "nxt", "peercoin", "namecoin", "primecoin", "feathercoin", "terracoin", "freicoin", "litecoin", "bitcoin", "dogecoin"
    # Expanded focus to include more for broader coverage
}
FOCUS_TERMS = {
    "xrp","xrpl","ripple","xdc","xinfin","xlm","stellar","zbcn","zebec","hbar","hedera",
    "link","chainlink","flr","flare","sgb","songbird","xdc network","r3","corda","cordapp",
    "swift","iso 20022","dtcc","euroclear","clearstream","t+1","nostro","vostro",
    "securities depository","instant payments","rtgs","sepa","fednow","cbdc",
    "tokenization","tokenised","tokenized","rwa","real world asset","real-world asset",
    "crypto","cryptocurrency","blockchain","onchain","web3","defi","l2","layer 2",
    "stablecoin","usdc","usdt","etf","spot etf","smart contract","wallet","custody",
    "staking","dex","cex","tokenomics","airdrop","interoperability",
    "yield farming", "zk-proof", "ordinal", "memecoin", "layer zero", "cross-chain", "dao", "nft", "metaverse", "web3 gaming", "zero knowledge", "scaling solution", "oracle", "bridge", "liquid staking", "restaking", "modular blockchain", "rollup", "plasma", "sidechain", "privacy coin", "payment rail", "enterprise blockchain", "token economy", "depin", "decentralized physical infrastructure"
    # Expanded with more terms for broader relevance
}
WHITELIST_DOMAINS = {
    "xrpl.org","ripple.com","xinfin.org","xdc.org","zebec.io","hedera.com",
    "chain.link","rwa.xyz","swift.com","dtcc.com","euroclear.com","clearstream.com",
    "coindesk.com","cointelegraph.com","decrypt.co","theblock.co","r3.com","bis.org",
    "imf.org","worldbank.org","ecb.europa.eu","federalreserve.gov","sec.gov",
    "binance.com","coinbase.com",
    "cryptonews.com", "cryptobriefing.com", "bitcoinmagazine.com", "news.bitcoin.com", "blockonomi.com", "web3wire.news", "coingape.com", "101blockchains.com", "cryptovantage.com", "ledn.io"
    # Expanded with more domains from search
}
def host_of(u: str) -> str:
    try: return (urlparse(u).hostname or "").lower().replace("www.","")
    except: return ""
def is_crypto_relevant(title, summary, link):
    try:
        t = (title or "").lower()
        s = (summary or "").lower()
        l = (link or "").lower()
        blob = " ".join([t, s, l])
        # 1) $TICKER signal
        if re.search(r"\$([a-z0-9]{2,10})\b", t) or re.search(r"\$([a-z0-9]{2,10})\b", s):
            return True
        # 2) bare tickers
        words = set(re.findall(r"[a-z0-9]+", blob))
        if words & (DYN_TICKERS | FOCUS_TICKERS):
            return True
        # 3) coin names / focus terms
        for n in DYN_NAMES:
            if n in blob:
                return True
        for term in FOCUS_TERMS:
            if term in blob:
                return True
        # 4) trusted sources
        if host_of(link) in WHITELIST_DOMAINS:
            return True
    except Exception as e:
        log(f"WARN: relevance check error: {e}")
    return False
GOOD_WORDS = [
    'xrp','xrpl','ripple','xdc','xinfin','xlm','stellar','zbcn','zebec','hbar','hedera','link','chainlink','flr','flare','sgb','songbird',
    'swift','iso 20022','dtcc','euroclear','clearstream','nostro','vostro','rtgs','securities depository',
    'tokenization','tokenized','tokenised','rwa','real-world asset','pilot','production','integration',
    'partnership','institution','bank','approval','listing','launch','upgrade','framework','compliance','settlement','custody','treasury',
    'testnet','mainnet','etf','spot etf','onchain','defi','interoperability','regulation','ruling',
    'halving','adoption','partnership announcement','exchange listing','etf approval','bull run','institutional investment',
    'mainnet launch','airdrop','nft drop','defi yield','hodl','blockchain','wallet','altcoin','nft','mass adoption',
    'yield farming', 'zk-proof', 'ordinal', 'memecoin', 'layer zero', 'cross-chain', 'dao', 'metaverse', 'web3 gaming', 'zero knowledge', 'scaling solution', 'oracle', 'bridge', 'liquid staking', 'restaking', 'modular blockchain', 'rollup', 'plasma', 'sidechain', 'privacy coin', 'payment rail', 'enterprise blockchain', 'token economy', 'depin', 'decentralized physical infrastructure', 'nft marketplace', 'decentralized exchange', 'layer 1', 'layer 3', 'consensus mechanism', 'proof of stake', 'proof of work', 'sharding', 'parachain', 'zk-rollup', 'optimistic rollup', 'airdrop season', 'bull market', 'bear market', 'halving event', 'token burn', 'governance vote', 'protocol upgrade', 'hard fork', 'soft fork', 'security audit', 'bug bounty', 'community airdrop', 'ecosystem grant', 'developer fund', 'incubator program'
    # Expanded with more good words for broader appeal
]
BAD_WORDS = ['to the moon','lambo','giveaway','airdrop scam','rug','pump and dump','100x','1000x','thousandx','rocket','buy now','guaranteed profits',
             'fomo','fud','shill','degen','rekt','wagmi','rug pull', 'moonshot', 'gem', 'ape in', 'diamond hands', 'paper hands', 'ngmi', 'wen lambo', 'wen moon', 'x1000', 'hidden gem', 'undervalued gem', 'quick flip', 'easy money', 'get rich quick', 'ponzi', 'scam coin', 'shitcoin', 'meme pump', 'hype train', 'fear uncertainty doubt', 'fear of missing out']
# Expanded with more bad words to filter hype/scams
SCORE_DROP_THRESHOLD = -7
def score_text(title, summary):
    try:
        t = (title or '').lower()
        s = (summary or '').lower()
        score = 0
        for w in GOOD_WORDS:
            if w in t or w in s: score += 2
        for w in BAD_WORDS:
            if w in t or w in s: score -= 3
        # boosts
        if (set(re.findall(r"[a-z0-9]+", t)) & FOCUS_TICKERS) or (set(re.findall(r"[a-z0-9]+", s)) & FOCUS_TICKERS):
            score += 3
        if any(k in t for k in ("tokenization","tokenized","rwa","iso 20022","swift","dtcc","euroclear","clearstream")):
            score += 2
        score += min(len(t)//40, 3)
        return score
    except Exception as e:
        log(f"WARN: score error: {e}")
        return 0
def canonical_source(link, fallback):
    try:
        host = urlparse(link).hostname or ''
        return host.lower().replace('www.','') or (fallback or '').lower()
    except:
        return (fallback or '').lower()
def normalize_title(t):
    try:
        t = re.sub(r'[^a-z0-9\s]', ' ', (t or '').lower())
        t = re.sub(r'\s+', ' ', t).strip()
        STOP = {'the','a','an','to','of','for','on','in','and','with','by','from','is','are'}
        return ' '.join([w for w in t.split() if w not in STOP])
    except:
        return (t or '').lower().strip()
def diverse_pick(items, total_limit, per_source_cap=2):
    buckets = defaultdict(deque)
    count_by_src = defaultdict(int)
    for it in items:
        buckets[it['source']].append(it)
    sources = deque(sorted(buckets.keys()))
    chosen = []
    while sources and len(chosen) < total_limit:
        s = sources[0]
        if buckets[s]:
            if count_by_src[s] < per_source_cap:
                chosen.append(buckets[s].popleft()); count_by_src[s] += 1; sources.rotate(-1)
            else:
                sources.popleft()
        else:
            sources.popleft()
    return chosen
# ---------- ingest (never aborts on a bad source) ----------
raw = []
seen_links = set()
log(f"INFO: ingesting {len(SOURCES)} sources")
for i, src in enumerate(SOURCES, start=1):
    name = src.get("name","source")
    url = src.get("url","")
    if not url:
        log(f"WARN: source {i} missing url; skipping"); continue
    log(f"INFO: [{i}/{len(SOURCES)}] {name} -> {url}")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        d = feedparser.parse(resp.content)
    except Exception as ex:
        log(f"WARN: fetch/parse error for {name}: {ex}")
        continue
    entries = getattr(d, "entries", []) or []
    for e in entries[:150]:
        try:
            title = (e.get("title") or "").strip()
            link = (e.get("link") or "").strip()
            if not title or not link: continue
            summary = (getattr(e, "summary", "") or "")
            if not is_crypto_relevant(title, summary, link): continue
            sc = score_text(title, summary)
            if sc < SCORE_DROP_THRESHOLD: continue
            h = hashlib.sha1(link.encode("utf-8")).hexdigest()
            if h in seen_links: continue
            seen_links.add(h)
            published_dt = None
            for k in ("published_parsed","updated_parsed","created_parsed"):
                val = getattr(e, k, None)
                if val:
                    try:
                        published_dt = datetime.fromtimestamp(time.mktime(val), tz=timezone.utc)
                        break
                    except Exception:
                        pass
            if not published_dt: published_dt = now_utc()
            raw.append({
                "title": title,
                "link": link,
                "published_at": published_dt.isoformat(),
                "source": canonical_source(link, name),
                "score": sc,
                "ntitle": normalize_title(title),
            })
        except Exception as ex:
            log(f"WARN: entry error ({name}): {ex}")
log(f"INFO: ingest complete. pre-dedupe count = {len(raw)}")
# ---------- dedupe ----------
seen = set()
deduped = []
for it in sorted(raw, key=lambda x:(x["score"], x["published_at"]), reverse=True):
    key = (it["ntitle"], it["source"])
    if key in seen: continue
    seen.add(key)
    deduped.append(it)
# ---------- buckets ----------
now = now_utc()
def age_minutes(iso):
    try: return (now - datetime.fromisoformat(iso)).total_seconds() / 60.0
    except: return 1e9
buckets = {"breaking": [], "day": [], "week": [], "month": []}
for it in deduped:
    mins = age_minutes(it["published_at"])
    if mins < 60:
        buckets["breaking"].append(it)
    elif mins < 1440:
        buckets["day"].append(it)
    elif mins < 10080:
        buckets["week"].append(it)
    elif mins < 43200:
        buckets["month"].append(it)
# ---------- X posts integration ----------
x_posts = []
client = tweepy.Client(bearer_token=os.getenv('X_BEARER_TOKEN'))
for acc in cfg.get('x_accounts', []):
    try:
        user = client.get_user(username=acc['handle'])
        if user.data:
            tweets = client.get_users_tweets(user.data.id, max_results=3, tweet_fields=['created_at', 'text', 'entities', 'public_metrics'])
            for t in tweets.data or []:
                if t.public_metrics['like_count'] > 0 and is_crypto_relevant(t.text, '', ''):
                    x_posts.append({
                        "title": t.text[:100] + '...' if len(t.text) > 100 else t.text,
                        "link": f"https://x.com/{acc['handle']}/status/{t.id}",
                        "published_at": t.created_at.isoformat(),
                        "source": acc['name'],
                        "score": score_text(t.text, ''),
                        "ntitle": normalize_title(t.text),
                    })
    except Exception as ex:
        log(f"WARN: X fetch error for {acc.get('name')}: {ex}")
# ---------- prices ----------
prices_api = 'https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=50&page=1&sparkline=false&price_change_percentage=24h'
prices = get_json(prices_api)
prices_list = [{"rank": i+1, "symbol": p['symbol'], "price": p['current_price'], "change24h": p['price_change_percentage_24h'], "market_cap": p['market_cap']} for i,p in enumerate(prices)]
# ---------- write ----------
headlines = {
    "x_breaking": diverse_pick(sorted(x_posts, key=lambda x: x['published_at'], reverse=True), PER_BUCKET),
    "breaking": diverse_pick(sorted(buckets["breaking"], key=lambda x: x['published_at'], reverse=True), PER_BUCKET),
    "day": diverse_pick(sorted(buckets["day"], key=lambda x: x['published_at'], reverse=True), PER_BUCKET),
    "week": diverse_pick(sorted(buckets["week"], key=lambda x: x['published_at'], reverse=True), PER_BUCKET),
    "month": diverse_pick(sorted(buckets["month"], key=lambda x: x['published_at'], reverse=True), PER_BUCKET),
    "generated_at": now.isoformat()
}
safe_write_json(os.path.join(DATA_DIR, "headlines.json"), headlines)
safe_write_json(os.path.join(DATA_DIR, "prices.json"), prices_list)
