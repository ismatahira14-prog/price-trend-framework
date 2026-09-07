"""Inflation heat map page - monthly change by CPI group.

Registered in dashboard/app.py's st.navigation() (the top nav bar) - that's
also where st.set_page_config() now lives (once per app, not once per page).

The actual heat map (controls, table, colouring, CSV download) lives in
pricelab.dashboard.heatmap.render_inflation_heatmap() so this page and the
Home page's inline copy stay identical - see that module's docstring.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from pricelab.dashboard.heatmap import render_inflation_heatmap  # noqa: E402

render_inflation_heatmap()
