import os, json, time, yfinance as yf
from pathlib import Path
from datetime import datetime
import pytz
from flask import Flask

app = Flask(__name__)
BASE = Path(__file__).parent
HTML_TEMPLATE = (BASE / "index.html").read_text(encoding="utf-8")

def get_fx():
    """Returns (USD_to_AUD, GBP_to_AUD) conversion rates."""
    try:
        a = yf.Ticker("AUDUSD=X").history(period="1d", interval="1d")
        g = yf.Ticker("GBPAUD=X").history(period="1d", interval="1d")
        audusd = float(a.iloc[-1]["Close"]) if not a.empty else 0.77
        gbpaud = float(g.iloc[-1]["Close"]) if not g.empty else 0.52
        # GBPAUD = price of 1 AUD in GBP. GBP to AUD = 1 / GBPAUD
        return round(1/audusd, 4), round(gbpaud, 4)
    except:
        return 1.30, 1.92  # fallback: USD→AUD, GBP→AUD
        return 1.56, 1.92

def get_price(ticker):
    try:
        tk = yf.Ticker(ticker)
        h = tk.history(period="5d", interval="1d")
        if h.empty or len(h) < 2:
            return None
        return {"price": float(h.iloc[-1]["Close"]), "prev": float(h.iloc[-2]["Close"])}
    except:
        return None


def get_day_pct(ticker):
    """Returns (day_pct_str, color) e.g. ('+1.23%', '#2ecc71')"""
    try:
        tk = yf.Ticker(ticker)
        h = tk.history(period="5d", interval="1d")
        if h.empty or len(h) < 2:
            return "N/A", "#8b949e"
        cur  = float(h.iloc[-1]["Close"])
        prev = float(h.iloc[-2]["Close"])
        pct  = (cur - prev) / prev * 100 if prev else 0
        sign = "+" if pct >= 0 else ""
        color = "#2ecc71" if pct > 0 else ("#e74c3c" if pct < 0 else "#8b949e")
        return f"{sign}{pct:.2f}%", color
    except Exception:
        return "N/A", "#8b949e"

def fmt_date(s):
    if not s:
        return "—"
    try:
        s2 = s.replace("+11:00", "+1100").replace("+10:00", "+1000").replace("Z", "+0000")
        dt = datetime.fromisoformat(s2)
        return dt.strftime("%d/%m/%y")
    except:
        return str(s)[:10]

