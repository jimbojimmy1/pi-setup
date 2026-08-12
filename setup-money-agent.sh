#!/usr/bin/env bash
# Install or upgrade the Money Agent from its canonical versioned source.

set -euo pipefail

APP_DIR="${MONEY_AGENT_DIR:-$HOME/money-agent}"
PORT="${MA_PORT:-8086}"
RELEASE_REF="${MA_RELEASE_REF:-main}"
REPOSITORY="${MA_REPOSITORY:-jimbojimmy1/pi-setup}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_SOURCE="$SCRIPT_DIR/money_agent"
REQUIRED_FILES=(
  __init__.py
  store.py
  llm.py
  agent.py
  experiments.py
  monitoring.py
  import_observation.py
  app.py
  profile.json
  templates/index.html
)

stage="$(mktemp -d)"
trap 'rm -rf -- "$stage"' EXIT

log() {
  printf '[money-agent] %s\n' "$*"
}

copy_local_source() {
  local relative
  for relative in "${REQUIRED_FILES[@]}"; do
    mkdir -p "$stage/$(dirname "$relative")"
    cp -- "$LOCAL_SOURCE/$relative" "$stage/$relative"
  done
}

download_release_source() {
  local relative url
  command -v curl >/dev/null 2>&1 || {
    printf 'curl is required for a standalone install\n' >&2
    return 1
  }
  for relative in "${REQUIRED_FILES[@]}"; do
    mkdir -p "$stage/$(dirname "$relative")"
    url="https://raw.githubusercontent.com/$REPOSITORY/$RELEASE_REF/money_agent/$relative"
    curl --fail --silent --show-error --location \
      --retry 3 --connect-timeout 15 --max-time 60 \
      --output "$stage/$relative" "$url"
  done
}

validate_stage() {
  local relative
  for relative in "${REQUIRED_FILES[@]}"; do
    if [ ! -s "$stage/$relative" ]; then
      printf 'required release file is missing or empty: %s\n' "$relative" >&2
      return 1
    fi
  done
  python3 -m py_compile "$stage/"*.py
  python3 -m json.tool "$stage/profile.json" >/dev/null
}

install_config() {
  if [ -f "$APP_DIR/config.env" ]; then
    log 'config.env exists; preserving it'
    return
  fi
  cat > "$APP_DIR/config.env" <<'EOF'
# LLM backend. Leave the key empty to use the Claude CLI or dry-run backend.
ANTHROPIC_API_KEY=
MA_MODEL=claude-opus-5
MA_EFFORT=medium
MA_MAX_TOKENS=12000

# API spending is disabled by default. Raise only with explicit owner approval.
MA_DAILY_USD=0.00

# Comma-separated sources configured outside the model (for example,
# analytics_readonly). Leave empty until a read-only source is actually wired.
MA_TRUSTED_MEASUREMENT_SOURCES=

MA_TICK_SECONDS=900
MA_HORIZON=fast
MA_MAX_ROUNDS=4
MA_MAX_DEPTH=2
MA_CHILD_FANOUT=2
MA_MAX_OPEN=12
MA_PROMOTE_AT=72
MA_KILL_AT=35
EOF
  chmod 600 "$APP_DIR/config.env"
  log 'created config.env with API spending disabled'
}

install_runtime() {
  local relative
  mkdir -p "$APP_DIR/templates"
  install_config

  for relative in "${REQUIRED_FILES[@]}"; do
    if [ "$relative" = "profile.json" ] && [ -f "$APP_DIR/profile.json" ]; then
      log 'profile.json exists; preserving it'
      continue
    fi
    install -m 0644 "$stage/$relative" "$APP_DIR/$relative"
  done
}

install_services() {
  local service_user
  service_user="${MA_SERVICE_USER:-${SUDO_USER:-$USER}}"

  sudo tee /etc/systemd/system/money-agent.service >/dev/null <<EOF
[Unit]
Description=Money Agent bounded revenue experiment daemon
After=network-online.target
Wants=network-online.target

[Service]
User=$service_user
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/config.env
ExecStart=/usr/bin/python3 $APP_DIR/agent.py
Restart=always
RestartSec=15

[Install]
WantedBy=multi-user.target
EOF

  sudo tee /etc/systemd/system/money-agent-web.service >/dev/null <<EOF
[Unit]
Description=Money Agent dashboard
After=network.target

[Service]
User=$service_user
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/config.env
Environment=MA_PORT=$PORT
ExecStart=/usr/bin/python3 $APP_DIR/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

  sudo systemctl daemon-reload
  sudo systemctl enable --now money-agent-web money-agent
}

if [ "${MA_SKIP_APT:-0}" != "1" ]; then
  log 'installing operating-system dependencies'
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-flask python3-pip curl
  pip3 install --quiet --upgrade --break-system-packages anthropic 2>/dev/null \
    || pip3 install --quiet --upgrade anthropic 2>/dev/null \
    || log 'Anthropic SDK unavailable; Claude CLI or dry-run remains available'
fi

if [ -d "$LOCAL_SOURCE" ]; then
  log "staging canonical source from $LOCAL_SOURCE"
  copy_local_source
else
  log "staging $REPOSITORY at exact ref $RELEASE_REF"
  download_release_source
fi

validate_stage
mkdir -p "$APP_DIR"
install_runtime

if [ "${MA_SKIP_SYSTEMD:-0}" != "1" ]; then
  log 'installing and starting systemd services'
  install_services
else
  log 'systemd installation skipped'
fi

ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
ip="${ip:-YOUR_PI_IP}"
log "installed validated runtime in $APP_DIR"
log "dashboard: http://$ip:$PORT"
log 'existing config.env, profile.json, money.db, and artifacts were preserved'
log 'no spending, outreach, account creation, or payment changes were performed'
