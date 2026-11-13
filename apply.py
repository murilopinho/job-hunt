#!/usr/bin/env python3
"""
Abre vagas do inbox.json e tenta se candidatar automaticamente.
Suporte: Greenhouse, Lever, Gupy. Outros: abre no browser pra candidatura manual.
"""
import json, sys, time
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

DIR     = Path(__file__).parent
INBOX   = DIR / "inbox.json"
SEEN    = DIR / "seen.txt"
PROFILE = DIR / "profile.json"
REPORT_DIR = DIR / "reports" / "auto_apply"

def _first_existing(*paths):
    for p in paths:
        if p.exists():
            return p
    return paths[0]

CV_EN = _first_existing(DIR / "cv" / "cv_en.pdf", DIR / "cv" / "cv_pt.pdf")
CV_PT = _first_existing(DIR / "cv" / "cv_pt.pdf", DIR / "cv" / "cv_en.pdf")

def load_profile():
    if not PROFILE.exists():
        print(f"⚠️  Perfil não encontrado em {PROFILE} — pulando auto-apply.")
        print("    Copie profile.example.json para profile.json e preencha.")
        sys.exit(0)
    return json.loads(PROFILE.read_text(encoding="utf-8"))

def load_inbox():
    if not INBOX.exists(): return []
    return json.loads(INBOX.read_text())

def save_inbox(jobs):
    INBOX.write_text(json.dumps(jobs, indent=2, ensure_ascii=False))

def mark_seen(job_id):
    seen = set()
    if SEEN.exists():
        seen = set(l.strip() for l in SEEN.read_text().splitlines() if l.strip())
    seen.add(job_id)
    SEEN.write_text("\n".join(sorted(seen)) + "\n")

def fill_input(page, selectors, value):
    """Tenta preencher input por múltiplos seletores."""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.fill(value)
                return True
        except: pass
    return False

def select_option_containing(page, selector, text):
    """Seleciona opção de dropdown que contém o texto."""
    try:
        sel = page.locator(selector).first
        if not sel.is_visible(timeout=2000): return False
        opts = sel.locator("option").all()
        for o in opts:
            if text.lower() in (o.inner_text() or "").lower():
                sel.select_option(value=o.get_attribute("value") or "")
                return True
    except: pass
    return False

def check_missing_required(page):
    """Retorna lista de campos obrigatórios não preenchidos."""
    missing = []
    try:
        # React Selects obrigatórios: backing input aria-hidden vazio = dropdown não preenchido
        # Detecta pelo container select__container que NÃO tem single-value
        empties = page.evaluate("""() => {
            const containers = document.querySelectorAll('.select__container');
            return Array.from(containers).filter(c => {
                // ignora se não tem required dentro
                if (!c.querySelector('[required]')) return false;
                return !c.querySelector('.select__single-value');
            }).map(c => {
                const lbl = c.querySelector('label');
                return lbl ? lbl.innerText.trim().substring(0, 60) : '?';
            });
        }""")
        missing.extend(empties)

        # checkboxes required: pelo menos um do grupo deve estar marcado
        handled = set()
        for el in page.locator('input[type="checkbox"][required]').all():
            try:
                name = el.get_attribute("name") or ""
                if not name or name in handled: continue
                handled.add(name)
                group = page.locator(f'input[type="checkbox"][name="{name}"]').all()
                if not any(o.is_checked() for o in group):
                    lbl = page.locator(f'label[for="{el.get_attribute("id") or ""}"]')
                    missing.append(lbl.first.inner_text(timeout=300)[:40] if lbl.count() else name)
            except: pass

        # inputs de texto/select nativos required e vazios (exclui aria-hidden e checkboxes)
        for el in page.locator('input[required]:not([aria-hidden]):not([type="checkbox"]):not([type="file"]):not([type="hidden"]), textarea[required], select[required]').all():
            try:
                if not el.is_visible(timeout=300): continue
                val = el.input_value(timeout=300)
                if not val or not val.strip():
                    label = el.get_attribute("name") or el.get_attribute("id") or "?"
                    missing.append(label)
            except: pass
    except: pass
    return missing

