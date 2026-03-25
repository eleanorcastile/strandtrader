import os, json, time, yfinance as yf
from pathlib import Path
from datetime import datetime
from flask import Flask, jsonify

app = Flask(__name__)
BASE = Path(__file__).parent

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

def load_json(name, fallback):
    try:
        with open(BASE / name) as f:
            return json.load(f)
    except:
        return fallback

def arrow(pnl):
    if pnl > 0: return '<span style="color:#2ecc71;font-weight:bold">▲</span>'
    if pnl < 0: return '<span style="color:#e74c3c;font-weight:bold">▼</span>'
    return '<span style="color:#e6edf3">▶</span>'

def badge(pnl):
    if pnl > 0: return '<span style="color:#2ecc71"><strong>+' + str(pnl) + '</strong></span>'
    if pnl < 0: return '<span style="color:#e74c3c"><strong>' + str(pnl) + '</strong></span>'
    return '<span style="color:#e6edf3">—</span>'

def pct_color(v):
    if v > 0: return '#2ecc71'
    if v < 0: return '#e74c3c'
    return '#e6edf3'

def fmt(v, prefix='$', decimals=2):
    if v >= 0: return f"{prefix}{v:,.{decimals}f}"
    return f"{prefix}{v:,.{decimals}f}"

def win_ratio(hist):
    w = hist.get("summary", {}).get("wins", 0)
    l = hist.get("summary", {}).get("losses", 0)
    t = w + l
    if t == 0: return "white", "0% (0W / 0L)"
    pct = round(w/t*100)
    color = "green" if pct >= 50 else "red"
    return color, f"{pct}% ({w}W / {l}L)"

def build_table(positions, is_closed=False, currency="$"):
    if not positions:
        return "<tr><td colspan='11' style='color:#8b949e;text-align:center;padding:20px'>No positions</td></tr>"
    rows = ""
    for p in positions:
        a = arrow(p["pnl"])
        bc = badge(p["pnl"])
        dc = pct_color(p["day"])
        pc = pct_color(p["pnl_pct"])
        opened = p.get("date","—")
        closed = p.get("closed_date","—") if is_closed else "—"
        rows += f"""<tr>
          <td>{a} <strong>{p['ticker']}</strong></td>
          <td>{p['qty']}</td>
          <td>{currency}{p['entry']:.2f}</td>
          <td>{currency}{p['current']:.2f}</td>
          <td>{currency}{p['cost']:.2f}</td>
          <td>{currency}{p['value']:.2f}</td>
          <td style='color:{\"#2ecc71\" if p[\"pnl\"]>=0 else \"#e74c3c\"}'><strong>{bc}</strong></td>
          <td style='color:{pc}'>{p['pnl_pct']:.1f}%</td>
          <td style='color:{dc}'>{p['day']:.1f}%</td>
          <td>{opened}</td>
          <td>{closed}</td>
        </tr>"""
    return rows

def us_stats(us_pos, us_hist, USD):
    total_cost = sum(p["cost"] for p in us_pos)
    total_val = sum(p["value"] for p in us_pos)
    upnl = sum(p["pnl"] for p in us_pos)
    rpnl = sum(t["pnl"] for t in us_hist.get("trades", []))
    wr_color, wr = win_ratio(us_hist)
    return {
        "capital": "USD 50,000",
        "cash": f"USD {50000 - total_cost:,.2f}",
        "deployed": f"USD {total_cost:,.2f}",
        "upnl": (upnl, (upnl/total_cost*100) if total_cost else 0),
        "rpnl": rpnl,
        "wr_color": wr_color, "wr": wr
    }

def uk_stats(uk_pos, uk_hist):
    total_cost = sum(p["cost"] for p in uk_pos)
    total_val = sum(p["value"] for p in uk_pos)
    upnl = sum(p["pnl"] for p in uk_pos)
    rpnl = sum(t["pnl"] for t in uk_hist.get("trades", []))
    wr_color, wr = win_ratio(uk_hist)
    return {
        "capital": "GBP 50,000",
        "cash": f"GBP {50000 - total_cost:,.2f}",
        "deployed": f"GBP {total_cost:,.2f}",
        "upnl": (upnl, (upnl/total_cost*100) if total_cost else 0),
        "rpnl": rpnl,
        "wr_color": wr_color, "wr": wr
    }

