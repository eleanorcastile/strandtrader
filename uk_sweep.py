#!/usr/bin/env python3
"""
STRANDTRADER UK — RNS-Style Sweep Script
Uses Yahoo Finance as news source (covers RNS-announced events).
Scoring based on UK-specific event categories:
  - Contract wins / supply agreements
  - Trading updates / profit warnings
  - M&A activity (acquisitions, disposals)
  - Director dealings (buys/sells)
  - Regulatory approvals / licences
  - CEO changes / leadership
  - Fundraises (placing, subscription)

Market hours: London 8am-4:30pm GMT
Pre-market scan: 7:30am London = 5:30pm AEST
"""

import os, json, time, yfinance as yf
from datetime import datetime, timedelta

MAX_POSITION = 250       # £250 per trade
STOP_PCT = 0.15         # 15% stop-loss
MIN_VOLUME = 100_000    # 100K avg daily volume
MIN_PRICE = 1.00        # £1 minimum
MAX_ORDERS_PER_RUN = 5

# ── RNS-STYLE EVENT SCORING ─────────────────────────────────────────────────

# These replicate the categories that move UK small/mid caps via RNS
# Each event type has a base score and optional modifiers

RNS_CATEGORIES = {
    # Category: (base_score, keywords)
    # Keywords checked against news headline + summary
    "contract_win":      (6, [
        "contract", "supply agreement", "purchase order", "awarded",
        "framework", "strategic partnership", "preferred supplier",
        "significant contract", "major order", "contract worth",
    ]),
    "trading_update":    (5, [
        "trading update", "trading statement", "revenue", "profit",
        "outlook", "expects", "forecast", "performance review",
        "materially", "ahead of expectations", "in line",
        "second half", "full year", "annual results",
    ]),
    "acquisition":       (7, [
        "acquisition", "acquire", "acquires", "disposal", "sell",
        "merger", "combination", "recommended offer", "bid",
        "proposed acquisition", "subject to", "conditional",
    ]),
    "director_dealing":  (4, [
        "director", "chief executive", "cfo", "chair", "ceo",
        "purchase", "acquisition", "buy", "sell", "dispose",
        "market purchase", "placing", "subscribe",
    ]),
    "regulatory":        (5, [
        "approval", "approved", "regulatory", "fda", "mhra",
        "licence", "license", "clearance", "notified",
        "authorisation", "marketing authorisation", "ce mark",
    ]),
    "fundraise":         (4, [
        "placing", "subscription", "fundraise", "fundraising",
        "equity raise", "capital raise", "issue of shares",
        "open offer", "rights issue", "broker placing",
    ]),
    "partnership":       (4, [
        "partnership", "joint venture", "collaboration",
        "distribution agreement", "licensing agreement",
        "strategic", "co-development", "co-promotion",
    ]),
    "leadership":        (3, [
        "appoints", "appointed", "ceo", "chairman", "director",
        "chief financial", "chief operating", "board",
        "resignation", "step down", "new hire",
    ]),
    "operational":       (2, [
        "facility", "expansion", "new site", "manufacturing",
        "commercial launch", "product launch", "first sale",
        "site acquired", " commences", "operational",
    ]),
}

# Event modifiers
SURPRISE_BONUS = 3      # awarded to rare/surprise events
VOLUME_SPIKE_BONUS = 2  # awarded if volume > 3x avg
PRICE_MOVE_BONUS = 2    # awarded if stock moved > 5% on news


def score_event(headline, summary, price_move_pct, volume_ratio):
    """
    Score a news event based on category keywords + modifiers.
    Headline matches score higher than body/description matches.
    """
    text_lower = ((headline or "") + " " + (summary or "")).lower()
    headline_lower = (headline or "").lower()

    best_score = 0
    best_cat = None
    best_keywords = []

    for category, (base_score, keywords) in RNS_CATEGORIES.items():
        # Count headline matches (weighted 3x) vs body matches
        hl_matches = [kw for kw in keywords if kw in headline_lower]
        body_matches = [kw for kw in keywords if kw in text_lower and kw not in headline_lower]
        total_matches = len(hl_matches) + len(body_matches)

        if total_matches > 0:
            # Headline match = 3 points each, body match = 1 point each
            score = base_score + len(hl_matches) * 3 + len(body_matches) * 1
            if score > best_score:
                best_score = score
                best_cat = category
                best_keywords = hl_matches[:3] or body_matches[:2]

    if best_score == 0:
        return 0, None, None

    detail = f"{best_cat}" + (f" ({', '.join(best_keywords)})" if best_keywords else "")
    return best_score, best_cat, detail