def fill_gh_react_select(page, label_id, desired_text):
    """Seleciona opção em React Select do Greenhouse via locator :has()."""
    try:
        ctrl = page.locator(f'div.select__container:has(#{label_id}) .select__control').first
        ctrl.scroll_into_view_if_needed(timeout=2000)
        ctrl.click(timeout=3000)
        page.wait_for_timeout(800)
        opts = page.locator('[class*="option"]:visible, [role="option"]:visible').all()
        for opt in opts:
            txt = opt.inner_text(timeout=500)
            if desired_text.lower() in txt.lower():
                opt.click(); page.wait_for_timeout(300); return True
        page.keyboard.press("Escape")
    except: pass
    return False

def fill_greenhouse(page, p):
    """Preenche formulário padrão do Greenhouse."""
    filled = 0
    mapping = [
        (["#first_name", 'input[name="first_name"]'],       p.get("First Name","")),
        (["#last_name",  'input[name="last_name"]'],         p.get("Last Name","")),
        (["#email",      'input[name="email"]'],             p.get("Email","")),
        (["#phone",      'input[name="phone"]'],             p.get("Phone","")),
        (['input[name="job_application[location]"]'],        p.get("City","")),
        (['textarea[name="job_application[cover_letter_text]"]'], p.get("Cover Letter","")),
    ]
    for sels, val in mapping:
        if fill_input(page, sels, val): filled += 1

    # LinkedIn — campo de texto simples ou React Select text input
    linkedin_val = p.get("LinkedIn","")
    try:
        li = page.locator('input[name*="linkedin"], input[id*="linkedin"], input[placeholder*="linkedin" i]').first
        if li.is_visible(timeout=2000):
            li.fill(linkedin_val); filled += 1
    except: pass
    # tenta também pelo id do campo custom (question_*) com label linkedin
    try:
        lbl = page.locator('label:has-text("LinkedIn")').first
        for_id = lbl.get_attribute("for")
        if for_id:
            inp = page.locator(f'#{for_id}')
            if inp.is_visible(timeout=1000):
                inp.fill(linkedin_val); filled += 1
    except: pass

    # Resume upload
    try:
        up = page.locator('input[type="file"]').first
        if up.is_visible(timeout=2000):
            up.set_input_files(str(CV_EN)); filled += 1
    except: pass

    # Dropdowns nativos (select) — visa/autorização
    # só responde se você disser no profile.json (é declaração legal; vazio = fica pra você)
    if p.get("Needs Sponsorship"):
        for sel in ['select[name*="sponsor"]', 'select[id*="sponsor"]']:
            if select_option_containing(page, sel, p["Needs Sponsorship"]): filled += 1; break
    if p.get("Authorized To Work"):
        for sel in ['select[name*="authorized"]', 'select[name*="legally"]', 'select[id*="authorized"]']:
            if select_option_containing(page, sel, p["Authorized To Work"]): filled += 1; break

    # Country — input nativo ou React Select
    country_val = p.get("Country", "")
    try:
        c = page.locator('input[name="country"], select[name="country"]').first
        if c.is_visible(timeout=1000): c.fill(country_val); filled += 1
    except: pass

    # Location (City) — campo de texto custom obrigatório em muitos boards
    try:
        loc_inp = page.locator('input[id*="location" i], input[placeholder*="city" i], input[aria-label*="location" i]').first
        if loc_inp.is_visible(timeout=1500) and not (loc_inp.input_value() or "").strip():
            loc_inp.fill(f'{p.get("City","")}, {p.get("Country","")}')
            page.wait_for_timeout(600)
            # autocomplete: clica primeira sugestão se aparecer
            try:
                sug = page.locator('[class*="option"]:visible, [role="option"]:visible').first
                if sug.is_visible(timeout=1000): sug.click()
            except: pass
            filled += 1
    except: pass

    # React Select custom questions — detecta por texto do label
    # NOTA: NÃO auto-responde elegibilidade/visto (atestado legal → fica p/ revisão manual)
    react_dropdowns = [
        ("ITAR", "Not currently"),
        ("how did you hear", "LinkedIn"),
        ("source", "LinkedIn"),
        ("referred", "LinkedIn"),
        ("worked for", "No"),
        ("previously employed", "No"),
        ("former employee", "No"),
        ("currently employed", "No"),
        ("relationship", "No"),
        ("related to", "No"),
        ("family", "No"),
        ("conflict of interest", "No"),
        ("gender", "Decline"),
        ("race", "Decline"),
        ("ethnicity", "Decline"),
        ("veteran", "Decline"),
        ("disability", "Decline"),
        ("hispanic", "Decline"),
    ]
    labels = page.locator('label[id$="-label"]').all()
    for lbl in labels:
        try:
            lbl_text = lbl.inner_text(timeout=500).lower()
            lbl_id   = lbl.get_attribute("id")
            for keyword, answer in react_dropdowns:
                if keyword.lower() in lbl_text:
                    if fill_gh_react_select(page, lbl_id, answer):
                        filled += 1
                    break
        except: pass

    # Checkbox groups obrigatórios — ex: "preferred location"
    # Marca opção "Remote" se disponível, senão a primeira opção
    handled_groups = set()
    for chk in page.locator('input[type="checkbox"][required]').all():
        try:
            name = chk.get_attribute("name") or ""
            if not name or name in handled_groups: continue
            group = page.locator(f'input[type="checkbox"][name="{name}"]').all()
            # tenta achar opção "remote"
            chosen = None
            for opt in group:
                oid = opt.get_attribute("id") or ""
                lbl_el = page.locator(f'label[for="{oid}"]')
                opt_txt = lbl_el.first.inner_text(timeout=300).lower() if lbl_el.count() else ""
                if "remote" in opt_txt:
                    chosen = opt; break
            if not chosen and group:
                chosen = group[0]
            if chosen:
                chosen.check()
                filled += 1
            handled_groups.add(name)
        except: pass

    return filled

