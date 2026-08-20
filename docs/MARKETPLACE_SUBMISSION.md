# Marketplace submission draft

Do not open this issue until the repository is public, the preview is reviewed, the exact public commit passes CI and current Omarchy acceptance, and the owner explicitly confirms every checklist statement. Real Omarchy acceptance is not yet recorded, so the boxes remain unchecked.

**Title**

```text
[Plugin]: ClickAble
```

**Body**

```markdown
### Repository URL

https://github.com/josephbriones/omarchy-clickable

### Category

Desktop

### Tags

hyprland, quickshell

### Suggest a missing tag

accessibility

### Maintainer notes

ClickAble turns a deliberate pointer dwell into one ordinary click for people who can position a pointer but cannot press a button reliably or comfortably. It starts paused on every load, requires movement after Arm and after every click, displays a click-through countdown, and provides persistent left plus one-shot right and double actions. Non-positional activity detected with a stationary pointer cancels a dwell; beyond-tolerance pointer motion resets it, while small involuntary motion can preserve progress but cannot commit until input is quiet. Lock, scene, helper, protocol, and uncertain-dispatch failures stop or suspend the session. The plugin uses only current Omarchy's Quickshell idle/lock integration, a bounded foreground Python helper, and fixed targetless requests to the current user's local Hyprland socket. It installs no package, privilege, virtual input device, daemon, native compositor extension, or configuration change, and it records no screen content, keys, clicks, or coordinates. A deterministic demo exercises the state machine without dispatching a real click.

### Submission checklist

- [ ] The repository is public and contains installation and removal instructions.
- [ ] I have documented the plugin license and any external dependencies.
- [ ] I confirm that I own or have permission to submit this plugin and its preview assets.
- [ ] The plugin does not overwrite user configuration without explicit consent.
- [ ] I understand that approval is for listing and is not a security review.
```

After the owner personally confirms these statements, change all five boxes to `[x]`, show the final title and body to the owner, obtain explicit approval, and create one issue in the marketplace repository.

The category and tags must be rechecked against the marketplace's controlled vocabulary at submission time. `accessibility` is intentionally proposed as a missing ecosystem tag.
