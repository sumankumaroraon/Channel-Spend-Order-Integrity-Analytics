"""
build_dashboard.py
Generates dashboard/index.html — a self-contained, four-page interactive
dashboard (Overview / Channel & Campaign / Customer & Order Quality /
Exceptions & Savings), styled as a standalone stand-in for what the Power BI
version of this project would show. All numbers are embedded directly from
outputs/kpi_summary.json, channel_summary.csv, monthly_trend.csv, and
audit_flags.csv — nothing in the HTML is hand-typed, so the dashboard can
never drift from the audit engine's actual output.

Charts are drawn with Chart.js — vendored directly into the page from
python/vendor/chart.umd.js (pulled once from the npm registry; see that
file's header) rather than loaded from a CDN, so the dashboard renders
identically with zero internet connection and isn't at the mercy of a
blocked CDN domain, an ad-blocker, or a flaky network. Open dashboard/
index.html directly in a browser — no server, no build step, no
external requests required at all.
"""

import json
import os
import pandas as pd

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT_DIR = os.path.join(ROOT, "outputs")
DASH_DIR = os.path.join(ROOT, "dashboard")
VENDOR_CHARTJS = os.path.join(os.path.dirname(__file__), "vendor", "chart.umd.js")
os.makedirs(DASH_DIR, exist_ok=True)

with open(VENDOR_CHARTJS) as f:
    CHARTJS_SRC = f.read()

with open(os.path.join(OUT_DIR, "kpi_summary.json")) as f:
    kpis = json.load(f)

channel_summary = pd.read_csv(os.path.join(OUT_DIR, "channel_summary.csv"))
monthly_trend = pd.read_csv(os.path.join(OUT_DIR, "monthly_trend.csv"))
audit_flags = pd.read_csv(os.path.join(OUT_DIR, "audit_flags.csv"))

flag_counts = (
    audit_flags["flag"].value_counts().rename_axis("flag").reset_index(name="count")
)
flag_dollars = audit_flags.groupby("flag")["amount"].apply(lambda s: s.abs().sum())
flag_summary = flag_counts.merge(flag_dollars.rename("dollars"), on="flag")
flag_summary = flag_summary.sort_values("count", ascending=False)

top_flags = (
    audit_flags.reindex(audit_flags["amount"].abs().sort_values(ascending=False).index)
    .head(20)[["record_type", "record_id", "flag", "detail", "amount"]]
)

def records(df):
    """DataFrame -> list[dict], routing through pandas' own JSON encoder so that
    NaN (e.g. ROAS for a channel with zero spend) becomes valid JSON `null`
    instead of the bare `NaN` token python's json.dumps would otherwise emit."""
    return json.loads(df.to_json(orient="records"))


DATA = {
    "kpis": kpis,
    "channels": records(channel_summary.round(2)),
    "monthly": records(monthly_trend.round(2)),
    "flag_summary": records(flag_summary.round(2)),
    "top_flags": records(top_flags.round(2)),
}

DATA_JSON = json.dumps(DATA)

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Channel Spend &amp; Order Integrity Analytics — Northfield Retail Co.</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500&display=swap" rel="stylesheet">
<!-- Chart.js is vendored inline below (see the <script id="chartjs-lib"> block just before
     </body>) rather than loaded from a CDN, so every chart renders with no internet
     connection required. Only the Google Fonts above are external, and those degrade
     gracefully to the system font stack if unreachable -- they never affect the charts. -->