def fill_lever(page, p):
    """Preenche formulário padrão do Lever."""
    filled = 0
    mapping = [
        (['input[name="name"]'],     p.get("Full Name","")),
        (['input[name="email"]'],    p.get("Email","")),
        (['input[name="phone"]'],    p.get("Phone","")),
        (['input[name="org"]'],      p.get("Current Company","")),
        (['textarea[name="comments"]'], p.get("Cover Letter","")),
        (['input[name="urls[LinkedIn]"]', 'input[placeholder*="linkedin"]'], p.get("LinkedIn","")),
    ]
    for sels, val in mapping:
        if fill_input(page, sels, val): filled += 1
    try:
        up = page.locator('input[type="file"]').first
        if up.is_visible(timeout=2000):
            up.set_input_files(str(CV_EN))
            filled += 1
    except: pass
    return filled

def fill_gupy(page, p):
    """Preenche formulário do Gupy (board brasileiro)."""
    filled = 0
    # Gupy pede login — pula campos de auth, foca nos dados
    mapping = [
        (['input[id*="name"]', 'input[placeholder*="nome"]'],    p.get("Full Name","")),
        (['input[id*="email"]', 'input[placeholder*="e-mail"]'], p.get("Email","")),
        (['input[id*="phone"]', 'input[placeholder*="telefone"]'],p.get("Phone","")),
        (['input[id*="city"]', 'input[placeholder*="cidade"]'],  p.get("City","")),
    ]
    for sels, val in mapping:
        if fill_input(page, sels, val): filled += 1
    return filled

