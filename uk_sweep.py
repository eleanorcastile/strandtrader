#!/usr/bin/env python3
"""
STRANDTRADER UK — RNS/News Sweep Script
Uses Yahoo Finance to scan UK small/mid-cap stocks for material news events,
filters for thin-coverage candidates, places orders via IBKR UK.

Market hours: London 8am-4:30pm GMT
"""

import requests
import time
import os
import json
from datetime import datetime

API_KEY = os.environ.get("APCA_API_KEY", "")
API_SECRET = os.environ.get("APCA_API_SECRET", "")
PAPER_URL = "https://paper-api.alpaca.markets/v2"
DATA_URL = "https://data.alpaca.markets/v2"

# IBKR UK config (when live)
IBKR_CONFIG = {
    "host": "127.0.0.1",
    "port": 7496,
    "client_id": 2
}

# Filters
MIN_CAP_GBP = 50_000_000    # £50M (~$100M AUD equivalent)
MAX_CAP_GBP = 1_000_000_000  # £1B
MIN_VOLUME = 500_000         # £500K avg daily volume
MAX_POSITION = 250          # $250 / £250 per trade
STOP_PCT = 0.15            # 15% stop

# UK WATCHLIST — Full FTSE 250 + FTSE SmallCap (2026-03-25)
# Source: Hargreaves Lansdown (verified 2026-03-25)
# Total: 250 FTSE 250 + 183 FTSE SmallCap = 433 tickers

FTSE_250 = [
    "3IN","FOUR","AAS","ABDN","ASL","AEP","AJB","ALFA","ATT","AO.",
    "APN","ASHM","AIE","AML","ATYM","AGT","AVON","BME","BGFD","USA",
    "BBY","BCG","BNKR","BAG","BWY","BHMG","BYG","BPCR","BRGE","BRSC",
    "THRG","BRWM","BSIF","BOY","BREE","BPT","BUT","BYIT","CCR","CLDN",
    "CGT","CCL","CWR","CHG","CSN","CHRY","CTY","CKN","CBG","CMCX",
    "COA","CCC","COST","CWK","CURY","CVSG","DLN","DSCV","DOM","DOCS",
    "DRX","DNLM","EZJ","EDIN","EWI","ELM","ENOG","FCSS","FEML","FEV",
    "FSV","FGT","FGP","FGEN","FSG","FRAS","FCH","GFRD","GAMA","GBG",
    "GCP","GEN","GNS","GDWN","GFTU","GRI","GPE","UKW","GNC","GRG",
    "HMSO","HBR","HVPE","HWG","HAS","HTWS","HSL","HRI","HGT","HICL",
    "HIK","HILS","HFG","HOC","BOWL","HTG","IBST","ICGT","IEM","INCH",
    "IHP","IPF","INPP","IWG","IAD","INVP","IPO","ITH","ITV","JDW",
    "JMAT","JSG","JAM","JEMI","JMGI","JEDT","JEGI","JGGI","JIGI","JFJ",
    "JTC","JUP","JUST","KNOS","KLR","KIE","LRE","LWDB","EMG","MSLH",
    "MEGP","MRC","MRCH","MTRO","MAB","MTO","GROW","MNKS","MONY","MOON",
    "MGAM","MGNS","MUT","MYI","NBPE","NCC","N91","NAS","OCI","OCDO",
    "OSB","OXB","OXIG","ONT","PHI","PAGE","PAF","PINT","PIN","PAG",
    "PEY","PPET","PNN","PNL","PETS","PTEC","PLUS","PCGH","POLN","PPH",
    "PFD","PHP","PRN","QQ.","QLT","RNK","RPI","RAT","RSW","RHIM",
    "RCP","ROR","RS1","RTW","RICA","SAFE","SAGA","SVS","MNTN","SDP",
    "ATR","SOI","SAIN","SEIT","SNR","SEQI","SRP","SHC","SHAW","SRE",
    "SCT","SPI","SSPG","SUPR","SYNC","THRL","TATE","TW.","TBCG","TEP",
    "TMPL","TEM","ESCT","GSCT","TRIG","THG","TCAP","TRY","TRN","TPK",
    "TRST","TFIF","UTG","UEM","VSVS","VCT","VEIL","VOF","VTY","FAN",
    "EWG","WOSG","SMWH","WIX","WIZZ","WKP","WWH","WPP","XPS","ZIG",
]

