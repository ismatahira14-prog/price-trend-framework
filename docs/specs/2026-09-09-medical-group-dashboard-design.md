# Medical Group (Health / Group 06) dashboard — design

_2026-09-09_

## Goal

A new page in the IMIS app that recreates the supplied reference image as a
**healthcare analytics dashboard for CPI Group 06 (Health)**, using only
real Group 06 data from IMIS. Light-mode, pastel blue / mint / teal, rounded
cards, hero with a soft illustration, 4 KPI cards, a 5-group masonry, and
the reference's bottom analytics row. The reference's **Key Insights** panel
is replaced by a full 5th group, **Medical Equipment**.

This is its own visual system (the reference's palette), **not** the
existing PBS-green Home page. It lives beside the Home page, reachable from
a page link.

## Data (all real, from IMIS)

Group 06 has **31 items** across COICOP sub-classes → the 5 dashboard groups:

| Group | COICOP | n |
|---|---|--:|
| Medicines | 06.1.1 | 17 |
| Services | 06.2.1, 06.2.2 | 4 |
| Diagnostics | 06.2.3 | 6 |
| Procedures | 06.3.0 | 2 |
| Medical Equipment | 06.1.3 | 2 |

- Item prices: `dbo.CPI`, Jan 2025 – Jul 2026 (19 months). Equal-city
  arithmetic mean per item-month.
- Weights: `dbo.CPI_WT` `Weight0`, latest month.
- Group index: `dbo.Inflation` `G06`, monthly **2016 – 2026** (real long
  series for the dynamics chart).
- **"Revisions"** = number of months (of the 19) in which the item's price
  changed.
- Group 06: basket weight **2.31 %**, index **296.7** (Jul 2026),
  MoM **+0.5 %**, YoY **+7.8 %**, ~35 cities.

## Architecture

### `src/pricelab/dashboard/medical_group.py` (no Streamlit)

`load_medical_group()` → one dict with everything the page needs:
`group` (KPIs + 121-pt index series), `items` DataFrame, `subgroups`
(items grouped into the 5), `revisions_timeline` (cumulative items with ≥1
revision, by month), `most_revised` (top 6), `city_pressure` (each city's
latest Group-06 average price vs the national average, as an index),
`moves_together` (within-sub-group item pairs whose prices rose/fell
together — plain words, **no r shown** — plus the 3 CPI groups the Health
index tracks most closely), `coverage`.

`dbo.CPI` is read in chunks (a single 266k-row fetch intermittently crashes
pyodbc on this box). Results cached to
`data/interim/medical_group_06*.parquet` (6 h TTL); a stale cache is served
if a refresh fails.

### `dashboard/pages/2_Medical_Group.py`

Python builds the dict, then renders **one hand-built HTML/CSS/SVG
dashboard** in a full-width `components.html` iframe (same technique as the
Home page's heat-table + map). Sections, matching the reference:

1. **Header bar** — logo, search field (visual), horizontal menu
   `Home · Medical Groups` (Medical Groups active, mint pill), date chip,
   bell, profile.
2. **Hero** — title *"Medical Group — Item Mosaic Storyboard"*, subtitle
   *"A complete view of medicines, medical equipment, services, diagnostics
   and procedures"*, a handwritten-style tagline, and a **hand-drawn soft
   SVG** (family silhouettes + heart line + leaves) faded top-right.
3. **4 KPI cards** — Total Items (31) · Overall Change (MoM, +0.5 %) ·
   Basket Weight (2.31) · Overall Change (YoY, +7.8 %). Icon, big number,
   heading, pastel accent — reference proportions.
4. **5-group masonry** — Medicines / Services / Diagnostics / Procedures /
   Medical Equipment. Each: header with icon + item count + one-line
   descriptor, then item cards (name, unit, Rs price, weight, YoY chip,
   "N rev"). Medicines gets the small grid; Procedures the large single
   card (C-Section); Diagnostics the compact stack; Medical Equipment
   styled identically to the rest.
5. **Bottom analytics row** (5 cards, reference styles):
   - **Group Price Dynamics (Index)** — area/line of `G06` (start → now,
     +YoY% badge).
   - **Revisions Timeline** — stepped line of cumulative revised items.
   - **Most Revised Items** — ranked table (top 6).
   - **Pakistan City Price Pressure** — small Pakistan SVG with the 5–6
     cities furthest above / below the national Group-06 average.
   - **Relationship Explorer** — "moves together" item pairs (plain) +
     "Health prices tend to track: <3 groups>".
6. Footer strip.

Colours: a scoped `--mg-*` token set (blue `#3b82c4`-ish, mint `#5bbf9c`,
teal, soft orange, ink, hairline) — **only inside this page's iframe**, so
the Home page's PBS-green system is untouched.

### `app.py` / nav

Register `2_Medical_Group.py` as a 3rd `st.Page` (nav stays hidden). Add a
small in-theme `st.page_link` row on each page.

### Testing

- `tests/test_medical_group.py` — unit tests on the calc module with a
  synthetic mini-panel: sub-group routing, revision counting, YoY math,
  city-pressure index centred on 100, `moves_together` only returns
  same-sub-group pairs.
- `tests/test_dashboard_app.py` — AppTest smoke test: page renders, all 5
  group titles + the 5 bottom cards present, no exception, **no `r =` /
  "correlation" text** on the page.

### Dependencies

None added.

## Fidelity notes / honest gaps

- The hero illustration is hand-drawn SVG, not a photo.
- The reference's exact numbers (Rs 658.9 Doctor fee, Rs 36,714 C-Section)
  are a different month's snapshot; this page shows the current IMIS values
  (Rs 704, Rs 39,502).
- "Cities Covered" is the latest-month city count (~35).
- No fabricated statistics anywhere; where the reference implies a metric
  we can't derive, the panel shows the nearest real one.
