#!/usr/bin/env python3
"""Check which LinkedIn/Indeed jobs are no longer accepting applications and mark as 'closed'."""

import json, time
from pathlib import Path
from playwright.sync_api import sync_playwright

INBOX = Path(__file__).parent / "inbox.json"
CLOSED_PHRASES = [
    "no longer accepting applications",
    "não está mais aceitando candidaturas",
    "nao esta mais aceitando candidaturas",
    "candidaturas encerradas",
    "vaga encerrada",
    "job is no longer available",
    "this job is closed",
    "posting has expired",
    "vaga expirada",
    "não encontramos essa vaga",
    "this job is no longer available",
    "404",
]

def is_closed(page, url: str) -> bool:
    try:
        page.goto(url, timeout=15000, wait_until="domcontentloaded")
        time.sleep(1.5)
        text = page.content().lower()
        return any(phrase in text for phrase in CLOSED_PHRASES)
    except Exception as e:
        print(f"  ERROR: {e}")
        return False

def flag_old_jobs(data):
    """Marca vagas com >45 dias como ghost (provavelmente fantasma)."""
    from datetime import datetime
    count = 0
    for job in data:
        if job.get("status") in ("done", "closed", "skipped", "ghost"):
            continue
        try:
            age = (datetime.now() - datetime.fromisoformat(job.get("found",""))).days
        except Exception:
            continue
        if age > 45:
            job["status"] = "ghost"
            count += 1
    if count:
        INBOX.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        print(f"  {count} vagas antigas (>45 dias) marcadas como ghost.")

def main():
    data = json.loads(INBOX.read_text())

    flag_old_jobs(data)

    # Only check jobs that might still be open (not done/closed/skipped already)
    to_check = [i for i in data if i.get("status") not in ("done", "closed", "skipped", "ghost")
                and ("linkedin.com" in i.get("url","") or "indeed.com" in i.get("url",""))]

    print(f"Checking {len(to_check)} jobs...")
    closed_count = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = ctx.new_page()

        for idx, job in enumerate(to_check, 1):
            url = job.get("url","")
            title = job.get("title","?")[:45]
            print(f"[{idx}/{len(to_check)}] {title}...", end=" ", flush=True)

            if is_closed(page, url):
                print("CLOSED")
                job["status"] = "closed"
                closed_count += 1
                INBOX.write_text(json.dumps(data, ensure_ascii=False, indent=2))  # ponytail: save on each close so we don't lose progress on interrupt
            else:
                print("open")

            time.sleep(0.5)

        browser.close()
    print(f"\nDone. Marked {closed_count} jobs as closed.")

    # Summary
    statuses = {}
    for i in data:
        s = i.get("status","?")
        statuses[s] = statuses.get(s, 0) + 1
    print("\nStatus summary:")
    for k,v in sorted(statuses.items(), key=lambda x: -x[1]):
        print(f"  {v:4} {k}")

if __name__ == "__main__":
    main()
