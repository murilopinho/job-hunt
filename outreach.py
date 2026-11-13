#!/usr/bin/env python3
"""
Rastreio de outreach direto a recrutadores / QA leads / hiring managers.

Uso:
  python3 outreach.py --add "Nome" --company "Empresa" --role "QA Jr" \
        --url "https://linkedin.com/in/..." --channel linkedin --notes "postou vaga X"
  python3 outreach.py --list                 # tabela no terminal
  python3 outreach.py --pending              # só quem precisa de follow-up hoje
  python3 outreach.py --touch "Nome"         # registra que você falou hoje (+3 dias pro follow-up)
  python3 outreach.py --set "Nome" status respondeu
  python3 outreach.py --from-inbox           # importa recrutadores achados no inbox.json
  python3 outreach.py --md                   # (re)gera outreach.md

Status possíveis: novo, enviado, respondeu, conversando, entrevista, sem_resposta, descartado
"""
import csv, json, sys, argparse
from datetime import datetime, timedelta, date
from pathlib import Path

DIR   = Path(__file__).parent
CSV   = DIR / "outreach.csv"
MD    = DIR / "outreach.md"
INBOX = DIR / "inbox.json"
COLS  = ["nome", "empresa", "cargo_alvo", "url", "canal", "status",
         "primeiro_contato", "ultimo_contato", "proximo_followup", "notas"]
FOLLOWUP_DIAS = 3


def load():
    if not CSV.exists():
        return []
    with CSV.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save(rows):
    with CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLS})
    gen_md(rows)


def find(rows, nome):
    nome = nome.lower().strip()
    for r in rows:
        if r["nome"].lower().strip() == nome:
            return r
    # match parcial
    for r in rows:
        if nome in r["nome"].lower():
            return r
    return None


def gen_md(rows):
    today = date.today().isoformat()
    def overdue(r):
        nf = r.get("proximo_followup", "")
        return nf and nf <= today and r["status"] in ("enviado", "conversando")
    pend = [r for r in rows if overdue(r)]
    lines = [
        "# Outreach — recrutadores / QA leads",
        "",
        f"_Atualizado {datetime.now():%d/%m/%Y %H:%M}_  ·  **{len(rows)}** contatos  ·  "
        f"**{len(pend)}** precisam de follow-up hoje",
        "",
        "## ⏰ Follow-up pendente",
        "",
    ]
    if pend:
        lines.append("| Nome | Empresa | Cargo | Último contato | Canal | URL |")
        lines.append("|---|---|---|---|---|---|")
        for r in pend:
            lines.append(f"| {r['nome']} | {r['empresa']} | {r['cargo_alvo']} | "
                         f"{r['ultimo_contato']} | {r['canal']} | {r['url']} |")
    else:
        lines.append("_Nada pendente._")
    lines += ["", "## 📋 Todos os contatos", "",
              "| Nome | Empresa | Cargo | Status | 1º contato | Últ. | Próx. FU | Notas | URL |",
              "|---|---|---|---|---|---|---|---|---|"]
    order = {s: i for i, s in enumerate(
        ["entrevista", "conversando", "respondeu", "enviado", "novo", "sem_resposta", "descartado"])}
    for r in sorted(rows, key=lambda r: order.get(r["status"], 9)):
        lines.append(f"| {r['nome']} | {r['empresa']} | {r['cargo_alvo']} | {r['status']} | "
                     f"{r['primeiro_contato']} | {r['ultimo_contato']} | {r['proximo_followup']} | "
                     f"{r.get('notas','')} | {r['url']} |")
    lines += ["", "## Mensagens prontas", "", "Ver `OUTREACH.md` para os templates.", ""]
    MD.write_text("\n".join(lines), encoding="utf-8")


def cmd_add(a):
    rows = load()
    if find(rows, a.add):
        print(f"'{a.add}' já está na lista. Use --touch ou --set.")
        return
    today = date.today().isoformat()
    rows.append({
        "nome": a.add, "empresa": a.company or "", "cargo_alvo": a.role or "",
        "url": a.url or "", "canal": a.channel or "linkedin",
        "status": "novo", "primeiro_contato": "", "ultimo_contato": "",
        "proximo_followup": "", "notas": a.notes or "",
    })
    save(rows)
    print(f"+ {a.add} ({a.company}) adicionado como 'novo'.")


def cmd_touch(a):
    rows = load()
    r = find(rows, a.touch)
    if not r:
        print("não achei esse contato.")
        return
    today = date.today()
    r["ultimo_contato"] = today.isoformat()
    if not r["primeiro_contato"]:
        r["primeiro_contato"] = today.isoformat()
    r["proximo_followup"] = (today + timedelta(days=FOLLOWUP_DIAS)).isoformat()
    if r["status"] in ("novo", ""):
        r["status"] = "enviado"
    save(rows)
    print(f"✓ {r['nome']}: contato registrado {today.isoformat()}, "
          f"follow-up em {r['proximo_followup']}.")


def cmd_set(a):
    rows = load()
    r = find(rows, a.set[0])
    if not r:
        print("não achei esse contato.")
        return
    field, val = a.set[1], a.set[2]
    if field not in COLS:
        print(f"campo inválido. use um de: {', '.join(COLS)}")
        return
    r[field] = val
    save(rows)
    print(f"✓ {r['nome']}: {field} = {val}")


def cmd_list(a, only_pending=False):
    rows = load()
    if not rows:
        print("lista vazia. adicione com --add.")
        return
    today = date.today().isoformat()
    for r in rows:
        pend = (r.get("proximo_followup", "") and r["proximo_followup"] <= today
                and r["status"] in ("enviado", "conversando"))
        if only_pending and not pend:
            continue
        flag = "⏰" if pend else "  "
        print(f"{flag} {r['status']:12} {r['nome']:28} {r['empresa']:20} "
              f"{r['cargo_alvo']:18} {r['url']}")


def cmd_from_inbox(a):
    if not INBOX.exists():
        print("inbox.json não encontrado.")
        return
    jobs = json.loads(INBOX.read_text())
    rows = load()
    n = 0
    for j in jobs:
        rec = j.get("recruiter")
        if not rec:
            continue
        if find(rows, rec):
            continue
        rows.append({
            "nome": rec, "empresa": j.get("company", ""),
            "cargo_alvo": j.get("title", ""), "url": j.get("recruiter_url", ""),
            "canal": "linkedin", "status": "novo",
            "primeiro_contato": "", "ultimo_contato": "", "proximo_followup": "",
            "notas": f"postou: {j.get('title','')} — {j.get('url','')}",
        })
        n += 1
    save(rows)
    print(f"+ {n} recrutador(es) importado(s) do inbox.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--add"); p.add_argument("--company"); p.add_argument("--role")
    p.add_argument("--url"); p.add_argument("--channel"); p.add_argument("--notes")
    p.add_argument("--touch")
    p.add_argument("--set", nargs=3, metavar=("NOME", "CAMPO", "VALOR"))
    p.add_argument("--list", action="store_true")
    p.add_argument("--pending", action="store_true")
    p.add_argument("--from-inbox", dest="from_inbox", action="store_true")
    p.add_argument("--md", action="store_true")
    a = p.parse_args()

    if a.add:            cmd_add(a)
    elif a.touch:        cmd_touch(a)
    elif a.set:          cmd_set(a)
    elif a.from_inbox:   cmd_from_inbox(a)
    elif a.pending:      cmd_list(a, only_pending=True)
    elif a.list:         cmd_list(a)
    elif a.md:           gen_md(load()); print(f"→ {MD}")
    else:               p.print_help()


if __name__ == "__main__":
    main()
