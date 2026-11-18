"""Narration script and slide HTML for the course video."""

from __future__ import annotations

CSS = r"""
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: #050914; }
body { font-family: 'Noto Sans', 'DejaVu Sans', sans-serif; }
.slide {
  width: 1920px; height: 1080px; position: relative; overflow: hidden;
  padding: 74px 96px 58px; color: #e5eefc;
  background:
    radial-gradient(1200px 700px at 82% 12%, rgba(14,165,233,.14), transparent 55%),
    radial-gradient(900px 600px at 8% 100%, rgba(34,197,94,.09), transparent 55%),
    linear-gradient(135deg, #08101f 0%, #0b1324 52%, #0c1830 100%);
}
.slide::before {
  content: ""; position: absolute; inset: 0; pointer-events: none;
  background-image: linear-gradient(rgba(148,163,184,.055) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148,163,184,.055) 1px, transparent 1px);
  background-size: 52px 52px;
  mask-image: linear-gradient(180deg, rgba(0,0,0,.65), transparent 70%);
}
.slide::after {
  content: ""; position: absolute; width: 660px; height: 660px; right: -260px; top: -260px;
  border: 1px solid rgba(56,189,248,.18); border-radius: 50%;
  box-shadow: 0 0 0 70px rgba(56,189,248,.025), 0 0 0 140px rgba(56,189,248,.018);
}
.kicker { color: #38bdf8; font-size: 21px; font-weight: 700; letter-spacing: .18em; text-transform: uppercase; }
h1 { margin: 18px 0 16px; font-size: 78px; line-height: 1.02; letter-spacing: -.035em; font-weight: 800; }
h2 { margin: 15px 0 26px; font-size: 57px; line-height: 1.07; letter-spacing: -.03em; font-weight: 750; }
h3 { margin: 0 0 14px; font-size: 28px; font-weight: 700; color: #f8fafc; }
p { margin: 0; }
.lead { color: #b6c5d9; font-size: 30px; line-height: 1.45; }
.subtle { color: #7f93ad; font-size: 22px; line-height: 1.35; }
.mono { font-family: 'DejaVu Sans Mono', monospace; }
.footer {
  position: absolute; left: 96px; right: 96px; bottom: 34px;
  display: flex; justify-content: space-between; align-items: center;
  color: #60728b; font-size: 19px; letter-spacing: .02em;
  border-top: 1px solid rgba(148,163,184,.18); padding-top: 15px;
}
.footer b { color: #8fa4bf; font-weight: 600; }
.slide-no { font-variant-numeric: tabular-nums; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 30px; }
.grid3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; }
.card {
  background: linear-gradient(180deg, rgba(15,23,42,.88), rgba(15,23,42,.68));
  border: 1px solid rgba(56,189,248,.20); border-radius: 22px; padding: 26px 28px;
  box-shadow: 0 18px 50px rgba(0,0,0,.22);
}
.card.green { border-color: rgba(52,211,153,.26); }
.card.orange { border-color: rgba(251,146,60,.28); }
.chip {
  display: inline-flex; align-items: center; gap: 10px;
  border: 1px solid rgba(56,189,248,.32); background: rgba(14,165,233,.10);
  color: #bae6fd; padding: 10px 16px; border-radius: 999px; font-size: 20px; font-weight: 600;
}
.chip.green { border-color: rgba(52,211,153,.32); background: rgba(34,197,94,.09); color: #bbf7d0; }
.chip.orange { border-color: rgba(251,146,60,.34); background: rgba(249,115,22,.09); color: #fed7aa; }
.row { display: flex; align-items: center; gap: 16px; }
.big-number { font-size: 66px; line-height: 1; font-weight: 800; letter-spacing: -.03em; }
.big-number.blue { color: #38bdf8; }
.big-number.green { color: #34d399; }
.big-number.orange { color: #fb923c; }
.label { color: #8ea4be; font-size: 20px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; }
.metric-card { padding: 22px 24px; border-radius: 18px; background: rgba(15,23,42,.78); border: 1px solid rgba(148,163,184,.16); }
.metric-card .v { font-size: 44px; font-weight: 800; letter-spacing: -.03em; margin-top: 5px; }
.metric-card .n { font-size: 19px; color: #93a8c3; margin-top: 7px; }
table { width: 100%; border-collapse: collapse; font-size: 23px; }
th { text-align: left; color: #7dd3fc; font-size: 18px; letter-spacing: .09em; text-transform: uppercase; padding: 0 12px 13px; border-bottom: 1px solid rgba(125,211,252,.24); }
td { padding: 12px; border-bottom: 1px solid rgba(148,163,184,.13); color: #d8e4f4; }
td code, code { font-family: 'DejaVu Sans Mono', monospace; font-size: .9em; color: #bae6fd; }
.code {
  font-family: 'DejaVu Sans Mono', monospace;
  background: #060c18; border: 1px solid rgba(125,211,252,.18); border-radius: 14px;
  padding: 18px 20px; color: #d6e9ff; font-size: 19px; line-height: 1.6; white-space: pre-wrap;
}
.divider { height: 1px; background: rgba(148,163,184,.18); margin: 22px 0; }
.note { color: #7f93ad; font-size: 19px; line-height: 1.45; }
.hl { color: #7dd3fc; }
.hl-green { color: #6ee7b7; }
.hl-orange { color: #fdba74; }
.arrow { color: #38bdf8; font-size: 32px; font-weight: 700; }
.flow { display: flex; align-items: stretch; gap: 14px; }
.flow .box { flex: 1; border: 1px solid rgba(125,211,252,.2); background: rgba(15,23,42,.72); border-radius: 18px; padding: 20px; }
.flow .box .t { font-size: 21px; font-weight: 750; color: #f8fafc; }
.flow .box .d { margin-top: 9px; font-size: 17px; line-height: 1.4; color: #8fa4bf; }
.diagram-note { margin-top: 16px; color: #7f93ad; font-size: 18px; }
.figure-card { background: #f8fbff; border-radius: 16px; padding: 10px; border: 1px solid rgba(56,189,248,.22); overflow: hidden; }
.figure-card img { width: 100%; height: 100%; object-fit: contain; display: block; }
.badge { position: absolute; top: 75px; right: 96px; color: #60728b; font-size: 20px; font-family: 'DejaVu Sans Mono', monospace; }
.battery { position: absolute; right: 96px; bottom: 150px; width: 620px; height: 360px; }
.live-dot { width: 14px; height: 14px; border-radius: 50%; background: #34d399; box-shadow: 0 0 22px #34d399; display: inline-block; margin-right: 12px; }
.two-col { display: grid; grid-template-columns: .92fr 1.08fr; gap: 34px; }
.small-h { font-size: 20px; color: #7dd3fc; text-transform: uppercase; letter-spacing: .12em; font-weight: 700; margin-bottom: 13px; }
.kpi-row { display: flex; gap: 18px; margin-top: 24px; }
.kpi { flex: 1; padding: 16px 18px; border-radius: 14px; background: rgba(2,6,23,.45); border: 1px solid rgba(148,163,184,.16); }
.kpi .v { font-size: 34px; font-weight: 800; color: #f8fafc; letter-spacing: -.02em; }
.kpi .l { font-size: 17px; color: #7f93ad; margin-top: 4px; }
"""

