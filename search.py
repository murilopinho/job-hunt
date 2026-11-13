#!/usr/bin/env python3
"""
Busca vagas — LinkedIn (multi-página), Indeed BR, Remotive, Arbeitnow.
Usa curl pra evitar problemas de DNS do urllib.
"""
import json, re, subprocess, sys, time, unicodedata, urllib.parse
from datetime import datetime
from pathlib import Path

DIR   = Path(__file__).parent
SEEN  = DIR / "seen.txt"
INBOX = DIR / "inbox.json"
REPORT_DIR = DIR / "reports"
CFG   = json.loads((DIR / "config.json").read_text(encoding="utf-8"))

KEYWORDS = [k.lower() for k in CFG["keywords"]]

def load_seen():
    if not SEEN.exists(): return set()
    return set(l.strip() for l in SEEN.read_text().splitlines() if l.strip())

def load_inbox():
    if not INBOX.exists(): return []
    return json.loads(INBOX.read_text())

def save_inbox(jobs):
    INBOX.write_text(json.dumps(jobs, indent=2, ensure_ascii=False))

def curl(url):
    cmd = ["curl", "-s", "--max-time", "20",
           "-H", "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
           "-H", "Accept-Language: pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
           url]
    r = subprocess.run(cmd, capture_output=True, timeout=30)
    return r.stdout.decode("utf-8", errors="ignore")

SENIOR_FILTER = ["senior", "sênior", "lead", "principal", "staff", "sr.", " sr ", "head of", "manager"]

def matches(text):
    t = text.lower()
    if any(s in t for s in SENIOR_FILTER): return False
    return any(k in t for k in KEYWORDS)

BR_STATES = {'ac','al','am','ap','ba','ce','df','es','go','ma','mg','ms','mt',
             'pa','pb','pe','pi','pr','rj','rn','ro','rr','rs','sc','se','sp','to'}

# regiões geo-travadas onde você não pode atuar (sem visto/presença local).
# comparado SEM acento: LinkedIn manda em PT-BR ("Índia", "Bangalor", "Coreia do Sul")
BLOCKED_REGIONS = ('india', 'asia', 'taipei', 'taiwan', 'china', 'singap', 'vietn',
                   'philippines', 'filipinas', 'indonesia', 'japan', 'japao', 'korea', 'coreia',
                   'hong kong', 'bangalor', 'mumbai', 'delhi', 'shanghai', 'xangai', 'hyderabad', 'pune')
REMOTE_MARKS = ('remoto', 'remote', 'worldwide', 'anywhere', 'home office')

def _norm(s):
    return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower().strip()

def location_ok(loc):
    # não confiar em f_WT=2: o LinkedIn guest ignora às vezes, e "remoto" com país
    # ("Estados Unidos", "França") costuma exigir morar lá. Só passa se o local diz.
    l = _norm(loc)
    if any(b in l for b in BLOCKED_REGIONS): return False
    if not l or any(m in l for m in REMOTE_MARKS): return True
    if 'america latina' in l or 'latam' in l: return True
    if any(h in l for h in CFG['home_places']): return True
    # detecta estado BR pelo sufixo ", UF" (formato Indeed BR e outros)
    parts = l.rsplit(',', 1)
    if len(parts) == 2 and parts[1].strip() in BR_STATES:
        return parts[1].strip() == CFG['home_uf']   # só seu estado é aceito presencial
    if l in ('brasil', 'brazil'): return True  # genérico sem cidade
    return False                               # outra cidade BR ou exterior presencial = não dá

def detect_ats(url):
    if "greenhouse.io" in url or "boards.greenhouse" in url: return "greenhouse"
    if "lever.co" in url:       return "lever"
    if "gupy.io" in url:        return "gupy"
    if "ashbyhq.com" in url:    return "ashby"
    if "workday.com" in url:    return "workday"
    if "indeed.com" in url:     return "indeed"
    if "linkedin.com" in url:   return "linkedin"
    return "other"

def today():
    return datetime.now().isoformat()[:10]

# ── LinkedIn guest (multi-página, multi-keyword) ──────────────────────────────

LI_SEARCHES = [tuple(s) for s in CFG["linkedin_searches"]]

