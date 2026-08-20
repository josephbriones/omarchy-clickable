## What changed

Describe the user problem and the smallest change that solves it.

## Safety

- [ ] ClickAble still starts paused.
- [ ] Movement, lock, helper failure, and stale events still fail closed.
- [ ] No new privilege, package, network, or configuration requirement was added.
- [ ] The countdown and active state remain unmistakable.

## Verification

- [ ] `bash scripts/validate.sh`
- [ ] Current Omarchy validator and `qmllint`
- [ ] Deterministic demo
- [ ] Relevant real Omarchy acceptance checks
