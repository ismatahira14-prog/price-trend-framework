"""Medical Group dashboard - CPI Group 06 (Health).

A light-mode healthcare analytics dashboard recreating the supplied
reference image, populated only with real Group 06 data from IMIS.
Everything is rendered as one hand-built HTML/CSS/SVG canvas inside a
components.html iframe (same technique as the Home page heat-table + map),
so the layout can match the reference without fighting Streamlit widgets.
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from pricelab.dashboard import medical_group as mg  # noqa: E402
from pricelab.dashboard.data import ImisDataError  # noqa: E402


def _nav() -> None:
    a, b, c = st.columns([1, 1, 4])
    try:
        with a:
            st.page_link("pages/0_Home.py", label="Home", icon="🏠")
        with b:
            st.page_link("pages/2_Medical_Group.py", label="Medical Groups", icon="🩺")
    except Exception:  # noqa: BLE001
        a.caption("🏠 Home")
        b.caption("🩺 Medical Groups")


@st.cache_data(ttl=1800, show_spinner="Loading Medical Group (Health) data…")
def _load() -> dict:
    return mg.load_medical_group()


# --------------------------------------------------------------------------- #
# small SVG helpers
# --------------------------------------------------------------------------- #

def _area_chart(series: list[dict], w: int = 300, h: int = 120) -> str:
    vals = [p["value"] for p in series]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    pad = 6
    step = (w - 2 * pad) / (len(vals) - 1)
    pts = [
        (pad + i * step, h - pad - (v - lo) / rng * (h - 2 * pad))
        for i, v in enumerate(vals)
    ]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    fill = f"{pad},{h - pad} " + line + f" {w - pad},{h - pad}"
    return (
        f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" class="mg-spark">'
        f'<polygon points="{fill}" fill="url(#mgGrad)"/>'
        f'<polyline points="{line}" fill="none" stroke="var(--mg-blue)" stroke-width="2.2"/>'
        f'<circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="3.6" fill="var(--mg-blue)"/>'
        f'<defs><linearGradient id="mgGrad" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="var(--mg-blue)" stop-opacity="0.28"/>'
        f'<stop offset="1" stop-color="var(--mg-blue)" stop-opacity="0.02"/>'
        f'</linearGradient></defs></svg>'
    )


def _step_chart(series: list[dict], w: int = 300, h: int = 120) -> str:
    vals = [p["count"] for p in series]
    if len(vals) < 2:
        return ""
    lo, hi = 0, max(vals) or 1
    pad = 8
    step = (w - 2 * pad) / (len(vals) - 1)
    pts = []
    for i, v in enumerate(vals):
        x = pad + i * step
        y = h - pad - v / hi * (h - 2 * pad)
        if i:
            pts.append((x, pts[-1][1]))
        pts.append((x, y))
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    dots = "".join(
        f'<circle cx="{pad + i * step:.1f}" cy="{h - pad - v / hi * (h - 2 * pad):.1f}" '
        f'r="3" fill="var(--mg-mint)"/>'
        for i, v in enumerate(vals) if i % 3 == 0 or i == len(vals) - 1
    )
    return (
        f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" class="mg-spark">'
        f'<polyline points="{line}" fill="none" stroke="var(--mg-mint)" stroke-width="2.4"/>'
        f'{dots}</svg>'
    )


# Rough normalised positions (0-1) of CPI cities on a Pakistan outline.
_CITY_XY = {
    "Islamabad": (0.55, 0.16), "Rawalpindi": (0.54, 0.18), "Peshawar": (0.44, 0.15),
    "Lahore": (0.66, 0.34), "Faisalabad": (0.58, 0.38), "Gujranwala": (0.64, 0.30),
    "Sialkot": (0.68, 0.27), "Multan": (0.52, 0.50), "Bahawalpur": (0.55, 0.56),
    "D. G. Khan": (0.44, 0.52), "Sargodha": (0.56, 0.33), "Sahiwal": (0.60, 0.42),
    "Bannu": (0.40, 0.24), "Karachi": (0.34, 0.90), "Hyderabad": (0.38, 0.82),
    "Sukkur": (0.42, 0.66), "Larkana": (0.38, 0.68), "Nawabshah": (0.40, 0.74),
    "Mirpur Khas": (0.44, 0.84), "Quetta": (0.28, 0.44), "Khuzdar": (0.26, 0.62),
    "Turbat": (0.12, 0.72), "Gwadar": (0.16, 0.80), "Zhob": (0.34, 0.30),
    "Loralai": (0.32, 0.40), "Kalat": (0.28, 0.54), "Mingora": (0.46, 0.09),
    "Abbottabad": (0.50, 0.13), "Mardan": (0.44, 0.13), "Kohat": (0.42, 0.20),
    "D. I. Khan": (0.42, 0.32), "D. M. Jamali": (0.30, 0.58),
}


def _pakistan_map(city_pressure: list[dict]) -> str:
    # very stylised outline - enough to read as "Pakistan"
    outline = (
        "M40,30 L120,18 190,40 260,30 300,70 280,120 320,150 300,210 260,250 "
        "230,320 170,360 120,340 90,270 60,210 40,150 60,90 Z"
    )
    dots = []
    for row in city_pressure[:8]:
        xy = _CITY_XY.get(row["city"])
        if not xy:
            continue
        x, y = 30 + xy[0] * 300, 12 + xy[1] * 360
        diff = row["diff_pct"]
        col = "#d98a4a" if diff > 6 else "#4a90c4" if diff < -6 else "#8aa0b4"
        sign = "+" if diff >= 0 else ""
        dots.append(
            f'<g><circle cx="{x:.0f}" cy="{y:.0f}" r="5" fill="{col}"/>'
            f'<text x="{x + 8:.0f}" y="{y + 3:.0f}" class="mg-map-lbl">'
            f'{html.escape(row["city"])} <tspan fill="{col}">{sign}{diff:.0f}%</tspan></text></g>'
        )
    return (
        '<svg viewBox="0 0 360 384" class="mg-map">'
        f'<path d="{outline}" fill="#e8f1f8" stroke="#cfe0ec" stroke-width="1.5"/>'
        + "".join(dots)
        + "</svg>"
    )


# --------------------------------------------------------------------------- #
# card builders
# --------------------------------------------------------------------------- #

_SUB_META = {
    "Medicines": ("💊", "Everyday care for healthier lives"),
    "Services": ("🩺", "Expert care, stronger communities"),
    "Diagnostics": ("🔬", "Clarity through knowledge"),
    "Procedures": ("🏥", "Advanced care for brighter tomorrows"),
    "Medical Equipment": ("🩹", "Tools that keep families well"),
}


def _chip(pct: float) -> str:
    if pct is None or pct != pct:  # NaN
        return ""
    up = pct >= 0
    cls = "up" if up else "down"
    return f'<span class="mg-chip {cls}">{"+" if up else ""}{pct:.1f}%</span>'


def _rs(v: float) -> str:
    if v is None or v != v:
        return "—"
    return f"Rs {v:,.1f}" if v < 1000 else f"Rs {v:,.0f}"


def _item_card(it: dict, *, big: bool = False) -> str:
    w = it.get("weight")
    wtxt = "" if (w is None or w != w) else f'<span class="mg-w">Weight {w:.3f}</span>'
    rev = it.get("revisions") or 0
    return (
        f'<div class="mg-item{" big" if big else ""}">'
        f'<div class="mg-item-name">{html.escape(str(it["name"]))}</div>'
        f'<div class="mg-item-unit">{html.escape(str(it.get("unit") or ""))}</div>'
        f'<div class="mg-item-price">{_rs(it["price_now"])}</div>'
        f'<div class="mg-item-foot">{wtxt}{_chip(it.get("yoy_pct"))}'
        f'<span class="mg-rev">{rev} rev</span></div>'
        f'</div>'
    )


def _group_column(title: str, items: list[dict]) -> str:
    icon, tagline = _SUB_META.get(title, ("•", ""))
    big = title in ("Procedures",)
    cards = "".join(_item_card(it, big=big) for it in items) or '<div class="mg-empty">No items</div>'
    return (
        f'<section class="mg-col">'
        f'<header class="mg-col-head"><span class="mg-col-icon">{icon}</span>'
        f'<div><div class="mg-col-title">{title}</div>'
        f'<div class="mg-col-tag">{tagline}</div></div>'
        f'<span class="mg-col-count">{len(items)} item{"s" if len(items) != 1 else ""}</span>'
        f'</header><div class="mg-col-body{" grid" if title == "Medicines" else ""}">{cards}</div>'
        f'</section>'
    )


def _kpi(icon: str, value: str, label: str, accent: str) -> str:
    return (
        f'<div class="mg-kpi" style="--acc:{accent}">'
        f'<span class="mg-kpi-icon">{icon}</span>'
        f'<div><div class="mg-kpi-value">{value}</div>'
        f'<div class="mg-kpi-label">{label}</div></div></div>'
    )


def _hero_svg() -> str:
    return (
        '<svg class="mg-hero-art" viewBox="0 0 320 180" aria-hidden="true">'
        '<path d="M20,150 C60,70 110,60 140,150" fill="none" stroke="#bfe0d3" stroke-width="7" stroke-linecap="round"/>'
        '<path d="M235 70 c-10-16-34-16-34 4 c0 18 34 34 34 34 c0-0 34-16 34-34 c0-20-24-20-34-4z" fill="#cfe6f4"/>'
        '<g fill="#cfe0ec">'
        '<circle cx="150" cy="70" r="13"/><rect x="138" y="86" width="24" height="52" rx="11"/>'
        '<circle cx="182" cy="78" r="10"/><rect x="173" y="92" width="18" height="44" rx="9"/>'
        '<circle cx="120" cy="86" r="8"/><rect x="112" y="98" width="16" height="36" rx="8"/>'
        '</g>'
        '<g fill="#d6ead9"><ellipse cx="270" cy="140" rx="26" ry="12"/><ellipse cx="55" cy="150" rx="22" ry="10"/></g>'
        '</svg>'
    )


def _mono_line_chart(series, key, w, h, colorvar):
    return _area_chart(series, w, h) if key == "value" else _step_chart(series, w, h)


# --------------------------------------------------------------------------- #

# Page-local only: widen the content column so this full-bleed dashboard has
# room to match the reference. Scoped to this page's script run - the Home
# page never renders this and keeps its own spacing untouched.
st.markdown(
    """
    <style>
    html body [data-testid="stMainBlockContainer"],
    html body .stMainBlockContainer,
    html body .block-container {
        max-width: 100% !important;
        padding-left: 1.1rem !important;
        padding-right: 1.1rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

_nav()

try:
    D = _load()
except ImisDataError as exc:
    st.error(f"Group 06 data is unavailable: {exc}")
    st.stop()

g = D["group"]
cov = D["coverage"]

kpis = "".join([
    _kpi("📋", str(g["total_items"]), "Total Items", "#4a90c4"),
    _kpi("📈", f'{g["mom_pct"]:+.1f}%', "Overall Change (MoM)", "#5bbfa3"),
    _kpi("⚖️", f'{g["basket_weight"]:.2f}', "Basket Weight", "#e0a25c"),
    _kpi("📅", f'{g["yoy_pct"]:+.1f}%', "Overall Change (YoY)", "#7c9ed4"),
])

groups_html = "".join(_group_column(name, D["subgroups"].get(name, [])) for name in mg.GROUP_ORDER)

# --- bottom row ---
dyn = (
    f'<div class="mg-analytic"><div class="mg-an-head"><span>Group Price Dynamics (Index)</span>'
    f'<b class="mg-an-badge">+{g["yoy_pct"]:.1f}%</b></div>'
    f'{_area_chart(g["index_series"])}'
    f'<div class="mg-an-foot"><span>{g["index_series"][0]["value"]:.0f}</span>'
    f'<span>Rs {g["index_now"]:.0f} · {g["as_of"]}</span></div></div>'
)
timeline = (
    f'<div class="mg-analytic"><div class="mg-an-head"><span>Revisions Timeline</span></div>'
    f'{_step_chart(D["revisions_timeline"])}'
    f'<div class="mg-an-foot"><span>cumulative items revised</span>'
    f'<span>{D["revisions_timeline"][-1]["count"]} of {g["total_items"]}</span></div></div>'
)
rows = "".join(
    f'<tr><td>{i + 1}</td><td>{html.escape(r["name"])}</td><td>{r["revisions"]}</td></tr>'
    for i, r in enumerate(D["most_revised"])
)
most_revised = (
    f'<div class="mg-analytic"><div class="mg-an-head"><span>Most Revised Items</span></div>'
    f'<table class="mg-tbl"><thead><tr><th>#</th><th>Item</th><th>Revisions</th></tr></thead>'
    f'<tbody>{rows}</tbody></table></div>'
)
city_card = (
    f'<div class="mg-analytic"><div class="mg-an-head"><span>Pakistan City Price Pressure</span></div>'
    f'{_pakistan_map(D["city_pressure"])}'
    f'<div class="mg-an-foot"><span>Group 06 avg price vs national</span></div></div>'
)
pair_pills = "".join(
    f'<div class="mg-pair">{html.escape(p["a"])} <i>&harr;</i> {html.escape(p["b"])}'
    f'<span>move together</span></div>'
    for p in D["moves_together"]["item_pairs"]
) or '<div class="mg-pair-empty">No clear item pairs in the available months.</div>'
grp_links = " · ".join(html.escape(x["group"]) for x in D["moves_together"]["group_links"])
rel = (
    f'<div class="mg-analytic"><div class="mg-an-head"><span>Relationship Explorer</span></div>'
    f'{pair_pills}'
    f'<div class="mg-rel-note">Health prices tend to track: <b>{grp_links}</b></div></div>'
)

BODY = f"""
<div class="mg-root">
  <div class="mg-topbar">
    <div class="mg-logo"><span>✚</span> CPI PAKISTAN</div>
    <div class="mg-search">Search items, services or insights…</div>
    <nav class="mg-menu"><a class="mg-menu-a">Home</a><a class="mg-menu-a active">Medical Groups</a></nav>
    <div class="mg-topright"><span class="mg-date">{g["as_of"]}</span><span>🔔</span>
      <span class="mg-avatar">HG</span><span class="mg-user">Health Group 06</span></div>
  </div>

  <header class="mg-hero">
    {_hero_svg()}
    <div class="mg-eyebrow">PAKISTAN CPI</div>
    <h1>Medical Group — Item Mosaic Storyboard</h1>
    <p class="mg-sub">A complete view of medicines, medical equipment, services, diagnostics and procedures</p>
    <p class="mg-tag">Care Today, A Healthier Tomorrow</p>
  </header>

  <div class="mg-kpis">{kpis}</div>

  <div class="mg-groups">{groups_html}</div>

  <div class="mg-analytics">{dyn}{timeline}{most_revised}{city_card}{rel}</div>

  <footer class="mg-footer">Pakistan CPI · Health Group 06 · Item Mosaic Storyboard
    <span>Prices, weights and revisions from PBS CPI (IMIS) · {cov["date_min"]} – {cov["date_max"]}</span>
  </footer>
</div>
"""

CSS = """
<style>
 .mg-root {
   --mg-bg:#f2f6fb; --mg-card:#ffffff; --mg-ink:#20303f; --mg-muted:#7089a0;
   --mg-line:#e4edf4; --mg-blue:#4a90c4; --mg-mint:#5bbfa3; --mg-teal:#3faec0;
   --mg-orange:#e0a25c;
   font-family:Inter,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
   background:var(--mg-bg); color:var(--mg-ink); padding:14px 18px 22px;
   border-radius:16px;
 }
 .mg-root * { box-sizing:border-box; }
 a { text-decoration:none; }

 .mg-topbar { display:flex; align-items:center; gap:14px; padding:4px 4px 14px; flex-wrap:wrap; }
 .mg-logo { flex-shrink:0; font-weight:800; font-size:.78rem; letter-spacing:.06em; color:var(--mg-blue);
   display:flex; align-items:center; gap:6px; white-space:nowrap; }
 .mg-logo span { background:var(--mg-blue); color:#fff; width:22px; height:22px; border-radius:7px;
   display:inline-flex; align-items:center; justify-content:center; font-size:.8rem; flex-shrink:0; }
 .mg-search { flex:1 1 200px; min-width:150px; background:#fff; border:1px solid var(--mg-line);
   border-radius:999px; padding:9px 16px; color:var(--mg-muted); font-size:.82rem;
   white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
   box-shadow:0 2px 8px rgba(31,60,80,.05); }
 .mg-menu { flex-shrink:0; display:flex; gap:6px; }
 .mg-menu-a { padding:7px 14px; border-radius:999px; font-size:.82rem; font-weight:600;
   color:var(--mg-muted); white-space:nowrap; }
 .mg-menu-a.active { background:#e4f4ee; color:#1f7d63; }
 .mg-topright { flex-shrink:0; display:flex; align-items:center; gap:10px; font-size:.8rem; color:var(--mg-muted); }
 .mg-date { background:#fff; border:1px solid var(--mg-line); border-radius:999px; padding:5px 12px;
   white-space:nowrap; }
 .mg-avatar { background:var(--mg-blue); color:#fff; width:26px; height:26px; border-radius:50%;
   display:inline-flex; align-items:center; justify-content:center; font-size:.66rem; font-weight:700; flex-shrink:0; }
 .mg-user { font-weight:600; color:var(--mg-ink); white-space:nowrap; }

 .mg-hero { position:relative; background:linear-gradient(120deg,#ffffff,#eef6fb 70%);
   border:1px solid var(--mg-line); border-radius:18px; padding:22px 26px 20px;
   overflow:hidden; box-shadow:0 6px 22px rgba(31,60,80,.06); }
 .mg-hero-art { position:absolute; right:14px; top:6px; width:280px; height:auto; opacity:.55; }
 .mg-eyebrow { font-size:.66rem; letter-spacing:.16em; color:var(--mg-muted); font-weight:700; }
 .mg-hero h1 { margin:4px 0 4px; font-size:1.7rem; font-weight:800; letter-spacing:-.02em; }
 .mg-sub { margin:0; color:var(--mg-muted); font-size:.9rem; max-width:640px; }
 .mg-tag { margin:10px 0 0; font-family:"Segoe Script","Brush Script MT",cursive;
   color:var(--mg-teal); font-size:1.05rem; }

 .mg-kpis { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:14px 0; }
 .mg-kpi { background:var(--mg-card); border:1px solid var(--mg-line); border-radius:14px;
   padding:14px 16px; display:flex; gap:12px; align-items:center;
   box-shadow:0 4px 16px rgba(31,60,80,.05); }
 .mg-kpi-icon { width:40px; height:40px; border-radius:12px; display:inline-flex; align-items:center;
   justify-content:center; font-size:1.1rem; background:color-mix(in srgb,var(--acc) 15%,#fff);
   color:var(--acc); }
 .mg-kpi-value { font-size:1.5rem; font-weight:800; line-height:1.1; }
 .mg-kpi-label { font-size:.76rem; color:var(--mg-muted); font-weight:600; }

 .mg-groups { display:grid; grid-template-columns:repeat(5,1fr); gap:12px; align-items:start; }
 .mg-col { background:var(--mg-card); border:1px solid var(--mg-line); border-radius:16px;
   padding:12px; box-shadow:0 4px 16px rgba(31,60,80,.05); }
 .mg-col-head { display:flex; align-items:flex-start; gap:9px; padding-bottom:9px;
   border-bottom:1px solid var(--mg-line); margin-bottom:10px; }
 .mg-col-icon { width:30px; height:30px; border-radius:9px; background:#eaf3fa; display:inline-flex;
   align-items:center; justify-content:center; font-size:.95rem; flex-shrink:0; }
 .mg-col-title { font-weight:800; font-size:.92rem; }
 .mg-col-tag { font-size:.66rem; color:var(--mg-muted); }
 .mg-col-count { margin-left:auto; font-size:.66rem; color:var(--mg-muted); background:#f1f6fb;
   border-radius:999px; padding:3px 8px; white-space:nowrap; }
 .mg-col-body { display:flex; flex-direction:column; gap:8px; }
 .mg-col-body.grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
 .mg-item { border:1px solid var(--mg-line); border-radius:11px; padding:9px 10px; background:#fcfdff; }
 .mg-item.big { grid-column:1/-1; padding:14px; background:linear-gradient(160deg,#fff,#f2f8fb); }
 .mg-item-name { font-weight:700; font-size:.78rem; line-height:1.2; }
 .mg-item-unit { font-size:.64rem; color:var(--mg-muted); margin-top:1px; }
 .mg-item-price { font-weight:800; font-size:1rem; margin:5px 0 4px; }
 .mg-item.big .mg-item-price { font-size:1.5rem; }
 .mg-item-foot { display:flex; flex-wrap:wrap; align-items:center; gap:5px; }
 .mg-w { font-size:.6rem; color:var(--mg-muted); }
 .mg-rev { font-size:.6rem; color:var(--mg-muted); background:#eef3f8; border-radius:999px; padding:1px 6px; }
 .mg-chip { font-size:.64rem; font-weight:700; border-radius:999px; padding:1px 7px; }
 .mg-chip.up { background:#e8f5ec; color:#2e9e5b; }
 .mg-chip.down { background:#fdece6; color:#d9683f; }
 .mg-empty { font-size:.72rem; color:var(--mg-muted); padding:8px; }

 .mg-analytics { display:grid; grid-template-columns:repeat(5,1fr); gap:12px; margin-top:14px; }
 .mg-analytic { background:var(--mg-card); border:1px solid var(--mg-line); border-radius:16px;
   padding:12px 14px; box-shadow:0 4px 16px rgba(31,60,80,.05); display:flex; flex-direction:column; gap:8px; }
 .mg-an-head { display:flex; align-items:center; justify-content:space-between; font-size:.78rem;
   font-weight:700; }
 .mg-an-badge { background:#e4f4ee; color:#1f7d63; border-radius:999px; padding:2px 9px; font-size:.72rem; }
 .mg-spark { width:100%; height:110px; }
 .mg-an-foot { display:flex; justify-content:space-between; font-size:.62rem; color:var(--mg-muted); }
 .mg-tbl { width:100%; border-collapse:collapse; font-size:.72rem; }
 .mg-tbl th { text-align:left; color:var(--mg-muted); font-size:.62rem; text-transform:uppercase;
   letter-spacing:.05em; padding:4px 4px; border-bottom:1px solid var(--mg-line); }
 .mg-tbl td { padding:5px 4px; border-bottom:1px solid #f0f5f9; }
 .mg-tbl td:first-child { color:var(--mg-muted); width:18px; }
 .mg-tbl td:last-child { text-align:right; font-weight:700; }
 .mg-map { width:100%; height:230px; }
 .mg-map-lbl { font-size:8px; fill:var(--mg-ink); font-weight:600; }
 .mg-pair { font-size:.72rem; border:1px solid var(--mg-line); border-radius:10px; padding:7px 9px;
   display:flex; align-items:center; gap:5px; flex-wrap:wrap; }
 .mg-pair i { color:var(--mg-blue); font-style:normal; }
 .mg-pair span { margin-left:auto; font-size:.6rem; color:#1f7d63; background:#e4f4ee;
   border-radius:999px; padding:1px 7px; }
 .mg-pair-empty { font-size:.7rem; color:var(--mg-muted); }
 .mg-rel-note { font-size:.68rem; color:var(--mg-muted); }

 .mg-footer { margin-top:16px; padding-top:10px; border-top:1px solid var(--mg-line);
   font-size:.68rem; color:var(--mg-muted); display:flex; justify-content:space-between; gap:12px; }

 @media (max-width:1400px) {
   .mg-groups { grid-template-columns:repeat(3,1fr); }
   .mg-analytics { grid-template-columns:repeat(3,1fr); }
 }
 @media (max-width:1000px) {
   .mg-groups, .mg-analytics { grid-template-columns:repeat(2,1fr); }
   .mg-kpis { grid-template-columns:repeat(2,1fr); }
   .mg-hero-art { display:none; }
 }
 @media (max-width:620px) {
   .mg-groups, .mg-analytics, .mg-kpis { grid-template-columns:1fr; }
 }
</style>
"""

_RESIZE = """
<script>
  function __mgFit(){
    var h = document.querySelector('.mg-root');
    if (!h) return;
    var target = Math.ceil(h.getBoundingClientRect().height) + 24;
    if (window.frameElement) {
      window.frameElement.style.height = target + 'px';
      var wrap = window.frameElement.parentElement;
      if (wrap) wrap.style.height = target + 'px';
    }
  }
  __mgFit();
  window.addEventListener('resize', function(){ setTimeout(__mgFit, 120); });
  setTimeout(__mgFit, 300); setTimeout(__mgFit, 1200);
</script>
"""
components.html(CSS + BODY + _RESIZE, height=1780, scrolling=False)
