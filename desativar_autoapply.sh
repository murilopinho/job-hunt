#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")" && pwd)"
crontab -l 2>/dev/null | grep -vF "$DIR/run_nightly.sh" | crontab -
echo "Desativado."