BATTERY_SVG = """
<svg class="battery" viewBox="0 0 620 360" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="cell" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#38bdf8" stop-opacity=".28"/>
      <stop offset="1" stop-color="#0ea5e9" stop-opacity=".05"/>
    </linearGradient>
    <linearGradient id="cell2" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#34d399" stop-opacity=".30"/>
      <stop offset="1" stop-color="#10b981" stop-opacity=".05"/>
    </linearGradient>
    <filter id="glow"><feGaussianBlur stdDeviation="5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  </defs>
  <rect x="12" y="30" width="596" height="292" rx="26" stroke="#38bdf8" stroke-opacity=".5" stroke-width="2"/>
  <rect x="560" y="124" width="24" height="104" rx="8" fill="#38bdf8" fill-opacity=".15" stroke="#38bdf8" stroke-opacity=".35"/>
  <g filter="url(#glow)">
    <rect x="42" y="70" width="30" height="210" rx="8" fill="url(#cell)" stroke="#38bdf8" stroke-opacity=".6"/>
    <rect x="82" y="70" width="30" height="210" rx="8" fill="url(#cell)" stroke="#38bdf8" stroke-opacity=".6"/>
    <rect x="122" y="70" width="30" height="210" rx="8" fill="url(#cell)" stroke="#38bdf8" stroke-opacity=".6"/>
    <rect x="162" y="70" width="30" height="210" rx="8" fill="url(#cell)" stroke="#38bdf8" stroke-opacity=".6"/>
    <rect x="202" y="70" width="30" height="210" rx="8" fill="url(#cell2)" stroke="#34d399" stroke-opacity=".65"/>
    <rect x="242" y="70" width="30" height="210" rx="8" fill="url(#cell2)" stroke="#34d399" stroke-opacity=".65"/>
    <rect x="282" y="70" width="30" height="210" rx="8" fill="url(#cell)" stroke="#38bdf8" stroke-opacity=".6"/>
    <rect x="322" y="70" width="30" height="210" rx="8" fill="url(#cell)" stroke="#38bdf8" stroke-opacity=".6"/>
    <rect x="362" y="70" width="30" height="210" rx="8" fill="url(#cell)" stroke="#38bdf8" stroke-opacity=".6"/>
    <rect x="402" y="70" width="30" height="210" rx="8" fill="url(#cell)" stroke="#38bdf8" stroke-opacity=".6"/>
    <rect x="442" y="70" width="30" height="210" rx="8" fill="url(#cell2)" stroke="#34d399" stroke-opacity=".65"/>
    <rect x="482" y="70" width="30" height="210" rx="8" fill="url(#cell)" stroke="#38bdf8" stroke-opacity=".6"/>
    <rect x="522" y="70" width="30" height="210" rx="8" fill="url(#cell)" stroke="#38bdf8" stroke-opacity=".6"/>
  </g>
  <rect x="40" y="302" width="80" height="30" rx="8" fill="#0f172a" stroke="#38bdf8" stroke-opacity=".35"/>
  <text x="50" y="323" fill="#7dd3fc" font-family="monospace" font-size="14">BMS</text>
  <path d="M200 333 C260 333 280 310 340 310 C400 310 430 330 490 330" stroke="#34d399" stroke-opacity=".6" stroke-width="2" stroke-dasharray="6 7"/>
  <circle cx="490" cy="330" r="4" fill="#34d399"/>
  <text x="50" y="58" fill="#8fa4bf" font-family="monospace" font-size="16">13 cells in series · ~10 Ah</text>
</svg>
"""


def slide(kicker: str, title: str, body: str, number: int, total: int = 11) -> str:
    return f"""
<div class="slide" id="slide-{number:02d}">
  <div class="badge">{number:02d} / {total:02d}</div>
  <div class="kicker">{kicker}</div>
  <h2>{title}</h2>
  {body}
  <div class="footer">
    <span><b>Battery Digital Twin</b> · 48 V / 13S · MQTT · EKF + RLS</span>
    <span class="slide-no">course project · {number:02d}</span>
  </div>
</div>
"""


