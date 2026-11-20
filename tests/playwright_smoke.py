"""Live browser smoke test for the Streamlit dashboard.

Start the app first, then run:
    python tests/playwright_smoke.py
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


BASE_URL = "http://127.0.0.1:8501"
PAGES = ("Home", "CPI Trends", "Crop Production", "Data Explorer", "Inflation Heatmap")
REPORT_DIR = Path(__file__).resolve().parents[1] / "reports" / "playwright"


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    console_errors: list[str] = []
    page_errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60_000)
        page.locator("[data-testid='stAppViewContainer']").wait_for(timeout=60_000)

        for index, name in enumerate(PAGES):
            if index:
                page.get_by_role("link", name=name, exact=True).first.click()
            page.wait_for_timeout(1_000)
            skeletons_cleared = True
            try:
                page.wait_for_function(
                    "document.querySelectorAll('[data-testid=stSkeleton]').length === 0",
                    timeout=30_000,
                )
            except PlaywrightTimeoutError:
                skeletons_cleared = False
            # Allow chart animations/custom-component rendering to settle.
            page.wait_for_timeout(2_000)
            visible_text = page.locator("body").inner_text()
            overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
            results.append(
                {
                    "page": name,
                    "url": page.url,
                    "title": page.title(),
                    "has_visible_content": len(visible_text.strip()) > 100,
                    "skeletons_cleared": skeletons_cleared,
                    "horizontal_overflow": overflow,
                }
            )
            page.screenshot(path=REPORT_DIR / f"{index}-{name.lower().replace(' ', '-')}.png", full_page=True)

        browser.close()

    report = {"pages": results, "console_errors": console_errors, "page_errors": page_errors}
    (REPORT_DIR / "smoke-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if console_errors or page_errors or not all(
        item["has_visible_content"] and item["skeletons_cleared"] for item in results
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
