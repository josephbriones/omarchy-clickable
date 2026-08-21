# Release checklist

> **Current status:** Release candidate only. No production release or marketplace submission is approved until the exact commit passes this checklist on exact recorded Omarchy and Hyprland versions and the owner accepts the documented lock-transition race.

## Automated

- [ ] `bash scripts/validate.sh` passes from a clean checkout.
- [ ] Python 3.12 and 3.14 GitHub Actions jobs pass.
- [ ] Arch `qmllint` and the official Omarchy validator pass.
- [ ] Marketplace baseline reports clear with no unexplained capability.
- [ ] `git diff --check` and executable-mode checks pass.

## Safe startup and lifecycle

- [ ] Enabling, login, shell restart, and plugin reload all begin paused.
- [ ] Paused state makes no pointer or lock request and cannot click.
- [ ] Disable, removal, helper kill, hot reload, and shell exit leave no helper process.
- [ ] Observed lock, suspend, and relevant scene transitions cancel a countdown before any dispatch; a changed `activewindowv2` address requires fresh movement, while title-only events for the same address do not restart the guard.
- [ ] Repeated lock-transition testing is recorded immediately before a single click and before and between both halves of a double click; the acceptance record states that the separate lock query and click dispatch leave a residual non-atomic race.
- [ ] Stale events from a previous epoch never change the current service.

## Input behavior

- [ ] Initial Arm requires movement before the first dwell.
- [ ] Beyond-tolerance movement and stationary-pointer keyboard/manual-button activity cancel the ring; in-tolerance motion cannot commit until input is quiet, and coincident device input plus tracker jitter is calibrated with the intended hardware.
- [ ] Left, one-shot right, and one-shot double produce the exact expected events.
- [ ] Uncertain and partial outcomes fail closed and require movement.
- [ ] Post-click rearm prevents repeated clicks at one resting target.
- [ ] In Left, Right once, and Double once modes, the first accepted armed-bar activation pauses before popup- or button-specific behavior.
- [ ] 1,000 dwell cycles produce no duplicate click, click storm, wrong target, stuck button, helper leak, or unbounded memory growth.

## Surfaces and displays

- [ ] Omarchy bar, popup, and other layer-shell surfaces work.
- [ ] Native GTK, Qt, terminal, Chromium Wayland, Electron Wayland, and XWayland work.
- [ ] Multi-monitor, negative origins, mixed fractional scaling, rotation, flipping, vertical layouts, and hotplug work.
- [ ] The ring is correctly positioned and never steals input.

## Accessibility

- [ ] Every control is keyboard reachable with visible focus; Escape and the explicit Close controls button both dismiss the popup.
- [ ] Every popup control is at least 44×44 logical pixels; the bar trigger keeps one axis at least 44 logical pixels, and the configured Omarchy bar thickness keeps its shorter axis at least 24 logical pixels.
- [ ] Orca announces state, buttons, one-shot selection, settings, errors, and the armed/paused transition.
- [ ] A single-key or switch binding can Arm/Pause without a chord.
- [ ] Reduced-motion behavior is acceptable and the countdown remains understandable without color alone.

## Release

- [ ] README, preview, privacy, security, setup, testing, changelog, and manifest match the exact behavior.
- [ ] Public install URL works from a clean current Omarchy system.
- [ ] The acceptance runner verifies a clean candidate checkout and the installed plugin share the recorded full Git commit, reloads that installed source, and includes the commit, `omarchy-version`, `pacman -Q hyprland`, and `hyprctl version` output.
- [ ] GitHub Actions passes on the public commit.
- [ ] Marketplace submission text and preview contain no private or machine-specific data.
- [ ] The owner accepts the documented lock-transition residual risk for the recorded release candidate.
- [ ] The repository owner approves the final marketplace submission.
