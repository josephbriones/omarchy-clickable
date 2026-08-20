.pragma library

var SETTINGS_VERSION = 1
var DEFAULT_DWELL_MS = 900
var DEFAULT_TOLERANCE_PX = 12
var DWELL_CHOICES = [600, 900, 1200, 1600]
var TOLERANCE_CHOICES = [6, 12, 20]
var MIN_DWELL_MS = 600
var MAX_DWELL_MS = 1600
var MIN_TOLERANCE_PX = 6
var MAX_TOLERANCE_PX = 20
var MAX_LINE_LENGTH = 4096
var MAX_COORDINATE = 1000000

var ACTIONS = ["left", "right", "double"]
var STATES = [
  "paused",
  "require_move",
  "tracking",
  "dwelling",
  "committing",
  "rearming",
  "suspended",
  "faulted",
  "stopped"
]

var EVENT_FIELDS = {
  ready: ["type", "epoch", "capabilities", "pollMs"],
  state: ["type", "epoch", "state", "reason", "action"],
  frame: ["type", "epoch", "state", "x", "y", "progress", "action"],
  clicked: ["type", "epoch", "action", "x", "y"],
  error: ["type", "epoch", "code", "message", "fatal"]
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}

function isInteger(value) {
  return typeof value === "number" && isFinite(value) && Math.floor(value) === value
}

function inList(value, values) {
  return values.indexOf(value) !== -1
}

function exactFields(value, expected) {
  var keys = Object.keys(value).sort()
  var wanted = expected.slice().sort()
  if (keys.length !== wanted.length) return false
  for (var i = 0; i < keys.length; i++) {
    if (keys[i] !== wanted[i]) return false
  }
  return true
}

function boundedString(value, limit, allowEmpty) {
  return typeof value === "string"
    && value.length <= limit
    && (allowEmpty || value.length > 0)
    && value.indexOf("\u0000") === -1
}

function validCoordinate(value) {
  return isInteger(value) && value >= -MAX_COORDINATE && value <= MAX_COORDINATE
}

function validEpoch(value) {
  return isInteger(value) && value >= 1 && value <= 2147483647
}

function validAction(value) {
  return inList(value, ACTIONS)
}

function validState(value) {
  return inList(value, STATES)
}

function boundedDwell(value) {
  return isInteger(value) && inList(value, DWELL_CHOICES) ? value : DEFAULT_DWELL_MS
}

function boundedTolerance(value) {
  return isInteger(value) && inList(value, TOLERANCE_CHOICES) ? value : DEFAULT_TOLERANCE_PX
}

function parseSettings(raw) {
  if (typeof raw !== "string" || raw.trim() === "") {
    return {
      dwellMs: DEFAULT_DWELL_MS,
      tolerancePx: DEFAULT_TOLERANCE_PX,
      rewrite: false,
      error: false
    }
  }

  try {
    var value = JSON.parse(raw)
    if (!isObject(value)
        || !exactFields(value, ["version", "dwellMs", "tolerancePx"])
        || value.version !== SETTINGS_VERSION
        || !isInteger(value.dwellMs)
        || !inList(value.dwellMs, DWELL_CHOICES)
        || !isInteger(value.tolerancePx)
        || !inList(value.tolerancePx, TOLERANCE_CHOICES)) {
      throw new Error("invalid settings")
    }
    return {
      dwellMs: value.dwellMs,
      tolerancePx: value.tolerancePx,
      rewrite: false,
      error: false
    }
  } catch (_error) {
    return {
      dwellMs: DEFAULT_DWELL_MS,
      tolerancePx: DEFAULT_TOLERANCE_PX,
      rewrite: true,
      error: true
    }
  }
}

function settingsJson(dwellMs, tolerancePx) {
  return JSON.stringify({
    version: SETTINGS_VERSION,
    dwellMs: boundedDwell(dwellMs),
    tolerancePx: boundedTolerance(tolerancePx)
  }, null, 2) + "\n"
}

