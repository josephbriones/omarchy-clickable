# Security

## Supported version

Security fixes are provided for the latest released ClickAble version on the current supported Omarchy Quattro release.

## Report privately

Please use [GitHub's private vulnerability reporting](https://github.com/josephbriones/omarchy-clickable/security/advisories/new). Do not open a public issue for a vulnerability that can cause unintended input, bypass a guard, expose another user's runtime socket, or survive plugin shutdown.

## Security model

ClickAble runs as the signed-in user inside Omarchy's shell. It does not request administrator privileges, open a network listener, install a package, create a virtual input device, or rewrite Hyprland configuration.

The QML service controls when clicking is allowed. A foreground Python helper owns the safety-critical countdown and compositor requests. The shell owns a launcher process; the launcher owns the worker; Linux parent-death signals and bounded shutdown keep that process tree tied to the shell even when Quickshell forcefully destroys its direct child.

## Fail-closed boundaries

- ClickAble loads paused and does not persist an armed state.
- Every command and event carries the current positive session epoch. Stale output cannot commit a click in a new session.
- Commands and JSON events use exact schemas, unique keys, bounded lines, bounded rates, finite coordinate ranges, and legal state transitions.
- Hyprland request strings are fixed constants. User-controlled text is never interpolated into a compositor request or shell command.
- The runtime path and Hyprland instance signature are validated before opening the local Unix socket.
- A click is committed only after a fresh pointer sample, a movement-tolerance check, an immediate lock-state check, and the active QML guard state.
- Non-positional activity detected with a stationary pointer cancels a dwell. Pointer movement beyond the configured tolerance resets it; smaller involuntary motion may preserve progress, but commit remains blocked until the idle signal reports a quiet input interval.
- Arming, unblocking, and every successful or uncertain click require the pointer to move before another dwell can begin.
- If a dispatch times out, ClickAble treats its outcome as unknown and pauses. A later explicit Arm starts from a fresh baseline and requires movement. A partial double-click is a fatal session error.
- Lock and relevant desktop-scene changes suspend the countdown and require fresh movement. Stale-epoch output is ignored; helper exit, malformed current-session protocol data, and output loss pause or fault the session rather than clicking.

## Compositor dependency

ClickAble uses Hyprland's targetless `send_shortcut` mouse dispatcher so the existing pointer-focus surface receives the button action. This is version-sensitive compositor behavior. CI pins the shell contract; release acceptance must re-prove exactly-once delivery on the target Omarchy/Hyprland release across native Wayland, XWayland, and layer-shell surfaces.

ClickAble does not silently fall back to kernel input injection or a native compositor extension if that contract changes.

## Known limits

ClickAble cannot determine what an application will do with a valid click. It does not inspect target semantics, undo application actions, or claim suitability as the only control for a safety-critical operation. Omarchy's idle signal also does not identify the active input device; non-positional input coinciding with in-tolerance pointer jitter can be interpreted as tolerated motion, although commit still waits for a quiet interval. Drag and scrolling are excluded from v1 because they introduce held-button and cancellation states that require separate proof.
