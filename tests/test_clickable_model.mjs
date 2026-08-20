import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"
import vm from "node:vm"

const source = readFileSync(new URL("../ClickAbleModel.js", import.meta.url), "utf8")
  .replace(/^\.pragma library\s*/, "")
const model = vm.createContext({ console })
vm.runInContext(source, model, { filename: "ClickAbleModel.js" })

function event(value, epoch = 41) {
  return model.parseEvent(JSON.stringify(value), epoch)
}

test("settings use only backend-supported, paused-safe presets", () => {
  assert.equal(model.DEFAULT_DWELL_MS, 900)
  assert.equal(model.DEFAULT_TOLERANCE_PX, 12)
  assert.deepEqual(Array.from(model.DWELL_CHOICES), [600, 900, 1200, 1600])
  assert.deepEqual(Array.from(model.TOLERANCE_CHOICES), [6, 12, 20])

  const valid = model.parseSettings('{"version":1,"dwellMs":1200,"tolerancePx":20}')
  assert.equal(valid.error, false)
  assert.equal(valid.dwellMs, 1200)
  assert.equal(valid.tolerancePx, 20)

  for (const raw of [
    "not json",
    '{"version":1,"dwellMs":700,"tolerancePx":12}',
    '{"version":1,"dwellMs":900,"tolerancePx":10}',
    '{"version":1,"dwellMs":900,"tolerancePx":12,"armed":true}',
  ]) {
    const parsed = model.parseSettings(raw)
    assert.equal(parsed.error, true)
    assert.equal(parsed.dwellMs, 900)
    assert.equal(parsed.tolerancePx, 12)
  }

  const persisted = JSON.parse(model.settingsJson(1600, 20))
  assert.deepEqual(persisted, { version: 1, dwellMs: 1600, tolerancePx: 20 })
  assert.equal("armed" in persisted, false)
  assert.equal("action" in persisted, false)
})

test("ready accepts only the exact backend capability object and epoch", () => {
  const ready = {
    type: "ready",
    epoch: 41,
    capabilities: { cursor: true, locked: true, click: true },
    pollMs: 40,
  }
  assert.equal(event(ready).ok, true)

  assert.equal(event({ ...ready, epoch: 40 }).code, "stale_epoch")
  assert.equal(event({ ...ready, capabilities: ["left", "right", "double"] }).ok, false)
  assert.equal(event({ ...ready, capabilities: { cursor: true, locked: true, click: false } }).ok, false)
  assert.equal(event({ ...ready, protocol: 1 }).ok, false)
})

test("state, frame, click, and error fields are strict and bounded", () => {
  assert.equal(event({
    type: "state", epoch: 41, state: "require_move", reason: "resumed", action: "left",
  }).ok, true)
  assert.equal(event({
    type: "frame", epoch: 41, state: "dwelling", x: -1920, y: 50,
    progress: 0.5, action: "double",
  }).ok, true)
  assert.equal(event({ type: "clicked", epoch: 41, action: "right", x: 10, y: 20 }).ok, true)
  assert.equal(event({
    type: "error", epoch: 41, code: "cursor_retry", message: "No click was sent.", fatal: false,
  }).ok, true)

  assert.equal(event({
    type: "frame", epoch: 41, state: "dwelling", x: 0, y: 0,
    progress: 1.01, action: "left",
  }).ok, false)
  assert.equal(event({
    type: "state", epoch: 41, state: "clicking", reason: "resumed", action: "left",
  }).ok, false)
  assert.equal(event({
    type: "error", epoch: 41, code: "UPPER", message: "bad", fatal: true,
  }).ok, false)
  assert.equal(model.parseEvent("x".repeat(4097), 41).code, "invalid_line")
})

test("state machine permits recovery paths but rejects impossible jumps", () => {
  assert.equal(model.transitionAllowed("paused", "require_move"), true)
  assert.equal(model.transitionAllowed("require_move", "tracking"), true)
  assert.equal(model.transitionAllowed("tracking", "dwelling"), true)
  assert.equal(model.transitionAllowed("dwelling", "committing"), true)
  assert.equal(model.transitionAllowed("committing", "rearming"), true)
  assert.equal(model.transitionAllowed("dwelling", "require_move"), true)
  assert.equal(model.transitionAllowed("tracking", "suspended"), true)
  assert.equal(model.transitionAllowed("suspended", "require_move"), true)
  assert.equal(model.transitionAllowed("paused", "committing"), false)
  assert.equal(model.transitionAllowed("rearming", "committing"), false)
  assert.equal(model.transitionAllowed("faulted", "tracking"), false)
})

test("indicator routing handles negative-origin multi-monitor layouts", () => {
  const left = { x: -1920, y: 0, width: 1920, height: 1080 }
  const right = { x: 0, y: 0, width: 2560, height: 1440 }
  assert.equal(model.screenContains(left, -1, 100), true)
  assert.equal(model.screenContains(left, 0, 100), false)
  assert.equal(model.screenContains(right, 0, 100), true)
  assert.equal(model.screenContains(right, 2560, 100), false)
})
