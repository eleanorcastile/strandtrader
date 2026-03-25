#!/usr/bin/env python3
"""
STRANDTRADER — EDGAR Sweep Script V6 (Local)
Places simulated paper trades: writes to local us_portfolio.json.
Yahoo Finance for prices. IBKR wiring for later.
"""

import json, os, re, time, html
from datetime import datetime, date, timedelta
from pathlib import Path

import requests
import yfinance as yf

# ─── CONFIG ──────────────────────────────────────────────────────────────────

PAPER_POSITIONS_FILE = Path("/Users/eleanor/.openclaw/workspace-soros/strandtrader/us_portfolio.json")
PAPER_HISTORY_FILE  = Path("/Users/eleanor/.openclaw/workspace-soros/strandtrader/us_history.json")
EDGAR_HDR  = {"User-Agent": "STRANDTrader/1.0 soros@strand.ai"}

# Filters
MIN_PRICE   = 3.00
MIN_VOLUME  = 100_000
MAX_POSITION = 250
MAX_ORDERS  = 5
TARGET_ITEMS = ["1.01", "2.02", "5.02"]

# ─── LOGGING ─────────────────────────────────────────────────────────────────

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# ─── PORTFOLIO HELPERS ─────────────────────────────────────────────────────────

def load_portfolio():
    try:
        with open(PAPER_POSITIONS_FILE) as f:
            return json.load(f)
    except:
        return {"positions": {}, "cash": 50000.0}

