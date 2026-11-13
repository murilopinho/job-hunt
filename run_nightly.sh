#!/usr/bin/env bash
# Job hunt — roda toda noite: busca novas vagas e notifica
set -euo pipefail
cd "$(dirname "$0")"

LOG="log_$(date +%Y%m%d).txt"
echo "=== job-hunt $(date) ===" | tee "$LOG"
python3 search.py 2>&1 | tee -a "$LOG"

# Conta novas vagas (status ausente = pendente)
NEW=$(python3 -c "
import json; f=open('inbox.json')
jobs=json.load(f)
print(sum(1 for j in jobs if not j.get('status')))
" 2>/dev/null || echo "0")

echo ""
echo "Novas vagas pendentes: $NEW"

# Auto-apply SÓ se você ligar de propósito: AUTO_APPLY=1 no cron/ambiente.
# Ele ENVIA candidaturas de verdade (Greenhouse/Lever). Padrão: só busca.
[ "${AUTO_APPLY:-0}" = "1" ] || { echo "Auto-apply desligado (AUTO_APPLY=1 para ligar)."; exit 0; }
GH=$(python3 -c "
import json
jobs=json.load(open('inbox.json'))
print(sum(1 for j in jobs if not j.get('status') and j.get('ats') in ('greenhouse','lever','ashby')))
" 2>/dev/null || echo "0")

if [ "$GH" -gt 0 ]; then
    echo "Auto-aplicando em $GH vagas Greenhouse/Lever..."
    python3 apply.py --auto 2>&1 | tee -a "$LOG"
fi