def enrich(positions):
    result = []
    for ticker, pos in positions.items():
        md = get_price(ticker)
        if md is None:
            md = {"price": pos.get("entry_price", 0), "prev": pos.get("entry_price", 0)}
        cur = md["price"]
        ent = pos.get("entry_price", cur)
        qty = pos.get("qty", 0)
        cost = ent * qty
        val = cur * qty
        pnl = val - cost
        pnl_pct = (cur - ent) / ent * 100 if ent else 0
        day = (cur - md["prev"]) / md["prev"] * 100 if md["prev"] else 0
        result.append({
            "ticker": ticker,
            "qty": qty,
            "entry": ent,
            "current": round(cur, 4),
            "cost": round(cost, 2),
            "value": round(val, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "day": round(day, 2),
            "date": pos.get("date_added", "")
        })
        time.sleep(0.05)
    return result

def load_json(name, fallback=None):
    try:
        with open(BASE / name) as f:
            return json.load(f)
    except:
        return fallback if fallback is not None else {}

def fmt_money(val, currency="$", pnl=False):
    """Format money. 
    USD: $50.00, -$50.00, +$50.00
    GBP: £50.00, -£50.00, +£50.00  
    AUD: AUD $50.00, AUD -$50.00, AUD +$50.00
    """
    if abs(val) < 0.005:
        val = 0.0
    # Determine sign
    if val < 0:
        sign = "-"
    elif pnl and val >= 0:
        sign = "+"
    else:
        sign = ""
    # For AUD $xxx format: sign goes after currency (AUD -$12.71)
    if currency.startswith("AUD") and sign:
        return f"AUD {sign}${abs(val):,.2f}"
    return f"{sign}{currency}{abs(val):,.2f}"


def fmt_pct(val, pnl=False):
    """Format percentage. Examples: 5.2%, -5.2%, +5.2% (for P&L)."""
    if abs(val) < 0.05:
        val = 0.0
    if val < 0:
        return f"-{abs(val):,.1f}%"
    if pnl and val >= 0:
        return f"+{val:,.1f}%"
    return f"{val:,.1f}%"

def open_row(p, currency="$"):
    pnl = p["pnl"]
    pnl_color = "#2ecc71" if pnl > 0 else ("#e74c3c" if pnl < 0 else "#8b949e")
    
    day_val = p.get("day", 0)
    day_color = "#2ecc71" if day_val > 0 else ("#e74c3c" if day_val < 0 else "#8b949e")
    pnl_pct = p.get("pnl_pct", 0)
    pnl_pct_color = "#2ecc71" if pnl_pct > 0 else ("#e74c3c" if pnl_pct < 0 else "#8b949e")
    if pnl > 0:
        arrow = '<span style="color:#2ecc71;font-weight:bold">&#9650;</span>'
    elif pnl < 0:
        arrow = '<span style="color:#e74c3c;font-weight:bold">&#9660;</span>'
    else:
        arrow = '<span style="color:#e6edf3">&#9654;</span>'
    return (
        f"<tr>"
        f"<td>{arrow} <strong>{p['ticker']}</strong></td>"
        f"<td>{p['qty']}</td>"
        f"<td>{fmt_money(p['entry'], currency)}</td>"
        f"<td>{fmt_money(p['current'], currency)}</td>"
        f"<td>{fmt_money(p['cost'], currency)}</td>"
        f"<td>{fmt_money(p['value'], currency)}</td>"
        f"<td style='color:{pnl_color}'><strong>{fmt_money(pnl, currency, pnl=True)}</strong></td>"
        f"<td style='color:{pnl_pct_color}'>{fmt_pct(pnl_pct, pnl=True)}</td>"
        f"<td style='color:{day_color}'>{fmt_pct(day_val, pnl=True)}</td>"
        f"<td>{fmt_date(p.get('date', ''))}</td>"
        f"<td>—</td>"
        f"</tr>"
    )

def closed_row(trade, currency="$"):
    t = trade
    pnl = t.get("pnl", 0)
    pnl_color = "#2ecc71" if pnl > 0 else ("#e74c3c" if pnl < 0 else "#8b949e")
    pnl_pct = t.get("pnl_pct", 0)
    pnl_pct_color = "#2ecc71" if pnl_pct > 0 else ("#e74c3c" if pnl_pct < 0 else "#8b949e")
    emoji = "&#128994;" if pnl > 0 else "&#128308;" if pnl < 0 else "&#9898;"
    return (
        f"<tr class='closed-row'>"
        f"<td>{emoji} <strong>{t.get('ticker','')}</strong></td>"
        f"<td>{t.get('qty', 0)}</td>"
        f"<td>{fmt_money(t.get('entry_price', t.get('entry', 0)), currency)}</td>"
        f"<td>{fmt_money(t.get('exit_price', t.get('exit', 0)), currency)}</td>"
        f"<td>{fmt_money(t.get('cost_basis', t.get('cost', 0)), currency)}</td>"
        f"<td>{fmt_money(t.get('proceeds', 0), currency)}</td>"
        f"<td style='color:{pnl_color}'><strong>{fmt_money(pnl, currency, pnl=True)}</strong></td>"
        f"<td style='color:{pnl_pct_color}'>{fmt_pct(pnl_pct, pnl=True)}</td>"
        f"<td style='color:#e6edf3'>—</td>"
        f"<td>{fmt_date(t.get('opened', ''))}</td>"
        f"<td>{fmt_date(t.get('closed', ''))}</td>"
        f"</tr>"
    )

def open_rows(positions, currency="$"):
    if not positions:
        return "<tr><td colspan='11' style='color:#8b949e;text-align:center;padding:20px'>No positions</td></tr>"
    return "".join(open_row(p, currency) for p in positions)

def closed_rows(trades, currency="$"):
    if not trades:
        return "<tr><td colspan='11' style='color:#8b949e;text-align:center;padding:20px'>No closed trades</td></tr>"
    return "".join(closed_row(t, currency) for t in trades)

@app.route("/")
def index():
    us_portfolio = load_json("us_portfolio.json", {"positions": {}, "cash": 50000})
    us_history   = load_json("us_history.json", {"trades": [], "summary": {"wins": 0, "losses": 0}})
    uk_portfolio = load_json("uk_portfolio.json", {"positions": {}, "cash": 50000})
    uk_history   = load_json("uk_history.json", {"trades": [], "summary": {"wins": 0, "losses": 0}})
    au_portfolio = load_json("au_portfolio.json", {"positions": {}, "cash": 50000, "currency": "AUD"})
    au_history   = load_json("au_history.json", {"trades": [], "summary": {"wins": 0, "losses": 0}})

    USD, GBP = get_fx()
    us_enr = enrich(us_portfolio.get("positions", {}))
    uk_enr = enrich(uk_portfolio.get("positions", {}))
    au_enr = enrich(au_portfolio.get("positions", {}))

    us_deployed = sum(p["cost"] for p in us_enr)
    uk_deployed = sum(p["cost"] for p in uk_enr)
    au_deployed = sum(p["cost"] for p in au_enr)
    us_upnl = sum(p["pnl"] for p in us_enr)
    uk_upnl = sum(p["pnl"] for p in uk_enr)
    au_upnl = sum(p["pnl"] for p in au_enr)
    us_rpnl = sum(t["pnl"] for t in us_history.get("trades", []))
    uk_rpnl = sum(t["pnl"] for t in uk_history.get("trades", []))
    au_rpnl = sum(t["pnl"] for t in au_history.get("trades", []))

    total_deployed = us_deployed * USD + uk_deployed * GBP + au_deployed * AUD
    total_pnl = (us_upnl + us_rpnl) * USD + (uk_upnl + uk_rpnl) * GBP + (au_upnl + au_rpnl) * AUD
    total_ret = (total_pnl / total_deployed * 100) if total_deployed else 0

    uw = us_history.get("summary", {}).get("wins", 0)
    ul = us_history.get("summary", {}).get("losses", 0)
    kw = uk_history.get("summary", {}).get("wins", 0)
    kl = uk_history.get("summary", {}).get("losses", 0)
    aw = au_history.get("summary", {}).get("wins", 0)
    al = au_history.get("summary", {}).get("losses", 0)
    tw, tl = uw + kw + aw, ul + kl + al
    wr_pct = round(tw / (tw + tl) * 100) if (tw + tl) > 0 else 0

    ts = datetime.now(pytz.timezone("Australia/Sydney")).strftime("%A, %d/%m/%Y %H:%M")

    html = HTML_TEMPLATE
    html = html.replace("{{timestamp}}", ts)
    html = html.replace("{{comb_deployed}}", fmt_money(total_deployed, "AUD $"))
    html = html.replace("{{comb_pnl}}", fmt_money(total_pnl, "AUD $", pnl=True))
    html = html.replace("{{comb_ret}}", fmt_pct(total_ret, pnl=True))
    html = html.replace("{{comb_wr}}", "{}% ({}W / {}L)".format(wr_pct, tw, tl))
    html = html.replace("{{comb_pnl_color}}", "#2ecc71" if total_pnl > 0 else ("#e74c3c" if total_pnl < 0 else "#8b949e"))
    html = html.replace("{{comb_ret_color}}", "#2ecc71" if total_ret > 0 else ("#e74c3c" if total_ret < 0 else "#8b949e"))
    html = html.replace("{{comb_wr_color}}", "#2ecc71" if wr_pct >= 50 else ("#e74c3c" if (tw+tl) > 0 else "#e6edf3"))

    us_upnl_pct = (us_upnl / us_deployed * 100) if us_deployed else 0
    us_wr_pct = round(uw / (uw + ul) * 100) if (uw + ul) > 0 else 0
    html = html.replace("{{us_cash}}", fmt_money(50000 - us_deployed, "$"))
    html = html.replace("{{us_deployed}}", fmt_money(us_deployed, "$"))
    html = html.replace("{{us_upnl}}", "{} ({})".format(fmt_money(us_upnl, "$", pnl=True), fmt_pct(us_upnl_pct, pnl=True)))
    html = html.replace("{{us_upnl_color}}", "#2ecc71" if us_upnl > 0 else ("#e74c3c" if us_upnl < 0 else "#8b949e"))
    html = html.replace("{{us_rpnl_color}}", "#2ecc71" if us_rpnl > 0 else ("#e74c3c" if us_rpnl < 0 else "#8b949e"))

    # ── Index Day % ─────────────────────────────────────────────────────
    rut_day,     rut_color      = get_day_pct("^RUT")
    sp600_day,   sp600_color    = get_day_pct("^SP600")
    ftse250_day, ftse250_color  = get_day_pct("^FTMC")
    ftsesc_day,  ftsesc_color   = get_day_pct("^FTSC")
    asx200_day,  asx200_color  = get_day_pct("^AXTJ")
    allords_day,  allords_color  = get_day_pct("^AORD")
    # ─────────────────────────────────────────────────────────────────────

    
    html = html.replace("{{us_rpnl}}", fmt_money(us_rpnl, "$", pnl=True))
    html = html.replace("{{us_wr}}", "{}% ({}W / {}L)".format(us_wr_pct, uw, ul))
    html = html.replace("{{us_wr_color}}", "#2ecc71" if us_wr_pct >= 50 else ("#e74c3c" if (uw+ul) > 0 else "#e6edf3"))

    html = html.replace("{{rut_day}}",        rut_day)
    html = html.replace("{{rut_color}}",      rut_color)
    html = html.replace("{{sp600_day}}",       sp600_day)
    html = html.replace("{{sp600_color}}",   sp600_color)
    html = html.replace("{{ftse250_day}}",    ftse250_day)
    html = html.replace("{{ftse250_color}}", ftse250_color)
    html = html.replace("{{ftsesc_day}}",     ftsesc_day)
    html = html.replace("{{ftsesc_color}}",  ftsesc_color)

    

    uk_upnl_pct = (uk_upnl / uk_deployed * 100) if uk_deployed else 0
    uk_wr_pct = round(kw / (kw + kl) * 100) if (kw + kl) > 0 else 0
    html = html.replace("{{uk_cash}}", fmt_money(50000 - uk_deployed, "£"))
    html = html.replace("{{uk_deployed}}", fmt_money(uk_deployed, "£"))
    html = html.replace("{{uk_upnl}}", "{} ({})".format(fmt_money(uk_upnl, "£", pnl=True), fmt_pct(uk_upnl_pct, pnl=True)))
    html = html.replace("{{uk_upnl_color}}", "#2ecc71" if uk_upnl > 0 else ("#e74c3c" if uk_upnl < 0 else "#8b949e"))
    html = html.replace("{{uk_rpnl_color}}", "#2ecc71" if uk_rpnl > 0 else ("#e74c3c" if uk_rpnl < 0 else "#8b949e"))
    html = html.replace("{{uk_rpnl}}", fmt_money(uk_rpnl, "£", pnl=True))
    html = html.replace("{{uk_wr}}", "{}% ({}W / {}L)".format(uk_wr_pct, kw, kl))
    html = html.replace("{{uk_wr_color}}", "#2ecc71" if uk_wr_pct >= 50 else ("#e74c3c" if (kw+kl) > 0 else "#e6edf3"))

    html = html.replace("{{us_open_rows}}", open_rows(sorted(us_enr, key=lambda p: p["pnl"], reverse=True), "$"))
    html = html.replace("{{uk_open_rows}}", open_rows(sorted(uk_enr, key=lambda p: p["pnl"], reverse=True), "\u00a3"))
    html = html.replace("{{us_closed_rows}}", closed_rows(us_history.get("trades", []), "$"))
    html = html.replace("{{uk_closed_rows}}", closed_rows(uk_history.get("trades", []), "\u00a3"))

    return html

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
