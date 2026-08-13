#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
app="$tmp/app dir"
stub="$tmp/stub"
mkdir -p "$app" "$stub"

for command_name in git curl sudo systemctl; do
  cat > "$stub/$command_name" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "called:${0##*/}" >> "$PREFLIGHT_CALL_LOG"
exit 97
EOF
  chmod +x "$stub/$command_name"
done

reviewed='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
installed='bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
call_log="$tmp/calls.log"
printf '%s\n' "$installed" > "$app/release.txt"
printf '%s\n' 'keep' > "$app/sentinel"

run_preflight() {
  PATH="$stub:$PATH" PREFLIGHT_CALL_LOG="$call_log" MONEY_AGENT_DIR="$app" \
    bash "$root/money-agent-deploy-preflight.sh" "$reviewed"
}

output="$(run_preflight)"
grep -Fx "REVIEWED_COMMIT: $reviewed" <<<"$output"
grep -Fx "INSTALLED_RELEASE: $installed" <<<"$output"
grep -Fx 'STATUS: outdated' <<<"$output"
grep -Fx 'SERVICES: money-agent money-agent-web' <<<"$output"
grep -Fx 'NO_ACTIONS_EXECUTED: true' <<<"$output"
grep -F "git fetch --depth 1 origin $reviewed" <<<"$output"
grep -F "git checkout --detach $reviewed" <<<"$output"
grep -F "git checkout --detach $installed" <<<"$output"
grep -F "else printf '\\nMA_EXPECTED_RELEASE_REF=$reviewed\\n'" <<<"$output"
grep -F "else printf '\\nMA_EXPECTED_RELEASE_REF=$installed\\n'" <<<"$output"
grep -F 'MONEY_AGENT_DIR=' <<<"$output"
grep -F 'app\ dir' <<<"$output"
test ! -e "$call_log"
grep -Fx "$installed" "$app/release.txt"
grep -Fx 'keep' "$app/sentinel"
test "$(find "$app" -mindepth 1 -maxdepth 1 -type f | wc -l)" -eq 2

printf '%s\n' "$reviewed" > "$app/release.txt"
output="$(run_preflight)"
grep -Fx 'STATUS: current' <<<"$output"
if grep -F 'ROLLBACK COMMANDS' <<<"$output"; then
  printf 'current release unexpectedly offered a rollback to itself\n' >&2
  exit 1
fi

printf '%s\n' "${installed}-dirty" > "$app/release.txt"
output="$(run_preflight)"
grep -Fx 'STATUS: dirty' <<<"$output"
if grep -F "git checkout --detach $installed" <<<"$output"; then
  printf 'dirty release unexpectedly became a rollback target\n' >&2
  exit 1
fi

rm "$app/release.txt"
output="$(run_preflight)"
grep -Fx 'INSTALLED_RELEASE: not-recorded' <<<"$output"
grep -Fx 'STATUS: unknown' <<<"$output"

printf '%s\n' '../../secret' > "$app/release.txt"
output="$(run_preflight)"
grep -Fx 'INSTALLED_RELEASE: invalid' <<<"$output"
grep -Fx 'STATUS: unknown' <<<"$output"

if PATH="$stub:$PATH" PREFLIGHT_CALL_LOG="$call_log" MONEY_AGENT_DIR="$app" \
  bash "$root/money-agent-deploy-preflight.sh" main >"$tmp/invalid.out" 2>&1; then
  printf 'preflight accepted a mutable reviewed ref\n' >&2
  exit 1
else
  test "$?" -eq 2
fi
grep -F 'full 40-character commit SHA' "$tmp/invalid.out"
test ! -e "$call_log"
