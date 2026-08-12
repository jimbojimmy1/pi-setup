#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
app="$tmp/app"

MONEY_AGENT_DIR="$app" MA_SKIP_APT=1 MA_SKIP_SYSTEMD=1 \
  bash "$root/setup-money-agent.sh"

for file in \
  store.py llm.py agent.py experiments.py monitoring.py import_observation.py inbox.py app.py profile.json templates/index.html
do
  cmp "$root/money_agent/$file" "$app/$file"
done

grep -Fx 'MA_TRUSTED_MEASUREMENT_SOURCES=' "$app/config.env"

printf '%s\n' 'MA_DAILY_USD=0' > "$app/config.env"
printf '%s\n' '{"customized": true}' > "$app/profile.json"
printf '%s\n' 'durable data' > "$app/money.db"

MONEY_AGENT_DIR="$app" MA_SKIP_APT=1 MA_SKIP_SYSTEMD=1 \
  bash "$root/setup-money-agent.sh"

grep -Fx 'MA_DAILY_USD=0' "$app/config.env"
grep -Fx '{"customized": true}' "$app/profile.json"
grep -Fx 'durable data' "$app/money.db"
python3 -m py_compile "$app/"*.py
