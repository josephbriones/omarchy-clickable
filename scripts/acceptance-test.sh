#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REAL=false

usage() {
  printf '%s\n' \
    'Usage: bash scripts/acceptance-test.sh [--real]' \
    '' \
    'The default exercises the deterministic helper without sending a real click.' \
    '--real adds an interactive disposable-target check for left, right, and double click.'
}

while (( $# > 0 )); do
  case "$1" in
    --real)
      REAL=true
      ;;
    --help | -h)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

bash "$ROOT/scripts/validate.sh"

for command_name in omarchy omarchy-shell; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'FAIL: %s is required for desktop acceptance\n' "$command_name" >&2
    exit 1
  fi
done

if [[ ${XDG_SESSION_TYPE:-} != "wayland" || -z ${HYPRLAND_INSTANCE_SIGNATURE:-} ]]; then
  printf '%s\n' 'FAIL: run desktop acceptance inside an active Omarchy Hyprland session' >&2
  exit 1
fi

plugin_call() {
  omarchy-shell clickable "$@"
}

cleanup() {
  plugin_call pause >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

wait_for_ping() {
  local attempt
  for (( attempt = 0; attempt < 100; attempt++ )); do
    [[ $(plugin_call ping 2>/dev/null || true) == "ok" ]] && return 0
    sleep 0.1
  done
  return 1
}

wait_for_state() {
  local wanted=$1 expected_action=${2:-left} attempt state
  for (( attempt = 0; attempt < 150; attempt++ )); do
    state=$(plugin_call state 2>/dev/null || true)
    if python3 - "$wanted" "$expected_action" "$state" <<'PY'
import json
import sys

wanted, expected_action, raw = sys.argv[1:]
try:
    state = json.loads(raw)
except (TypeError, ValueError):
    raise SystemExit(1)

if wanted == "paused-clean":
    ok = (
        state.get("active") is False
        and state.get("running") is False
        and state.get("starting") is False
        and state.get("state") == "paused"
        and state.get("demo") is False
        and state.get("ready") is False
        and state.get("settingsReady") is True
        and state.get("progress") == 0
    )
elif wanted == "paused":
    ok = (
        state.get("active") is False
        and state.get("running") is False
        and state.get("starting") is False
        and state.get("state") == "paused"
        and state.get("action") == "left"
        and state.get("demo") is False
        and state.get("ready") is False
        and state.get("settingsReady") is True
        and state.get("progress") == 0
    )
elif wanted == "ready":
    ok = (
        state.get("active") is True
        and state.get("running") is True
        and state.get("starting") is False
        and state.get("state") in {"require_move", "tracking", "dwelling"}
        and state.get("ready") is True
        and state.get("locked") is False
        and state.get("guarded") is False
        and state.get("error") == ""
    )
elif wanted == "demo-clicked":
    ok = (
        state.get("active") is True
        and state.get("running") is True
        and state.get("state") == "rearming"
        and state.get("action") == "left"
        and state.get("demo") is True
        and state.get("ready") is True
        and state.get("progress") == 0
        and state.get("error") == ""
    )
elif wanted == "action-selected":
    ok = (
        state.get("active") is True
        and state.get("running") is True
        and state.get("action") == expected_action
        and state.get("actionPending") is False
        and state.get("state") in {"require_move", "tracking", "dwelling"}
        and state.get("ready") is True
        and state.get("error") == ""
    )
elif wanted == "real-clicked":
    ok = (
        state.get("active") is True
        and state.get("running") is True
        and state.get("state") == "rearming"
        and state.get("action") == "left"
        and state.get("demo") is False
        and state.get("ready") is True
        and state.get("locked") is False
        and state.get("guarded") is False
        and state.get("progress") == 0
        and state.get("error") == ""
    )
else:
    ok = False

if wanted == "ready" and expected_action != "left":
    ok = ok and state.get("action") in {"left", expected_action}
raise SystemExit(0 if ok else 1)
PY
    then
      return 0
    fi
    sleep 0.1
  done
  return 1
}

pause_and_verify() {
  plugin_call pause >/dev/null
  wait_for_state paused-clean || {
    printf '%s\n' 'FAIL: ClickAble did not stop its helper and settle before reset' >&2
    exit 1
  }
  plugin_call left >/dev/null
  wait_for_state paused || {
    printf '%s\n' 'FAIL: ClickAble did not stop its helper and return to a clean paused state' >&2
    exit 1
  }
}

select_action() {
  local action=$1 result
  [[ $action == "left" ]] && return 0
  result=$(plugin_call "$action")
  if ! python3 - "$result" <<'PY'
import json
import sys

raw = sys.argv[1]
try:
    json.loads(raw)
except (TypeError, ValueError):
    raise SystemExit(1)
PY
  then
    printf 'FAIL: ClickAble did not select the one-shot %s action\n' "$action" >&2
    exit 1
  fi
  wait_for_state action-selected "$action" || {
    printf 'FAIL: ClickAble did not acknowledge the one-shot %s action\n' "$action" >&2
    exit 1
  }
}

run_demo_action() {
  local action=$1 result
  result=$(plugin_call demo)
  if [[ -z $result || $result == "unavailable" ]]; then
    printf '%s\n' 'FAIL: ClickAble did not start its deterministic demo' >&2
    exit 1
  fi
  wait_for_state ready "$action" || {
    printf 'FAIL: deterministic demo did not become ready for %s click\n' "$action" >&2
    exit 1
  }
  select_action "$action"
  wait_for_state demo-clicked || {
    printf 'FAIL: deterministic demo did not confirm exactly one %s action\n' "$action" >&2
    exit 1
  }
  pause_and_verify
}

wait_for_ping || {
  printf '%s\n' 'FAIL: ClickAble service IPC is unavailable; install and enable the plugin first' >&2
  exit 1
}

printf '%s\n' '==> Resetting ClickAble to its fail-safe paused state'
pause_and_verify

for action in left right double; do
  printf '==> Exercising deterministic %s-click session\n' "$action"
  run_demo_action "$action"
done

if [[ $REAL == "false" ]]; then
  printf '%s\n' 'PASS: deterministic left, right, and double sessions completed without Hyprland click dispatch'
  exit 0
fi

if [[ ! -t 0 ]]; then
  printf '%s\n' 'NOT PERFORMED: real click acceptance requires an interactive terminal.' >&2
  exit 3
fi

for command_name in git omarchy-version pacman hyprctl; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'FAIL: %s is required to record the real acceptance target\n' "$command_name" >&2
    exit 1
  fi
done

plugin_id=$(python3 - "$ROOT/manifest.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as manifest_file:
    manifest = json.load(manifest_file)
plugin_id = manifest.get("id")
if not isinstance(plugin_id, str) or not plugin_id:
    raise SystemExit(1)
print(plugin_id)
PY
) || {
  printf '%s\n' 'FAIL: manifest.json does not contain a valid plugin id' >&2
  exit 1
}

installed_root="$HOME/.config/omarchy/plugins/$plugin_id"
if [[ ! -d $installed_root/.git ]]; then
  printf 'FAIL: the running plugin must come from the git-managed Omarchy install at %s\n' "$installed_root" >&2
  exit 1
fi

if ! candidate_root=$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null) \
    || ! candidate_sha=$(git -C "$ROOT" rev-parse --verify HEAD 2>/dev/null) \
    || ! installed_sha=$(git -C "$installed_root" rev-parse --verify HEAD 2>/dev/null); then
  printf '%s\n' 'FAIL: real acceptance requires valid candidate and installed Git checkouts' >&2
  exit 1
