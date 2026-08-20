# Competition position

## The idea

ClickAble removes one hard barrier: pressing a mouse button.

People who can position a pointer with an eye tracker, head tracker, trackball, mouse, or other device should not lose the desktop because pressing is painful, unreliable, or impossible. ClickAble turns a deliberate pause into one ordinary click, then refuses to click again until the pointer moves away.

## Why it belongs in Omarchy

Omarchy is built around direct manipulation, but its existing accessibility and pointer controls do not provide dwell clicking. ClickAble uses the compositor's current pointer-focus surface, the shell's existing idle and lock signals, and the normal Omarchy bar. It needs no privileged input device, daemon, native compositor extension, or configuration rewrite.

That narrow integration is the product. A user gets one visible state, one predictable countdown, one fail-safe Pause action, and one path that works with any pointer source.

## Why it endures

Dwell clicking is not a demo shortcut. For its users, it can mediate every button press in every session. The useful future is deeper calibration, device-specific profiles, improved tremor handling, and separately proven drag or scroll support—not a pile of unrelated accessibility toggles.

Version 0.1 deliberately stops at left click plus one-shot right and double click. Held-button and axis input introduce different failure states and will not ship until they can meet the same exactly-once and cleanup standard.

## Twenty-second demonstration

1. Show that ClickAble loads paused and the pointer can rest without any click.
2. Arm with one accessible key or switch, move to a disposable button, and stop moving.
3. Let the visible ring finish and show the button receives exactly one click.
4. Keep the pointer still and show that no second click occurs.
5. Move to the ClickAble bar widget, dwell once, and show the service returns to Paused.

The deterministic demo can show the same state machine without asking Hyprland to deliver a click. Real competition evidence must use disposable targets on the exact published Omarchy release.

## Honest claim

“If you can point, you should be able to click.”

ClickAble does not promise drag, scroll, semantic target discovery, perfect tremor filtering, or compatibility with a surface that rejects compositor-synthesized input. It is not the only control to use for a safety-critical operation.