def fetch_linkedin_page(keyword, location, start):
    q   = urllib.parse.quote(keyword)
    loc = urllib.parse.quote(location)
    url = (f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
           f"?keywords={q}&location={loc}&start={start}&count=25&f_TPR=r86400"
           + ("&f_WT=2" if location == "Worldwide" else ""))
    html = curl(url)
    titles    = re.findall(r'base-search-card__title[^>]*>\s*([^<]+?)\s*<', html)
    companies = re.findall(r'base-search-card__subtitle[^>]*>\s*([^<]+?)\s*<', html)
    urls      = re.findall(r'href="(https://[^"]*linkedin\.com/jobs/view/[^"?]+)', html)
    locations = re.findall(r'job-search-card__location[^>]*>\s*([^<]+?)\s*<', html)
    jobs = []
    for i, title in enumerate(titles):
        title = title.strip()
        if not matches(title): continue
        apply_url = urls[i] if i < len(urls) else ""
        job_loc = locations[i].strip() if i < len(locations) else location
        if not location_ok(job_loc): continue
        slug = re.search(r'/jobs/view/([^/?\\s]+)', apply_url)
        job_id = f"li_{slug.group(1)}" if slug else f"li_{abs(hash(title+apply_url))}"
        jobs.append({
            "id":      job_id,
            "title":   title,
            "company": companies[i].strip() if i < len(companies) else "—",
            "url":     apply_url,
            "apply":   apply_url,
            "location": job_loc,
            "source":  "LinkedIn",
            "ats":     "linkedin",
            "found":   today(),
        })
    return jobs

ATS_PATTERNS = {
    "greenhouse": r"boards\.greenhouse\.io|app\.greenhouse\.io",
    "lever":      r"jobs\.lever\.co",
    "ashby":      r"ashbyhq\.com",
    "gupy":       r"gupy\.io",
    "workable":   r"apply\.workable\.com",
    "breezy":     r"breezy\.hr",
    "smartrecruiters": r"jobs\.smartrecruiters\.com",
}

def resolve_offsite_url(job_id):
    """Usa cookies autenticados para pegar o URL real de candidatura."""
    if not COOKIES_PATH.exists():
        return None
    try:
        cookies = json.loads(COOKIES_PATH.read_text())
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    except Exception:
        return None
    cmd = ["curl", "-s", "--max-time", "15", "-L",
           "-H", f"Cookie: {cookie_str}",
           "-H", "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
           f"https://www.linkedin.com/jobs/view/{job_id}"]
    html = subprocess.run(cmd, capture_output=True, text=True).stdout
    SKIP = ["static.licdn", "media.licdn", "business.linkedin", "careers.linkedin",
            "mobile.linkedin", "safety.linkedin", "about.linkedin", "trk=", "/company/",
            "schema.org", "w3.org", "google", "facebook"]
    ext = re.findall(r'https?://(?!(?:www\.)?linkedin\.com)[^\s"<>\\]{20,150}', html)
    for u in ext:
        if any(s in u for s in SKIP): continue
        for ats_name, pattern in ATS_PATTERNS.items():
            if re.search(pattern, u):
                return ats_name, u.rstrip("\\")
    return None

def classify_linkedin_job(job_id):
    """
    Checa a página individual do job e retorna:
      'easy_apply'  — candidatura dentro do LinkedIn (não redireciona)
      'offsite'     — redireciona para site externo
    e o URL externo real se encontrado.
    """
    html = curl(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}")
    if "apply-link-offsite" in html or "offsite-apply-icon" in html:
        apply_type = "offsite"
        # Tenta capturar o URL externo direto
        ext = re.findall(r'"(https?://(?!(?:www\.)?linkedin\.com)[^"]{15,200})"', html)
        real_url = None
        for u in ext:
            for ats_name, pattern in ATS_PATTERNS.items():
                if re.search(pattern, u):
                    return apply_type, ats_name, u
            # Salva o primeiro URL não-LinkedIn como candidato
            if not real_url and not any(skip in u for skip in ["static.licdn", "media.licdn", "google", "facebook", "/company/", "trk="]):
                real_url = u
        # Se não achou ATS no guest HTML, tenta com cookies autenticados
        li_id = re.search(r'\d{10,}', job_id)
        if li_id:
            resolved = resolve_offsite_url(li_id.group())
            if resolved:
                return apply_type, resolved[0], resolved[1]
        return apply_type, "offsite", real_url
    elif "apply-link-onsite" in html or "apply-button--default" in html:
        return "easy_apply", "linkedin_easy", None
    return "unknown", "linkedin", None

