#!/usr/bin/env python3
"""Busca leve resiliente: roda cada fonte curl isolada, com timeout, e salva
incrementalmente. Pula LinkedIn (estoura RAM no PC de 8GB). Uso: python3 run_light_safe.py"""
import signal, sys, traceback
import search

FETCHERS = [
    ("Greenhouse",      search.fetch_greenhouse),
    ("Lever",           search.fetch_lever),
    ("Remotive",        search.fetch_remotive),
    ("Arbeitnow",       search.fetch_arbeitnow),
    ("WeWorkRemotely",  search.fetch_weworkremotely),
    ("RemoteOK",        search.fetch_remoteok),
    ("GitHub vagas",    search.fetch_github_vagas),
    ("HN hiring",       search.fetch_hn_hiring),
    ("LinkedIn (auth)", search.fetch_linkedin_auth),
]

class Timeout(Exception): pass
def _alarm(s, f): raise Timeout()
signal.signal(signal.SIGALRM, _alarm)

seen        = set(search.load_seen())
current     = search.load_inbox()
current_ids = {j["id"] for j in current}
found       = []

new_total = 0
for name, fn in FETCHERS:
    try:
        signal.alarm(90)
        res = fn() or []
        signal.alarm(0)
        print(f"  {name}: {len(res)} vagas")
        # salva incrementalmente — se o processo morrer no meio (RAM/sessão),
        # o que já foi achado nao se perde
        new_here = [j for j in res if j["id"] not in seen and j["id"] not in current_ids]
        if new_here:
            current.extend(new_here)
            current_ids.update(j["id"] for j in new_here)
            search.save_inbox(current)
            new_total += len(new_here)
            found += new_here
    except Timeout:
        print(f"  {name}: TIMEOUT (90s) — pulado")
    except Exception as e:
        signal.alarm(0)
        print(f"  {name}: erro {e.__class__.__name__}: {e}")

new = found
if new:
    print(f"\n✅ {len(new)} vaga(s) nova(s). inbox agora: {len(current)}")
    for j in new[:30]:
        print(f"  [{j.get('source',''):14}] {j.get('title','')} — {j.get('company','')}")
    if len(new) > 30: print(f"  ... e mais {len(new)-30}")
else:
    print("\n— Nenhuma vaga nova.")
try:
    search.gerar_relatorio(current, new)
except Exception as e:
    print(f"(relatorio falhou: {e})")