<style>
  :root{
    --ink:#12203D; --ink-soft:#4C5A73;
    --bg:#F3F4F7; --card:#FFFFFF; --line:#DFE2E8;
    --amber:#C1852C; --teal:#2F6F62; --brick:#AE3B41;
    --amber-tint:#FBF1E2; --teal-tint:#E9F2EF; --brick-tint:#FAEBEC;
    --serif:'Fraunces', Georgia, 'Times New Roman', serif;
    --sans:'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    --mono:'IBM Plex Mono', 'SF Mono', Consolas, monospace;
  }
  *{box-sizing:border-box;}
  html,body{margin:0;padding:0;background:var(--bg);color:var(--ink);font-family:var(--sans);}
  body{-webkit-font-smoothing:antialiased;}

  .shell{max-width:1180px;margin:0 auto;padding:0 28px 80px;}

  header.top{border-bottom:1px solid var(--line);background:var(--card);}
  .top-inner{max-width:1180px;margin:0 auto;padding:30px 28px 0;}
  .brand-row{display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:12px;}
  .brand{display:flex;flex-direction:column;gap:2px;}
  .brand .mark{font-family:var(--mono);font-size:11px;letter-spacing:.08em;color:var(--amber);}
  .brand h1{font-family:var(--serif);font-weight:500;font-size:28px;margin:2px 0 0;line-height:1.15;}
  .brand .sub{color:var(--ink-soft);font-size:13.5px;margin-top:4px;max-width:520px;}
  .period{font-family:var(--mono);font-size:12px;color:var(--ink-soft);text-align:right;line-height:1.6;}

  nav.tabs{display:flex;gap:2px;margin-top:22px;}
  nav.tabs button{
    font-family:var(--sans);font-size:13.5px;font-weight:600;color:var(--ink-soft);
    background:none;border:none;border-bottom:2px solid transparent;
    padding:12px 4px;margin-right:26px;cursor:pointer;
  }
  nav.tabs button.active{color:var(--ink);border-bottom-color:var(--amber);}
  nav.tabs button:hover{color:var(--ink);}

  section.page{display:none;padding-top:30px;}
  section.page.active{display:block;}

  h2.page-title{font-family:var(--serif);font-weight:500;font-size:20px;margin:0 0 4px;}
  p.page-note{color:var(--ink-soft);font-size:13px;margin:0 0 24px;max-width:640px;}

  .kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:28px;}
  .kpi-grid.hero{grid-template-columns:1.4fr 1fr 1fr 1fr;}
  .kpi{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--amber);padding:16px 18px;}
  .kpi.teal{border-left-color:var(--teal);}
  .kpi.brick{border-left-color:var(--brick);}
  .kpi .label{font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--ink-soft);font-weight:600;}
  .kpi .value{font-family:var(--serif);font-size:26px;margin-top:6px;}
  .kpi.hero .value{font-size:34px;}
  .kpi .foot{font-size:11.5px;color:var(--ink-soft);margin-top:4px;}

  .panel{background:var(--card);border:1px solid var(--line);padding:20px 22px;margin-bottom:20px;}
  .panel h3{font-family:var(--serif);font-weight:500;font-size:16px;margin:0 0 14px;}
  .two-col{display:grid;grid-template-columns:1.3fr 1fr;gap:16px;align-items:start;}

  table{width:100%;border-collapse:collapse;font-size:12.5px;}
  table th{text-align:left;font-size:10.5px;text-transform:uppercase;letter-spacing:.04em;color:var(--ink-soft);
            border-bottom:1px solid var(--line);padding:6px 8px;font-weight:600;}
  table td{padding:7px 8px;border-bottom:1px solid #EEF0F3;vertical-align:top;}
  table tr:last-child td{border-bottom:none;}
  td.num{font-family:var(--mono);text-align:right;white-space:nowrap;}
  .tag{display:inline-block;font-family:var(--mono);font-size:10.5px;background:var(--brick-tint);color:var(--brick);
       padding:2px 7px;border-radius:2px;}

  .savings-banner{display:flex;justify-content:space-between;align-items:center;background:var(--ink);color:#fff;padding:22px 26px;margin-bottom:20px;}
  .savings-banner .l{font-family:var(--mono);font-size:11px;letter-spacing:.08em;color:#B9C2D6;}
  .savings-banner .v{font-family:var(--serif);font-size:36px;margin-top:4px;}
  .savings-banner .r{max-width:340px;font-size:12.5px;color:#C9D1E0;text-align:right;}

  .chart-wrap{position:relative;height:280px;}
  .chart-wrap.tall{height:340px;}

  footer{max-width:1180px;margin:40px auto 0;padding:20px 28px;border-top:1px solid var(--line);
         color:var(--ink-soft);font-size:11.5px;font-family:var(--mono);}

  @media (max-width:880px){
    .kpi-grid, .kpi-grid.hero{grid-template-columns:1fr 1fr;}
    .two-col{grid-template-columns:1fr;}
    .savings-banner{flex-direction:column;align-items:flex-start;gap:12px;}
    .savings-banner .r{text-align:left;}
  }
</style>
</head>
<body>

<header class="top">
  <div class="top-inner">
    <div class="brand-row">
      <div class="brand">
        <span class="mark">EXCEPTION &amp; PERFORMANCE REPORTING</span>
        <h1>Channel Spend &amp; Order Integrity Analytics</h1>
        <div class="sub">Northfield Retail Co. — marketing spend, order revenue, and a rule-based audit engine, cross-validated across Python, SQL, and Excel.</div>
      </div>
      <div class="period">FY2025 (Jan – Dec)<br>Generated from outputs/kpi_summary.json</div>
    </div>
    <nav class="tabs">
      <button data-page="overview" class="active">Overview</button>
      <button data-page="channel">Channel &amp; Campaign</button>
      <button data-page="quality">Customer &amp; Order Quality</button>
      <button data-page="exceptions">Exceptions &amp; Savings</button>
    </nav>
  </div>
</header>

<div class="shell">

  <!-- ============ PAGE 1: OVERVIEW ============ -->
  <section class="page active" id="page-overview">
    <h2 class="page-title">Executive Overview</h2>
    <p class="page-note">Blended performance across all channels for the fiscal year, plus the monthly revenue-vs-spend trend.</p>

    <div class="kpi-grid hero">
      <div class="kpi hero"><div class="label">Total Revenue</div><div class="value" id="k-revenue"></div><div class="foot">net of discounts</div></div>
      <div class="kpi teal"><div class="label">Marketing Spend</div><div class="value" id="k-spend"></div></div>
      <div class="kpi teal"><div class="label">Blended ROAS</div><div class="value" id="k-roas"></div></div>
      <div class="kpi"><div class="label">Avg. Order Value</div><div class="value" id="k-aov"></div></div>
    </div>

    <div class="panel">
      <h3>Monthly Revenue vs. Marketing Spend</h3>
      <div class="chart-wrap tall"><canvas id="chart-monthly"></canvas></div>
    </div>

    <div class="two-col">
      <div class="panel">
        <h3>Revenue by Channel</h3>
        <div class="chart-wrap"><canvas id="chart-rev-channel"></canvas></div>
      </div>
      <div class="panel">
        <h3>At a Glance</h3>
        <table>
          <tr><td>Total Orders</td><td class="num" id="k-orders"></td></tr>
          <tr><td>Refund Rate</td><td class="num" id="k-refund-rate"></td></tr>
          <tr><td>Chargeback Rate</td><td class="num" id="k-cb-rate"></td></tr>
          <tr><td>Repeat Purchase Rate</td><td class="num" id="k-repeat"></td></tr>
          <tr><td>Budget Compliance</td><td class="num" id="k-budget-compliance"></td></tr>
          <tr><td>Blended CAC</td><td class="num" id="k-cac"></td></tr>
        </table>
      </div>
    </div>
  </section>

  <!-- ============ PAGE 2: CHANNEL & CAMPAIGN ============ -->
  <section class="page" id="page-channel">
    <h2 class="page-title">Channel &amp; Campaign Performance</h2>
    <p class="page-note">Revenue, spend, and efficiency by channel. Organic/Direct carries no media spend, so ROAS is not applicable there.</p>

    <div class="panel">
      <h3>Revenue vs. Spend by Channel</h3>
      <div class="chart-wrap tall"><canvas id="chart-channel-bar"></canvas></div>
    </div>

    <div class="panel">
      <h3>Channel Detail</h3>
      <table id="tbl-channels">
        <thead><tr><th>Channel</th><th>Revenue</th><th>Spend</th><th>Orders</th><th>Refund Rate</th><th>ROAS</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </section>

  <!-- ============ PAGE 3: CUSTOMER & ORDER QUALITY ============ -->
  <section class="page" id="page-quality">
    <h2 class="page-title">Customer &amp; Order Quality</h2>
    <p class="page-note">How clean is the order book, and how much of revenue is being given away in discounts and refunds.</p>

    <div class="kpi-grid">
      <div class="kpi brick"><div class="label">Refund Rate</div><div class="value" id="q-refund-rate"></div></div>
      <div class="kpi brick"><div class="label">Chargeback Rate</div><div class="value" id="q-cb-rate"></div></div>
      <div class="kpi"><div class="label">Discount Leakage</div><div class="value" id="q-discount"></div></div>
      <div class="kpi teal"><div class="label">Repeat Purchase Rate</div><div class="value" id="q-repeat"></div></div>
    </div>

    <div class="two-col">
      <div class="panel">
        <h3>Refund Rate by Channel</h3>
        <div class="chart-wrap"><canvas id="chart-refund-channel"></canvas></div>
      </div>
      <div class="panel">
        <h3>Reading the numbers</h3>
        <table>
          <tr><td>Total Refund Dollars</td><td class="num" id="q-refund-dollars"></td></tr>
          <tr><td>Discount Leakage ($)</td><td class="num" id="q-discount-dollars"></td></tr>
          <tr><td>Repeat vs. One-Time Customers</td><td class="num" id="q-repeat-rate2"></td></tr>
        </table>
      </div>
    </div>
  </section>

  <!-- ============ PAGE 4: EXCEPTIONS & SAVINGS ============ -->
  <section class="page" id="page-exceptions">
    <h2 class="page-title">Exceptions &amp; Savings Opportunities</h2>
    <p class="page-note">Output of the rule-based audit engine (10 independent checks) — cross-validated identically in Python and SQL.</p>

    <div class="savings-banner">
      <div>
        <div class="l">ESTIMATED RECOVERABLE SAVINGS</div>
        <div class="v" id="x-savings"></div>
      </div>
      <div class="r">Sum of flagged dollars from the five avoidable-spend flags (excessive discounts, duplicate charges, orphaned campaign spend, wasted spend, budget overruns). Data-quality-only flags are excluded from this figure.</div>
    </div>

    <div class="kpi-grid">
      <div class="kpi"><div class="label">Flagged Records</div><div class="value" id="x-count"></div></div>
      <div class="kpi"><div class="label">Total Flagged $</div><div class="value" id="x-dollars"></div></div>
      <div class="kpi teal"><div class="label">Budget Compliance</div><div class="value" id="x-budget"></div></div>
      <div class="kpi brick"><div class="label">Campaigns Over Budget</div><div class="value" id="x-over"></div></div>
    </div>

    <div class="two-col">
      <div class="panel">
        <h3>Flagged Records by Exception Type</h3>
        <div class="chart-wrap tall"><canvas id="chart-flags"></canvas></div>
      </div>
      <div class="panel">
        <h3>Top 20 Flags by Dollar Impact</h3>
        <table id="tbl-flags">
          <thead><tr><th>Record</th><th>Flag</th><th>Amount</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>
  </section>

</div>

<footer>
  DEMO / PORTFOLIO PROJECT — ALL DATA SYNTHETIC — GENERATED FROM outputs/kpi_summary.json, channel_summary.csv, monthly_trend.csv, audit_flags.csv
</footer>

<script id="chartjs-lib">
__CHARTJS_SRC__
</script>
<script>
const DATA = __DATA_JSON__;

const money = (v, d=0) => '$' + Number(v).toLocaleString('en-US', {minimumFractionDigits:d, maximumFractionDigits:d});
const pct = (v, d=1) => (Number(v)*100).toFixed(d) + '%';
const num = (v) => Number(v).toLocaleString('en-US');

function paint(){
  const k = DATA.kpis;
  document.getElementById('k-revenue').textContent = money(k.total_revenue);
  document.getElementById('k-spend').textContent = money(k.total_marketing_spend);
  document.getElementById('k-roas').textContent = k.roas.toFixed(2) + 'x';
  document.getElementById('k-aov').textContent = money(k.average_order_value, 2);
  document.getElementById('k-orders').textContent = num(k.total_orders);
  document.getElementById('k-refund-rate').textContent = pct(k.refund_rate);
  document.getElementById('k-cb-rate').textContent = pct(k.chargeback_rate);
  document.getElementById('k-repeat').textContent = pct(k.repeat_purchase_rate);
  document.getElementById('k-budget-compliance').textContent = pct(k.budget_compliance_rate);
  document.getElementById('k-cac').textContent = money(k.blended_cac, 2);

  document.getElementById('q-refund-rate').textContent = pct(k.refund_rate);
  document.getElementById('q-cb-rate').textContent = pct(k.chargeback_rate);
  document.getElementById('q-discount').textContent = money(k.discount_leakage_dollars);
  document.getElementById('q-repeat').textContent = pct(k.repeat_purchase_rate);
  document.getElementById('q-refund-dollars').textContent = money(k.total_refund_dollars);
  document.getElementById('q-discount-dollars').textContent = money(k.discount_leakage_dollars);
  document.getElementById('q-repeat-rate2').textContent = pct(k.repeat_purchase_rate);

  document.getElementById('x-savings').textContent = money(k.estimated_recoverable_savings);
  document.getElementById('x-count').textContent = num(k.total_flagged_records);
  document.getElementById('x-dollars').textContent = money(k.total_flagged_dollars);
  document.getElementById('x-budget').textContent = pct(k.budget_compliance_rate);
  document.getElementById('x-over').textContent = num(k.campaigns_over_budget);

  // Channel table
  const chTbody = document.querySelector('#tbl-channels tbody');
  DATA.channels.forEach(c => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${c.channel}</td><td class="num">${money(c.revenue)}</td><td class="num">${money(c.spend)}</td>` +
                   `<td class="num">${num(c.orders)}</td><td class="num">${pct(c.refund_rate)}</td>` +
                   `<td class="num">${c.roas ? c.roas.toFixed(2)+'x' : '—'}</td>`;
    chTbody.appendChild(tr);
  });

  // Flags table
  const flTbody = document.querySelector('#tbl-flags tbody');
  DATA.top_flags.forEach(f => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${f.record_id}</td><td><span class="tag">${f.flag.replace(/_/g,' ')}</span></td><td class="num">${money(f.amount)}</td>`;
    flTbody.appendChild(tr);
  });

  drawCharts();
}

function drawCharts(){
  Chart.defaults.font.family = "'IBM Plex Sans', sans-serif";
  Chart.defaults.color = '#4C5A73';
  Chart.defaults.borderColor = '#DFE2E8';

  const months = DATA.monthly.map(m => m.month);
  new Chart(document.getElementById('chart-monthly'), {
    type: 'line',
    data: {
      labels: months,
      datasets: [
        {label:'Revenue', data: DATA.monthly.map(m=>m.revenue), borderColor:'#C1852C', backgroundColor:'#FBF1E2', tension:.3, fill:true, pointRadius:2},
        {label:'Marketing Spend', data: DATA.monthly.map(m=>m.spend), borderColor:'#2F6F62', backgroundColor:'#E9F2EF', tension:.3, fill:true, pointRadius:2},
      ]
    },
    options: {responsive:true, maintainAspectRatio:false, plugins:{legend:{position:'top', align:'end'}}, scales:{y:{ticks:{callback:v=>money(v)}}}}
  });

  const channels = DATA.channels.map(c=>c.channel);
  new Chart(document.getElementById('chart-rev-channel'), {
    type: 'bar',
    data: {labels: channels, datasets:[{label:'Revenue', data: DATA.channels.map(c=>c.revenue), backgroundColor:'#C1852C'}]},
    options: {responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:{y:{ticks:{callback:v=>money(v)}}}}
  });

  new Chart(document.getElementById('chart-channel-bar'), {
    type: 'bar',
    data: {
      labels: channels,
      datasets: [
        {label:'Revenue', data: DATA.channels.map(c=>c.revenue), backgroundColor:'#C1852C'},
        {label:'Spend', data: DATA.channels.map(c=>c.spend), backgroundColor:'#2F6F62'},
      ]
    },
    options: {responsive:true, maintainAspectRatio:false, plugins:{legend:{position:'top', align:'end'}}, scales:{y:{ticks:{callback:v=>money(v)}}}}
  });

  new Chart(document.getElementById('chart-refund-channel'), {
    type: 'bar',
    data: {labels: channels, datasets:[{label:'Refund Rate', data: DATA.channels.map(c=>c.refund_rate), backgroundColor:'#AE3B41'}]},
    options: {responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:{y:{ticks:{callback:v=>pct(v)}}}}
  });

  new Chart(document.getElementById('chart-flags'), {
    type: 'bar',
    data: {
      labels: DATA.flag_summary.map(f=>f.flag.replace(/_/g,' ')),
      datasets: [{label:'Count', data: DATA.flag_summary.map(f=>f.count), backgroundColor:'#12203D'}]
    },
    options: {indexAxis:'y', responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}}
  });
}

document.querySelectorAll('nav.tabs button').forEach(btn=>{
  btn.addEventListener('click', () => {
    document.querySelectorAll('nav.tabs button').forEach(b=>b.classList.remove('active'));
    document.querySelectorAll('section.page').forEach(p=>p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('page-' + btn.dataset.page).classList.add('active');
  });
});

paint();
</script>
</body>
</html>
"""

HTML = HTML.replace("__CHARTJS_SRC__", CHARTJS_SRC)
HTML = HTML.replace("__DATA_JSON__", DATA_JSON)

with open(os.path.join(DASH_DIR, "index.html"), "w") as f:
    f.write(HTML)

print("Dashboard written:", os.path.abspath(os.path.join(DASH_DIR, "index.html")))