def fetch_linkedin_all():
    by_id = {}
    for keyword, location in LI_SEARCHES:
        for page in range(3):
            start = page * 25
            jobs  = fetch_linkedin_page(keyword, location, start)
            if not jobs and page > 0:
                break
            for j in jobs:
                by_id[j["id"]] = j
            time.sleep(0.8)

    result = list(by_id.values())

    # Classifica cada vaga: easy apply vs offsite
    easy_count    = 0
    offsite_count = 0
    auto_count    = 0
    for j in result:
        li_id = re.search(r'/jobs/view/[^-]+-(\d+)', j["url"])
        if not li_id:
            li_id = re.search(r'-(\d{10,})$', j["url"].split("?")[0])
        if not li_id:
            continue
        job_num = li_id.group(1)
        apply_type, ats, real_url = classify_linkedin_job(job_num)
        j["li_apply_type"] = apply_type
        if apply_type == "easy_apply":
            j["ats"] = "linkedin_easy"
            easy_count += 1
        elif apply_type == "offsite":
            offsite_count += 1
            if ats != "offsite" and real_url:
                j["ats"]   = ats
                j["apply"] = real_url
                auto_count += 1
            else:
                j["ats"] = "offsite"
                if real_url:
                    j["apply"] = real_url
        time.sleep(0.3)

    print(f"  LinkedIn: {len(result)} vagas ({easy_count} Easy Apply, {offsite_count} offsite, {auto_count} com ATS detectado)")
    return result

# ── Indeed Brasil ─────────────────────────────────────────────────────────────

