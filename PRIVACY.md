# Privacy

ClickAble is local, transient, and intentionally blind to screen content.

## Data it uses while armed

ClickAble processes only:

- the pointer's current global `x` and `y` coordinates from the local Hyprland request socket;
- Hyprland's boolean locked state;
- Omarchy's boolean idle/activity state;
- the selected click action, dwell duration, movement tolerance, and in-memory countdown state.

The idle signal does not tell ClickAble which key or button was used. ClickAble does not receive typed text, application content, window pixels, an accessibility tree, clipboard data, audio, camera data, or a pointer-device identifier.

## Storage

Pointer coordinates, activity, click attempts, and countdown state are never written by ClickAble. They are discarded when paused or stopped.

ClickAble persists only `version`, `dwellMs`, and `tolerancePx` in `$XDG_CONFIG_HOME/omarchy/clickable/config.json`, falling back to `~/.config/omarchy/clickable/config.json` when `XDG_CONFIG_HOME` is unset. It creates the plugin-owned directory with private permissions when needed and writes the file atomically. It never persists the armed state or a one-shot click action. Removing the plugin does not automatically remove this small preference file.

ClickAble creates no click history, pointer trail, screenshot, recording, analytics record, crash-upload record, or account.

## Network

ClickAble makes no network request. Its Python helper connects only to the current user's local Hyprland Unix socket under the active runtime directory.

## Pausing and stopping

Pausing clears the active countdown and stops the owned helper, preventing another dwell or compositor request. A click already handed to the compositor cannot be withdrawn. Stopping or unloading the service uses the same bounded ownership path. The service always reloads paused.

## Explicit effect

When a dwell completes, ClickAble asks the local compositor to deliver the selected mouse-button action to the surface under the real pointer. That application handles the click under its own privacy and data policies.