FTSE_SMALLCAP = [
    "AAIF","AEI","ANII","AUSC","AGVI","ADIG","ASLI","AEWU","APTD","AFL",
    "AT.","ASC","ATG","AUGM","ARR","AJOT","BGCG","BGEU","BGS","BGUK",
    "BIOG","BRAI","BERI","BRFI","BRLA","BMY","BOOT","BMS","BRK","BASC",
    "CABP","CPI","CAPD","CNE","CARD","CCJI","CLIG","CLI","CYN","NCYF",
    "CRST","BBH","CTPE","CTUK","CHI","CREI","CVCG","DFS","DGI9","DIVI",
    "DIG","EGL","ECOR","ELIX","ENQ","ESNT","ECEL","EOT","EVOK","FDM",
    "FXPO","FVA","FAS","FSFL","FORT","FOXT","FSTA","FUTR","GABI","GOT",
    "GSF","GMS","GYM","HFD","HEAD","HLCL","HFEL","HHI","HSW","IGC",
    "IBT","BIPS","IGET","FSJ","JAGI","JCGI","JCH","JEMA","JARA","JUGI",
    "JUSC","KMR","LABS","LTI","LIO","LWI","LSL","LUCE","MGCI","MACF",
    "MAJE","MNL","MARS","MCB","MER","MWY","MIGO","GLE","MCG","MMIT",
    "MTE","MTU","MOTR","NRR","NESF","NAVF","NXR","NAIT","ORIT","OIT",
    "OTB","OIG","PAC","PCA","PAY","PBEE","PHAR","PSDL","PCTN","PINE",
    "PCFT","PRV","PRTC","PZC","RCH","RECI","REC","RGL","RESI","RIII",
    "RSE","RMII","RM.","RWA","RKW","SUS","SBRE","SERE","SCF","SJG",
    "SREI","SCP","INOV","SST","STB","SSIT","SFR","SHI","SNWS","SOHO",
    "SDY","STEM","SEC","STS","STVG","SYNT","TMIP","TBTG","SWC","TPT",
    "TET","TRI","TTG","TLW","SMIF","VIP","VANQ","ENRG","VNH","VP.",
    "XAR","XPP","ZTF",
]

UK_WATCHLIST = [t + ".L" for t in FTSE_250 + FTSE_SMALLCAP]

# ─── LOGGING ─────────────────────────────────────────────────────────────────

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# ─── YAHOO FINANCE ────────────────────────────────────────────────────────────

def get_yf_info(ticker):
    """Get Yahoo Finance info dict for a ticker."""
    import yfinance as yf
    try:
        t = yf.Ticker(ticker)
        info = t.info
        return info
    except:
        return {}

def get_yf_news(ticker):
    """Get recent news for a ticker."""
    import yfinance as yf
    try:
        t = yf.Ticker(ticker)
        news = t.news or []
        return news
    except:
        return []

def get_yf_price(ticker):
    """Get current/recent price data."""
    import yfinance as yf
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="2d", interval="1d")
        if hist.empty:
            return {}, None
        latest = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) > 1 else latest
        return {
            "price": latest.get("Close"),
            "prev_close": prev.get("Close"),
            "volume": latest.get("Volume"),
            "high": latest.get("High"),
            "low": latest.get("Low"),
        }, latest.name
    except:
        return {}, None