def save_portfolio(data):
    with open(PAPER_POSITIONS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_history():
    try:
        with open(PAPER_HISTORY_FILE) as f:
            return json.load(f)
    except:
        return {"trades": [], "summary": {"wins": 0, "losses": 0}}

def save_history(data):
    with open(PAPER_HISTORY_FILE, "w") as f:
        json.dump(data, f, indent=2)

def add_position(ticker, qty, entry_price, Syd_time=None):
    """Add or add-to existing position. Writes to local portfolio.json."""
    data = load_portfolio()
    entry = Syd_time or datetime.now().astimezone(
        __import__('pytz').timezone("Australia/Sydney")
    ).isoformat()
    if ticker in data["positions"]:
        # Average in
        existing = data["positions"][ticker]
        total_qty = existing["qty"] + qty
        avg_price = (existing["entry_price"] * existing["qty"] + entry_price * qty) / total_qty
        data["positions"][ticker]["qty"] = total_qty
        data["positions"][ticker]["entry_price"] = round(avg_price, 4)
        data["positions"][ticker]["date_added"] = existing.get("date_added", entry)
    else:
        data["positions"][ticker] = {
            "ticker": ticker,
            "qty": qty,
            "entry_price": round(entry_price, 4),
            "date_added": entry,
        }
    data["cash"] = data.get("cash", 50000.0) - qty * entry_price
    save_portfolio(data)
    return data["positions"][ticker]

# ─── EDGAR ───────────────────────────────────────────────────────────────────

def get_edgar_filings():
    r = requests.get(
        "https://www.sec.gov/cgi-bin/browse-edgar",
        params={"action": "getcurrent", "type": "8-K", "count": "200", "output": "atom"},
        headers=EDGAR_HDR, timeout=30
    )
    if r.status_code != 200:
        log(f"EDGAR {r.status_code}")
        return []

    entries = r.text.split("<entry>")
    results = []
    for entry in entries[1:]:
        sm_m = re.search(r"<summary[^>]*>(.*?)</summary>", entry, re.DOTALL)
        if not sm_m:
            continue
        raw = html.unescape(sm_m.group(1))
        summary = re.sub(r"<[^>]+>", " ", raw)
        summary = re.sub(r"\s+", " ", summary).strip()
        items = re.findall(r"Item (\d+\.\d+)", summary)
        overlap = [i for i in items if i in TARGET_ITEMS]
        if not overlap:
            continue
        t_m = re.search(r"8-K - ([^(]+)", raw)
        company = t_m.group(1).strip() if t_m else "Unknown"
        cik_m = re.search(r"/data/(\d+)", entry)
        cik = cik_m.group(1).lstrip("0") if cik_m else None
        link_m = re.search(r'href="(https://www\.sec\.gov/Archives/edgar/data/[^"]+)"', entry)
        filing_url = link_m.group(1) if link_m else None
        results.append({"cik": cik, "company": company, "items": overlap, "summary": summary[:2000], "filing_url": filing_url})
    log(f"EDGAR entries: {len(entries)-1} | Qualifying: {len(results)}")
    return results


def resolve_tickers(filings):
    for f in filings:
        if not f.get("cik"):
            continue
        padded = f["cik"].zfill(10)
        try:
            r = requests.get(f"https://data.sec.gov/submissions/CIK{padded}.json", headers=EDGAR_HDR, timeout=10)
            if r.status_code == 200:
                tickers = r.json().get("tickers", [])
                if tickers:
                    f["ticker"] = tickers[0]
        except:
            pass
        time.sleep(0.12)
    return [f for f in filings if "ticker" in f]


def get_filing_text(filing_url):
    if not filing_url:
        return ""
    try:
        r = requests.get(filing_url, headers=EDGAR_HDR, timeout=15)
        if r.status_code != 200:
            return ""
        text = re.sub(r"<[^>]+>", " ", r.text)
        text = re.sub(r"\s+", " ", html.unescape(text))
        return text[:12000].strip()
    except:
        return ""


def get_filing_habit(cik):
    if not cik:
        return "routine", 999
    padded = cik.zfill(10)
    try:
        r = requests.get(f"https://data.sec.gov/submissions/CIK{padded}.json", headers=EDGAR_HDR, timeout=10)
        if r.status_code != 200:
            return "routine", 999
        dates = r.json().get("filings", {}).get("recent", {}).get("filingDate", [])
        cutoff = (date.today() - timedelta(days=30)).isoformat()
        count = sum(1 for d in dates if d >= cutoff)
        if count < 3:   return "rare", count
        elif count <= 8: return "medium", count
        else:            return "routine", count
    except:
        return "routine", 999


# ─── YAHOO FINANCE ───────────────────────────────────────────────────────────

def get_market_data(ticker_list):
    result = {}
    for t in ticker_list:
        try:
            tk = yf.Ticker(t)
            h = tk.history(period="5d", interval="1d")
            if h.empty:
                continue
            result[t] = {
                "price": float(h.iloc[-1]["Close"]),
                "prev":  float(h.iloc[-2]["Close"]) if len(h) > 1 else float(h.iloc[-1]["Close"]),
                "vol":   int(h.iloc[-1]["Volume"]),
            }
        except:
            pass
        time.sleep(0.05)
    return result


# ─── LLM GAUNTLET ───────────────────────────────────────────────────────────

OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")

GAUNTLET_PROMPT = """You are the STRANDTRADER event-driven trading system. Score this 8-K filing on 5 criteria (1-5 each, 5=best for BUY):

1. COVERAGE: Company recognition and analyst coverage (5=well-known SMID-cap, 1=unknown micro-cap)
2. NEWS_IMPACT: Genuine market-moving surprise? (5=surprise CEO exit/M&A, 1=routine filing)
3. DRIFT: 5-15 day directional move realistic? (5=yes clear catalyst, 1=no drift expected)
4. SIZING: $250 position appropriate? (5=liquid enough, 1=illiquid micro-cap)
5. STOP: 15% stop meaningful protection? (5=normal volatility, 1=extreme/noisy stock)

FILING:
Company: {company} | Ticker: {ticker} | Items: {items}
Summary: {summary}
Filing text: {filing_text}
Price: ${price:.2f} | Prev: ${prev:.2f} | Chg: {pct_change:+.1f}% | Vol: {volume:,}
8-Ks in past 30 days: {habit_count} ("{habit}")

DECISION:
- avg >= 3.0 AND news_impact >= 3 AND sizing >= 2 AND stop >= 2 → BUY
- avg >= 2.5 but not BUY criteria → WATCH
- else → SKIP

Return ONLY JSON (no markdown):
{{"scores":{{"coverage":N,"news_impact":N,"drift":N,"sizing":N,"stop":N}},"avg_score":N,"decision":"BUY|WATCH|SKIP","reasoning":"one sentence"}}
"""


def score_filing(filing, price, prev, vol, pct_change, habit, habit_count, filing_text):
    prompt = GAUNTLET_PROMPT.format(
        company=filing["company"],
        ticker=filing.get("ticker", "?"),
        items=", ".join(filing["items"]),
        summary=filing["summary"][:500],
        filing_text=filing_text[:1000] if filing_text else "[not available]",
        price=price, prev=prev,
        pct_change=pct_change,
        volume=vol,
        habit=habit,
        habit_count=habit_count,
    )
    if not OPENROUTER_KEY:
        return None

    from openai import OpenAI
    client = OpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1")
    try:
        resp = client.chat.completions.create(
            model="openrouter/minimax/minimax-m2.7",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())
        s = result.get("scores", {})
        avg = (s.get("coverage",0) + s.get("news_impact",0) + s.get("drift",0) +
               s.get("sizing",0) + s.get("stop",0)) / 5
        return {
            "scores": s,
            "avg_score": round(avg, 2),
            "decision": result.get("decision", "SKIP"),
            "reasoning": result.get("reasoning", ""),
        }
    except Exception as e:
        log(f"  LLM error: {e}")
        return None


# ─── RULE-BASED FALLBACK ─────────────────────────────────────────────────────

ITEM_SCORE = {"1.01": 4, "2.02": 2, "5.02": 5}

def rule_based_score(filing, price, vol, pct, habit):
    item_score = max([ITEM_SCORE.get(i, 1) for i in filing["items"]], default=1)
    surprise   = {"rare": 2, "medium": 1, "routine": 0}.get(habit, 0)
    sz  = 3 if vol >= 500_000 else (2 if vol >= 200_000 else 1)
    st  = 3 if vol >= 200_000 else 1
    avg = (item_score + surprise) / 5
    decision = "BUY" if (avg >= 3.0 and item_score >= 4 and sz >= 2 and st >= 2) else ("WATCH" if avg >= 2.5 else "SKIP")
    return {
        "scores": {"coverage": "?", "news_impact": item_score, "drift": "?", "sizing": sz, "stop": st},
        "avg_score": round(avg, 2),
        "decision": decision,
        "reasoning": f"item={item_score} surprise={surprise} vol={vol:,}",
    }


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    log(f"=== EDGAR SWEEP — {datetime.now().strftime('%Y-%m-%d %H:%M ET')} ===")

    portfolio = load_portfolio()
    existing = set(portfolio["positions"].keys())
    cash = portfolio.get("cash", 50000.0)
    log(f"Cash: ${cash:.2f} | Existing positions: {len(existing)}")

    if cash < MAX_POSITION:
        log("Insufficient cash.")
        return

    # 1. EDGAR filings
    filings = get_edgar_filings()
    if not filings:
        log("No qualifying filings.")
        return

    # 2. Resolve tickers
    filings = resolve_tickers(filings)
    filings = [f for f in filings if f["ticker"] not in existing]
    log(f"New tickers (not already held): {len(filings)}")

    # 3. Market data
    tickers = [f["ticker"] for f in filings]
    log(f"Fetching Yahoo Finance data for {len(tickers)} tickers...")
    mkt_data = get_market_data(tickers)
    log(f"Got data for {len(mkt_data)} tickers")

    # 4. Score each candidate
    candidates = []
    for f in filings:
        t = f.get("ticker")
        if t not in mkt_data:
            continue
        md = mkt_data[t]
        price = md["price"]
        prev  = md["prev"]
        vol   = md["vol"]
        pct   = (price - prev) / prev * 100 if prev else 0

        if price < MIN_PRICE:
            log(f"  SKIP {t}: price ${price:.2f} < ${MIN_PRICE}")
            continue
        if vol < MIN_VOLUME:
            log(f"  SKIP {t}: vol {vol:,} < {MIN_VOLUME:,}")
            continue
        if pct > 8:
            log(f"  SKIP {t}: already up {pct:.1f}%")
            continue

        habit, habit_count = get_filing_habit(f["cik"])
        log(f"  Scoring {t} | {f['company'][:40]} | habit={habit}({habit_count})...")

        filing_text = get_filing_text(f.get("filing_url"))
        result = score_filing(f, price, prev, vol, pct, habit, habit_count, filing_text)

        if not result:
            result = rule_based_score(f, price, vol, pct, habit)
            log(f"    → {result['decision']} (rule-based) | {result['reasoning'][:80]}")
        else:
            log(f"    → {result['decision']} | avg={result['avg_score']} | {result['reasoning'][:80]}")

        candidates.append({
            "ticker": t, "company": f["company"], "items": f["items"],
            "habit": habit, "habit_count": habit_count,
            "price": price, "pct_change": pct, "volume": vol,
            **result,
        })
        time.sleep(0.5)

    buys    = [c for c in candidates if c["decision"] == "BUY"]
    watches  = [c for c in candidates if c["decision"] == "WATCH"]
    buys.sort(key=lambda x: x["avg_score"], reverse=True)

    log(f"Candidates: BUY={len(buys)} | WATCH={len(watches)} | SKIP={len(candidates)-len(buys)-len(watches)}")
    print()
    print("=== BUY CANDIDATES ===")
    for c in buys:
        print(f"  {c['ticker']} | {c['company'][:50]} | score={c['avg_score']} | {c['reasoning'][:80]}")
    print()
    print("=== WATCH ===")
    for c in watches:
        print(f"  {c['ticker']} | {c['company'][:50]} | score={c['avg_score']}")

    # 5. Place simulated orders (write to local portfolio)
    orders_placed = []
    for c in buys[:MAX_ORDERS]:
        t   = c["ticker"]
        p   = c["price"]
        qty = max(1, int(MAX_POSITION / p))
        cost = qty * p
        if cost > cash:
            log(f"  SKIP {t}: ${cost:.2f} > cash ${cash:.2f}")
            continue
        add_position(t, qty, p)
        orders_placed.append(t)
        cash -= cost
        log(f"ORDER: {t} | {qty} sh @ ${p:.2f} | ~${cost:.2f} | ✅ added to portfolio")

    # Save report
    report = {
        "timestamp": datetime.now().isoformat(),
        "candidates": candidates,
        "orders_placed": orders_placed,
    }
    with open("/Users/eleanor/.openclaw/workspace-soros/strandtrader/last_sweep.json", "w") as f:
        json.dump(report, f, indent=2)

    log(f"=== DONE — {len(orders_placed)} positions added: {orders_placed} ===")


if __name__ == "__main__":
    main()