def get_news_for_ticker(ticker):
    """Get recent news for a ticker via Yahoo Finance."""
    try:
        tk = yf.Ticker(ticker)
        raw = tk.news
        if not raw or not isinstance(raw, list):
            return []
        results = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            # Yahoo Finance nests data under 'content' key
            content = item.get("content", item)
            if not isinstance(content, dict):
                continue
            title = content.get("title", "") or ""
            description = content.get("description", "") or ""
            summary = content.get("summary", "") or ""
            pub_str = content.get("pubDate", "") or content.get("displayTime", "") or ""
            results.append({
                "title": title,
                "description": description,
                "summary": summary,
                "pubDate": pub_str,
            })
        return results
    except Exception:
        return []


def get_price_data(ticker):
    """Get current price, previous close, and avg volume."""
    try:
        tk = yf.Ticker(ticker)
        h = tk.history(period="5d")
        if h.empty or len(h) < 2:
            return None, None, None, None
        cur = float(h.iloc[-1]["Close"])
        prev = float(h.iloc[-2]["Close"])
        vol = int(h["Volume"].iloc[-1]) if "Volume" in h.columns else 0
        # 20-day avg volume approximation
        avg_vol = int(h["Volume"].mean()) if "Volume" in h.columns else vol
        day_chg_pct = ((cur - prev) / prev * 100) if prev else 0
        return cur, prev, day_chg_pct, max(vol, avg_vol)
    except:
        return None, None, None, None


def scan_ticker(ticker):
    """
    Scan a single ticker. Returns a candidate dict if score >= threshold.
    """
    price, prev_close, day_chg, avg_vol = get_price_data(ticker)
    if not price or price < MIN_PRICE:
        return None
    if price > 100:  # Skip stocks > £100 (too expensive for £250 budget)
        return None
    if avg_vol and avg_vol < MIN_VOLUME:
        return None

    news = get_news_for_ticker(ticker)
    cutoff = time.time() - 120 * 3600  # last 5 days (broader for UK RNS)
    recent = []
    for n in news:
        pub_str = n.get("pubDate", "")
        if not pub_str:
            continue
        try:
            pub_ts = datetime.fromisoformat(pub_str.replace("Z", "+0000")).timestamp()
            if pub_ts > cutoff:
                recent.append(n)
        except:
            recent.append(n)

    if not recent:
        return None

    # Score each news item, take the best score
    best = {"score": 0, "category": None, "detail": None, "headline": None}

    for item in recent:
        headline = item.get("title", "")
        summary = item.get("summary", "")
        # Try to get additional context
        extra = ""
        try:
            related = item.get("related", [])
            if related:
                extra = " ".join(str(r) for r in related)
        except:
            pass

        score, cat, detail = score_event(
            headline, summary + " " + extra,
            day_chg,
            None  # volume_ratio only available with broader context
        )

        if score > best["score"]:
            best = {"score": score, "category": cat, "detail": detail, "headline": headline}

    if best["score"] < 6:
        return None

    # Get market cap
    try:
        info = yf.Ticker(ticker).info
        mktcap = info.get("marketCap", 0) or 0
        name = info.get("shortName", info.get("longName", ticker))
    except:
        mktcap = 0
        name = ticker

    # Volume ratio
    vol_ratio = None
    try:
        h = yf.Ticker(ticker).history(period="10d")
        if not h.empty and "Volume" in h.columns:
            recent_vol = h["Volume"].iloc[-1]
            avg_vol_long = h["Volume"].mean()
            if avg_vol_long > 0:
                vol_ratio = recent_vol / avg_vol_long
    except:
        pass

    return {
        "ticker": ticker,
        "name": name,
        "price": price,
        "prev_close": prev_close,
        "day_chg_pct": round(day_chg, 2) if day_chg else 0,
        "avg_volume": avg_vol,
        "vol_ratio": round(vol_ratio, 1) if vol_ratio else 1.0,
        "mktcap_gbp": round(mktcap / 1.25, 0) if mktcap else 0,  # rough USD→GBP
        "score": best["score"],
        "category": best["category"],
        "detail": best["detail"],
        "headline": best["headline"],
        "news_count": len(recent),
    }