SLIDES: list[dict] = []

SLIDES.append(
    {
        "name": "01_title",
        "pause_s": 1.0,
        "html": f"""
<div class="slide" id="slide-01">
  <div class="badge">01 / 11</div>
  <div style="position:absolute; left:96px; top:126px; width:1080px;">
    <div class="kicker">Digital Twin · Course Project</div>
    <h1>A 48 V battery pack<br>with a living digital twin.</h1>
    <p class="lead" style="max-width:920px;">Hidden-state estimation, anomaly explanation, and what-if decision support. Built with a plant simulator, MQTT, SQLite, an EKF, and a live Streamlit service.</p>
    <div class="row" style="margin-top:44px; flex-wrap:wrap;">
      <span class="chip">13S · 10 Ah</span>
      <span class="chip">1 Hz telemetry</span>
      <span class="chip green">EKF + RLS</span>
      <span class="chip orange">measured, not claimed</span>
    </div>
  </div>
  {BATTERY_SVG}
  <div class="footer"><span><b>Battery Digital Twin</b> · course project</span><span class="slide-no">01 / 11</span></div>
</div>
""",
        "narration": (
            "Battery packs are everywhere: scooters, robots, and small storage systems. "
            "But the states that matter are hidden. The operator sees voltage, current, and surface temperature, "
            "not the state of charge, the internal resistance, or the core temperature. "
            "Failures are often handled after they happen. "
            "This project builds a digital twin for a 48 volt, thirteen cell pack, about ten amp hours. "
            "The user is a fleet or storage operator who needs three answers: how much runtime is left, "
            "is the pack getting less healthy, and will the planned load overheat it? "
            "The twin estimates hidden states from measurements, predicts remaining runtime, explains anomalies, "
            "and supports what-if decisions. We built all five components: acquisition, MQTT communication, "
            "data management, a hybrid model, and a user service. Every claim is backed by an executable check or a measured number."
        ),
    }
)

SLIDES.append(
    {
        "name": "02_problem",
        "pause_s": 0.8,
        "html": slide(
            "01 · Problem and user",
            "The states that matter are hidden.",
            """
<div class="grid3" style="margin-top:22px;">
  <div class="card">
    <div class="small-h">What is measured</div>
    <div style="display:flex; flex-direction:column; gap:16px; margin-top:12px;">
      <div class="chip mono">voltage_V</div>
      <div class="chip mono">current_A</div>
      <div class="chip mono">surface_temp_C</div>
    </div>
    <p class="note" style="margin-top:22px;">Raw signals are necessary, but they do not directly answer an operational question.</p>
  </div>
  <div class="card green">
    <div class="small-h" style="color:#6ee7b7;">What the operator needs</div>
    <div class="metric-card" style="margin-top:12px; background:rgba(6,78,59,.18); border-color:rgba(52,211,153,.20);">
      <div class="label">How long?</div><div class="v" style="font-size:31px;">SoC → runtime</div>
    </div>
    <div class="metric-card" style="margin-top:12px; background:rgba(6,78,59,.18); border-color:rgba(52,211,153,.20);">
      <div class="label">Degrading?</div><div class="v" style="font-size:31px;">R0 → SoH</div>
    </div>
    <div class="metric-card" style="margin-top:12px; background:rgba(6,78,59,.18); border-color:rgba(52,211,153,.20);">
      <div class="label">Overheat?</div><div class="v" style="font-size:31px;">T_core + load</div>
    </div>
  </div>
  <div class="card orange">
    <div class="small-h" style="color:#fdba74;">What the twin adds</div>
    <p class="lead" style="font-size:25px; margin-top:10px;">Update on every new measurement:</p>
    <div class="kpi-row" style="flex-direction:column; gap:14px; margin-top:20px;">
      <div class="kpi"><div class="v">EKF</div><div class="l">fuse voltage + thermal measurements</div></div>
      <div class="kpi"><div class="v">Residuals</div><div class="l">detect and explain faults</div></div>
      <div class="kpi"><div class="v">Forward sim</div><div class="l">answer what-if load scenarios</div></div>
    </div>
  </div>
</div>
<div class="card" style="margin-top:24px; padding:18px 24px; border-color:rgba(56,189,248,.18); background:rgba(14,165,233,.07);">
  <p class="lead" style="font-size:23px;">A digital twin is useful only if it estimates states that are <span class="hl">not directly measured</span> and turns them into a decision.</p>
</div>
""",
            2,
        ),
        "narration": (
            "So the project is built around hidden states. On the left are the measurements: voltage, current, "
            "and surface temperature. In the middle are the three questions that operators actually ask: how much runtime is left, "
            "is the pack degrading, and will a planned load overheat it? "
            "On the right is what the twin adds. An extended Kalman filter fuses measurements; residuals detect and explain faults; "
            "and forward simulation answers what-if scenarios. This is the value of a digital twin: it turns raw signals into an actionable estimate."
        ),
    }
)

