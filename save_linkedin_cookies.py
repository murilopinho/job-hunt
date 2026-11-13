#!/usr/bin/env python3
from playwright.sync_api import sync_playwright
import json

import os
SAVE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "linkedin_cookies.json")

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=False, slow_mo=100)
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto("https://www.linkedin.com/login")
    print("Faça login no LinkedIn. Quando chegar no feed, pressione ENTER aqui...")
    input()
    cookies = ctx.cookies()
    with open(SAVE_PATH, "w") as f:
        json.dump(cookies, f, indent=2)
    print(f"OK: {len(cookies)} cookies salvos em {SAVE_PATH}")
    browser.close()
