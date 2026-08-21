## What changed

Describe the user problem and the smallest change that solves it.

## Safety

- [ ] ClickAble still starts paused.
- [ ] Movement, observed lock/scene changes, helper failure, and stale events still suspend or fail closed as documented.
- [ ] The separate lock preflight and dispatch remain described as a residual non-atomic race requiring real acceptance.
- [ ] No new privilege, package, network, or configuration requirement was added.
- [ ] The countdown and active state remain unmistakable.

## Verification

- [ ] `bash scripts/validate.sh`
- [ ] Current Omarchy validator and `qmllint`
- [ ] Deterministic demo
- [ ] Relevant real Omarchy acceptance checks
