# Testing

ClickAble's portable suite proves protocol, state-machine, parser, timeout, rate-limit, process, and repository invariants without moving the developer's pointer or dispatching a real click. This branch remains a release candidate until the exact commit also passes real acceptance on exact recorded Omarchy and Hyprland versions.

## Portable validation

```bash
bash scripts/validate.sh
```

The suite includes:

- exact cursor and lock-response parsing, including duplicate keys, booleans, floats, oversized values, and malformed JSON;
- fixed targetless left/right/double dispatcher requests and bounded Unix-socket behavior, including fragmented replies, oversized streams, empty EOF, send failures, cancellation between fragments, and one absolute deadline across the request;
- paused startup, initial move-away, dwell cancellation, tolerance boundaries, click uncertainty, one-shot actions, and post-click rearm;
- stale epoch rejection, malformed protocol failure, command rate limits, broken stdout, EOF, and signal cancellation;
- launcher-to-worker parent identity and Linux shell-death cleanup;
- deterministic demo behavior with no compositor click;
- strict QML event parsing, legal transitions, de-duplicated focus and lock/activity guards, input-transparent indicators, accessible controls, and IPC contracts;
- manifest, documentation, executable-mode, privacy, and release metadata checks.

GitHub Actions runs the portable suite on Python 3.12 and 3.14. A separate Arch job checks the official Omarchy validator and `qmllint` against a pinned current Omarchy tree.

## Deterministic desktop demo

The default acceptance run must remain safe and non-interactive:

```bash
bash scripts/acceptance-test.sh
```

It first resets and verifies a clean paused service, then runs separate deterministic left, right, and double sessions through the normal Arm/Pause lifecycle. The demo backend has no Hyprland socket path, and the runner waits for every helper to stop before reporting success.

## Real Omarchy acceptance

Real acceptance is intentionally interactive:

```bash
bash scripts/acceptance-test.sh --real
```

Use disposable targets and no sensitive or destructive application state. The release gate must record all of the following:

- one left-button press/release reaches the exact target under the pointer with keyboard focus in a different window;
- one right-button press/release reaches the exact target and the mode returns to left only after success;
- double click produces exactly two bounded left clicks and no stuck button;
- repeated lock transitions are exercised before a double click and between its two complete click requests, with the residual outcome recorded rather than represented as atomic exclusion;
- countdown cancels on beyond-tolerance pointer movement and on keyboard or manual-button input with the pointer held stationary; in-tolerance motion never commits until input is quiet, and coincident device input plus tracker jitter is tested as a documented calibration edge;
- the bar widget, its popup, an Omarchy layer-shell surface, native GTK, native Qt/Quickshell, a terminal, Chromium Wayland, Electron Wayland, and XWayland receive the correct click;
- mixed 100%, 125%, 150%, and 200% scale, negative output origins, rotated/flipped outputs, vertical layouts, and hotplug place the ring on the real pointer;
- lock at the last countdown frame, workspace/toplevel changes, fullscreen transitions, suspend/resume, helper kill, plugin disable, hot reload, and shell exit produce no unintended click; a real toplevel address change requires fresh movement, while title-only updates in the same toplevel do not restart the guard;
- after an uncertain dispatch, no new dwell begins until the pointer moves away;
- 1,000 dwell cycles produce no duplicate click, click storm, wrong target, stuck button, or unbounded process/memory growth;
- Left, Right once, and Double once all pause on the first accepted armed-bar activation before popup-specific behavior;
- all popup controls are keyboard reachable, visibly focused, at least 44×44 logical pixels, announced meaningfully by Orca, and dismissible with Escape or the Close controls button; the bar trigger keeps one axis at least 44 logical pixels and uses Omarchy's configured bar thickness on its shorter axis, which must be at least 24 logical pixels for release;
- the ring and invisible overlay never steal pointer or keyboard focus.

The lock-transition exercise is evidence, not proof of atomic exclusion. `j/locked` and the click dispatcher are separate requests, so a lock can begin in between them. The acceptance record must acknowledge this residual race; neither portable tests nor a successful stress run may be represented as a hard guarantee that no transition-time click can occur.

## Release evidence

Portable green tests are necessary but do not prove compositor delivery or remove the lock-transition race. The release checklist remains unchecked until the exact published commit passes hardware acceptance on the recorded Omarchy and Hyprland versions and the owner accepts the documented residual risk. Until then this branch is a release candidate, not approved for production use or marketplace submission. Do not replace missing evidence with an assumption.