def combined_stats(us_pos, us_hist, uk_pos, uk_hist, USD, GBP):
    uc = sum(p["cost"] for p in us_pos)
    uv = sum(p["value"] for p in us_pos)
    u_pnl = sum(p["pnl"] for p in us_pos) + sum(t["pnl"] for t in us_hist.get("trades", []))
    kc = sum(p["cost"] for p in uk_pos)
    k_pnl = sum(p["pnl"] for p in uk_pos) + sum(t["pnl"] for t in uk_hist.get("trades", []))
    total_deployed = uc * USD + kc * GBP
    total_pnl = u_pnl * USD + k_pnl * GBP
    ret = (total_pnl / total_deployed * 100) if total_deployed else 0
    tw = us_hist.get("summary",{}).get("wins",0) + uk_hist.get("summary",{}).get("wins",0)
    tl = us_hist.get("summary",{}).get("losses",0) + uk_hist.get("summary",{}).get("losses",0)
    tt = tw + tl
    wr_pct = round(tw/tt*100) if tt else 0
    wr_color = "green" if wr_pct >= 50 else "red" if tt > 0 else "white"
    return {
        "deployed": round(total_deployed, 2),
        "pnl": round(total_pnl, 2),
        "ret": round(ret, 2),
        "wr_color": wr_color, "wr_pct": wr_pct, "tw": tw, "tl": tl
    }

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>STRANDTRADER — Portfolio Dashboard</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0d1117;color:#e6edf3;padding:16px}
h1{color:#fff;font-size:26px}
.subtitle{color:#8b949e;font-size:16px}
.meta{color:#8b949e;font-size:14px;margin-bottom:14px}
.header-row{display:flex;align-items:flex-start;flex-wrap:wrap;gap:12px;margin-bottom:5px}
.header-row .header-left{flex:1;min-width:300px}
.header-row .comb-box{flex:1;min-width:300px;max-width:700px}
.comb-box{background:linear-gradient(135deg,#2a2a2a,#1a1a1a);border:1px solid #fff;border-radius:8px;padding:24px 32px;display:flex;align-items:center;flex-wrap:wrap;max-width:680px}
.comb-stat{text-align:center;flex:1;min-width:110px}
.comb-div{width:1px;background:#555;height:40px;margin:0 8px}
.comb-label{color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px}
.comb-value{font-size:16px;font-weight:bold}
.tabs{display:flex;gap:4px;margin:14px 0 0 0}
.tab-btn{background:#21262d;color:#8b949e;border:1px solid #30363d;border-bottom:none;border-radius:8px 8px 0 0;padding:6px 16px;font-size:13px;cursor:pointer;font-weight:600}
.tab-btn.active{background:#161b22;color:#58a6ff;border-color:#58a6ff}
.tab-content{background:#161b22;border:1px solid #30363d;border-radius:0 12px 12px 12px;padding:14px;display:none}
.tab-content.active{display:block}
.summary-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:6px;margin-bottom:14px}
.stat{background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:8px 6px}
.stat-label{color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:2px}
.stat-value{font-size:16px;font-weight:bold}
.section-title{color:#8b949e;font-size:13px;text-transform:uppercase;letter-spacing:0.5px;margin:14px 0 6px 0}
.closed-title{color:#8b949e;font-size:13px;text-transform:uppercase;letter-spacing:0.5px;margin:14px 0 6px 0;border-top:1px solid #30363d;padding-top:8px}
table{width:100%;border-collapse:collapse}
th{background:#21262d;color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;padding:6px 8px;text-align:left;border-bottom:1px solid #30363d}
td{padding:6px 8px;border-bottom:1px solid #1c2129;font-size:14px}
tr:last-child td{border-bottom:none}
tr:hover td{background:#1c2129}
.footer{margin-top:12px;color:#484f58;font-size:12px}
</style>
</head>
<body>
<div class="header-row">
  <div class="header-left">
    <h1>🏛️ STRANDTRADER</h1>
    <p class="subtitle">Paper Trading — US NYSE/NASDAQ + UK FTSE AIM/SmallCap</p>
    <p class="meta">Generated: {{timestamp}} AEST | Data: Yahoo Finance (15-min delay) | Auto-refreshes every 60s</p>
  </div>
  <div class="comb-box">
    <div class="comb-stat"><div class="comb-label">Total Deployed</div><div class="comb-value" style="color:#58a6ff">AUD {{"{:,}".format(comb["deployed"])}}</div></div>
    <div class="comb-div"></div>
    <div class="comb-stat"><div class="comb-label">Combined P&L</div><div class="comb-value" style="color:{{'#2ecc71' if comb['pnl']>=0 else '#e74c3c'}}">{{"AUD {:,.2f}".format(comb["pnl"])}}</div></div>
    <div class="comb-div"></div>
    <div class="comb-stat"><div class="comb-label">Return on Deployed</div><div class="comb-value" style="color:{{'#2ecc71' if comb['ret']>=0 else '#e74c3c'}}">{{"{}%".format(comb["ret"])}}</div></div>
    <div class="comb-div"></div>
    <div class="comb-stat"><div class="comb-label">Win Ratio</div><div class="comb-value" style="color:{{'#2ecc71' if comb['wr_color']=='green' else ('#e74c3c' if comb['wr_color']=='red' else '#e6edf3')}}">{{"{}% ({}W / {}L)".format(comb["wr_pct"], comb["tw"], comb["tl"])}}</div></div>
  </div>
</div>

<div class="tabs">
  <button class="tab-btn active" onclick="showTab('us')">🇺🇸 US Market</button>
  <button class="tab-btn" onclick="showTab('uk')">🇬🇧 UK Market</button>
</div>

<div id="tab-us" class="tab-content active">
  <div class="summary-grid">
    <div class="stat"><div class="stat-label">Paper Capital</div><div class="stat-value" style="color:#58a6ff">USD 50,000</div></div>
    <div class="stat"><div class="stat-label">Cash Available</div><div class="stat-value" style="color:#58a6ff">{{us["cash"]}}</div></div>
    <div class="stat"><div class="stat-label">Capital Deployed</div><div class="stat-value" style="color:#58a6ff">{{us["deployed"]}}</div></div>
    <div class="stat"><div class="stat-label">Unrealised P&L</div><div class="stat-value" style="color:{{'#2ecc71' if us['upnl'][0]>=0 else '#e74c3c'}}">{{"USD {:,.2f} ({:.1f}%)".format(us["upnl"][0], us["upnl"][1])}}</div></div>
    <div class="stat"><div class="stat-label">Realised P&L</div><div class="stat-value" style="color:{{'#2ecc71' if us['rpnl']>=0 else '#e74c3c'}}">{{"USD {:,.2f}".format(us["rpnl"])}}</div></div>
    <div class="stat"><div class="stat-label">Win Ratio</div><div class="stat-value" style="color:{{'#2ecc71' if us['wr_color']=='green' else ('#e74c3c' if us['wr_color']=='red' else '#e6edf3')}}">{{us["wr"]}}</div></div>
  </div>
  <div class="section-title">Open Positions — 🇺🇸 US</div>
  <table><thead><tr><th style="width:13%">Ticker</th><th style="width:6%">Shares</th><th style="width:9%">Entry</th><th style="width:9%">Current</th><th style="width:10%">Invested</th><th style="width:10%">Mkt Value</th><th style="width:10%">P&L (USD)</th><th style="width:8%">P&L (%)</th><th style="width:7%">Day</th><th style="width:9%">Opened</th><th style="width:9%">Closed</th></tr></thead><tbody>{{us_open_rows}}</tbody></table>
  <div class="closed-title">Closed Positions — 🇺🇸 US</div>
  <table><thead><tr><th style="width:13%">Ticker</th><th style="width:6%">Shares</th><th style="width:9%">Entry</th><th style="width:9%">Exit</th><th style="width:10%">Cost</th><th style="width:10%">Proceeds</th><th style="width:10%">P&L (USD)</th><th style="width:8%">P&L (%)</th><th style="width:7%">Day</th><th style="width:9%">Opened</th><th style="width:9%">Closed</th></tr></thead><tbody>{{us_closed_rows}}</tbody></table>
</div>

<div id="tab-uk" class="tab-content">
  <div class="summary-grid">
    <div class="stat"><div class="stat-label">Paper Capital</div><div class="stat-value" style="color:#58a6ff">GBP 50,000</div></div>
    <div class="stat"><div class="stat-label">Cash Available</div><div class="stat-value" style="color:#58a6ff">{{uk["cash"]}}</div></div>
    <div class="stat"><div class="stat-label">Capital Deployed</div><div class="stat-value" style="color:#58a6ff">{{uk["deployed"]}}</div></div>
    <div class="stat"><div class="stat-label">Unrealised P&L</div><div class="stat-value" style="color:{{'#2ecc71' if uk['upnl'][0]>=0 else '#e74c3c'}}">{{"GBP {:,.2f} ({:.1f}%)".format(uk["upnl"][0], uk["upnl"][1])}}</div></div>
    <div class="stat"><div class="stat-label">Realised P&L</div><div class="stat-value" style="color:{{'#2ecc71' if uk['rpnl']>=0 else '#e74c3c'}}">{{"GBP {:,.2f}".format(uk["rpnl"])}}</div></div>
    <div class="stat"><div class="stat-label">Win Ratio</div><div class="stat-value" style="color:{{'#2ecc71' if uk['wr_color']=='green' else ('#e74c3c' if uk['wr_color']=='red' else '#e6edf3')}}">{{uk["wr"]}}</div></div>
  </div>
  <div class="section-title">Open Positions — 🇬🇧 UK</div>
  <table><thead><tr><th style="width:13%">Ticker</th><th style="width:6%">Shares</th><th style="width:9%">Entry</th><th style="width:9%">Current</th><th style="width:10%">Invested</th><th style="width:10%">Mkt Value</th><th style="width:10%">P&L (GBP)</th><th style="width:8%">P&L (%)</th><th style="width:7%">Day</th><th style="width:9%">Opened</th><th style="width:9%">Closed</th></tr></thead><tbody>{{uk_open_rows}}</tbody></table>
  <div class="closed-title">Closed Positions — 🇬🇧 UK</div>
  <table><thead><tr><th style="width:13%">Ticker</th><th style="width:6%">Shares</th><th style="width:9%">Entry</th><th style="width:9%">Exit</th><th style="width:10%">Cost</th><th style="width:10%">Proceeds</th><th style="width:10%">P&L (GBP)</th><th style="width:8%">P&L (%)</th><th style="width:7%">Day</th><th style="width:9%">Opened</th><th style="width:9%">Closed</th></tr></thead><tbody>{{uk_closed_rows}}</tbody></table>
</div>

<div class="footer">STRANDTRADER | No API keys exposed | Data via Yahoo Finance</div>
<script>
function showTab(name){
  document.querySelectorAll('.tab-content').forEach(el=>el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
  document.querySelector('.tab-btn[onclick="showTab(\\''+name+'\\')"]').classList.add('active');
}
setTimeout(function(){location.reload();}, 60000);
</script>
</body>
</html>"""

def build_us_closed_rows(trades):
    if not trades:
        return "<tr><td colspan='11' style='color:#8b949e;text-align:center;padding:20px'>No closed trades</td></tr>"
    rows = ""
    for t in trades:
        pnl = t.get("pnl", 0)
        a = '<span style="color:#2ecc71">🟢</span>' if pnl > 0 else '<span style="color:#e74c3c">🔴</span>' if pnl < 0 else '<span style="color:#e6edf3">⚪</span>'
        rows += f"""<tr class='closed-row'>
          <td>{a} <strong>{t['ticker']}</strong></td>
          <td>{t.get('qty',0)}</td>
          <td>£{t.get('entry',0):.2f}</td>
          <td>£{t.get('exit',0):.2f}</td>
          <td>£{t.get('cost',0):.2f}</td>
          <td>£{t.get('proceeds',0):.2f}</td>
          <td style='color:{"#2ecc71" if pnl>=0 else "#e74c3c"}'><strong>{"+" if pnl>=0 else ""}{pnl:.2f}</strong></td>
          <td style='color:{"#2ecc71" if t.get("pnl_pct",0)>=0 else "#e74c3c"}'>{t.get("pnl_pct",0):.1f}%</td>
          <td>—</td>
          <td>{t.get('opened','—')}</td>
          <td>{t.get('closed','—')}</td>
        </tr>"""
    return rows

@app.route("/")
def index():
    us_portfolio = load_json("us_portfolio.json", {"positions": {}, "cash": 50000})
    us_history   = load_json("us_history.json", {"trades": [], "summary": {"wins": 0, "losses": 0}})
    uk_portfolio = load_json("uk_portfolio.json", {"positions": {}, "cash": 50000})
    uk_history   = load_json("uk_history.json", {"trades": [], "summary": {"wins": 0, "losses": 0}})

    USD, GBP = get_fx()
    us_enr = enrich(us_portfolio.get("positions", {}))
    uk_enr = enrich(uk_portfolio.get("positions", {}))

    us = us_stats(us_enr, us_history, USD)
    uk = uk_stats(uk_enr, uk_history)
    comb = combined_stats(us_enr, us_history, uk_enr, uk_history, USD, GBP)

    ts = datetime.now().strftime("%A, %d/%m/%Y %H:%M")

    # Build table rows
    us_open_rows = build_table(us_enr, is_closed=False, currency="$")
    uk_open_rows = build_table(uk_enr, is_closed=False, currency="£")
    us_closed_rows = build_us_closed_rows(us_history.get("trades", []))
    uk_closed_rows = build_us_closed_rows(uk_history.get("trades", []))

    html = HTML_TEMPLATE.replace("{{timestamp}}", ts) \
        .replace("{{us_open_rows}}", us_open_rows) \
        .replace("{{uk_open_rows}}", uk_open_rows) \
        .replace("{{us_closed_rows}}", us_closed_rows) \
        .replace("{{uk_closed_rows}}", uk_closed_rows)

    # Stats replacements
    for key, val in [("us_cash", us["cash"]), ("us_deployed", us["deployed"]),
                      ("uk_cash", uk["cash"]), ("uk_deployed", uk["deployed"]),
                      ("us_upnl", f"USD {us['upnl'][0]:,.2f} ({us['upnl'][1]:.1f}%)"),
                      ("uk_upnl", f"GBP {uk['upnl'][0]:,.2f} ({uk['upnl'][1]:.1f}%)"),
                      ("us_rpnl", f"USD {us['rpnl']:,.2f}"),
                      ("uk_rpnl", f"GBP {uk['rpnl']:,.2f}")]:
        html = html.replace("{{" + key + "}}", str(val))

    # Simple replacements first
    simple = {
        "comb_deployed": f"AUD {{:,.0f}}".format(comb["deployed"]),
        "comb_pnl": "AUD {:,.2f}".format(comb["pnl"]),
        "comb_ret": "{}%".format(comb["ret"]),
        "comb_wr": "{}% ({}W / {}L)".format(comb["wr_pct"], comb["tw"], comb["tl"]),
        "us_wr": us["wr"],
        "uk_wr": uk["wr"],
    }
    for k, v in simple.items():
        html = html.replace("{{" + k + "}}", v)

    # Comb box color logic
    html = html.replace("{{comb_pnl_color}}", "#2ecc71" if comb["pnl"] >= 0 else "#e74c3c")
    html = html.replace("{{comb_ret_color}}", "#2ecc71" if comb["ret"] >= 0 else "#e74c3c")
    html = html.replace("{{comb_wr_color}}", "#2ecc71" if comb["wr_color"]=="green" else ("#e74c3c" if comb["wr_color"]=="red" else "#e6edf3"))

    return html

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
