"""Capture dashboard screenshots for README (run from repo root)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By


def _wait_for_url(url: str, timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"Server did not respond at {url}")


def _click_tab(driver, label: str) -> None:
    for el in driver.find_elements(By.XPATH, f"//*[contains(text(), '{label}')]"):
        if el.is_displayed():
            el.click()
            time.sleep(1.5)
            return
    raise RuntimeError(f"Tab not found: {label}")


def _current_theme(driver) -> str:
    return driver.execute_script(
        "return document.documentElement.getAttribute('data-theme') || 'teal';"
    )


def _set_theme(driver, theme: str) -> None:
    theme = "dark" if theme == "dark" else "teal"
    for _ in range(3):
        if _current_theme(driver) == theme:
            return
        driver.find_element(By.ID, "theme-toggle").click()
        time.sleep(1.5)
    raise RuntimeError(f"Could not switch theme to {theme}")


def _capture_tab_screenshots(driver, out_dir: str, *, suffix: str = "") -> None:
    _click_tab(driver, "Expenses")
    driver.save_screenshot(os.path.join(out_dir, f"01-expenses{suffix}.png"))
    _click_tab(driver, "Assets Overview")
    driver.save_screenshot(os.path.join(out_dir, f"02-assets{suffix}.png"))
    _click_tab(driver, "Sequences")
    driver.save_screenshot(os.path.join(out_dir, f"03-sequences{suffix}.png"))
    _click_tab(driver, "Data & Mappings")
    driver.save_screenshot(os.path.join(out_dir, f"04-data-mappings{suffix}.png"))


def main() -> int:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    out_dir = os.path.join(repo_root, "docs", "screenshots")
    os.makedirs(out_dir, exist_ok=True)

    port = os.environ.get("MONEY_TRACKER_PORT", "8060")
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env["PYTHONPATH"] = repo_root
    env["MONEY_TRACKER_PORT"] = port

    proc = subprocess.Popen(
        [sys.executable, "-m", "money_tracker.dashboard"],
        cwd=repo_root,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_url(f"{base_url}/health")
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1440,1200")
        driver = webdriver.Chrome(options=options)
        try:
            driver.get(base_url)
            time.sleep(3)
            driver.execute_script("window.localStorage.clear();")
            driver.refresh()
            time.sleep(3)
            _set_theme(driver, "teal")
            _capture_tab_screenshots(driver, out_dir)
            _set_theme(driver, "dark")
            _capture_tab_screenshots(driver, out_dir, suffix="-dark")
        finally:
            driver.quit()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    print(f"Saved screenshots to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