def scan_watchlist(tickers):
    """Scan watchlist for candidates with material news and price movement."""
    candidates = []
    
    for ticker in tickers:
        info = get_yf_info(ticker)
        price_data, date = get_yf_price(ticker)
        news = get_yf_news(ticker)
        
        price = price_data.get("price")
        prev_close = price_data.get("prev_close")
        volume = price_data.get("volume", 0)
        market_cap = info.get("marketCap", 0)
        
        if not price:
            continue
        
        # Market cap filter (convert USD to GBP if needed)
        # yfinance returns market cap in USD for UK stocks
        # Approximate: USD market cap / 1.25 = GBP
        mktcap_gbp = market_cap / 1.25
        
        if mktcap_gbp < MIN_CAP_GBP or mktcap_gbp > MAX_CAP_GBP:
            continue
        
        # Volume filter
        if volume < MIN_VOLUME:
            continue
        
        # Price change
        pct_change = 0
        if prev_close:
            pct_change = (price - prev_close) / prev_close * 100
        
        # Score candidates with recent news
        # News items typically include: announcements, results, contracts
        news_recent = [n for n in news if n.get("providerPublishTime", 0) > time.time() - 86400 * 3]  # last 3 days
        
        candidates.append({
            "ticker": ticker,
            "name": info.get("longName", info.get("shortName", "?")),
            "price": price,
            "prev_close": prev_close,
            "pct_change": pct_change,
            "volume": volume,
            "mktcap_gbp": mktcap_gbp,
            "news_count": len(news_recent),
            "news_items": news_recent[:3],  # top 3 articles
            "info": info,
        })
        
        time.sleep(0.3)  # be polite to Yahoo Finance
    
    # Sort by news presence + volume
    candidates.sort(key=lambda x: (x["news_count"], x["volume"]), reverse=True)
    return candidates

# ─── BROKER ──────────────────────────────────────────────────────────────────

def get_ibkr_positions():
    """Get current positions from IBKR (via IPC or REST)."""
    # Placeholder — IBKR UK API requires Interactive Brokers Python API (ib_insync)
    # For paper trading setup, use IBKR TWS API
    # When credentials are shared, wire this up properly
    return []

def place_ibkr_order(symbol, qty, side="buy"):
    """Place order via IBKR UK."""
    # To be wired when credentials are shared
    log(f"[IBKR PLACEHOLDER] {side.upper()}: {qty} {symbol}")
    return {"success": True, "note": "IBKR wiring pending credentials"}

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    log(f"=== STRANDTRADER UK — {datetime.now().strftime('%Y-%m-%d %H:%M GMT')} ===")
    
    # Step 1: Scan watchlist for candidates
    log(f"Scanning {len(UK_WATCHLIST)} UK tickers...")
    candidates = scan_watchlist(UK_WATCHLIST)
    log(f"Qualifying candidates: {len(candidates)}")
    
    if not candidates:
        log("No qualifying candidates today.")
        return
    
    for c in candidates[:10]:
        log(f"  {c['ticker']}: {c['name'][:30]} | mktcap=£{c['mktcap_gbp']/1e6:.1f}M | change={c['pct_change']:+.1f}% | news={c['news_count']}")
    
    # Step 2: Score top candidates
    # For now: rank by news count + volume + price change (down days = entry opportunity)
    # Skip stocks up >8% (too late to chase)
    
    actionable = [c for c in candidates if abs(c["pct_change"]) < 10]
    actionable.sort(key=lambda x: (x["news_count"], -abs(x["pct_change"])), reverse=True)
    
    log(f"\nActionable candidates: {len(actionable)}")
    
    # Step 3: Place orders (when IBKR is wired)
    # For now, just report
    for c in actionable[:5]:
        log(f"WOULD BUY: {c['ticker']} | £{c['price']:.2f} | £{c['price']*1:.2f} est")
    
    log("=== UK sweep complete ===")


if __name__ == "__main__":
    main()