SLIDES.append(
    {
        "name": "03_architecture",
        "pause_s": 0.8,
        "html": slide(
            "02 · Architecture",
            "Five components, one feedback loop.",
            f"""
<div class="flow" style="margin-top:18px;">
  <div class="box" style="border-color:rgba(56,189,248,.45);"><div class="t">1 · Plant simulator</div><div class="d">2RC electrical<br>two-node thermal<br>noise, aging, faults</div></div>
  <div class="arrow">→</div>
  <div class="box" style="border-color:rgba(52,211,153,.45);"><div class="t">2 · MQTT broker</div><div class="d">telemetry · commands<br>QoS1 · retained status<br>last will</div></div>
  <div class="arrow">→</div>
  <div class="box" style="border-color:rgba(251,146,60,.48);"><div class="t">4 · Twin</div><div class="d">1RC + EKF + RLS<br>anomaly detection<br>what-if predictor</div></div>
  <div class="arrow">→</div>
  <div class="box" style="border-color:rgba(168,85,247,.45);"><div class="t">5 · Dashboard</div><div class="d">monitor<br>explain · decide<br>SQLite history</div></div>
</div>
<div style="display:flex; justify-content:center; gap:20px; margin-top:18px; color:#52647d; font-size:19px;">
  <span>telemetry ───────────────────────────────→</span><span>twin/state + alarms ─────────────────────→</span>
</div>
<div class="flow" style="margin-top:18px; width:62%;">
  <div class="box"><div class="t">3 · Ingestor</div><div class="d">validate · dedupe · gaps</div></div>
  <div class="arrow">→</div>
  <div class="box"><div class="t">SQLite</div><div class="d">raw + clean + twin_outputs + alarms</div></div>
  <div class="arrow">→</div>
  <div class="box"><div class="t">history / CSV</div><div class="d">auditable evidence</div></div>
</div>
<div class="grid2" style="margin-top:24px;">
  <div class="card green" style="padding:20px 24px;"><div class="small-h" style="color:#6ee7b7;">Critical separation</div><p class="lead" style="font-size:24px;">The plant parameters are private. Truth is written only to a local CSV. The twin never subscribes to truth.</p></div>
  <div class="card orange" style="padding:20px 24px;"><div class="small-h" style="color:#fdba74;">Why it matters</div><p class="lead" style="font-size:24px;">A different model structure and different parameters make accuracy a real test, not circular validation.</p></div>
</div>
""",
            3,
        ),
        "narration": (
            "The architecture has five moving parts. On the left, the plant simulator represents the real world. "
            "It uses a two-RC electrical model, a two-node thermal model, temperature-dependent resistance, aging drift, noise, and packet loss. "
            "It publishes telemetry at one hertz over MQTT. The same broker feeds the ingestor and the twin. "
            "The ingestor validates data and writes SQLite. The twin runs a deliberately different model: one RC, one thermal node, "
            "an extended Kalman filter, and online resistance tracking. It publishes state and alarms. The dashboard consumes live MQTT and historical SQLite data. "
            "The critical design choice is separation. Plant parameters are private, and truth is written only to a local CSV. "
            "The twin never subscribes to truth. That avoids validating a model against itself."
        ),
    }
)

SLIDES.append(
    {
        "name": "04_acquisition",
        "pause_s": 0.8,
        "html": slide(
            "03 · Acquisition",
            "Five signals, explicit assumptions.",
            f"""
<div class="two-col">
  <div class="card">
    <div class="small-h">Telemetry at the edge</div>
    <table>
      <tr><th>Variable</th><th>Unit</th><th>Rate</th></tr>
      <tr><td><code>voltage_V</code></td><td>V</td><td>1 Hz</td></tr>
      <tr><td><code>current_A</code></td><td>A · discharge +</td><td>1 Hz</td></tr>
      <tr><td><code>surface_temp_C</code></td><td>°C · NTC</td><td>1 Hz</td></tr>
      <tr><td><code>ambient_temp_C</code></td><td>°C</td><td>0.1 Hz</td></tr>
      <tr><td><code>seq</code> + <code>ts</code></td><td>— / ISO-8601</td><td>each message</td></tr>
    </table>
    <div class="divider"></div>
    <p class="note">Simulation speed is configurable. Source timestamps are simulated time; SQLite also records wall-clock ingest time. Freshness must use <span class="hl">ts_ingest</span>.</p>
  </div>
  <div>
    <div class="grid2">
      <div class="card" style="padding:20px 22px;"><div class="small-h">Plant</div><p class="lead" style="font-size:23px;">2RC · Arrhenius R0<br>core + surface nodes<br>noise, quantization, loss</p><div class="chip orange" style="margin-top:16px;">private params</div></div>
      <div class="card green" style="padding:20px 22px;"><div class="small-h" style="color:#6ee7b7;">Twin</div><p class="lead" style="font-size:23px;">1RC · one thermal node<br>HPPC parameters<br>only telemetry</p><div class="chip green" style="margin-top:16px;">no truth</div></div>
    </div>
    <div class="card" style="margin-top:20px; padding:20px 24px;">
      <div class="small-h">Assumptions written down</div>
      <p class="note" style="font-size:20px;">balanced cells · constant capacity per run · literature OCV curve · fixed convection · no hysteresis <span style="color:#475569;">— all listed as limitations</span></p>
    </div>
    <div class="row" style="margin-top:18px;">
      <span class="chip mono">±5 mV</span><span class="chip mono">±0.05 A</span><span class="chip mono">±0.5 °C</span><span class="chip orange">0.5% loss</span>
    </div>
  </div>
</div>
""",
            4,
        ),
        "narration": (
            "The acquisition table has five signals: pack voltage and current at one hertz, surface temperature at one hertz, "
            "ambient temperature at zero point one hertz, and a sequence plus source timestamp on every message. Current is positive on discharge. "
            "The simulator adds voltage, current, and temperature noise, quantization, and a small packet loss rate. It also supports a simulation speed multiplier, "
            "so a two-hour discharge can be demonstrated in six minutes. Source time is simulation time; ingest time is wall-clock time. "
            "The assumptions are explicit: cells are balanced, capacity is constant within a run, the OCV curve comes from literature, convection is fixed, "
            "and hysteresis is ignored. The plant uses private parameters; the twin only receives telemetry."
        ),
    }
)

