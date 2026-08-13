#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
app="$tmp/app"

expected_release="$(git -C "$root" rev-parse HEAD)"
if [ -n "$(git -C "$root" status --porcelain --untracked-files=normal)" ]; then
  expected_release="${expected_release}-dirty"
fi

MONEY_AGENT_DIR="$app" MA_SKIP_APT=1 MA_SKIP_SYSTEMD=1 \
  bash "$root/setup-money-agent.sh"

for file in \
  store.py llm.py agent.py experiments.py monitoring.py import_observation.py inbox.py app.py profile.json templates/index.html
do
  cmp "$root/money_agent/$file" "$app/$file"
done

grep -Fx 'MA_TRUSTED_MEASUREMENT_SOURCES=' "$app/config.env"
grep -Fx 'MA_EXPECTED_RELEASE_REF=' "$app/config.env"
grep -Fx "$expected_release" "$app/release.txt"

printf '%s\n' 'MA_DAILY_USD=0' > "$app/config.env"
printf '%s\n' '{"customized": true}' > "$app/profile.json"
printf '%s\n' 'durable data' > "$app/money.db"

MONEY_AGENT_DIR="$app" MA_SKIP_APT=1 MA_SKIP_SYSTEMD=1 \
  bash "$root/setup-money-agent.sh"

grep -Fx 'MA_DAILY_USD=0' "$app/config.env"
grep -Fx '{"customized": true}' "$app/profile.json"
grep -Fx 'durable data' "$app/money.db"
grep -Fx "$expected_release" "$app/release.txt"
python3 -m py_compile "$app/"*.py

cp "$root/setup-money-agent.sh" "$tmp/standalone-installer.sh"
if MONEY_AGENT_DIR="$tmp/invalid" MA_SKIP_APT=1 MA_SKIP_SYSTEMD=1 \
  MA_RELEASE_REF='main' bash "$tmp/standalone-installer.sh"; then
  printf 'installer accepted a mutable standalone ref\n' >&2
  exit 1
fi

mkdir "$tmp/bin"
cat > "$tmp/bin/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
output=''
url=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    --output) output="$2"; shift 2 ;;
    http*) url="$1"; shift ;;
    *) shift ;;
  esac
done
relative="${url#*/money_agent/}"
cp -- "$TEST_SOURCE_ROOT/$relative" "$output"
EOF
chmod +x "$tmp/bin/curl"
standalone_sha='0123456789abcdef0123456789abcdef01234567'
PATH="$tmp/bin:$PATH" TEST_SOURCE_ROOT="$root/money_agent" \
  MONEY_AGENT_DIR="$tmp/standalone" MA_SKIP_APT=1 MA_SKIP_SYSTEMD=1 \
  MA_RELEASE_REF="$standalone_sha" bash "$tmp/standalone-installer.sh"
grep -Fx "$standalone_sha" "$tmp/standalone/release.txt"

mkdir "$tmp/fail-bin"
cat > "$tmp/fail-bin/install" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
destination="${!#}"
if [[ "$destination" == */app.py ]]; then
  exit 55
fi
exec /usr/bin/install "$@"
EOF
chmod +x "$tmp/fail-bin/install"
if PATH="$tmp/fail-bin:$PATH" MONEY_AGENT_DIR="$app" MA_SKIP_APT=1 \
  MA_SKIP_SYSTEMD=1 bash "$root/setup-money-agent.sh"; then
  printf 'installer failure injection unexpectedly succeeded\n' >&2
  exit 1
fi
if [ -e "$app/release.txt" ]; then
  printf 'failed upgrade left a stale release marker\n' >&2
  exit 1
fi
