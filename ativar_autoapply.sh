#!/usr/bin/env bash
# Liga a busca noturna (cron, 23h23). Desligar: ./desativar_autoapply.sh
DIR="$(cd "$(dirname "$0")" && pwd)"
LINE="23 23 * * * bash $DIR/run_nightly.sh >> $DIR/log_cron.txt 2>&1"
( crontab -l 2>/dev/null | grep -vF "$DIR/run_nightly.sh" ; echo "$LINE" ) | crontab -
echo "Ativado: roda todo dia às 23h23 (PC ligado)."