SLIDES.append(
    {
        "name": "05_mqtt",
        "pause_s": 0.8,
        "html": slide(
            "04 · Communication",
            "MQTT: one contract for every component.",
            f"""
<div class="two-col">
  <div class="card">
    <div class="small-h">Topics under <code>dt/battery/pack01/</code></div>
    <table>
      <tr><th>Topic</th><th>Content</th><th>QoS / option</th></tr>
      <tr><td><code>telemetry</code></td><td>V, I, T, ambient, seq</td><td>1</td></tr>
      <tr><td><code>twin/state</code></td><td>SoC, R0, T_core, runtime</td><td>1</td></tr>
      <tr><td><code>twin/alarm</code></td><td>code + reason + advice</td><td>1</td></tr>
      <tr><td><code>cmd/load · cmd/fault</code></td><td>operator actions</td><td>1</td></tr>
      <tr><td><code>whatif/request · response</code></td><td>decision support</td><td>1</td></tr>
      <tr><td><code>meta · status</code></td><td>units · online/offline</td><td>retained</td></tr>
    </table>
    <div class="row" style="margin-top:20px;"><span class="chip green">LWT offline</span><span class="chip">clean_session = false</span><span class="chip">units in field names</span></div>
  </div>
  <div>
    <div class="code">$ python scripts/mqtt_monitor.py

dt/battery/pack01/telemetry
{{"seq":1532,"voltage_V":46.82,
 "current_A":12.4,"surface_temp_C":31.6}}

dt/battery/pack01/twin/state
{{"soc":0.712,"r0_ohm":0.104,
 "t_core_C":33.1,"remaining_s":4200}}

dt/battery/pack01/twin/alarm
{{"code":"THERMAL_ANOMALY",
 "reason":"temperature +5.8 C vs twin"}}</div>
    <div class="card orange" style="margin-top:20px; padding:18px 22px;">
      <p class="lead" style="font-size:23px;">The dashboard subscribes to live state; the ingestor subscribes to the same broker for history. A late subscriber immediately receives retained metadata and status.</p>
    </div>
  </div>
</div>
""",
            5,
        ),
        "narration": (
            "Communication uses MQTT only. There are separate topics for telemetry, metadata, status, twin state, twin alarms, "
            "load commands, fault injection, and what-if requests and responses. Telemetry and twin outputs use QoS one. "
            "Meta and status are retained, so a dashboard that connects late immediately knows the units and the asset state. "
            "Status also configures a last will: if the simulator dies, the broker publishes offline, retained. "
            "The ingestor uses a persistent session, so a normal disconnect does not drop QoS one messages. Commands are logged to SQLite. "
            "Field names carry units. In the demo you will see actual topic traffic and the resulting dashboard updates."
        ),
    }
)

SLIDES.append(
    {
        "name": "06_data",
        "pause_s": 0.8,
        "html": slide(
            "05 · Data management",
            "Raw and clean side by side.",
            f"""
<div class="flow" style="margin-top:10px;">
  <div class="box"><div class="t">raw JSON</div><div class="d">every topic + payload + arrival</div></div><div class="arrow">→</div>
  <div class="box"><div class="t">validate</div><div class="d">schema · units · ranges</div></div><div class="arrow">→</div>
  <div class="box"><div class="t">dedupe</div><div class="d">unique run + seq + variable</div></div><div class="arrow">→</div>
  <div class="box"><div class="t">gap / NaN</div><div class="d">never fill missing with zero</div></div><div class="arrow">→</div>
  <div class="box"><div class="t">1 Hz grid</div><div class="d">alignment for analysis</div></div><div class="arrow">→</div>
  <div class="box" style="border-color:rgba(52,211,153,.4);"><div class="t">SQLite</div><div class="d">query · CSV · dashboard</div></div>
</div>
<div class="two-col" style="margin-top:24px;">
  <div class="card">
    <div class="small-h">Narrow, auditable measurement table</div>
    <div class="code" style="font-size:18px;">measurements(
  asset_id, variable, value, unit,
  ts_source, ts_ingest, seq, quality
)
UNIQUE(asset_id, run_id, seq, variable)
INDEX(asset_id, variable, ts_source)</div>
    <p class="note" style="margin-top:18px;">Also stored: <code>twin_outputs</code>, <code>alarms</code>, <code>data_gaps</code>, <code>commands</code>, <code>runs</code>, <code>asset_status</code>, <code>asset_meta</code>.</p>
  </div>
  <div class="card green">
    <div class="small-h" style="color:#6ee7b7;">Query and export</div>
    <div class="code" style="font-size:18px;">SELECT variable, value, unit,
       ts_source, ts_ingest, quality
FROM measurements
WHERE asset_id = 'pack01'
  AND variable = 'voltage_V'
ORDER BY ts_source DESC
LIMIT 100;</div>
    <p class="note" style="margin-top:18px;">WAL mode and batched commits keep ingestion fast on a slow filesystem. Raw messages are never overwritten by cleaning.</p>
  </div>
</div>
""",
            6,
        ),
        "narration": (
            "Data management starts with a raw message table that keeps every JSON payload, topic, and arrival time. "
            "Then a narrow clean table stores asset, variable, value, unit, source time, ingest time, sequence, and quality. "
            "Every message is range checked; impossible values are marked invalid. A uniqueness constraint removes duplicates. "
            "Sequence gaps are recorded as gaps, not filled with zero. For offline analysis, a one-hertz alignment function keeps missing values as NaN. "
            "The database uses WAL and batched commits. Queries and CSV export are available from the dashboard and a small CLI. "
            "This separation keeps the twin auditable: raw data is never overwritten by cleaning."
        ),
    }
)

