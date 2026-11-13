# Job Hunt

Busca vagas todo dia (LinkedIn, Indeed BR, Greenhouse, Lever, Remotive e outras), guarda tudo num `inbox.json` e, se você quiser, preenche formulários de candidatura por você.

Feito para Linux, em Python. O exemplo vem configurado para QA júnior em Brasília; **você troca pela sua área e cidade** em `config.json`.

## Leia antes (limites reais)

- **Busca funciona bem.** Ela gera uma lista de vagas novas por dia em `reports/`.
- **Auto-candidatura é limitada.** Só envia sozinha em formulários **Greenhouse/Lever abertos** (sem login). A maioria das vagas do Brasil passa pelo LinkedIn/Gupy e pede login, então você aplica à mão. Na prática, a lista curada vale mais que o envio automático.
- **O envio automático manda candidatura de verdade.** Por isso vem **desligado**: o cron só busca. Para ligar, rode a noturna com `AUTO_APPLY=1`.
- Visto e autorização de trabalho **não são respondidos sozinhos**, a menos que você preencha `Needs Sponsorship` / `Authorized To Work` no `profile.json`. É declaração legal, decida você.
- O LinkedIn bloqueia buscas em excesso (depois de ~40 seguidas). Se vier vazio, espere e rode de novo.
- A busca completa usa bastante memória. Em PC com 8 GB, prefira `python3 search.py --light`.

## Instalar

```bash
git clone <url-deste-repo> job-hunt && cd job-hunt
pip install playwright && playwright install chromium
cp config.example.json config.json      # sua área, termos de busca, cidade
cp profile.example.json profile.json    # seus dados para os formulários
# coloque seus currículos em cv/cv_pt.pdf e cv/cv_en.pdf (um só serve: o outro vira cópia dele)
```

`config.json`, `profile.json`, `cv/` e `inbox.json` ficam só no seu PC (estão no `.gitignore`). Não os envie para o GitHub.

## Usar

```bash
python3 search.py --light      # busca leve (sem LinkedIn pesado)
python3 search.py              # busca completa
python3 busca_li_br.py 1       # LinkedIn Brasil, vagas das últimas 24h (N dias)
python3 apply.py               # lista pendentes e abre 5 por vez para você aplicar
python3 apply.py --auto        # ENVIA sozinho (só Greenhouse/Lever). Cuidado.
```

Relatórios em `reports/vagas_AAAA-MM-DD.md`. Status de cada vaga no `inbox.json`: sem status = pendente, `done`, `manual`, `skipped`, `error`, `closed`, `filtered`.

Rodar toda noite às 23h23 (o PC precisa estar ligado): `./ativar_autoapply.sh`. Desligar: `./desativar_autoapply.sh`.

Outros: `check_closed.py` marca vagas que já fecharam; `outreach.py` é um rastreador de contatos com recrutadores (`--add`, `--touch`, `--pending`); `save_linkedin_cookies.py` salva o login do LinkedIn (opcional, para `fetch_linkedin_auth`).

## O que ajustar para a sua área

| O quê | Onde |
|---|---|
| Palavras que o título da vaga precisa ter | `config.json` → `keywords` |
| Buscas no LinkedIn (termo, lugar) | `linkedin_searches` |
| Termos PT (Indeed e `busca_li_br.py`) / termos EN | `br_terms` / `en_terms` |
| Sua cidade: presencial só aceita ela; o resto precisa ser remoto | `home_uf`, `home_places` |
| Cargos a excluir (sênior, pleno, estágio...) | `SENIOR_FILTER` em `search.py`, `FORA` e `ESTAGIO` em `busca_li_br.py` |
| Empresas com board Greenhouse/Lever | `GH_COMPANIES`, `LV_COMPANIES` em `search.py` |
| Regiões que você não pode atender | `BLOCKED_REGIONS` em `search.py` |

O `FORA` do `busca_li_br.py` descarta pleno, sênior, hardware, SAP etc., pensado para QA júnior. Revise.

---

## Para a sua IA (Claude Code, Codex, Cursor...)

Abra a IA na pasta do projeto e cole:

> Leia o README.md e o GUIA_IA.md e siga o guia: me entreviste primeiro, depois configure. Não rode `apply.py --auto` nem ligue `AUTO_APPLY=1` sem eu pedir.

O [`GUIA_IA.md`](GUIA_IA.md) tem as perguntas que a IA vai te fazer (área, nível, cidade, remoto, inglês, dados do formulário...) e o passo a passo de teste.

Mapa rápido dos arquivos:

- `search.py`: fontes (`fetch_*`), filtros `matches()` (título) e `location_ok()` (local); grava `inbox.json`, `seen.txt` e o relatório. `--light` roda só as fontes via curl.
- `busca_li_br.py`: busca no LinkedIn Brasil (`geoId`) com janela de dias; grava `posted`.
- `apply.py`: Playwright. `fill_greenhouse`, `fill_lever`, `fill_gupy` leem o `profile.json`. Sem `--auto` é interativo (use um terminal de verdade). Campo obrigatório faltando manda a vaga para `manual`.
- `run_nightly.sh`: busca + (opcional) auto-apply. Chamado pelo cron.
