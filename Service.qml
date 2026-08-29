import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import "ClickAbleModel.js" as ClickAbleModel

Item {
  id: service

  // Injected by omarchy-shell's generic service loader.
  property var shell: null
  property var manifest: null

  property string omarchyPath: Quickshell.env("OMARCHY_PATH")
  readonly property string pluginId: manifest && manifest.id
    ? String(manifest.id)
    : "io.github.josephbriones.clickable"
  readonly property string sourceDir: manifest && manifest.__sourceDir
    ? String(manifest.__sourceDir)
    : ""
  readonly property string backendPath: sourceDir + "/bin/clickable"
  readonly property string settingsHelperPath: sourceDir + "/bin/clickable-settings"
  readonly property string shellProcessId: String(Quickshell.processId)

  readonly property string configHome: Quickshell.env("XDG_CONFIG_HOME") !== ""
    ? Quickshell.env("XDG_CONFIG_HOME")
    : (Quickshell.env("HOME") !== "" ? Quickshell.env("HOME") + "/.config" : "")
  property int dwellMs: ClickAbleModel.DEFAULT_DWELL_MS
  property int tolerancePx: ClickAbleModel.DEFAULT_TOLERANCE_PX
  readonly property var dwellChoices: ClickAbleModel.DWELL_CHOICES
  readonly property var toleranceChoices: ClickAbleModel.TOLERANCE_CHOICES

  property bool settingsLoaded: false
  property bool settingsComponentReady: false
  property bool settingsHydrating: false
  property bool settingsPersistenceReady: false
  property bool settingsReadStartPending: false
  property bool settingsSaveStartPending: false
  property bool settingsDirty: false

  // Deliberate session state is never persistent. Every shell load is paused.
  property bool runningRequested: false
  property bool demoMode: false
  property bool helperReady: false
  property bool helperStartPending: false
  property bool helperExpectedStop: false
  property bool acceptingEvents: false
  property int epochSerial: 0
  property int activeEpoch: 0
  property string engineState: "paused"
  property string stateReason: "loaded_paused"
  // requestedAction is the user's session-only next choice. selectedAction is
  // the worker-acknowledged value used to validate frames and click events.
  property string requestedAction: "left"
  property string selectedAction: "left"
  property string pendingAction: ""
  property var capabilities: ({ cursor: false, locked: false, click: false })
  property int pollMs: 0
  property int cursorX: 0
  property int cursorY: 0
  property real progress: 0
  property string errorCode: ""
  property string errorMessage: ""
  property string helperDiagnostic: ""
  property bool sceneGuarded: false
  property string activeWindowAddress: ""
  property bool sessionLocked: !!(lockService && lockService.locked)

  readonly property var lockService: shell && shell.firstPartyServiceFor
    ? shell.firstPartyServiceFor("omarchy.lock")
    : null
  readonly property bool active: runningRequested && helperReady
    && engineState !== "paused" && engineState !== "faulted" && engineState !== "stopped"
  readonly property string displayAction: pendingAction !== ""
    ? pendingAction
    : (helperReady ? selectedAction : requestedAction)
  readonly property bool indicatorVisible: active && !sessionLocked && !sceneGuarded
    && ClickAbleModel.frameAllowed(engineState) && progress > 0
  readonly property string statusLabel: !settingsLoaded
    ? "Loading preferences"
    : (errorMessage !== ""
    ? "Needs attention"
    : ClickAbleModel.stateLabel(engineState, stateReason))

  function nextEpoch() {
    epochSerial = epochSerial >= 2147483647 ? 1 : epochSerial + 1
    return epochSerial
  }

  function supportsAction(action) {
    return !!capabilities.click && ClickAbleModel.validAction(String(action || ""))
  }

  function stateJson() {
    return JSON.stringify({
      active: active,
      running: helperProcess.running || helperStartPending,
      starting: helperStartPending,
      state: engineState,
      reason: stateReason,
      action: displayAction,
      actionPending: pendingAction !== "",
      settingsReady: settingsLoaded,
      progress: progress,
      demo: demoMode,
      ready: helperReady,
      locked: sessionLocked,
      guarded: sceneGuarded,
      dwellMs: dwellMs,
      tolerancePx: tolerancePx,
      error: errorCode
    })
  }

  function sendCommand(command) {
    if (!helperProcess.running || !helperReady || !acceptingEvents) return false
    var payload = {}
    var keys = Object.keys(command || {})
    for (var i = 0; i < keys.length; i++) payload[keys[i]] = command[keys[i]]
    payload.epoch = activeEpoch
    var line = JSON.stringify(payload)
    if (line.length > ClickAbleModel.MAX_LINE_LENGTH) {
      failClosed("command_too_large", "ClickAble stopped because a local command was invalid.")
      return false
    }
    helperProcess.write(line + "\n")
    return true
  }

  function sendConfiguration() {
    return sendCommand({
      type: "configure",
      dwellMs: dwellMs,
      tolerancePx: tolerancePx
    })
  }

  function arm(useDemo) {
    if (runningRequested || helperStartPending || helperProcess.running) return stateJson()
    if (!settingsLoaded) {
      engineState = "paused"
      stateReason = "settings_loading"
      return stateJson()
    }
    if (sessionLocked) {
      engineState = "suspended"
      stateReason = "session_locked"
      return stateJson()
    }
    if (sourceDir === "" || backendPath === "/bin/clickable") {
      failClosed("helper_missing", "ClickAble could not locate its local helper. Reinstall the plugin.")
      return stateJson()
    }

    errorCode = ""
    errorMessage = ""
    helperDiagnostic = ""
    progress = 0
    cursorX = 0
    cursorY = 0
    selectedAction = "left"
    pendingAction = ""
    runningRequested = true
    demoMode = !!useDemo
    helperReady = false
    acceptingEvents = true
    helperExpectedStop = false
    helperStartPending = true
    activeEpoch = nextEpoch()
    engineState = "paused"
    stateReason = "starting"
    capabilities = ({ cursor: false, locked: false, click: false })
    pollMs = 0

    var command = [backendPath, "--shell-pid", shellProcessId,
      "--epoch", String(activeEpoch)]
    if (demoMode) command.push("--demo")
    helperProcess.command = command
    helperProcess.running = true
    readyWatchdog.restart()
    return stateJson()
  }

  function start() {
    return arm(false)
  }

  function demo() {
    return arm(true)
  }

  function pause(reason) {
    var why = String(reason || "user")
    if (pendingAction !== "") requestedAction = pendingAction
    else if (helperReady && ClickAbleModel.validAction(selectedAction)) requestedAction = selectedAction
    if (helperProcess.running && helperReady && acceptingEvents) {
      sendCommand({ type: "pause", reason: why })
      sendCommand({ type: "stop" })
    }

    readyWatchdog.stop()
    eventWatchdog.stop()
    sceneGuardTimer.stop()
    sceneGuarded = false
    runningRequested = false
    helperReady = false
    acceptingEvents = false
    helperStartPending = false
    progress = 0
    cursorX = 0
    cursorY = 0
    selectedAction = "left"
    pendingAction = ""
    demoMode = false
    engineState = "paused"
    stateReason = why

    if (helperProcess.running) {
      helperExpectedStop = true
      helperProcess.running = false
    }
    return stateJson()
  }

  function toggle() {
    return runningRequested ? pause("user") : start()
  }

  function setAction(action) {
    var value = String(action || "").toLowerCase()
    if (!ClickAbleModel.validAction(value) || sessionLocked) return false
    if (!runningRequested && !helperProcess.running && !helperStartPending) {
      requestedAction = value
      return true
    }
    if (!supportsAction(value)) return false
    if (pendingAction !== "") return false
    if (value === selectedAction) {
      requestedAction = value
      return true
    }
    if (!active || !sendCommand({ type: "set_action", action: value })) return false
    // The worker owns the action. Keep rendering the last acknowledged value
    // until its ordered state event arrives; an older in-flight frame is then
    // still valid instead of looking like a protocol violation.
    requestedAction = value
    pendingAction = value
    return true
  }

  function setDwellMs(value) {
    if (!settingsLoaded) return
    var next = ClickAbleModel.boundedDwell(Number(value))
    if (next === dwellMs) return
    dwellMs = next
    scheduleSettingsSave()
    if (helperReady) {
      sendConfiguration()
      sendCommand({ type: "activity", idle: activityMonitor.isIdle })
    }
  }

  function setTolerancePx(value) {
    if (!settingsLoaded) return
    var next = ClickAbleModel.boundedTolerance(Number(value))
    if (next === tolerancePx) return
    tolerancePx = next
    scheduleSettingsSave()
    if (helperReady) {
      sendConfiguration()
      sendCommand({ type: "activity", idle: activityMonitor.isIdle })
    }
  }

  function stopHelper() {
    helperReady = false
    acceptingEvents = false
    pendingAction = ""
    progress = 0
    cursorX = 0
    cursorY = 0
    if (helperProcess.running) {
      helperExpectedStop = true
      helperProcess.running = false
    }
  }

  function failClosed(code, message) {
    readyWatchdog.stop()
    eventWatchdog.stop()
    sceneGuardTimer.stop()
    sceneGuarded = false
    runningRequested = false
    progress = 0
    cursorX = 0
    cursorY = 0
    requestedAction = "left"
    selectedAction = "left"
    pendingAction = ""
    demoMode = false
    engineState = "faulted"
    stateReason = String(code || "helper_failure")
    errorCode = String(code || "helper_failure").slice(0, 64)
    errorMessage = String(message || "ClickAble stopped safely.").slice(0, 240)
    stopHelper()
  }

  function applyReady(event) {
    if (helperReady || engineState !== "paused" || stateReason !== "starting") {
      failClosed("unexpected_ready", "ClickAble stopped because its local helper broke the protocol.")
      return
    }
    helperReady = true
    helperStartPending = false
    capabilities = event.capabilities
    pollMs = event.pollMs
    readyWatchdog.stop()
    eventWatchdog.restart()

    if (!sendConfiguration()) return
    sendCommand({ type: "guard", name: "session_lock", blocked: sessionLocked })
    sendCommand({ type: "guard", name: "scene_change", blocked: false })
    sendCommand({ type: "resume" })
    if (requestedAction !== "left") {
      pendingAction = requestedAction
      sendCommand({ type: "set_action", action: requestedAction })
    }
    // Resume samples a fresh baseline and resets the quiet gate. Report the
    // current value even when IdleMonitor was already idle and will not emit.
    sendCommand({ type: "activity", idle: activityMonitor.isIdle })
  }

  function applyState(event) {
    if (!helperReady || !ClickAbleModel.transitionAllowed(engineState, event.state)) {
      failClosed("illegal_state", "ClickAble stopped because its local helper reported an impossible state.")
      return
    }
    if (pendingAction !== "") {
      if (event.action === pendingAction) {
        pendingAction = ""
        requestedAction = event.action
      } else if (event.action !== selectedAction) {
        failClosed("illegal_action", "ClickAble stopped because its local helper changed the click action unexpectedly.")
        return
      }
    } else if (event.action !== selectedAction) {
      failClosed("illegal_action", "ClickAble stopped because its local helper changed the click action unexpectedly.")
      return
    } else {
      requestedAction = event.action
    }
    engineState = event.state
    stateReason = event.reason
    selectedAction = event.action
    if (event.state !== "dwelling") progress = 0
    if (event.state === "paused" && errorCode !== "" && event.reason !== "configured") {
      failClosed(errorCode, errorMessage || "ClickAble paused safely after a local helper error.")
      return
    }
    if (event.state !== "paused" && event.state !== "faulted") {
      errorCode = ""
      errorMessage = ""
    }
  }

  function applyFrame(event) {
    if (!helperReady || !ClickAbleModel.frameAllowed(event.state)
        || !ClickAbleModel.transitionAllowed(engineState, event.state)
        || event.action !== selectedAction) {
      failClosed("illegal_frame", "ClickAble stopped because its local helper reported an impossible countdown.")
      return
    }
    engineState = event.state
    cursorX = event.x
    cursorY = event.y
    progress = event.state === "dwelling" ? event.progress : 0
  }

  function applyClicked(event) {
    if (!helperReady || engineState !== "committing" || event.action !== selectedAction) {
      failClosed("illegal_click", "ClickAble stopped because its local helper reported an impossible click.")
      return
    }
    cursorX = event.x
    cursorY = event.y
    progress = 0
    if (event.action !== "left") {
      selectedAction = "left"
      if (pendingAction === "") requestedAction = "left"
    }
    // A click may already be inside Hyprland when a new one-shot choice is
    // queued. Preserve that ordered request; the worker's later state event
    // will acknowledge it after reporting the completed click's rearm state.
  }

  function applyEventLine(line) {
    if (!acceptingEvents) return
    var parsed = ClickAbleModel.parseEvent(String(line || ""), activeEpoch)
    if (!parsed.ok) {
      if (parsed.stale) return
      failClosed("protocol_error", "ClickAble stopped because its local helper sent invalid data.")
      return
    }

    var event = parsed.event
    eventWatchdog.restart()
    if (event.type === "ready") applyReady(event)
    else if (event.type === "state") applyState(event)
    else if (event.type === "frame") applyFrame(event)
    else if (event.type === "clicked") applyClicked(event)
    else if (event.type === "error") {
      if (event.fatal) failClosed(event.code, event.message)
      else {
        progress = 0
        errorCode = event.code
        errorMessage = event.message
        console.warn("clickable: helper warning:", event.code)
      }
    }
  }

  function handleLockChanged() {
    sessionLocked = !!(lockService && lockService.locked)
    progress = 0
    if (!helperReady) return
    sendCommand({ type: "guard", name: "session_lock", blocked: sessionLocked })
    if (sessionLocked) eventWatchdog.stop()
    else {
      sendCommand({ type: "activity", idle: activityMonitor.isIdle })
      eventWatchdog.restart()
    }
  }

  function hyprlandEventData(event) {
    var parts
    try {
      if (event && event.parse) parts = event.parse(1)
    } catch (_error) {
    }
    if (!parts) parts = String(event && event.data ? event.data : "").split(",")
    return String(parts[0] || "")
  }

  function sceneChanged(event) {
    var name = String(event && event.name ? event.name : "")
    // activewindow carries title text and fires for title-only updates. Its v2
    // companion carries the stable address needed to distinguish real focus.
    if (name === "activewindow" || name === "activewindowv2") {
      var focus = ClickAbleModel.focusEventUpdate(
        activeWindowAddress, name, hyprlandEventData(event))
      activeWindowAddress = focus.address
      if (!focus.changed) return
    }

    var guarded = [
      "workspace", "workspacev2", "focusedmon", "focusedmonv2",
      "moveworkspace", "moveworkspacev2", "activespecial", "activespecialv2",
      "fullscreen", "changefloatingmode",
      "minimize", "minimized", "pin", "togglegroup", "moveintogroup", "moveoutofgroup",
      "openwindow", "closewindow", "movewindow", "movewindowv2",
      "openlayer", "closelayer", "monitoradded", "monitoraddedv2",
      "monitorremoved", "monitorremovedv2", "configreloaded"
    ]
    if (name !== "activewindowv2" && guarded.indexOf(name) === -1) return
    if (!helperReady || !runningRequested) return

    progress = 0
    if (!sceneGuarded) {
      sceneGuarded = true
      sendCommand({ type: "guard", name: "scene_change", blocked: true })
    }
    sceneGuardTimer.restart()
  }

  function loadSettings(raw) {
    if (settingsLoaded) return
    var parsed = ClickAbleModel.parseSettings(raw)
    settingsHydrating = true
    dwellMs = parsed.dwellMs
    tolerancePx = parsed.tolerancePx
    settingsHydrating = false
    settingsLoaded = true
    // Loading is asynchronous. If Arm won the race, immediately apply the
    // loaded values through configure(), which also establishes a fresh
    // movement baseline before any dwell can continue.
    if (helperReady) {
      sendConfiguration()
      sendCommand({ type: "activity", idle: activityMonitor.isIdle })
    }
    if ((parsed.error || parsed.rewrite) && settingsPersistenceReady)
      scheduleSettingsSave()
  }

  function startSettingsRead() {
    if (!settingsComponentReady || settingsLoaded || configHome === ""
        || sourceDir === "" || settingsReadProcess.running
        || settingsReadStartPending) return
    settingsReadStartPending = true
    settingsReadProcess.running = true
  }

  function scheduleSettingsSave() {
    if (!settingsLoaded || settingsHydrating || !settingsPersistenceReady) return
    settingsDirty = true
    settingsSaveTimer.restart()
  }

  function flushSettings() {
    if (!settingsDirty || !settingsPersistenceReady
        || settingsSaveProcess.running || settingsSaveStartPending) return
    settingsDirty = false
    settingsSaveProcess.command = [settingsHelperPath, "write", configHome,
      ClickAbleModel.settingsJson(dwellMs, tolerancePx)]
    settingsSaveStartPending = true
    settingsSaveProcess.running = true
  }

  onSourceDirChanged: Qt.callLater(function() { service.startSettingsRead() })

  Connections {
    target: service.lockService
    ignoreUnknownSignals: true
    function onLockedChanged() { service.handleLockChanged() }
  }

  // ext-idle-notify distinguishes pointer movement from non-positional input.
  // The helper samples immediately on active and owns the movement baseline,
  // so this 50 ms quiet gate cannot livelock the required-movement state.
  IdleMonitor {
    id: activityMonitor
    enabled: service.helperReady && service.runningRequested
    timeout: 0.05
    respectInhibitors: false
    onIsIdleChanged: {
      if (enabled) service.sendCommand({ type: "activity", idle: isIdle })
    }
  }

  Connections {
    target: Hyprland
    function onRawEvent(event) { service.sceneChanged(event) }
  }

  Timer {
    id: readyWatchdog
    interval: 2500
    repeat: false
    onTriggered: service.failClosed(
      "helper_unresponsive",
      "ClickAble's local helper did not become ready in time."
    )
  }

  Timer {
    id: eventWatchdog
    // A double action may consume four bounded 500 ms Hyprland requests:
    // final cursor, lock, then two whole clicks. Do not kill the worker between
    // the first and second click merely because the compositor used its bound.
    interval: Math.max(3000, service.pollMs * 8)
    repeat: false
    onTriggered: {
      if (!service.sessionLocked && !service.sceneGuarded)
        service.failClosed("helper_unresponsive", "ClickAble's local helper stopped responding.")
    }
  }

  Timer {
    id: sceneGuardTimer
    interval: 180
    repeat: false
    onTriggered: {
      service.sceneGuarded = false
      if (service.helperReady) {
        service.sendCommand({ type: "guard", name: "scene_change", blocked: false })
        service.sendCommand({ type: "activity", idle: activityMonitor.isIdle })
        eventWatchdog.restart()
      }
    }
  }

  Timer {
    id: settingsSaveTimer
    interval: 200
    repeat: false
    onTriggered: service.flushSettings()
  }

  Process {
    id: settingsReadProcess
    command: [service.settingsHelperPath, "read", service.configHome]
    stdout: StdioCollector {
      id: settingsReadOutput
      waitForEnd: true
    }
    onStarted: service.settingsReadStartPending = false
    onRunningChanged: {
      if (running || !service.settingsReadStartPending) return
      service.settingsReadStartPending = false
      service.settingsPersistenceReady = false
      service.settingsDirty = false
      service.loadSettings("")
      console.warn("clickable: could not start the private settings helper")
    }
    onExited: function(exitCode) {
      service.settingsReadStartPending = false
      if (exitCode !== 0) {
        service.settingsPersistenceReady = false
        service.settingsDirty = false
        service.loadSettings("")
        console.warn("clickable: unsafe or unavailable settings were ignored")
        return
      }
      var response = null
      try {
        if (settingsReadOutput.text.length <= 8192)
          response = JSON.parse(settingsReadOutput.text)
      } catch (_error) {
      }
      var responseKeys = response && typeof response === "object"
        ? Object.keys(response)
        : []
      if (!response || Array.isArray(response) || responseKeys.length !== 1
          || responseKeys[0] !== "text" || typeof response.text !== "string"
          || response.text.length > 1024) {
        service.settingsPersistenceReady = false
        service.settingsDirty = false
        service.loadSettings("")
        console.warn("clickable: invalid settings helper response was ignored")
        return
      }
      service.settingsPersistenceReady = true
      service.loadSettings(response.text)
    }
  }

  Process {
    id: settingsSaveProcess
    onStarted: service.settingsSaveStartPending = false
    onRunningChanged: {
      if (running || !service.settingsSaveStartPending) return
      service.settingsSaveStartPending = false
      service.settingsPersistenceReady = false
      service.settingsDirty = false
      console.warn("clickable: could not start the private settings helper")
    }
    onExited: function(exitCode) {
      service.settingsSaveStartPending = false
      if (exitCode !== 0) {
        service.settingsPersistenceReady = false
        service.settingsDirty = false
        console.warn("clickable: settings were not saved because persistence became unsafe")
        return
      }
      if (service.settingsDirty) settingsSaveTimer.restart()
    }
  }

  Process {
    id: helperProcess
    stdinEnabled: true
    stdout: SplitParser {
      onRead: function(line) { service.applyEventLine(line) }
    }
    stderr: SplitParser {
      onRead: function(line) {
        if (service.runningRequested)
          service.helperDiagnostic = String(line || "").slice(0, 240)
      }
    }
    onStarted: service.helperStartPending = false
    onRunningChanged: {
      if (running || !service.helperStartPending) return
      service.helperStartPending = false
      if (!service.helperExpectedStop)
        service.failClosed("helper_start_failed", "ClickAble could not start its local helper. Reinstall the plugin.")
    }
    onExited: function(exitCode) {
      service.readyWatchdog.stop()
      service.eventWatchdog.stop()
      service.helperStartPending = false
      service.helperReady = false
      service.acceptingEvents = false
      if (service.helperExpectedStop) {
        service.helperExpectedStop = false
        return
      }
      if (service.runningRequested)
        Qt.callLater(function() {
          service.failClosed(
            "helper_exited",
            service.helperDiagnostic !== ""
              ? "ClickAble's local helper stopped. Pause and try again."
              : "ClickAble's local helper stopped unexpectedly."
          )
        })
    }
  }

  IpcHandler {
    target: "clickable"

    function ping(): string { return "ok" }
    function arm(): string { return service.start() }
    function pause(): string { return service.pause("ipc") }
    function toggle(): string { return service.toggle() }
    function left(): string { return service.setAction("left") ? service.stateJson() : "unavailable" }
    function right(): string { return service.setAction("right") ? service.stateJson() : "unavailable" }
    function double(): string { return service.setAction("double") ? service.stateJson() : "unavailable" }
    function state(): string { return service.stateJson() }
    function demo(): string { return service.demo() }
  }

  Variants {
    model: Quickshell.screens

    PanelWindow {
      id: indicatorWindow
      required property var modelData
      screen: modelData
      visible: service.indicatorVisible
        && ClickAbleModel.screenContains(modelData, service.cursorX, service.cursorY)

      anchors { top: true; bottom: true; left: true; right: true }
      color: "transparent"
      exclusionMode: ExclusionMode.Ignore
      mask: Region {}

      WlrLayershell.namespace: "clickable-countdown"
      WlrLayershell.layer: WlrLayer.Overlay
      WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

      Canvas {
        id: ring
        width: 52
        height: 52
        x: Math.max(0, Math.min(indicatorWindow.width - width,
          service.cursorX - indicatorWindow.modelData.x - width / 2))
        y: Math.max(0, Math.min(indicatorWindow.height - height,
          service.cursorY - indicatorWindow.modelData.y - height / 2))

        onPaint: {
          var context = getContext("2d")
          context.clearRect(0, 0, width, height)
          context.lineWidth = 5
          context.lineCap = "round"
          context.strokeStyle = Qt.rgba(0, 0, 0, 0.55)
          context.beginPath()
          context.arc(width / 2, height / 2, 20, 0, Math.PI * 2)
          context.stroke()
          context.strokeStyle = Color.accent
          context.beginPath()
          context.arc(width / 2, height / 2, 20, -Math.PI / 2,
            -Math.PI / 2 + Math.PI * 2 * service.progress)
          context.stroke()
        }

        Connections {
          target: service
          function onProgressChanged() { ring.requestPaint() }
          function onSelectedActionChanged() { ring.requestPaint() }
        }

        Text {
          anchors.centerIn: parent
          text: service.selectedAction === "right" ? "R"
            : (service.selectedAction === "double" ? "2" : "L")
          textFormat: Text.PlainText
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          font.bold: true
        }
      }
    }
  }

  Component.onCompleted: {
    // Loading settings never arms input. The helper is launched only by an
    // explicit bar or IPC action.
    settingsComponentReady = true
    if (configHome === "") settingsLoaded = true
    else Qt.callLater(function() { service.startSettingsRead() })
  }

  Component.onDestruction: pause("shell_shutdown")
}