SLIDES.append(
    {
        "name": "07_model",
        "pause_s": 0.8,
        "html": slide(
            "06 · Model",
            "Physics, with a data-driven correction.",
            f"""
<div class="grid2">
  <div class="card orange">
    <div class="small-h" style="color:#fdba74;">Plant · the simulated real world</div>
    <div class="code" style="border-color:rgba(251,146,60,.22);">V = OCV(SoC) − I·R0 − V1 − V2
R0(T) = R0_ref · exp(Ea/R · (1/T − 1/T_ref))
core ↔ surface ↔ ambient  (two nodes)
+ aging drift · noise · quantization · loss</div>
    <p class="note" style="margin-top:16px;">2RC, Arrhenius resistance, two-node thermal model, aging drift.</p>
  </div>
  <div class="card green">
    <div class="small-h" style="color:#6ee7b7;">Twin · deployed reduced model</div>
    <div class="code" style="border-color:rgba(52,211,153,.22);">V = OCV(SoC) − I·R0 − V1
dV1/dt = −V1/(R1C1) + I/C1
dSoC/dt = −I/(3600·Q)
Cth·dT/dt = I²R0 + I·V1 − hA(T−Tamb)</div>
    <p class="note" style="margin-top:16px;">1RC + one thermal node. Deliberately simpler than the plant.</p>
  </div>
</div>
<div class="grid3" style="margin-top:22px;">
  <div class="card"><div class="small-h">EKF</div><p class="lead" style="font-size:23px;">state = SoC, RC voltage, surface temperature. Update with measured V and T.</p></div>
  <div class="card"><div class="small-h">R0 / SoH</div><p class="lead" style="font-size:23px;">RLS slow tracking; 45 s residual regression separates ΔR0 from sensor offset. SoH = R0_nom / R0_est.</p></div>
  <div class="card" style="border-color:rgba(56,189,248,.32);"><div class="small-h">HPPC identification</div><p class="lead" style="font-size:22px;">least squares on measured V/I/T only.<br><span class="hl-green">R0 0.104 Ω · R1 0.056 Ω · C1 1248 F</span><br>fit RMSE <span class="hl-green">8.8 mV</span></p></div>
</div>
<div class="card" style="margin-top:18px; padding:16px 22px; background:rgba(14,165,233,.07); border-color:rgba(56,189,248,.2);">
  <p class="lead" style="font-size:22px;">Remaining runtime and what-if use the same state: constant-current forward simulation to cutoff voltage or temperature limit.</p>
</div>
""",
            7,
        ),
        "narration": (
            "The plant and twin intentionally differ. The plant is a two-RC model. Its resistance follows an Arrhenius temperature law, "
            "and it has two thermal nodes, core and surface, plus aging drift. The twin is a one-RC model with a single thermal node. "
            "Its voltage is OCV of state of charge, minus current times R zero, minus the RC polarization. State of charge integrates current; "
            "the thermal node balances Joule heating against convection. "
            "The twin does not trust the initial state of charge. It starts at sixty percent while the plant starts at ninety-five. "
            "An extended Kalman filter estimates SoC, RC voltage, and surface temperature. A recursive least-squares tracker updates resistance, "
            "and a short-window regression separates a resistance change from a voltage-sensor offset. State of health is nominal resistance divided by estimated resistance. "
            "Offline, parameters are identified from HPPC data using least squares on measured voltage, current, and temperature only. "
            "The fit is eight point eight millivolts RMS."
        ),
    }
)

SLIDES.append(
    {
        "name": "08_t1_t3",
        "pause_s": 0.8,
        "html": slide(
            "07 · Evaluation · T1–T3",
            "Accuracy, convergence, and runtime.",
            f"""
<div class="grid3" style="margin-top:6px;">
  <div>
    <div class="figure-card" style="height:300px;"><img src="../../reports/figures/t1_voltage_error.png"></div>
    <div class="row" style="margin-top:16px;"><span class="big-number blue" style="font-size:48px;">13.0</span><span class="lead" style="font-size:22px;">mV RMS<br>on unseen cycle</span></div>
    <p class="note">No-RC baseline: 285.9 mV max. 1RC max error: 42.1 mV.</p>
  </div>
  <div>
    <div class="figure-card" style="height:300px;"><img src="../../reports/figures/t2_soc_convergence.png"></div>
    <div class="row" style="margin-top:16px;"><span class="big-number green" style="font-size:48px;">6 s</span><span class="lead" style="font-size:22px;">to ±2%<br>from −35 points</span></div>
    <p class="note">Post-convergence SoC RMSE: 0.11%. Wrong-initial coulomb counter: 35% RMSE.</p>
  </div>
  <div>
    <div class="figure-card" style="height:300px;"><img src="../../reports/figures/t3_endurance.png"></div>
    <div class="row" style="margin-top:16px;"><span class="big-number orange" style="font-size:48px;">4.23%</span><span class="lead" style="font-size:22px;">MAPE<br>vs 104% linear</span></div>
    <p class="note">10 checkpoints over a two-hour drive cycle; actual cutoff at 109 min.</p>
  </div>
</div>
<div class="card" style="margin-top:24px; padding:16px 22px;">
  <p class="lead" style="font-size:22px;">The baselines are deliberately simple: no RC, pure coulomb counting, and linear voltage extrapolation. The twin wins on all three, with numbers rather than adjectives.</p>
</div>
""",
            8,
        ),
        "narration": (
            "Now the quantitative part. First, open-loop voltage accuracy on a drive cycle that was not used for identification. "
            "The one-RC twin has thirteen millivolts RMS error and forty-two millivolts maximum error. A no-relaxation baseline is two hundred eighty-six millivolts, "
            "so the RC branch matters. Second, state of charge. Starting deliberately wrong by thirty-five points, the filter converges within two percent in six seconds. "
            "After convergence, RMSE is zero point one one percent. A pure coulomb counter with the same wrong initial value stays at thirty-five percent error. "
            "Third, endurance. At ten checkpoints on a two-hour drive cycle, the twin predicts time to cutoff with four point two percent mean absolute percentage error. "
            "Linear voltage extrapolation has over one hundred percent error because load changes make the voltage slope misleading. "
            "These are the kinds of numbers that separate a model from a curve."
        ),
    }
)

