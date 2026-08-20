# Architecture

ClickAble keeps the shell policy, local input primitive, and process lifetime separate without introducing a framework.

```text
Omarchy service
  ├─ IdleMonitor + lock/scene guards
  ├─ bar control + click-through ring windows
  └─ QML Process: bin/clickable (launcher)
       └─ Python worker
            ├─ strict epoch-tagged JSONL state machine
            └─ bounded Hyprland Unix-socket requests
```

## Why the worker owns the countdown

QML decides whether ClickAble is allowed to operate. The worker decides whether a particular click can commit. This keeps the last pointer sample, tolerance check, lock check, state transition, and fixed compositor dispatch in one foreground process.

QML never sends a raw `sample` or `click` command. It sends policy facts: configuration, resume, pause, activity, guards, and the requested fixed action. The worker polls the cursor only while the armed state machine needs it and emits bounded frames for the visual ring.

This avoids a check-to-click race where a QML timer could verify one pointer position and dispatch after the pointer or lock state changed.

## States

```text
paused
  └─ resume → require_move
       └─ sufficient movement → tracking
            └─ stable pointer + idle policy → dwelling
                 ├─ movement/activity/guard → tracking or suspended
                 └─ final checks → committing → rearming
                                      └─ sufficient movement → tracking
```

Lock and workspace, toplevel, fullscreen, layer, layout, or output changes force `suspended`. Clearing a guard never resumes directly into a dwell; it returns through `require_move`. A fatal helper or protocol problem enters `faulted`. Stop enters `stopped`. Suspend/resume safety depends on Omarchy establishing the session lock and remains an explicit real-desktop acceptance gate.

The initial `require_move` state matters. If the user arms ClickAble by clicking its bar control and leaves the pointer there, ClickAble must not immediately click that same control again.

## Exactly one current session

Each helper launch receives a new positive epoch. Every command and event carries that epoch. The parser rejects malformed current-session input, and QML ignores stale events from an earlier process. Restarting the helper always returns to paused/require-move policy; state from the previous process cannot authorize a click.

## Hyprland boundary

The worker opens one short-lived AF_UNIX connection for each bounded request to the current user's Hyprland socket. The path is derived only from validated `XDG_RUNTIME_DIR` and `HYPRLAND_INSTANCE_SIGNATURE` values.

The safety-critical sequence is:

1. Sample `j/cursorpos`.
2. Confirm the pointer stayed within the configured tolerance.
3. Query `j/locked` immediately before dispatch.
4. Enter the explicit `committing` state.
5. Send one fixed targetless dispatcher request for left or right, or two bounded left requests for double.
6. On confirmed success, enter `rearming`; on an uncertain or partial outcome, pause the session.

Targetless dispatch is intentional. On the supported Hyprland contract it preserves the compositor's real pointer-focus surface; supplying a window target would retarget the event and could move pointer focus to the wrong local coordinate.

All dispatcher strings are constants. Neither coordinates, settings, QML text, nor application data are interpolated into them.

## Ambiguous outcomes

A request timeout after sending cannot prove that the compositor did not deliver the click. ClickAble therefore pauses after an uncertain single click; a later explicit Arm starts from a fresh cursor baseline and still requires movement. If the first half of a double click succeeds and the second cannot be confirmed, the worker faults the session because the observed application state is unknowable. Confirmed clicks enter `rearming` and cannot begin another dwell until the pointer moves away.

## Process ownership

Quickshell owns `bin/clickable`. The launcher does not `exec` the worker: it waits and forwards termination. The worker binds itself to the launcher's expected PID with Linux parent-death signaling. This extra process is deliberate because Quickshell may use SIGKILL when destroying its direct child; killing the launcher gives the worker a catchable SIGTERM so it can stop its protocol loop before exiting.

No child is detached. Closing stdin, pausing, stopping, shell reload, plugin disable, and shell death all have bounded tests or explicit Linux acceptance gates.

## Visual indicator

The service creates one overlay instance per `Quickshell.screens` output. Each window uses an empty input region, no keyboard focus, and no exclusive zone. Only the ring is painted, positioned from the worker's global logical coordinates relative to `ShellScreen.x/y`. The indicator never becomes a click target and never changes pointer focus.

## Persistence

Only `version`, `dwellMs`, and `tolerancePx` persist at `$XDG_CONFIG_HOME/omarchy/clickable/config.json`, with the normal `~/.config` fallback. Armed state, action mode, epoch, pointer coordinates, guards, counters, diagnostics, and countdown progress are session-only.
