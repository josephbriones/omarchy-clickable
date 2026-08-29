# Changelog

## Unreleased

- Added rootless dwell clicking for current Omarchy Quattro.
- Added a visible click-through countdown, action-independent bar Pause, and an explicit paused/armed bar state.
- Added persistent left click plus one-shot right and double click.
- Added bounded dwell-duration and movement-tolerance preferences.
- Added initial and post-click move-away guards to prevent repeat clicks.
- Added lock, activity, stable-address scene-change, stale-event, and helper-failure guards.
- Added keyboard-native popup navigation plus Escape and an accessible Close control.
- Added a deterministic no-click demo, strict local JSON protocol, and parent-bound helper lifecycle.
- Added portable Python/JavaScript tests, pinned Arch `qmllint`, the official Omarchy validator, and an explicit real-desktop acceptance checklist.
- Read complete bounded Hyprland socket replies through EOF, including fragmented responses and partial-response timeouts.
- Enforce one monotonic deadline across each compositor request and check cancellation between response fragments.
- Document the residual non-atomic lock interval as an immediate best-effort preflight and keep the branch a release candidate only until acceptance on exact recorded Omarchy and Hyprland versions is complete.
