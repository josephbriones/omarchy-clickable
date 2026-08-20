# Setup

ClickAble targets current Omarchy Quattro. It uses Quickshell's idle monitor, Hyprland's existing request socket, Python's standard library, and no additional package.

## Install

Review the repository, then use Omarchy's normal plugin flow:

```bash
omarchy plugin add https://github.com/josephbriones/omarchy-clickable.git --enable
```

Enabling the plugin adds its bar widget and loads the associated service. The service starts paused.

## Confirm the service

```bash
omarchy-shell clickable ping
omarchy-shell clickable state
```

`ping` should return `ok`. The JSON state should report paused, with no active dwell or retained pointer coordinate.

## Run the safe demo

```bash
omarchy-shell clickable demo
```

The demo uses a fixed virtual pointer and never sends a compositor click. It is useful for checking the control surface, countdown ring, one-shot action behavior, and state transitions before real input is armed.

## Recommended single-key or switch control

The ClickAble IPC commands are designed to be called by a programmable switch or a single unmodified key. On current Omarchy, user keybindings live in `~/.config/hypr/bindings.lua`. For example:

```lua
o.bind("F13", "Toggle ClickAble", "omarchy-shell clickable toggle")
```

Choose a key your device can produce and verify it is not already bound with Omarchy's keybinding menu before adding it. Hyprland reloads user configuration after it changes; validate the configuration with the normal Omarchy/Hyprland tools.

This binding is required when the user cannot press any conventional pointer button to Arm ClickAble initially. Keep it reachable after Pause, shell reload, login, and an error; ClickAble intentionally does not remember or automatically restore an armed state.

The plugin does not add or rewrite this binding itself.

## Preferences

The bar control exposes only two persistent settings:

- Dwell delay: how long the pointer must remain deliberately still.
- Steadiness radius: how much unintentional movement remains within a dwell.

Start conservatively. A longer delay and smaller tolerance reduce unintended clicks. ClickAble validates and clamps both values before they reach the worker.

## Troubleshooting

If ClickAble pauses or faults, leave it paused and inspect:

```bash
omarchy-shell clickable state
```

Common causes are a locked session, a desktop scene transition, a missing or changed Hyprland request contract, a helper restart, or a pointer that never moved far enough to clear the rearm guard.

ClickAble deliberately offers no privileged fallback. If the supported targetless Hyprland click path does not work on the current Omarchy release, report the exact Omarchy and Hyprland versions and keep the plugin paused.