SLIDES.append(
    {
        "name": "09_t4_t5",
        "pause_s": 0.8,
        "html": slide(
            "08 · Evaluation · T4–T5",
            "Faults and robustness, measured.",
            f"""
<div class="grid2">
  <div class="card">
    <div class="small-h">T4 · detection delay after injection</div>
    <div class="figure-card" style="height:330px; background:#fff;"><img src="../../reports/figures/t4_detection_delay.png"></div>
    <div class="row" style="margin-top:14px; flex-wrap:wrap;"><span class="chip green">0 false alarms / 1 h</span><span class="chip">R0 63 s</span><span class="chip orange">cooling 352 s</span><span class="chip">V-sensor 1 s</span></div>
    <p class="note" style="margin-top:12px;">Thresholds are calibrated on normal data only. Fixed temperature threshold: 1158 s.</p>
  </div>
  <div class="card">
    <div class="small-h">T5 · 5% packet loss + 2× noise</div>
    <div class="figure-card" style="height:330px; background:#fff;"><img src="../../reports/figures/t5_robustness.png"></div>
    <div class="kpi-row" style="margin-top:14px;">
      <div class="kpi"><div class="v" style="color:#38bdf8;">0.108%</div><div class="l">degraded SoC RMSE</div></div>
      <div class="kpi"><div class="v" style="color:#fb923c;">2×</div><div class="l">voltage residual RMS</div></div>
      <div class="kpi"><div class="v" style="color:#34d399;">stable</div><div class="l">temperature accuracy</div></div>
    </div>
    <p class="note" style="margin-top:12px;">80 dropped sequence gaps were detected; no false alarm was generated.</p>
  </div>
</div>
<div class="card" style="margin-top:22px; padding:16px 22px; border-color:rgba(56,189,248,.2); background:rgba(14,165,233,.06);">
  <p class="lead" style="font-size:22px;">The detector uses pre-fit residuals, CUSUM, a resistance regression, and a SoC/coulomb consistency check. Each alarm explains evidence and recommends an action.</p>
</div>
""",
            9,
        ),
        "narration": (
            "For anomaly detection, thresholds are fixed only from normal data. On one hour of normal operation there are zero false alarms. "
            "A fifty percent resistance step is detected in sixty-three seconds by the residual regression. A cooling failure under load is detected in three hundred fifty-two seconds, "
            "compared with one thousand one hundred fifty-eight seconds for a fixed temperature threshold. A half-volt voltage-sensor step is caught in one second by the acute residual check. "
            "For robustness, we add five percent packet loss and double the sensor noise. State-of-charge RMSE grows from zero point zero nine seven to zero point one zero eight percent. "
            "Voltage residual RMS doubles, as expected, and temperature accuracy is unchanged. This is not perfection, but it is measured degradation."
        ),
    }
)

SLIDES.append(
    {
        "name": "10_demo_intro",
        "pause_s": 0.5,
        "html": slide(
            "09 · Integrated demo",
            "Now: commands, live state, and decisions.",
            """
<div class="grid3" style="margin-top:36px;">
  <div class="card" style="padding:32px;"><div class="small-h">1 · Operate</div><p class="lead" style="font-size:28px;">Change the load.<br>Inject a cooling fault.</p><div class="chip orange" style="margin-top:24px;">cmd/load · cmd/fault</div></div>
  <div class="card green" style="padding:32px;"><div class="small-h" style="color:#6ee7b7;">2 · Update</div><p class="lead" style="font-size:28px;">New telemetry updates<br>SoC, R0 and T_core.</p><div class="chip green" style="margin-top:24px;">twin/state</div></div>
  <div class="card" style="padding:32px;"><div class="small-h">3 · Decide</div><p class="lead" style="font-size:28px;">Explain the alarm.<br>Run a what-if scenario.</p><div class="chip" style="margin-top:24px;">whatif/response</div></div>
</div>
<div class="card" style="margin-top:44px; padding:24px 30px; background:rgba(14,165,233,.07); border-color:rgba(56,189,248,.22);">
  <div class="row" style="gap:14px;"><span class="live-dot"></span><span class="lead" style="font-size:27px;">One command starts broker, ingestor, twin, simulator and dashboard.</span></div>
  <div class="code" style="margin-top:16px; border:none; background:transparent; padding:0; font-size:24px; color:#7dd3fc;">$ python scripts/run_all.py --fresh</div>
</div>
""",
            10,
        ),
        "narration": (
            "Now the live integration demo. The broker, ingestor, twin, simulator, and dashboard are started with one command. "
            "The dashboard is receiving the actual MQTT stream. We will change the load, inject a cooling fault, read the alarm, run a what-if scenario, "
            "and finally trigger the last will by killing the simulator."
        ),
    }
)