fi
candidate_root=$(cd "$candidate_root" && pwd -P)
root_physical=$(cd "$ROOT" && pwd -P)
if [[ $candidate_root != "$root_physical" ]]; then
  printf '%s\n' 'FAIL: run the acceptance script from the root of the standalone ClickAble checkout' >&2
  exit 1
fi
if [[ -n $(git -C "$ROOT" status --porcelain --untracked-files=all) \
      || -n $(git -C "$installed_root" status --porcelain --untracked-files=all) ]]; then
  printf '%s\n' 'FAIL: candidate and installed ClickAble checkouts must both be clean' >&2
  exit 1
fi
if [[ $candidate_sha != "$installed_sha" ]]; then
  printf 'FAIL: installed ClickAble commit %s does not match candidate %s\n' "$installed_sha" "$candidate_sha" >&2
  exit 1
fi

omarchy-shell shell rescanPlugins >/dev/null
wait_for_ping || {
  printf '%s\n' 'FAIL: ClickAble did not reload from the verified installed commit' >&2
  exit 1
}
pause_and_verify

if ! omarchy_release=$(omarchy-version 2>&1) || [[ ! $omarchy_release =~ [^[:space:]] ]]; then
  printf '%s\n' 'FAIL: omarchy-version did not return a version' >&2
  exit 1
fi
if ! hyprland_package=$(pacman -Q hyprland 2>&1) || [[ ! $hyprland_package =~ [^[:space:]] ]]; then
  printf '%s\n' 'FAIL: pacman could not record the installed Hyprland package' >&2
  exit 1
fi
if ! hyprland_runtime=$(hyprctl version 2>&1) || [[ ! $hyprland_runtime =~ [^[:space:]] ]]; then
  printf '%s\n' 'FAIL: hyprctl could not record the running Hyprland version' >&2
  exit 1
fi

printf '%s\n' '==> Exact real-acceptance target'
printf 'ClickAble commit: %s\n' "$candidate_sha"
printf 'Omarchy: %s\n' "$omarchy_release"
printf '%s\n' "$hyprland_package"
printf '%s\n' "$hyprland_runtime"

run_real_action() {
  local action=$1 answer result

  printf '\n==> Real %s-click check\n' "$action"
  printf '%s\n' \
    'Open a disposable target with no destructive or sensitive action.' \
    'After ClickAble arms, move once, settle over the target, and wait for the ring.'
  read -r -p 'Press Enter to arm ClickAble: '

  result=$(plugin_call arm)
  if [[ -z $result || $result == "unavailable" ]]; then
    printf '%s\n' 'FAIL: ClickAble did not accept the Arm request' >&2
    exit 1
  fi
  wait_for_state ready "$action" || {
    printf 'FAIL: ClickAble did not become ready for real %s click\n' "$action" >&2
    exit 1
  }
  select_action "$action"

  wait_for_state real-clicked || {
    printf 'FAIL: helper did not confirm a bounded %s dispatch and rearm guard\n' "$action" >&2
    exit 1
  }
  printf 'The helper confirmed its dispatch. Did exactly one %s action reach the item under the pointer? [y/N] ' "$action"
  read -r answer
  if [[ ${answer,,} != "y" && ${answer,,} != "yes" ]]; then
    printf 'FAIL: real %s click was not positively confirmed\n' "$action" >&2
    exit 1
  fi
  pause_and_verify
}

for action in left right double; do
  run_real_action "$action"
done

printf '%s\n' 'PASS: disposable-target left, right, and double checks were positively confirmed and stopped cleanly'
printf '%s\n' 'NOTE: complete the remaining surface, display, lock, reload, stress, and Orca gates in docs/RELEASE_CHECKLIST.md.'
