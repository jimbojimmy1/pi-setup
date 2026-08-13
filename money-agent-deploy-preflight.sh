#!/usr/bin/env bash
# Print a recoverable Money Agent deployment plan without executing it.

set -euo pipefail

usage() {
  printf 'usage: %s FULL_REVIEWED_COMMIT_SHA\n' "${0##*/}" >&2
  printf 'the reviewed release must be a full 40-character commit SHA\n' >&2
  exit 2
}

if [ "$#" -ne 1 ] || [[ ! "$1" =~ ^[0-9a-fA-F]{40}$ ]]; then
  usage
fi

reviewed="${1,,}"
app_dir="${MONEY_AGENT_DIR:-$HOME/money-agent}"
script_path="${BASH_SOURCE[0]}"
case "$script_path" in
  */*) script_parent="${script_path%/*}" ;;
  *) script_parent='.' ;;
esac
script_dir="$(cd -- "$script_parent" && pwd)"
repo_dir="${MA_REPO_DIR:-$script_dir}"
marker="$app_dir/release.txt"
installed=''
installed_label='not-recorded'
status='unknown'

if [ -f "$marker" ] && [ ! -L "$marker" ]; then
  marker_chunk=''
  IFS= read -r -N 130 marker_chunk < "$marker" || true
  if [ "${#marker_chunk}" -le 129 ]; then
    marker_value="${marker_chunk%$'\n'}"
    if [ "${#marker_value}" -le 128 ] \
      && { [[ "$marker_value" =~ ^[0-9a-fA-F]{40}(-dirty)?$ ]] \
        || [ "$marker_value" = 'local-unversioned' ]; }; then
      installed="${marker_value,,}"
      installed_label="$installed"
    else
      installed_label='invalid'
    fi
  else
    installed_label='invalid'
  fi
fi

if [[ "$installed" =~ ^[0-9a-f]{40}-dirty$ ]]; then
  status='dirty'
elif [[ "$installed" =~ ^[0-9a-f]{40}$ ]]; then
  if [ "$installed" = "$reviewed" ]; then
    status='current'
  else
    status='outdated'
  fi
fi

printf -v quoted_repo '%q' "$repo_dir"
printf -v quoted_app '%q' "$app_dir"
printf -v quoted_config '%q' "$app_dir/config.env"

printf 'MONEY AGENT DEPLOYMENT PREFLIGHT\n'
printf 'REVIEWED_COMMIT: %s\n' "$reviewed"
printf 'INSTALLED_RELEASE: %s\n' "$installed_label"
printf 'STATUS: %s\n' "$status"
printf 'APP_DIR: %s\n' "$app_dir"
printf 'SERVICES: money-agent money-agent-web\n'
printf 'NO_ACTIONS_EXECUTED: true\n\n'

printf 'UPGRADE COMMANDS (execute only after explicit owner approval):\n'
printf '(\n'
printf '  set -euo pipefail\n'
printf '  cd %s\n' "$quoted_repo"
printf '  test -z "$(git status --porcelain)"\n'
printf '  git fetch --depth 1 origin %s\n' "$reviewed"
printf '  git checkout --detach %s\n' "$reviewed"
printf '  MONEY_AGENT_DIR=%s bash setup-money-agent.sh\n' "$quoted_app"
printf "  if grep -q '^MA_EXPECTED_RELEASE_REF=' %s; then sed -i 's/^MA_EXPECTED_RELEASE_REF=.*/MA_EXPECTED_RELEASE_REF=%s/' %s; else printf '\\\\nMA_EXPECTED_RELEASE_REF=%s\\\\n' >> %s; fi\n" \
  "$quoted_config" "$reviewed" "$quoted_config" "$reviewed" "$quoted_config"
printf '  sudo systemctl restart money-agent money-agent-web\n'
printf ')\n'

if [ "$status" = 'outdated' ]; then
  printf '\nROLLBACK COMMANDS (use only after explicit owner approval):\n'
  printf '(\n'
  printf '  set -euo pipefail\n'
  printf '  cd %s\n' "$quoted_repo"
  printf '  git fetch --depth 1 origin %s\n' "$installed"
  printf '  git checkout --detach %s\n' "$installed"
  printf '  MONEY_AGENT_DIR=%s bash setup-money-agent.sh\n' "$quoted_app"
  printf "  if grep -q '^MA_EXPECTED_RELEASE_REF=' %s; then sed -i 's/^MA_EXPECTED_RELEASE_REF=.*/MA_EXPECTED_RELEASE_REF=%s/' %s; else printf '\\\\nMA_EXPECTED_RELEASE_REF=%s\\\\n' >> %s; fi\n" \
    "$quoted_config" "$installed" "$quoted_config" "$installed" "$quoted_config"
  printf '  sudo systemctl restart money-agent money-agent-web\n'
  printf ')\n'
fi
