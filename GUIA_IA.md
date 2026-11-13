# Guia para a IA: configurar o rastreador de vagas

Este arquivo é para a IA (Claude Code, Codex, Cursor...) que está ajudando a pessoa a montar o Job Hunt. A pessoa é o usuário; **você é quem conduz a configuração**.

## Regras

1. **Pergunte antes de configurar.** Faça as perguntas abaixo, em blocos pequenos (3 a 5 por vez), em português simples. Não preencha nada por suposição.
2. **Não invente dados pessoais.** Nome, e-mail, telefone, LinkedIn e carta de apresentação vêm só do que a pessoa disser.
3. **Nunca rode `python3 apply.py --auto` nem ligue `AUTO_APPLY=1` sem pedido explícito.** Isso envia candidaturas reais em nome da pessoa.
4. **Nunca responda por ela visto, autorização de trabalho ou elegibilidade.** Só se ela mandar e você gravar no `profile.json`.
5. **Não suba para o GitHub** `config.json`, `profile.json`, `cv/`, `inbox.json` nem `linkedin_cookies.json` (já estão no `.gitignore`; confira com `git status` antes de qualquer commit).
6. Mostre o que vai gravar e peça confirmação antes de escrever os arquivos.

## Entrevista

### Bloco 1: o que procurar
1. Qual área e cargo você quer? (ex.: QA, desenvolvedor front-end, suporte, dados, design)
2. Qual nível? (estágio, júnior, pleno, sênior) E quais níveis você **não** quer ver?
3. Que nomes esse cargo tem nas vagas? Pense em português e em inglês. (ex.: "Analista de Testes", "QA Engineer", "SDET")
4. Há títulos que parecem a área mas não são? (ex.: "técnico de laboratório" para QA, "SAP" para dev). Vão para a lista de exclusão.
5. Aceita estágio ou trainee? (hoje o filtro descarta; mude se quiser)

### Bloco 2: onde
6. Em qual cidade e estado você mora? (vira `home_uf` e `home_places`; só ela é aceita em vaga presencial)
7. Aceita vaga híbrida/presencial só na sua cidade, ou só remoto?
8. Remoto: só para o Brasil, América Latina, ou o mundo todo? (muita vaga "remoto mundial" exige morar no país)
9. Procura vaga fora do Brasil? Se sim, precisa de visto lá? Há regiões que você não pode ou não quer atender? (vão em `BLOCKED_REGIONS`)
10. Qual seu nível de inglês? (leitura, escrita, conversa). Define se vale buscar em inglês.

> Limite do projeto: ele foi feito para o mercado brasileiro (estados BR, Indeed Brasil, LinkedIn com `geoId` do Brasil, repositórios de vagas BR). Se a pessoa mora em **outro país**, avise e adapte `location_ok()` em `search.py` e o `geoId` em `busca_li_br.py`; não finja que funciona de graça.

### Bloco 3: fontes e empresas
11. Há empresas que você quer acompanhar? Veja se têm board em `boards.greenhouse.io/<nome>` ou `jobs.lever.co/<nome>`; se tiver, entram em `GH_COMPANIES` / `LV_COMPANIES`.
12. Há empresas que você quer evitar?
13. Usa LinkedIn? Aceita fazer login uma vez (`save_linkedin_cookies.py`) para a busca autenticada, ou prefere só a busca pública?

### Bloco 4: dados dos formulários (`profile.json`)
14. Nome completo, e-mail e telefone com DDD.
15. Cidade e país.
16. Link do LinkedIn.
17. Empresa atual (pode ficar vazia).
18. Texto curto de apresentação que serve para qualquer vaga (até ~5 linhas). Se não tiver, ajude a escrever **só com fatos que ela deu**.
19. Onde estão os currículos em PDF? (copiar para `cv/cv_pt.pdf` e `cv/cv_en.pdf`)
20. Precisa de patrocínio de visto? Tem autorização de trabalho no país da vaga? (só grave se ela responder; senão deixe vazio e ela responde à mão)

### Bloco 5: como vai rodar
21. O computador fica ligado às 23h23? (horário do cron). Se não, qual horário serve?
22. Quanta memória tem o PC? Com 8 GB ou menos, use `search.py --light` e não a busca completa.
23. Quer **só receber a lista** de vagas ou também **candidatura automática**? Explique: o envio automático só funciona em Greenhouse/Lever abertos, a maior parte das vagas pede login e ela aplica à mão. Padrão recomendado: só a lista.

## Depois da entrevista

1. Crie `config.json` (a partir de `config.example.json`) e `profile.json` (a partir de `profile.example.json`) com as respostas. Mostre o conteúdo e peça "pode gravar?".
2. Ajuste `SENIOR_FILTER` (`search.py`) e `FORA`/`ESTAGIO` (`busca_li_br.py`) ao nível e às exclusões dela. Mostre o diff.
3. Instale: `pip install playwright && playwright install chromium`.
4. **Teste primeiro:** `python3 search.py --light`. Depois `python3 busca_li_br.py 7`.
5. Mostre as 10 melhores vagas e pergunte: "estas fazem sentido?". Procure dois erros:
   - **Lixo entrando** (cargo errado, nível errado, cidade que ela não atende): aperte os filtros.
   - **Boa vaga faltando**: afrouxe `keywords` ou adicione termos.
   Repita até ela aprovar.
6. Só então ofereça o cron (`./ativar_autoapply.sh`). Explique que `./desativar_autoapply.sh` desliga.
7. Explique o dia a dia: ler `reports/vagas_AAAA-MM-DD.md`, aplicar nas melhores e marcar o resultado. `python3 apply.py` abre 5 vagas por vez para ela revisar e enviar.

## Problemas conhecidos

- O LinkedIn bloqueia depois de ~40 buscas seguidas e devolve vazio sem avisar. Espere e tente de novo.
- `location=` em texto é ignorado pelo LinkedIn; por isso `busca_li_br.py` usa `geoId`.
- Títulos vêm com `&amp;` (use `html.unescape`). `f_WT=2` deixa passar vaga híbrida.
- "Remoto" puro em algumas fontes passa o filtro de local mesmo exigindo morar em outro país: confira a descrição antes de aplicar.
- Dropdowns do Greenhouse são React Select, não `<select>`: use `fill_gh_react_select`.
- Se o site mudar o HTML, a busca daquela fonte pode voltar vazia. Teste a fonte isolada antes de culpar o filtro.