function validateCapabilities(value) {
  return isObject(value)
    && exactFields(value, ["cursor", "locked", "click"])
    && value.cursor === true
    && value.locked === true
    && value.click === true
}

function parseEvent(line, expectedEpoch) {
  if (typeof line !== "string" || line.length === 0 || line.length > MAX_LINE_LENGTH) {
    return { ok: false, code: "invalid_line" }
  }

  var event
  try {
    event = JSON.parse(line)
  } catch (_error) {
    return { ok: false, code: "invalid_json" }
  }

  if (!isObject(event) || !boundedString(event.type, 32, false)
      || !Object.prototype.hasOwnProperty.call(EVENT_FIELDS, event.type)
      || !exactFields(event, EVENT_FIELDS[event.type])
      || !validEpoch(event.epoch)) {
    return { ok: false, code: "invalid_event" }
  }
  if (event.epoch !== expectedEpoch) return { ok: false, code: "stale_epoch", stale: true }

  if (event.type === "ready") {
    if (!validateCapabilities(event.capabilities)
        || !isInteger(event.pollMs) || event.pollMs < 10 || event.pollMs > 1000) {
      return { ok: false, code: "invalid_ready" }
    }
  } else if (event.type === "state") {
    if (!validState(event.state) || !validAction(event.action)
        || !boundedString(event.reason, 64, false)
        || !/^[a-z][a-z0-9_-]*$/.test(event.reason)) {
      return { ok: false, code: "invalid_state" }
    }
  } else if (event.type === "frame") {
    if (!validState(event.state) || !validAction(event.action)
        || !validCoordinate(event.x) || !validCoordinate(event.y)
        || typeof event.progress !== "number" || !isFinite(event.progress)
        || event.progress < 0 || event.progress > 1) {
      return { ok: false, code: "invalid_frame" }
    }
  } else if (event.type === "clicked") {
    if (!validAction(event.action) || !validCoordinate(event.x) || !validCoordinate(event.y)) {
      return { ok: false, code: "invalid_clicked" }
    }
  } else if (event.type === "error") {
    if (!boundedString(event.code, 64, false)
        || !/^[a-z0-9_]+$/.test(event.code)
        || !boundedString(event.message, 240, false)
        || typeof event.fatal !== "boolean") {
      return { ok: false, code: "invalid_error" }
    }
  }

  return { ok: true, event: event }
}

function transitionAllowed(previous, next) {
  if (!validState(previous) || !validState(next)) return false
  if (previous === next) return true
  if (next === "faulted" || next === "stopped" || next === "paused") return true

  var allowed = {
    paused: ["require_move", "suspended"],
    require_move: ["tracking", "suspended"],
    tracking: ["dwelling", "require_move", "suspended"],
    dwelling: ["tracking", "committing", "require_move", "suspended"],
    committing: ["rearming", "suspended"],
    rearming: ["tracking", "require_move", "suspended"],
    suspended: ["require_move"],
    faulted: [],
    stopped: []
  }
  return allowed[previous].indexOf(next) !== -1
}

function frameAllowed(state) {
  return inList(state, ["require_move", "tracking", "dwelling", "rearming"])
}

function screenContains(screen, x, y) {
  if (!screen || !validCoordinate(x) || !validCoordinate(y)) return false
  return x >= screen.x && x < screen.x + screen.width
    && y >= screen.y && y < screen.y + screen.height
}

function actionLabel(action) {
  if (action === "right") return "Right click"
  if (action === "double") return "Double click"
  return "Left click"
}

function stateLabel(state, reason) {
  if (state === "paused" || state === "stopped") return "Paused"
  if (state === "require_move" || state === "rearming") return "Move to rearm"
  if (state === "tracking") return "Ready"
  if (state === "dwelling") return "Hold still"
  if (state === "committing") return "Clicking"
  if (state === "suspended") return reason === "session_locked" ? "Locked" : "Waiting"
  if (state === "faulted") return "Needs attention"
  return "Starting"
}