SLIDES.append(
    {
        "name": "11_conclusion",
        "pause_s": 1.0,
        "html": slide(
            "10 · Conclusion",
            "What the project proves.",
            """
<div class="grid2">
  <div>
    <div class="card green" style="padding:24px 28px;"><div class="small-h" style="color:#6ee7b7;">Closed loop</div><p class="lead" style="font-size:24px;">Measurements update hidden states. Alarms explain evidence. What-if runs the same physics forward.</p></div>
    <div class="card" style="margin-top:18px; padding:24px 28px;"><div class="small-h">Reproducible</div><p class="lead" style="font-size:24px;">One command starts the stack; 13 tests and an evaluation suite produce the numbers shown here.</p></div>
    <div class="card orange" style="margin-top:18px; padding:24px 28px;"><div class="small-h" style="color:#fdba74;">No truth leakage</div><p class="lead" style="font-size:24px;">Plant parameters and truth stay out of the twin process and out of MQTT.</p></div>
  </div>
  <div class="card" style="padding:28px 30px;">
    <div class="small-h">Honest limits</div>
    <p class="lead" style="font-size:22px; line-height:1.55;">Simulation only · cells treated as identical · 1RC weak at low SoC/low temperature · thresholds calibrated on one duty cycle · small sensor offsets are hard to distinguish · SQLite is single-asset scale.</p>
    <div class="divider"></div>
    <p class="note" style="font-size:20px;">The model/twin mismatch is intentional. It makes the validation a real test rather than a tautology.</p>
    <div class="divider"></div>
    <div class="row"><span class="chip">python scripts/run_all.py --fresh</span><span class="chip green">reports/results.md</span></div>
  </div>
</div>
<div class="card" style="margin-top:24px; padding:18px 24px; background:rgba(14,165,233,.07); border-color:rgba(56,189,248,.2);">
  <p class="lead" style="font-size:23px;">A battery pack is a good digital-twin object because the important states are hidden, the physics is rich, and the decisions are concrete.</p>
</div>
""",
            11,
        ),
        "narration": (
            "What does this project not claim? It is a simulation, not a real pack. Cells are treated as identical, so cell imbalance and local hot spots are out of scope. "
            "The one-RC model degrades at low state of charge and low temperature. The anomaly thresholds are calibrated on one normal duty cycle. "
            "Small sensor offsets are hard to separate from SoC changes, and SQLite is fine for one asset, not a fleet. "
            "Still, the twin closes the loop: measurements update hidden states, alarms explain themselves, and what-if requests use the same physics. "
            "The result is a working, reproducible course project with executable evidence. Thank you."
        ),
    }
)


# Each scene is recorded from the live dashboard. The narration length controls
# how long the recorder stays in that scene.
DEMO_SCENES: list[dict] = [
    {
        "name": "d01_overview",
        "action": "overview",
        "pause_s": 0.8,
        "narration": (
            "This is the live dashboard. The green banner shows fresh MQTT data. "
            "The top row shows state of charge, state of health from resistance, estimated core temperature, and remaining runtime. "
            "The charts compare measured and twin-predicted voltage, temperature, SoC, and residuals. "
            "The twin is updating on every telemetry sample."
        ),
    },
    {
        "name": "d02_load",
        "action": "load",
        "pause_s": 1.5,
        "narration": (
            "I will apply a constant eighteen-amp load for the next hour. "
            "The dashboard publishes a load command to the simulator. The plant changes its current; "
            "new telemetry arrives at one hertz; and the twin recomputes SoC, power loss, temperature, and remaining runtime. "
            "This is the core digital-twin loop: new data changes the digital representation."
        ),
    },
    {
        "name": "d03_fault",
        "action": "fault",
        "pause_s": 2.5,
        "narration": (
            "Now I inject a cooling failure while the pack is under load. "
            "The plant reduces its surface-to-ambient conductance to five percent. "
            "The measured temperature rises faster than the twin thermal model expects, so the pre-fit thermal residual grows. "
            "After the residual stays above the calibrated threshold, the detector raises a thermal anomaly."
        ),
    },
    {
        "name": "d04_alarm",
        "action": "alarm",
        "pause_s": 1.0,
        "narration": (
            "The alarm is not just a red light. It shows the thermal residual and the estimated resistance ratio, "
            "and it recommends reducing load and inspecting the cooling path. I follow the recommendation and reduce the load to five amps. "
            "Normal operation produced zero false alarms with the same thresholds."
        ),
    },
    {
        "name": "d05_whatif",
        "action": "whatif",
        "pause_s": 1.5,
        "narration": (
            "Next, a what-if decision. Twenty amps, thirty minutes, thirty-five degree ambient. "
            "The twin starts from the current SoC, resistance, and temperature, and simulates forward in time. "
            "It reports both the time to cutoff voltage and the time to the temperature limit, "
            "then recommends a safer current. The response comes back over MQTT."
        ),
    },
    {
        "name": "d06_data",
        "action": "data",
        "pause_s": 1.0,
        "narration": (
            "The data tab shows the raw and clean SQLite tables, the latest measurements, source versus ingest timestamps, and CSV export. "
            "Every command and what-if request is also logged for traceability."
        ),
    },
    {
        "name": "d07_lwt",
        "action": "lwt",
        "pause_s": 5.0,
        "narration": (
            "Finally, I kill the simulator. The broker publishes the retained last-will offline status. "
            "The dashboard first warns that data is stale, then turns red after the offline threshold. "
            "The twin and historical database remain available. This is the complete integration path."
        ),
    },
]
