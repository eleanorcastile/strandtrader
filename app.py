import os, json, time, yfinance as yf
from pathlib import Path
from datetime import datetime
from flask import Flask, jsonify

app = Flask(__name__)
BASE = Path(__file__).parent
HTML_TEMPLATE = (BASE / "index.html").read_text(encoding="utf-8")

def get_fx():
    try:
        a = yf.Ticker("AUDUSD=X").history(period="1d", interval="1d")
        g = yf.Ticker("GBPAUD=X").history(period="1d", interval="1d")
        audusd = float(a.iloc[-1]["Close"]) if not a.empty else 0.77
        gbpaud = float(g.iloc[-1]["Close"]) if not g.empty else 0.52
        return round(1/audusd, 4), round(1/gbpaud, 4)
    except:
        return 1.56, 1.92

def get_price(ticker):
    try:
        tk = yf.Ticker(ticker)
        h = tk.history(period="5d", interval="1d")
        if h.empty or len(h) < 2: return None
        return {"price": float(h.iloc[-1]["Close"]), "prev": float(h.iloc[-2]["Close"])}
    except:
        return None

def enrich(positions):
    result = []
    for ticker, pos in positions.items():
        md = get_price(ticker)
        if md is None:
            md = {"price": pos.get("entry_price", 0), "prev": pos.get("entry_price", 0)}
        cur = md["price"]; ent = pos.get("entry_price", cur)
        qty = pos.get("qty", 0); cost = ent*qty; val = cur*qty
        pnl = val - cost
        pnl_pct = (cur-ent)/ent*100 if ent else 0
        day = (cur-md["prev"])/md["prev"]*100 if md["prev"] else 0
        result.append({
            "ticker": ticker, "qty": qty, "entry": ent, "current": round(cur, 4),
            "cost": round(cost, 2), "value": round(val, 2), "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2), "day": round(day, 2),
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

def row_html(p, currency="$", is_closed=False):
    pnl = p["pnl"]
    pnl_color = "#2ecc71" if pnl >= 0 else "#e74c3c"
    pnl_sign = "+" if pnl >= 0 else ""
    day_val = p.get("day") if not is_closed else 0
    day_color = "#2ecc71" if day_val >= 0 else "#e74c3c" if day_val else "#e6edf3"
    pnl_pct = p.get("pnl_pct", 0)
    pnl_pct_color = "#2ecc71" if pnl_pct >= 0 else "#e74c3c"
    if is_closed:
        emoji = "&#128994;" if pnl > 0 else "&#128308;" if pnl < 0 else "&#9898;"
        row_class = " class='closed-row'"
    else:
        emoji = ('<span style="color:#2ecc71;font-weight:bold">&#9650;</span>' if pnl > 0
                 else '<span style="color:#e74c3c;font-weight:bold">&#9660;</span>' if pnl < 0
                 else '<span style="color:#e6edf3">&#9654;</span>')
        row_class = ""
    current_or_exit = p.get("current") if not is_closed else p.get("exit", 0)
    value_or_proc = p.get("value") if not is_closed else p.get("proceeds", 0)
    return (
        f"<tr{row_class}>"
        f"<td>{emoji} <strong>{p['ticker']}</strong></td>"
        f"<td>{p.get('qty', 0)}</td>"
        f"<td>{currency}{p['entry']:.2f}</td>"
        f"<td>{currency}{(current_or_exit or 0):.2f}</td>"
        f"<td>{currency}{p.get('cost', 0):.2f}</td>"
        f"<td>{currency}{(value_or_proc or 0):.2f}</td>"
        f"<td style='color:{pnl_color}'><strong>{pnl_sign}{pnl:.2f}</strong></td>"
        f"<td style='color:{pnl_pct_color}'>{pnl_pct:.1f}%</td>"
        f"<td style='color:{day_color}'>{p.get('day', 0):.1f}%</td>"
        f"<td>{p.get('date', '') or '—'}</td>"
        f"<td>{p.get('closed_date', '') or '—'}</td>"
        f"</tr>"
    )

def closed_row(trade, currency="$"):
    t = trade
    pnl = t.get("pnl", 0)
    pnl_color = "#2ecc71" if pnl >= 0 else "#e74c3c"
    pnl_sign = "+" if pnl >= 0 else ""
    pnl_pct = t.get("pnl_pct", 0)
    pnl_pct_color = "#2ecc71" if pnl_pct >= 0 else "#e74c3c"
    emoji = "&#128994;" if pnl > 0 else "&#128308;" if pnl < 0 else "&#9898;"
    return (
        f"<tr class='closed-row'>"
        f"<td>{emoji} <strong>{t.get('ticker','')}</strong></td>"
        f"<td>{t.get('qty', 0)}</td>"
        f"<td>{currency}{t.get('entry_price', t.get('entry', 0)):.2f}</td>"
        f"<td>{currency}{t.get('exit_price', t.get('exit', 0)):.2f}</td>"
        f"<td>{currency}{t.get('cost_basis', t.get('cost', 0)):.2f}</td>"
        f"<td>{currency}{t.get('proceeds', 0):.2f}</td>"
        f"<td style='color:{pnl_color}'><strong>{pnl_sign}{pnl:.2f}</strong></td>"
        f"<td style='color:{pnl_pct_color}'>{pnl_pct:.1f}%</td>"
        f"<td style='color:#e6edf3'>—</td>"
        f"<td>{t.get('opened', '—')}</td>"
        f"<td>{t.get('closed', '—')}</td>"
        f"</tr>"
    )

def closed_rows(trades, currency="$"):
    if not trades:
        return "<tr><td colspan='11' style='color:#8b949e;text-align:center;padding:20px'>No closed trades</td></tr>"
    return "".join(closed_row(t, currency) for t in trades)

def open_rows(positions, currency="$"):
    if not positions:
        return "<tr><td colspan='11' style='color:#8b949e;text-align:center;padding:20px'>No positions</td></tr>"
    return "".join(row_html(p, currency=currency) for p in positions)

def stat_val(v, currency="$"):
    color = "#2ecc71" if v >= 0 else "#e74c3c"
    sign = "+" if v >= 0 else ""
    return f"<span class='stat-value' style='color:{color}'>{currency}{sign}{v:.2f}</span>"

@app.route("/")
def index():
    us_portfolio = load_json("us_portfolio.json", {"positions": {}, "cash": 50000})
    us_history   = load_json("us_history.json", {"trades": [], "summary": {"wins": 0, "losses": 0}})
    uk_portfolio = load_json("uk_portfolio.json", {"positions": {}, "cash": 50000})
    uk_history   = load_json("uk_history.json", {"trades": [], "summary": {"wins": 0, "losses": 0}})

    USD, GBP = get_fx()
    us_enr = enrich(us_portfolio.get("positions", {}))
    uk_enr = enrich(uk_portfolio.get("positions", {}))

    us_deployed = sum(p["cost"] for p in us_enr)
    uk_deployed = sum(p["cost"] for p in uk_enr)
    us_upnl = sum(p["pnl"] for p in us_enr)
    uk_upnl = sum(p["pnl"] for p in uk_enr)
    us_rpnl = sum(t["pnl"] for t in us_history.get("trades", []))
    uk_rpnl = sum(t["pnl"] for t in uk_history.get("trades", []))

    total_deployed = us_deployed * USD + uk_deployed * GBP
    total_pnl = (us_upnl + us_rpnl) * USD + (uk_upnl + uk_rpnl) * GBP
    total_ret = (total_pnl / total_deployed * 100) if total_deployed else 0

    uw = us_history.get("summary", {}).get("wins", 0)
    ul = us_history.get("summary", {}).get("losses", 0)
    kw = uk_history.get("summary", {}).get("wins", 0)
    kl = uk_history.get("summary", {}).get("losses", 0)
    tw, tl = uw + kw, ul + kl
    wr_pct = round(tw / (tw + tl) * 100) if (tw + tl) > 0 else 0

    ts = datetime.now().strftime("%A, %d/%m/%Y %H:%M")

    html = HTML_TEMPLATE
    html = html.replace("{{timestamp}}", ts)
    html = html.replace("{{comb_deployed}}", "AUD {:,.0f}".format(total_deployed))
    html = html.replace("{{comb_pnl}}", "AUD {:,.2f}".format(total_pnl))
    html = html.replace("{{comb_ret}}", "{:+.1f}%".format(total_ret))
    html = html.replace("{{comb_wr}}", "{}% ({}W / {}L)".format(wr_pct, tw, tl))

    # Colors
    pnl_c = "#2ecc71" if total_pnl >= 0 else "#e74c3c"
    ret_c = "#2ecc71" if total_ret >= 0 else "#e74c3c"
    wr_c  = "#2ecc71" if wr_pct >= 50 else ("#e74c3c" if (tw+tl) > 0 else "#e6edf3")
    html = html.replace("{{comb_pnl_color}}", pnl_c)
    html = html.replace("{{comb_ret_color}}", ret_c)
    html = html.replace("{{comb_wr_color}}", wr_c)

    # US stats
    us_upnl_pct = (us_upnl / us_deployed * 100) if us_deployed else 0
    us_wr_pct = round(uw / (uw + ul) * 100) if (uw + ul) > 0 else 0
    us_wr_c = "#2ecc71" if us_wr_pct >= 50 else ("#e74c3c" if (uw+ul) > 0 else "#e6edf3")
    html = html.replace("{{us_cash}}", "USD {:,.2f}".format(50000 - us_deployed))
    html = html.replace("{{us_deployed}}", "USD {:,.2f}".format(us_deployed))
    html = html.replace("{{us_upnl}}", "USD {:+,.2f} ({:+.1f}%)".format(us_upnl, us_upnl_pct))
    html = html.replace("{{us_upnl_color}}", "#2ecc71" if us_upnl >= 0 else "#e74c3c")
    html = html.replace("{{us_rpnl_color}}", "#2ecc71" if us_rpnl >= 0 else "#e74c3c")
    html = html.replace("{{us_rpnl}}", "USD {:+,.2f}".format(us_rpnl))
    html = html.replace("{{us_wr}}", "{}% ({}W / {}L)".format(us_wr_pct, uw, ul))
    html = html.replace("{{us_wr_color}}", us_wr_c)

    # UK stats
    uk_upnl_pct = (uk_upnl / uk_deployed * 100) if uk_deployed else 0
    uk_wr_pct = round(kw / (kw + kl) * 100) if (kw + kl) > 0 else 0
    uk_wr_c = "#2ecc71" if uk_wr_pct >= 50 else ("#e74c3c" if (kw+kl) > 0 else "#e6edf3")
    html = html.replace("{{uk_cash}}", "GBP {:,.2f}".format(50000 - uk_deployed))
    html = html.replace("{{uk_deployed}}", "GBP {:,.2f}".format(uk_deployed))
    html = html.replace("{{uk_upnl}}", "GBP {:+,.2f} ({:+.1f}%)".format(uk_upnl, uk_upnl_pct))
    html = html.replace("{{uk_upnl_color}}", "#2ecc71" if uk_upnl >= 0 else "#e74c3c")
    html = html.replace("{{uk_rpnl_color}}", "#2ecc71" if uk_rpnl >= 0 else "#e74c3c")
    html = html.replace("{{uk_rpnl}}", "GBP {:+,.2f}".format(uk_rpnl))
    html = html.replace("{{uk_wr}}", "{}% ({}W / {}L)".format(uk_wr_pct, kw, kl))
    html = html.replace("{{uk_wr_color}}", uk_wr_c)

    # Table rows
    html = html.replace("{{us_open_rows}}", open_rows(us_enr, "$"))
    html = html.replace("{{uk_open_rows}}", open_rows(uk_enr, "\u00a3"))
    html = html.replace("{{us_closed_rows}}", closed_rows(us_history.get("trades", []), "$"))
    html = html.replace("{{uk_closed_rows}}", closed_rows(uk_history.get("trades", []), "\u00a3"))

    return html

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