def fetch_indeed():
    jobs = []
    seen_ids = set()
    searches = [s.replace(" ", "+") for s in CFG["br_terms"]]
    for search in searches:
        html = curl(f"https://br.indeed.com/jobs?q={search}&sort=date&fromage=7")
        # Indeed embeds job cards in <div class="job_seen_beacon"> or similar
        # Extract via jobKeysWithInfo or window.mosaic.providerData
        raw = re.search(r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*(\{.+?\});', html, re.S)
        if raw:
            try:
                data = json.loads(raw.group(1))
                results = data.get("metaData", {}).get("mosaicProviderJobCardsModel", {}).get("results", [])
                for j in results:
                    title   = j.get("displayTitle", j.get("title", ""))
                    company = j.get("company", "—")
                    jk      = j.get("jobkey", "")
                    if not matches(title): continue
                    indeed_loc = j.get("formattedLocation", "Brasil")
                    if not location_ok(indeed_loc): continue
                    job_id = f"indeed_{jk}"
                    if job_id in seen_ids: continue
                    seen_ids.add(job_id)
                    url = f"https://br.indeed.com/viewjob?jk={jk}"
                    jobs.append({
                        "id": job_id, "title": title, "company": company,
                        "url": url, "apply": url,
                        "location": indeed_loc,
                        "source": "Indeed BR", "ats": "indeed", "found": today(),
                    })
            except: pass
        time.sleep(1.2)
    print(f"  Indeed BR: {len(jobs)} vagas")
    return jobs

# ── Remotive ──────────────────────────────────────────────────────────────────

def fetch_remotive():
    jobs = []
    raw = curl("https://remotive.com/api/remote-jobs?limit=100")
    try: data = json.loads(raw)
    except: return []
    for j in data.get("jobs", []):
        title = j.get("title", "")
        tags  = j.get("tags", [])
        tags_s = " ".join(tags) if isinstance(tags, list) else str(tags)
        if not matches(title + " " + tags_s): continue
        jobs.append({
            "id":      f"remotive_{j['id']}",
            "title":   title,
            "company": j["company_name"],
            "url":     j["url"], "apply": j["url"],
            "location": "Remote", "source": "Remotive",
            "ats":     detect_ats(j["url"]), "found": today(),
        })
    print(f"  Remotive: {len(jobs)} vagas")
    return jobs

# ── Arbeitnow ─────────────────────────────────────────────────────────────────

def fetch_arbeitnow():
    jobs = []
    seen_slugs = set()
    for kw in CFG["en_terms"]:
        raw = curl(f"https://www.arbeitnow.com/api/job-board-api?search={urllib.parse.quote(kw)}")
        try: data = json.loads(raw)
        except: continue
        for j in data.get("data", []):
            if j["slug"] in seen_slugs: continue
            if not matches(j["title"]): continue
            seen_slugs.add(j["slug"])
            url = j.get("url", f"https://www.arbeitnow.com/jobs/{j['slug']}")
            jobs.append({
                "id":      f"arb_{j['slug']}",
                "title":   j["title"], "company": j["company_name"],
                "url":     url, "apply": url,
                "location": "Remote" if j.get("remote") else j.get("location", "—"),
                "source":  "Arbeitnow", "ats": detect_ats(url), "found": today(),
            })
        time.sleep(0.5)
    print(f"  Arbeitnow: {len(jobs)} vagas")
    return jobs

# ── Greenhouse direct boards ──────────────────────────────────────────────────
# Empresas de tech que usam Greenhouse e têm times de QA — API pública, sem login

GH_COMPANIES = [
    "stripe", "notion", "figma", "linear", "vercel", "supabase", "railway",
    "shopify", "datadog", "hashicorp", "mongodb", "cockroachdb", "planetscale",
    "sentry", "postman", "grafana", "elastic", "netlify", "cloudflare",
    "brex", "ramp", "mercury", "plaid", "segment", "mixpanel", "amplitude",
    "retool", "airtable", "webflow", "loom", "miro", "canva", "pitch",
    "temporal", "dbt-labs", "airbyte", "prefect", "dagster",
    # foco remote-global / contrata LATAM-Brasil (board público Greenhouse)
    "gitlab", "sourcegraph", "gitpod", "hashicorp", "grafanalabs",
    "elastic", "mattermost", "close", "doist", "hotjar", "contentsquare",
    "aha", "toptal", "turing", "andela", "crossover", "revenuecat",
    "posthog", "railway", "render", "fly", "planetscale", "neon",
    "supabase", "prisma", "strapi", "appsmith", "n8n", "windmill",
    "cal", "documenso", "twenty", "medusajs", "novu", "trigger",
    "instabug", "sonarsource", "browserstack", "smartbear", "testrail",
]

def fetch_greenhouse():
    jobs = []
    seen_ids = set()
    for company in GH_COMPANIES:
        raw = curl(f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=false")
        try:
            data = json.loads(raw)
        except:
            continue
        for j in data.get("jobs", []):
            title = j.get("title", "")
            if not matches(title): continue
            job_id = f"gh_{j['id']}"
            if job_id in seen_ids: continue
            seen_ids.add(job_id)
            url = j.get("absolute_url", f"https://boards.greenhouse.io/{company}/jobs/{j['id']}")
            loc = ", ".join(o.get("name","") for o in j.get("offices",[])) or "Remote"
            if not location_ok(loc): continue
            jobs.append({
                "id":      job_id,
                "title":   title,
                "company": company.capitalize(),
                "url":     url,
                "apply":   url,
                "location": loc,
                "source":  "Greenhouse",
                "ats":     "greenhouse",
                "found":   today(),
            })
        time.sleep(0.2)
    print(f"  Greenhouse: {len(jobs)} vagas")
    return jobs

# ── Lever direct boards ───────────────────────────────────────────────────────

LV_COMPANIES = [
    "netflix", "reddit", "twitch", "discord", "coinbase", "robinhood",
    "duolingo", "calm", "headspace", "carta", "lattice", "rippling",
    "gusto", "deel", "remote", "oyster", "personio", "workato",
    "zapier", "make", "n8n", "hubspot", "intercom", "zendesk",
    "pagerduty", "statuspage", "incident.io", "firehydrant",
    # foco remote-global / contrata LATAM (boards Lever públicos)
    "deel", "remote", "oyster", "andela", "turing", "toptal",
    "gohighlevel", "clipboardhealth", "hostinger", "kraken",
    "binance", "consensys", "huggingface", "cohere", "replicate",
    "elevenlabs", "voiceflow", "weights-biases", "scale", "labelbox",
    "vidyard", "loom", "clari", "gong", "airbyte", "kong",
]

def fetch_lever():
    jobs = []
    seen_ids = set()
    for company in LV_COMPANIES:
        raw = curl(f"https://api.lever.co/v0/postings/{company}?mode=json&limit=250")
        try:
            data = json.loads(raw)
        except:
            continue
        if isinstance(data, dict):
            data = data.get("data", [])
        for j in data:
            title = j.get("text", "")
            if not matches(title): continue
            job_id = f"lv_{j['id']}"
            if job_id in seen_ids: continue
            seen_ids.add(job_id)
            url = j.get("hostedUrl", f"https://jobs.lever.co/{company}/{j['id']}")
            apply = j.get("applyUrl", url)
            cats  = j.get("categories", {})
            if not location_ok(cats.get("location", "Remote")): continue
            jobs.append({
                "id":      job_id,
                "title":   title,
                "company": company.capitalize(),
                "url":     url,
                "apply":   apply,
                "location": cats.get("location", "Remote"),
                "source":  "Lever",
                "ats":     "lever",
                "found":   today(),
            })
        time.sleep(0.2)
    print(f"  Lever: {len(jobs)} vagas")
    return jobs

# ── LinkedIn autenticado (feed de vagas recomendadas) ─────────────────────────

COOKIES_PATH = Path(__file__).parent / "linkedin_cookies.json"

def fetch_linkedin_auth():
    if not COOKIES_PATH.exists():
        return []
    try:
        cookies = json.loads(COOKIES_PATH.read_text())
    except Exception:
        return []

    from playwright.sync_api import sync_playwright
    jobs = []
    seen_ids_local = set()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )
        ctx.add_cookies(cookies)

        for keyword, location in LI_SEARCHES[:4]:  # ponytail: 4 buscas, ~20 vagas cada
            q   = urllib.parse.quote(keyword)
            loc = urllib.parse.quote(location)
            url = (f"https://www.linkedin.com/jobs/search/?keywords={q}&location={loc}"
                   f"&f_TPR=r86400&sortBy=DD" + ("&f_WT=2" if location == "Worldwide" else ""))
            try:
                page = ctx.new_page()
                page.goto(url, timeout=20000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                html = page.content()
                page.close()
            except Exception:
                continue

            ids = re.findall(r'jobs/view/[^"\']*?-(\d{10,})', html)
            ids += re.findall(r'"jobPostingId"\s*:\s*"(\d{10,})"', html)
            ids += re.findall(r'jobPosting:(\d{10,})', html)
            ids = list(dict.fromkeys(ids))

            for jid in ids[:20]:
                job_id = f"li_{jid}"
                if job_id in seen_ids_local: continue
                seen_ids_local.add(job_id)

                jhtml = curl(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{jid}")
                title_m = re.search(r'"title"\s*:\s*"([^"]+)"', jhtml)
                co_m    = re.search(r'"companyName"\s*:\s*"([^"]+)"', jhtml)
                loc_m   = re.search(r'"formattedLocation"\s*:\s*"([^"]+)"', jhtml)
                if not title_m: continue
                title = title_m.group(1)
                co    = co_m.group(1) if co_m else "—"
                loc_v = loc_m.group(1) if loc_m else location

                if not matches(title): continue
                if not location_ok(loc_v): continue

                apply_type, ats, apply_url = classify_linkedin_job(jid)
                if not apply_url:
                    apply_url = f"https://www.linkedin.com/jobs/view/{jid}"

                jobs.append({
                    "id":      job_id,
                    "title":   title,
                    "company": co,
                    "url":     f"https://www.linkedin.com/jobs/view/{jid}",
                    "apply":   apply_url,
                    "location": loc_v,
                    "source":  "LinkedIn Feed",
                    "ats":     ats,
                    "found":   today(),
                    "li_apply_type": apply_type,
                })
                time.sleep(0.5)
            time.sleep(2)

        browser.close()

    print(f"  LinkedIn Feed (auth): {len(jobs)} vagas")
    return jobs

# ── Hacker News "Who is Hiring" ──────────────────────────────────────────────

def fetch_hn_hiring():
    jobs = []
    # Pega o ID do thread mais recente via API oficial (sem bloqueio)
    raw = curl("https://hacker-news.firebaseio.com/v0/user/whoishiring/submitted.json")
    try: thread_ids = json.loads(raw)
    except: return []

    # Pega o thread mais recente que seja "Who is hiring?"
    thread_id = None
    for tid in thread_ids[:5]:
        item = json.loads(curl(f"https://hacker-news.firebaseio.com/v0/item/{tid}.json") or "{}")
        if "who is hiring" in item.get("title", "").lower():
            thread_id = tid
            break
    if not thread_id:
        print("  HN Who is Hiring: thread não encontrado")
        return []

    thread = json.loads(curl(f"https://hacker-news.firebaseio.com/v0/item/{thread_id}.json") or "{}")
    comment_ids = thread.get("kids", [])[:200]  # ponytail: 200 primeiros comentários

    for cid in comment_ids:
        raw_c = curl(f"https://hacker-news.firebaseio.com/v0/item/{cid}.json")
        try: comment = json.loads(raw_c)
        except: continue
        text = re.sub(r'<[^>]+>', ' ', comment.get("text", ""))
        if not matches(text): continue
        # Extrai URL de candidatura do texto
        urls = re.findall(r'https?://[^\s<>"]{10,}', text)
        apply_url = urls[0] if urls else f"https://news.ycombinator.com/item?id={cid}"
        title_match = re.match(r'([^|.]+)', text.strip())
        title = (title_match.group(1).strip()[:80] if title_match else text[:60]) or "HN Job"
        jobs.append({
            "id": f"hn_{cid}",
            "title": title,
            "company": comment.get("by", "—"),
            "url": f"https://news.ycombinator.com/item?id={cid}",
            "apply": apply_url,
            "location": "Remote",
            "source": "HN Who is Hiring",
            "ats": detect_ats(apply_url),
            "found": today(),
        })
        time.sleep(0.1)

    print(f"  HN Who is Hiring: {len(jobs)} vagas")
    return jobs

# ── WeWorkRemotely RSS ───────────────────────────────────────────────────────

def fetch_weworkremotely():
    jobs = []
    seen_ids = set()
    raw = curl("https://weworkremotely.com/remote-jobs.rss")
    items = re.findall(r'<item>(.*?)</item>', raw, re.S)
    for item in items:
        t = re.search(r'<title><!\[CDATA\[(.*?)\]\]></title>', item) or re.search(r'<title>(.*?)</title>', item)
        l = re.search(r'<link>(.*?)</link>', item)
        if not t or not l: continue
        title = t.group(1).strip()
        if not matches(title): continue
        url = l.group(1).strip()
        job_id = f"wwr_{abs(hash(url))}"
        if job_id in seen_ids: continue
        seen_ids.add(job_id)
        jobs.append({
            "id": job_id, "title": title, "company": "—",
            "url": url, "apply": url,
            "location": "Remote", "source": "WeWorkRemotely",
            "ats": detect_ats(url), "found": today(),
        })
    print(f"  WeWorkRemotely: {len(jobs)} vagas")
    return jobs

# ── RemoteOK API ─────────────────────────────────────────────────────────────

def fetch_remoteok():
    jobs = []
    seen_ids = set()
    raw = curl("https://remoteok.com/api")
    try: data = json.loads(raw)
    except: return []
    for j in data:
        if not isinstance(j, dict): continue
        title = j.get("position", "")
        tags  = " ".join(j.get("tags", []))
        if not matches(title + " " + tags): continue
        url = j.get("url", f"https://remoteok.com/remote-jobs/{j.get('id','')}")
        job_id = f"rok_{j.get('id', abs(hash(url)))}"
        if job_id in seen_ids: continue
        seen_ids.add(job_id)
        jobs.append({
            "id": job_id, "title": title, "company": j.get("company", "—"),
            "url": url, "apply": url,
            "location": "Remote", "source": "RemoteOK",
            "ats": detect_ats(url), "found": today(),
        })
    print(f"  RemoteOK: {len(jobs)} vagas")
    return jobs

# ── GitHub vagas BR ──────────────────────────────────────────────────────────

GH_VAGAS_REPOS = [
    "frontendbr/vagas",
    "backend-br/vagas",
    "pythonbrasil/vagas",
    "react-brasil/vagas",
]

def fetch_github_vagas():
    jobs = []
    seen_ids = set()
    for repo in GH_VAGAS_REPOS:
        raw = curl(f"https://api.github.com/repos/{repo}/issues?state=open&per_page=100")
        try: issues = json.loads(raw)
        except: continue
        if not isinstance(issues, list): continue
        for issue in issues:
            title = issue.get("title", "")
            if not matches(title): continue
            url = issue.get("html_url", "")
            job_id = f"ghv_{issue.get('id', abs(hash(url)))}"
            if job_id in seen_ids: continue
            seen_ids.add(job_id)
            jobs.append({
                "id": job_id, "title": title, "company": repo.split("/")[0],
                "url": url, "apply": url,
                "location": "Brasil",
                "source": f"GitHub/{repo}", "ats": "other", "found": today(),
            })
        time.sleep(0.3)
    print(f"  GitHub vagas BR: {len(jobs)} vagas")
    return jobs

# ── Relatório ──────────────────────────────────────────────────────────────────

def gerar_relatorio(inbox, new_jobs):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    seen = load_seen()
    pendentes  = [j for j in inbox if not j.get("status")]
    aplicadas  = [j for j in inbox if j.get("status") == "done"]
    puladas    = [j for j in inbox if j.get("status") == "skipped"]
    abertas    = [j for j in inbox if j.get("status") == "manual"]

    # mais novas primeiro (inbox é append-only, então a ordem natural é a mais antiga primeiro)
    pendentes.sort(key=lambda j: j.get("found", ""), reverse=True)
    aplicadas.sort(key=lambda j: j.get("applied", ""), reverse=True)

    auto    = [j for j in pendentes if j.get("ats") in ("greenhouse","lever","ashby","gupy")]
    offsite = [j for j in pendentes if j.get("ats") == "offsite"]
    easy    = [j for j in pendentes if j.get("ats") == "linkedin_easy"]

    linhas = [
        f"# Relatorio de Vagas — {today()}",
        "",
        f"## Resumo",
        f"| Metrica | Total |",
        f"|---|---|",
        f"| Novas hoje | {len(new_jobs)} |",
        f"| Auto-preenchimento (Greenhouse/Lever/Gupy) | {len(auto)} |",
        f"| Offsite — site externo (potencial auto-apply) | {len(offsite)} |",
        f"| Easy Apply LinkedIn | {len(easy)} |",
        f"| Candidaturas enviadas | {len(aplicadas)} |",
        f"| Puladas | {len(puladas)} |",
        f"| Total candidatado | {len(seen)} |",
        "",
    ]

    if new_jobs:
        linhas += [f"## Novas vagas de hoje ({len(new_jobs)})", ""]
        for j in new_jobs:
            linhas.append(f"- **{j['title']}** — {j['company']} ({j['location']}) [{j['source']}]")
            linhas.append(f"  {j['url']}")
            linhas.append("")

    if pendentes:
        linhas += [f"## Pendentes para candidatura ({len(pendentes)})", ""]
        for j in pendentes:
            linhas.append(f"- **{j['title']}** — {j['company']} ({j['location']})")
            linhas.append(f"  ATS: `{j['ats']}` | {j['url']}")
            linhas.append("")

    if aplicadas:
        linhas += [f"## Candidaturas enviadas ({len(aplicadas)})", ""]
        for j in aplicadas:
            linhas.append(f"- ✅ **{j['title']}** — {j['company']} em {j.get('applied','?')}")
            linhas.append("")

    relatorio = "\n".join(linhas)
    path = REPORT_DIR / f"vagas_{today()}.md"
    path.write_text(relatorio, encoding="utf-8")

    # Atualiza o arquivo fixo "ultimo_relatorio.md" tbm
    (REPORT_DIR / "ultimo_relatorio.md").write_text(relatorio, encoding="utf-8")
    print(f"  📄 Relatório: {path}")

# ── main ──────────────────────────────────────────────────────────────────────

# ── Enriquecimento: quem postou a vaga (recrutador / hiring manager) ──────────
# LinkedIn só expõe o "job poster" para sessão autenticada. Usa os cookies de
# linkedin_cookies.json via curl (sem Playwright, sem OOM). Best-effort: muitas
# vagas não têm poster individual (postadas pela empresa) — nesses casos ignora.

def _li_auth():
    if not COOKIES_PATH.exists():
        return None
    ck = {c["name"]: c["value"] for c in json.loads(COOKIES_PATH.read_text())}
    if "li_at" not in ck or "JSESSIONID" not in ck:
        return None
    cookie = "; ".join(f"{k}={v}" for k, v in ck.items())
    csrf   = ck["JSESSIONID"].strip('"')
    return cookie, csrf

def fetch_job_poster(jid, auth):
    cookie, csrf = auth
    url = (f"https://www.linkedin.com/voyager/api/jobs/jobPostings/{jid}"
           f"?decorationId=com.linkedin.voyager.deco.jobs.web.shared.WebFullJobPosting-65")
    cmd = ["curl", "-s", "--max-time", "20", "--compressed",
           "-H", f"cookie: {cookie}", "-H", f"csrf-token: {csrf}",
           "-H", "accept: application/vnd.linkedin.normalized+json+2.1",
           "-H", "x-restli-protocol-version: 2.0.0",
           "-H", "user-agent: Mozilla/5.0", url]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=30).stdout.decode("utf-8", "ignore")
        d = json.loads(out)
    except Exception:
        return None
    inc = d.get("included", [])
    # membros do hiring team referenciados por urn
    member_urns = []
    for x in inc:
        if x.get("$type", "").endswith("JobHiringTeam"):
            for m in x.get("hiringTeamMembers", []) or []:
                if isinstance(m, str):
                    member_urns.append(m)
                elif isinstance(m, dict):
                    member_urns.append(m.get("hiringTeamMemberProfile") or m.get("*hiringTeamMemberProfile") or "")
    people = []
    for x in inc:
        pid = x.get("publicIdentifier")
        if not pid:
            continue
        name = f"{x.get('firstName','')} {x.get('lastName','')}".strip()
        people.append({
            "name": name or pid,
            "url": f"https://www.linkedin.com/in/{pid}",
            "title": x.get("occupation", "") or "",
        })
    if not people:
        return None
    # se há urns de membros, tenta casar; senão devolve o primeiro perfil-pessoa
    return people[0]

def enrich_recruiters(limit=80):
    auth = _li_auth()
    if not auth:
        print("⚠️  Sem cookies válidos do LinkedIn (linkedin_cookies.json) — pulei o enriquecimento.")
        return
    inbox = load_inbox()
    # prioriza vagas pendentes, compatíveis de localização, ainda sem recrutador
    def prio(j):
        return (0 if location_ok(j.get("location", "")) else 1, j.get("found", ""))
    alvos = [j for j in inbox
             if not j.get("status")
             and "linkedin.com/jobs/view" in j.get("url", "")
             and not j.get("recruiter")
             and not j.get("_no_recruiter")]
    alvos.sort(key=prio)
    alvos = alvos[:limit]
    print(f"🔎 Buscando recrutador em {len(alvos)} vagas do LinkedIn...")
    achou = 0
    for j in alvos:
        m = re.search(r"(\d{10,})", j["url"])
        if not m:
            continue
        p = fetch_job_poster(m.group(1), auth)
        if p:
            j["recruiter"]       = p["name"]
            j["recruiter_url"]   = p["url"]
            j["recruiter_title"] = p["title"]
            achou += 1
            print(f"  ✅ {j['title'][:45]:45} → {p['name']} ({p['url']})")
        else:
            j["_no_recruiter"] = True
        time.sleep(1.0)
    save_inbox(inbox)
    print(f"\n{achou} recrutador(es) encontrado(s). Rode:  python3 outreach.py --from-inbox")

# ── fontes leves (só curl, sem Playwright / sem passo LinkedIn pesado) ─────────

def fetch_light():
    return (
        fetch_greenhouse() +
        fetch_lever() +
        fetch_remotive() +
        fetch_arbeitnow() +
        fetch_weworkremotely() +
        fetch_remoteok() +
        fetch_github_vagas() +
        fetch_hn_hiring()
    )

def main():
    light = "--light" in sys.argv

    if "--posters" in sys.argv:
        enrich_recruiters()
        return

    seen        = load_seen()
    current     = load_inbox()
    current_ids = {j["id"] for j in current}

    print("🔍 Buscando vagas..." + ("  (modo leve)" if light else ""))
    all_found = fetch_light() if light else (
        fetch_greenhouse() +
        fetch_lever() +
        fetch_linkedin_all() +
        fetch_indeed() +
        fetch_remotive() +
        fetch_arbeitnow() +
        fetch_weworkremotely() +
        fetch_remoteok() +
        fetch_github_vagas() +
        fetch_hn_hiring()
    )

    by_id    = {j["id"]: j for j in all_found}
    new_jobs = [j for jid, j in by_id.items()
                if jid not in seen and jid not in current_ids]

    if new_jobs:
        current.extend(new_jobs)
        save_inbox(current)
        print(f"\n✅ {len(new_jobs)} vaga(s) nova(s) encontrada(s)")
        for j in new_jobs[:15]:
            print(f"  [{j['source']:12}] {j['title']} — {j['company']}")
        if len(new_jobs) > 15:
            print(f"  ... e mais {len(new_jobs) - 15}")
        print("\nPara se candidatar: python3 apply.py")
    else:
        print("\n— Nenhuma vaga nova hoje.")

    gerar_relatorio(current, new_jobs)

    total_pend = sum(1 for j in current if not j.get("status"))
    print(f"\nPendentes: {total_pend} | Candidatado: {len(seen)}")

if __name__ == "__main__":
    main()
