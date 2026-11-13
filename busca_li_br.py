import html, re, sys, time, urllib.parse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import search
ESTAGIO = re.compile(r"est[aá]gi|\bintern\b|internship|trainee|working student|aprendiz", re.I)
# nível acima de júnior ou área fora de QA de software (hardware, SAP, laboratório...)
FORA = re.compile(r"pleno|\bpl\b|\bmid\b|mid.level|\bsr\b|especialista|specialist|supervisor|coordenador|\bii+\b|"
                  r"firmware|hardware|laborat|operador|\bsap\b|validation engineer|banco de talentos|"
                  r"t[eé]cnico|manuten[cç]|piloto|ve[ií]culo|pesquisador", re.I)
PRESENCIAL = re.compile(r"h[ií]brido|hybrid|presencial|on.?site", re.I)
DIAS = int(sys.argv[1]) if len(sys.argv) > 1 else 1  # janela de postagem (dias)
KW = search.CFG["br_terms"]
def ok_title(t):
    n = search._norm(t)
    return not ESTAGIO.search(t) and not FORA.search(t) and not any(s in t.lower() for s in search.SENIOR_FILTER) and \
        (search.matches(t) or "teste" in n or "qualidade de software" in n)
def page(kw, start, remote):
    url = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
           f"?keywords={urllib.parse.quote(kw)}&geoId=106057199&start={start}&f_TPR=r{DIAS * 86400}"
           + ("&f_WT=2" if remote else ""))
    h = search.curl(url)
    if "base-search-card" not in h: return None
    # um card por <li>: parse por card pra data/local não desalinharem do título
    out = []
    for card in h.split("<li")[1:]:
        g = lambda p: (re.search(p, card) or [None, ""])[1].strip()
        t = html.unescape(g(r'base-search-card__title[^>]*>\s*([^<]+?)\s*<'))
        if t: out.append((t, html.unescape(g(r'base-search-card__subtitle[^>]*>\s*(?:<a[^>]*>\s*)?([^<]+?)\s*<')) or "—",
                          g(r'href="(https://[^"]*linkedin\.com/jobs/view/[^"?]+)'),
                          g(r'job-search-card__location[^>]*>\s*([^<]+?)\s*<'), g(r'<time[^>]*datetime="([\d-]+)"')))
    return out
seen = search.load_seen(); cur = search.load_inbox(); ids = {j["id"] for j in cur}
start_n = len(cur); found = []; reqs = 0; blocked = 0
for remote in (True, False):
    for kw in KW:
        for s in range(0, 50, 10):
            res = page(kw, s, remote); reqs += 1; time.sleep(2)
            if res is None: blocked += 1; break
            if not res: break
            for title, comp, url, loc, posted in res:
                m = re.search(r'/jobs/view/([^/?\s]+)', url)
                if not m: continue
                jid = f"li_{m.group(1)}"
                if jid in ids or jid in seen or not ok_title(title): continue
                # f_WT=2 deixa passar híbrido: título manda
                is_remote = (remote and not PRESENCIAL.search(title)) or any(k in search._norm(title) for k in search.REMOTE_MARKS)
                if not (is_remote or search.location_ok(loc)): continue
                loc_show = f"{loc} (remoto)" if is_remote and "remot" not in search._norm(loc) else loc
                j = {"id": jid, "title": title, "company": comp, "url": url, "apply": url, "location": loc_show,
                     "source": "LinkedIn", "ats": "linkedin", "found": search.today(), "posted": posted}
                cur.append(j); ids.add(jid); found.append(j)
            search.save_inbox(cur)
        print(f"  {'remoto' if remote else 'geral '} | {kw}: total novas até agora {len(found)}", flush=True)
print(f"\nrequisições {reqs} | páginas bloqueadas/vazias {blocked}")
print(f"ANTES {start_n} -> AGORA {len(cur)} | novas {len(found)}")
for j in found: print(f"  {j['title']} | {j['company']} | {j['location']}")
try: search.gerar_relatorio(cur, found)
except Exception as e: print("relatorio falhou:", e)