def generate_auto_report(session_log):
    """Gera relatório Markdown da sessão --auto em REPORT_DIR."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    fname = f"auto_apply_{now.strftime('%Y-%m-%d_%Hh%M')}.md"
    path = REPORT_DIR / fname

    done    = [e for e in session_log if e["result"] == "done"]
    manual  = [e for e in session_log if e["result"] == "manual"]
    errors  = [e for e in session_log if e["result"] == "error"]

    lines = [
        f"# Relatório Auto-Apply — {now.strftime('%d/%m/%Y %H:%M')}",
        "",
        "## Resumo",
        f"| Métrica | Total |",
        f"|---|---|",
        f"| Submetidas com sucesso | {len(done)} |",
        f"| Enviadas para revisão manual (campos faltando) | {len(manual)} |",
        f"| Erros | {len(errors)} |",
        f"| Total processadas | {len(session_log)} |",
        "",
    ]

    if done:
        lines += ["## ✅ Candidaturas Enviadas", ""]
        for e in done:
            lines += [
                f"### {e['title']} — {e['company']}",
                f"- **Localização:** {e['location']}",
                f"- **ATS:** {e['ats'].upper()}",
                f"- **URL:** {e['apply']}",
                f"- **Campos preenchidos:** {e['fields_filled']}",
                f"- **Horário:** {e['time']}",
                "",
            ]

    if manual:
        lines += ["## ⚠️ Precisam de Revisão Manual (campos obrigatórios faltando)", ""]
        for e in manual:
            missing_str = ", ".join(e.get("missing_fields", [])) or "desconhecido"
            lines += [
                f"### {e['title']} — {e['company']}",
                f"- **Localização:** {e['location']}",
                f"- **ATS:** {e['ats'].upper()}",
                f"- **URL:** {e['apply']}",
                f"- **Campos faltando:** `{missing_str}`",
                f"- **Campos preenchidos:** {e['fields_filled']}",
                "",
            ]

    if errors:
        lines += ["## ❌ Erros", ""]
        for e in errors:
            lines += [
                f"### {e['title']} — {e['company']}",
                f"- **URL:** {e['apply']}",
                f"- **Erro:** {e.get('error_msg', 'desconhecido')}",
                "",
            ]

    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nRelatório salvo em: {path}")
    return path

def apply_job(job, p, browser, auto=False):
    ats  = job["ats"]
    url  = job["apply"]
    title = job["title"]
    co   = job["company"]
    print(f"\n  {title} — {co} [{ats}]")
    print(f"     {url}")

    # offsite = redireciona para site externo (pode ter formulário automatizavel)
    # linkedin_easy = candidatura dentro do LinkedIn (precisa de login)
    base_entry = {
        "title": title, "company": co, "location": job.get("location",""),
        "ats": ats, "apply": url, "fields_filled": 0,
        "time": datetime.now().strftime("%H:%M:%S"),
    }

    if ats in ("other", "linkedin", "linkedin_easy", "indeed", "workday"):
        tipo = "Easy Apply (LinkedIn)" if ats == "linkedin_easy" else "manual"
        print(f"     → {tipo}: abre no browser.")
        import subprocess
        subprocess.Popen(["xdg-open", url])
        time.sleep(3)
        return "manual", {**base_entry, "result": "manual"}

    if ats == "offsite":
        print(f"     → offsite: abre no browser.")
        import subprocess
        subprocess.Popen(["xdg-open", url])
        time.sleep(3)
        return "manual", {**base_entry, "result": "manual"}

    page = browser.new_page()
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        if ats == "greenhouse":
            n = fill_greenhouse(page, p)
        elif ats == "lever":
            n = fill_lever(page, p)
        elif ats == "gupy":
            n = fill_gupy(page, p)
        else:
            n = 0

        print(f"     {n} campos preenchidos")
        base_entry["fields_filled"] = n

        if auto:
            page.wait_for_timeout(1000)
            # ponytail: 0 campos preenchidos = não é formulário real (ex: página de carreira JS) → manual, não "done"
            if n == 0:
                print(f"     0 campos preenchidos — provavelmente não é form Greenhouse real. Marcando 'manual'.")
                page.close()
                return "manual", {**base_entry, "result": "manual", "missing_fields": ["formulário não detectado"]}
            missing = check_missing_required(page) if ats == "greenhouse" else []
            if missing:
                print(f"     CAMPOS OBRIGATORIOS FALTANDO: {missing}")
                print(f"     Marcando como 'manual' para revisao humana.")
                page.close()
                return "manual", {**base_entry, "result": "manual", "missing_fields": missing}
            try:
                btn = page.locator('button[type="submit"], input[type="submit"], #submit_app').first
                btn.click(timeout=5000)
                page.wait_for_timeout(2000)
                print(f"     Submetido automaticamente.")
            except Exception as e:
                # submit falhou = candidatura NÃO enviada → manual, não "done"
                print(f"     Nao conseguiu clicar em Submit: {e}")
                page.close()
                return "manual", {**base_entry, "result": "manual", "missing_fields": ["submit falhou"]}
            page.close()
            return "done", {**base_entry, "result": "done"}
        else:
            print("     Revise e clique em Submit. Pressione ENTER quando finalizar (ou 's' para pular)...")
            resp = input("     > ").strip().lower()
            if resp == "s":
                page.close()
                return "skipped", {**base_entry, "result": "skipped"}
            page.close()
            return "done", {**base_entry, "result": "done"}
    except Exception as e:
        print(f"     Erro: {e}")
        page.close()
        return "error", {**base_entry, "result": "error", "error_msg": str(e)}

def main():
    auto_mode = "--auto" in sys.argv

    inbox = load_inbox()
    if not inbox:
        print("Inbox vazio. Rode search.py primeiro.")
        sys.exit(0)

    p = load_profile()

    # Filtra não-candidatados
    pending = [j for j in inbox if j.get("status") not in ("done","skipped","manual","error","closed","ghost","filtered")]
    if not pending:
        print(f"Todas as {len(inbox)} vagas já foram processadas.")
        sys.exit(0)

    # Ordena: mais recente primeiro, depois por tipo de ATS (auto-fill antes de manual)
    ATS_PRIORITY = {"greenhouse": 0, "lever": 1, "ashby": 2, "gupy": 3, "offsite": 4}
    # "posted" = data real da vaga (busca_li_br.py); "found" = dia que entrou no inbox
    pending.sort(key=lambda j: (j.get("posted") or j.get("found",""),-ATS_PRIORITY.get(j.get("ats",""), 9)), reverse=True)

    # No modo auto: só processa Greenhouse/Lever (formulários automatizáveis)
    if auto_mode:
        pending = [j for j in pending if j.get("ats") in ("greenhouse","lever","ashby","gupy")]
        if not pending:
            print("Nenhuma vaga Greenhouse/Lever pendente para auto-apply.")
            sys.exit(0)
        print(f"Modo --auto: {len(pending)} vagas Greenhouse/Lever serao submetidas automaticamente.")

    # Separa por tipo para mostrar resumo
    auto  = [j for j in pending if j.get("ats") in ("greenhouse","lever","ashby","gupy")]
    offsite = [j for j in pending if j.get("ats") == "offsite"]
    easy  = [j for j in pending if j.get("ats") == "linkedin_easy"]
    rest  = [j for j in pending if j.get("ats") not in ("greenhouse","lever","ashby","gupy","offsite","linkedin_easy")]

    print(f"Resumo:")
    print(f"  {len(auto)} auto-preenchimento (Greenhouse/Lever/Gupy)")
    print(f"  {len(offsite)} offsite (site externo — pode ter formulario automatizavel)")
    print(f"  {len(easy)} Easy Apply (dentro do LinkedIn)")
    print(f"  {len(rest)} outros\n")

    print(f"Todas as {len(pending)} vagas:\n")
    for i, j in enumerate(pending):
        tag = j.get("ats","?")
        print(f"  [{i+1:2}] [{tag:14}] {j['title'][:45]} — {j['company']} ({j['location']})")

    if not auto_mode:
        print(f"\nCandidatar em todas? [s/n] ou número específico: ", end="")
        choice = input().strip().lower()
        if choice == "n":
            sys.exit(0)
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(pending):
                pending = [pending[idx]]
            else:
                print("Número inválido."); sys.exit(1)

    BATCH = 5
    headless = auto_mode
    session_log = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless, slow_mo=300 if not headless else 0)
        for i, job in enumerate(pending):
            result, entry = apply_job(job, p, browser, auto=auto_mode)
            session_log.append(entry)
            for j in inbox:
                if j["id"] == job["id"]:
                    j["status"] = result
                    j["applied"] = datetime.now().isoformat()[:10]
            save_inbox(inbox)
            if result == "done":
                mark_seen(job["id"])
                print(f"     Candidatura registrada.")
            if not auto_mode and (i + 1) % BATCH == 0 and (i + 1) < len(pending):
                print(f"\n{BATCH} vagas abertas. Feche as abas e pressione ENTER para continuar (ou 'q' para parar)...")
                resp = input("> ").strip().lower()
                if resp == "q":
                    break
        browser.close()

    done    = sum(1 for j in inbox if j.get("status") == "done")
    skipped = sum(1 for j in inbox if j.get("status") == "skipped")
    print(f"\nSessao encerrada — {done} candidaturas enviadas, {skipped} puladas.")

    if auto_mode and session_log:
        generate_auto_report(session_log)

if __name__ == "__main__":
    main()