def scan_watchlist(tickers, max_workers=10):
    """
    Scan all watchlist tickers. Returns sorted list of candidates.
    """
    from concurrent.futures import ThreadPoolExecutor

    results = []
    total = len(tickers)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(scan_ticker, t): t for t in tickers}
        done = 0
        for f in futures:
            r = f.result()
            done += 1
            if done % 50 == 0:
                print(f"  Scanned {done}/{total}...")
            if r:
                results.append(r)
            time.sleep(0.15)  # rate limit to avoid Yahoo Finance throttling

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def position_size(price, cash=50000):
    """
    Calculate share quantity and cost.
    £250 per trade. Skip if price > £250 (too expensive for meaningful position).
    """
    if price <= 0 or price > MAX_POSITION:
        return 0, 0
    qty = int(MAX_POSITION / price)
    return qty, round(qty * price, 2)


# ─── PORTFOLIO MANAGEMENT ───────────────────────────────────────────────────

PORTFOLIO_FILE = os.path.join(os.path.dirname(__file__), "portfolio.json")
HISTORY_FILE = os.path.join(os.path.dirname(__file__), "trade_history.json")


def load_portfolio():
    try:
        with open(PORTFOLIO_FILE) as f:
            return json.load(f)
    except:
        return {"positions": {}, "cash": 50000.0, "currency": "GBP"}


def save_portfolio(data):
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_history():
    try:
        with open(HISTORY_FILE) as f:
            return json.load(f)
    except:
        return {"trades": [], "summary": {"wins": 0, "losses": 0}}


def save_history(data):
    with open(HISTORY_FILE, "w") as f:
        json.dump(data, f, indent=2)


def already_held(ticker, portfolio):
    return ticker in portfolio.get("positions", {})


# ─── MAIN SWEEP ─────────────────────────────────────────────────────────────

def run_sweep():
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from watchlist import WATCHLIST as UK_WATCHLIST

    now = datetime.now()
    london_hour = int(now.strftime("%H"))  # approximate

    print(f"\n{'='*60}")
    print(f"STRANDTRADER UK — RNS Sweep")
    print(f"Time: {now.strftime('%A %d/%m/%Y %H:%M')} AEST")
    print(f"London approximate: {now.strftime('%H:%M')}")
    print(f"Scanning {len(UK_WATCHLIST)} tickers...")
    print(f"{'='*60}\n")

    candidates = scan_watchlist(UK_WATCHLIST)

    portfolio = load_portfolio()
    history = load_history()

    open_tickers = set(portfolio.get("positions", {}).keys())
    max_new = MAX_ORDERS_PER_RUN - len(open_tickers)

    print(f"\n📊 CANDIDATES (score >= 6)")
    print(f"{'Ticker':8} {'Score':5} {'Cat':15} {'Price':8} {'Day%':6} {'VolR':5} {'Headline'}")
    print("-" * 90)

    for c in candidates[:20]:
        cat = (c["category"] or "").replace("_", " ")[:15]
        headline = (c["headline"] or "")[:45]
        print(
            f"{c['ticker']:8} "
            f"{c['score']:5} "
            f"{cat:15} "
            f"£{c['price']:7.3f} "
            f"{c['day_chg_pct']:+.1f}% "
            f"{c['vol_ratio']:.1f}x "
            f"{headline}"
        )

    # Filter to new positions only
    new_candidates = [c for c in candidates if not already_held(c["ticker"], portfolio)]
    buys = new_candidates[:max_new]

    print(f"\n📋 ORDERS (new positions only, max {MAX_ORDERS_PER_RUN})")
    if not buys:
        print("No new signals.")
    else:
        for b in buys:
            qty, cost = position_size(b["price"])

            # Skip if qty = 0 or cost > available cash
            if qty == 0 or cost > portfolio["cash"]:
                print(f"  SKIP {b['ticker']:8} — price £{b['price']:.2f} exceeds budget (qty={qty})")
                continue

            portfolio["cash"] -= cost
            portfolio["positions"][b["ticker"]] = {
                "qty": qty,
                "entry_price": b["price"],
                "date_added": now.isoformat(),
                "stop": round(b["price"] * (1 - STOP_PCT), 3),
                "score": b["score"],
                "category": b["category"],
                "thesis": b["detail"],
            }

            print(
                f"  BUY  {b['ticker']:8} "
                f"£{b['price']:.3f} x {qty} shares = £{cost:.2f} | "
                f"stop £{b['price']*(1-STOP_PCT):.3f} | "
                f"score {b['score']} {b['category']}"
            )

        save_portfolio(portfolio)

    print(f"\nPortfolio: {len(portfolio['positions'])} open positions")
    print(f"Cash: £{portfolio['cash']:,.2f} / £50,000.00")
    print(f"\nDone: {now.strftime('%H:%M:%S')}")

    return candidates


if __name__ == "__main__":
    run_sweep()
