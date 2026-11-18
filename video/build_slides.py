"""Render the 1920x1080 slide deck to PNG files with Playwright."""

from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

from content import CSS, SLIDES

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "video"
SLIDE_DIR = VIDEO / "slides"


def chromium_path() -> str:
    candidates = sorted(Path.home().glob(".cache/ms-playwright/chromium-*/chrome-linux64/chrome"))
    if candidates:
        return str(candidates[-1])
    raise FileNotFoundError("no cached Playwright Chromium found; run `playwright install chromium`")


def main() -> None:
    SLIDE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path=chromium_path(),
            args=["--no-sandbox", "--allow-file-access-from-files", "--disable-dev-shm-usage"],
        )
        page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        for slide in SLIDES:
            name = slide["name"]
            html_path = SLIDE_DIR / f"{name}.html"
            html_path.write_text(
                "<!doctype html><html><head><meta charset='utf-8'><style>"
                + CSS
                + "</style></head><body>"
                + slide["html"]
                + "</body></html>",
                encoding="utf-8",
            )
            page.goto(html_path.as_uri(), wait_until="load")
            page.wait_for_timeout(350)
            page.screenshot(path=str(SLIDE_DIR / f"{name}.png"))
            print(f"rendered {name}.png")
        browser.close()


if __name__ == "__main__":
    main()
