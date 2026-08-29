import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVICE = (ROOT / "Service.qml").read_text(encoding="utf-8")
BAR = (ROOT / "BarWidget.qml").read_text(encoding="utf-8")
MODEL = (ROOT / "ClickAbleModel.js").read_text(encoding="utf-8")


class ManifestContractTests(unittest.TestCase):
  def test_manifest_is_one_loaded_service_and_one_bar_widget(self):
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))

    self.assertEqual(manifest["schemaVersion"], 1)
    self.assertEqual(manifest["id"], "io.github.josephbriones.clickable")
    self.assertEqual(manifest["kinds"], ["service", "bar-widget"])
    self.assertTrue(manifest["keepLoaded"])
    self.assertEqual(manifest["entryPoints"], {
      "service": "Service.qml",
      "barWidget": "BarWidget.qml",
    })
    self.assertFalse(manifest["barWidget"]["allowMultiple"])


class ServiceContractTests(unittest.TestCase):
  def function_body(self, name):
    match = re.search(rf"  function {re.escape(name)}\([^)]*\) \{{(.*?)\n  \}}", SERVICE, re.S)
    self.assertIsNotNone(match, name)
    return match.group(1)

  def test_load_is_paused_and_only_explicit_actions_launch_helper(self):
    self.assertIn('property bool runningRequested: false', SERVICE)
    self.assertIn('property string engineState: "paused"', SERVICE)
    completed = SERVICE.split("Component.onCompleted:", 1)[1].split("Component.onDestruction:", 1)[0]
    self.assertNotIn("service.start()", completed)
    self.assertNotIn("helperProcess.running = true", completed)
    self.assertIn('function start()', SERVICE)
    self.assertIn('function pause(reason)', SERVICE)
    arm = self.function_body("arm")
    self.assertIn('if (!settingsLoaded)', arm)
    self.assertLess(arm.index('if (!settingsLoaded)'), arm.index('helperProcess.running = true'))

  def test_helper_is_parent_bound_epoch_scoped_and_stopped_while_paused(self):
    self.assertIn('String(Quickshell.processId)', SERVICE)
    self.assertIn('"--shell-pid", shellProcessId', SERVICE)
    self.assertIn('"--epoch", String(activeEpoch)', SERVICE)
    self.assertIn('stdinEnabled: true', SERVICE)
    self.assertIn('payload.epoch = activeEpoch', SERVICE)
    pause = self.function_body("pause")
    self.assertIn('sendCommand({ type: "pause"', pause)
    self.assertIn('sendCommand({ type: "stop" })', pause)
    self.assertIn('helperProcess.running = false', pause)
    self.assertIn('cursorX = 0', pause)
    self.assertIn('cursorY = 0', pause)
    stop_helper = self.function_body("stopHelper")
    self.assertIn('cursorX = 0', stop_helper)
    self.assertIn('cursorY = 0', stop_helper)

  def test_backend_owns_polling_countdown_and_click_dispatch(self):
    self.assertIn('onRead: function(line) { service.applyEventLine(line) }', SERVICE)
    self.assertIn('event.type === "frame"', SERVICE)
    self.assertNotIn('type: "sample"', SERVICE)
    self.assertNotIn('type: "click"', SERVICE)
    self.assertNotIn("hyprctl", SERVICE)
    self.assertNotIn("mouse:272", SERVICE)

  def test_activity_follows_every_fresh_baseline(self):
    self.assertIn('IdleMonitor {', SERVICE)
    self.assertIn('timeout: 0.05', SERVICE)
    self.assertIn('respectInhibitors: false', SERVICE)
    ready = self.function_body("applyReady")
    self.assertLess(ready.index('sendCommand({ type: "resume" })'),
                    ready.index('sendCommand({ type: "activity"'))
    self.assertGreaterEqual(SERVICE.count('idle: activityMonitor.isIdle'), 5)

  def test_protocol_validation_and_errors_fail_closed_correctly(self):
    self.assertIn('ClickAbleModel.parseEvent(String(line || ""), activeEpoch)', SERVICE)
    self.assertIn('if (parsed.stale) return', SERVICE)
    self.assertIn('if (event.fatal) failClosed(event.code, event.message)', SERVICE)
    self.assertIn('else {\n        progress = 0', SERVICE)
    self.assertIn('ClickAbleModel.transitionAllowed', SERVICE)
    self.assertIn('engineState !== "committing"', SERVICE)

  def test_action_changes_wait_for_the_workers_ordered_acknowledgement(self):
    action = self.function_body("setAction")
    self.assertIn('if (pendingAction !== "") return false', action)
    self.assertIn('pendingAction = value', action)
    self.assertNotIn('selectedAction = value', action)
    self.assertLess(action.index('sendCommand({ type: "set_action"'),
                    action.rindex('requestedAction = value'))
    state = self.function_body("applyState")
    self.assertIn('event.action === pendingAction', state)
    self.assertIn('pendingAction = ""', state)
    self.assertGreaterEqual(state.count('event.action !== selectedAction'), 2)
    self.assertIn('failClosed("illegal_action"', state)

  def test_prearmed_one_shot_survives_startup_and_early_pause(self):
    self.assertIn(': (helperReady ? selectedAction : requestedAction)', SERVICE)
    pause = self.function_body("pause")
    self.assertIn('else if (helperReady && ClickAbleModel.validAction(selectedAction))', pause)

  def test_action_queued_at_commit_survives_the_completed_click(self):
    clicked = self.function_body("applyClicked")
    self.assertIn('if (pendingAction === "") requestedAction = "left"', clicked)
    self.assertNotIn('pendingAction = ""', clicked)

  def test_guards_cancel_scene_lock_and_helper_failures(self):
    for event in ("workspace", "openwindow", "closewindow", "openlayer",
                  "fullscreen", "changefloatingmode", "minimize", "minimized", "pin",
                  "moveworkspace", "activespecial", "configreloaded"):
      self.assertIn(f'"{event}"', SERVICE)
    self.assertIn('name: "session_lock"', SERVICE)
    self.assertIn('name: "scene_change"', SERVICE)
    self.assertIn('helper_unresponsive', SERVICE)
    self.assertIn('helper_exited', SERVICE)

  def test_focus_guard_deduplicates_addresses_and_ignores_title_events(self):
    scene = self.function_body("sceneChanged")
    self.assertIn('name === "activewindow" || name === "activewindowv2"', scene)
    self.assertIn('ClickAbleModel.focusEventUpdate(', scene)
    self.assertIn('activeWindowAddress = focus.address', scene)
    self.assertIn('if (!focus.changed) return', scene)
    guarded = scene.split("var guarded = [", 1)[1].split("]", 1)[0]
    self.assertNotIn('"activewindow"', guarded)
    self.assertNotIn('"activewindowv2"', guarded)
    self.assertIn('name !== "activewindowv2"', scene)
    self.assertLess(scene.index('activeWindowAddress = focus.address'),
                    scene.index('if (!helperReady || !runningRequested) return'))
    scene_timer = SERVICE.split("id: sceneGuardTimer", 1)[1].split("Process {", 1)[0]
    self.assertIn('name: "scene_change", blocked: false', scene_timer)
    self.assertIn('idle: activityMonitor.isIdle', scene_timer)

  def test_watchdog_exceeds_the_bounded_double_click_commit(self):
    self.assertIn('interval: Math.max(3000, service.pollMs * 8)', SERVICE)
    self.assertIn('four bounded 500 ms Hyprland requests', SERVICE)

  def test_indicator_is_per_output_passive_and_never_focuses(self):
    self.assertIn('Variants {\n    model: Quickshell.screens', SERVICE)
    self.assertIn('screen: modelData', SERVICE)
    self.assertIn('mask: Region {}', SERVICE)
    self.assertIn('WlrLayershell.keyboardFocus: WlrKeyboardFocus.None', SERVICE)
    self.assertIn('exclusionMode: ExclusionMode.Ignore', SERVICE)
    self.assertIn('textFormat: Text.PlainText', SERVICE)
    self.assertNotIn('MouseArea {', SERVICE)

  def test_settings_are_private_bounded_and_never_store_armed_state(self):
    self.assertIn('sourceDir + "/bin/clickable-settings"', SERVICE)
    self.assertIn('[service.settingsHelperPath, "read", service.configHome]', SERVICE)
    self.assertIn('[settingsHelperPath, "write", configHome,', SERVICE)
    self.assertIn('waitForEnd: true', SERVICE)
    self.assertIn('settingsReadOutput.text.length <= 8192', SERVICE)
    self.assertIn('responseKeys.length !== 1', SERVICE)
    self.assertIn('response.text.length > 1024', SERVICE)
    self.assertIn('property bool settingsPersistenceReady: false', SERVICE)
    self.assertIn('property bool settingsComponentReady: false', SERVICE)
    self.assertIn('onSourceDirChanged: Qt.callLater(function() { service.startSettingsRead() })', SERVICE)
    start_read = self.function_body("startSettingsRead")
    self.assertIn('!settingsComponentReady', start_read)
    self.assertIn('sourceDir === ""', start_read)
    self.assertIn('settingsReadProcess.running = true', start_read)
    completed = SERVICE.split('Component.onCompleted:', 1)[1]
    self.assertNotIn('sourceDir === ""', completed)
    self.assertIn('service.startSettingsRead()', completed)
    self.assertNotIn('FileView {', SERVICE)
    self.assertNotIn('["mkdir"', SERVICE)
    self.assertNotIn('settingsFile.setText', SERVICE)
    flush = self.function_body("flushSettings")
    self.assertIn('settingsSaveProcess.running || settingsSaveStartPending', flush)
    self.assertLess(flush.index('settingsDirty = false'),
                    flush.index('settingsSaveProcess.running = true'))
    save_process = SERVICE.split('id: settingsSaveProcess', 1)[1].split(
      'id: helperProcess', 1)[0]
    self.assertIn('if (service.settingsDirty) settingsSaveTimer.restart()', save_process)
    self.assertIn('service.settingsPersistenceReady = false', save_process)
    self.assertIn('if (!settingsLoaded) return', self.function_body("setDwellMs"))
    self.assertIn('if (!settingsLoaded) return', self.function_body("setTolerancePx"))
    self.assertGreaterEqual(
      BAR.count('enabled: !!(root.clickableService && root.clickableService.settingsLoaded)'),
      3,
    )
    settings_json = re.search(r"function settingsJson\(.*?\n\}", MODEL, re.S).group(0)
    self.assertIn('dwellMs:', settings_json)
    self.assertIn('tolerancePx:', settings_json)
    self.assertNotIn('armed', settings_json)
    self.assertNotIn('action', settings_json)
    load = self.function_body("loadSettings")
    self.assertIn('if (helperReady)', load)
    self.assertIn('sendConfiguration()', load)
    self.assertIn('type: "activity", idle: activityMonitor.isIdle', load)

  def test_public_ipc_is_exact_and_state_discloses_no_coordinates(self):
    self.assertIn('target: "clickable"', SERVICE)
    for name in ("ping", "demo", "toggle", "arm", "pause", "left", "right", "double", "state"):
      self.assertRegex(SERVICE, rf"function {name}\([^)]*\): string")
    self.assertIn('function ping(): string { return "ok" }', SERVICE)
    state = self.function_body("stateJson")
    for field in ("running:", "starting:", "locked:", "guarded:", "actionPending:",
                  "settingsReady:"):
      self.assertIn(field, state)
    self.assertNotIn("cursorX", state)
    self.assertNotIn("cursorY", state)


class BarContractTests(unittest.TestCase):
  def test_paused_bar_click_opens_controls_and_armed_click_pauses(self):
    pressed = re.search(r"    onPressed: function\(button\) \{(.*?)\n    \}", BAR, re.S)
    self.assertIsNotNone(pressed)
    body = pressed.group(1)
    self.assertNotIn('button === Qt.RightButton', body)
    self.assertNotIn('displayAction', body)
    self.assertIn('ClickAbleModel.barActivationDecision(', body)
    self.assertLess(body.index('if (decision === "ignore") return'),
                    body.index('if (decision === "pause")'))
    self.assertLess(body.index('root.triggerActivationSuppressed = true'),
                    body.index('root.clickableService.pause("bar")'))
    self.assertLess(body.index('triggerSuppressionTimer.restart()'),
                    body.index('root.clickableService.pause("bar")'))
    self.assertLess(body.index('root.clickableService.pause("bar")'),
                    body.index('root.close()'))
    armed_return = body.index('return', body.index('root.close()'))
    self.assertLess(body.index('root.close()'), armed_return)
    self.assertLess(armed_return, body.index('root.togglePopup()'))
    self.assertNotIn('onPressed: root.clickableService.start()', BAR)
    timer = BAR.split('id: triggerSuppressionTimer', 1)[1].split('KeyboardPanel {', 1)[0]
    self.assertIn('interval: 1250', timer)
    self.assertIn('onTriggered: root.triggerActivationSuppressed = false', timer)

  def test_arm_and_pause_release_popup_grab_immediately(self):
    primary = BAR.split("id: primaryAction", 1)[1].split("PanelSeparator", 1)[0]
    self.assertIn('root.clickableService.start()', primary)
    self.assertIn('if (root.clickableService.runningRequested) root.close()', primary)
    self.assertRegex(primary, r'root\.clickableService\.pause\("bar"\)\n\s+root\.close\(\)')

  def test_controls_are_large_keyboard_visible_and_screen_reader_named(self):
    self.assertIn('(44 - fontSize) / 2', BAR)
    self.assertGreaterEqual(BAR.count('width: Math.max(44,'), 5)
    self.assertIn('focusable: true', BAR)
    self.assertIn('visible: trigger.activeFocus', BAR)
    self.assertIn('Accessible.onPressAction', BAR)
    self.assertIn('Accessible.onToggleAction', BAR)
    self.assertIn('Accessible.RadioButton', BAR)
    self.assertIn('Accessible.StatusBar', BAR)
    self.assertIn('Accessible.AlertMessage', BAR)
    self.assertGreaterEqual(BAR.count('textFormat: Text.PlainText'), 8)

  def test_popup_is_bounded_scrollable_and_focus_reveals_controls(self):
    self.assertIn('KeyboardPanel {', BAR)
    self.assertIn('focusTarget: keyCatcher', BAR)
    self.assertIn('Qt.callLater(function() { primaryAction.forceActiveFocus() })', BAR)
    self.assertNotIn('PopupCard {', BAR)
    self.assertIn('contentHeight: popup.fittedContentHeight(content.implicitHeight)', BAR)
    self.assertIn('Flickable {', BAR)
    self.assertIn('clip: true', BAR)
    self.assertIn('function revealControl(item)', BAR)
    self.assertIn('onActiveFocusChanged: if (activeFocus) root.revealControl(this)', BAR)

  def test_popup_has_canonical_keyboard_dismissal_and_explicit_close(self):
    self.assertIn('PanelKeyCatcher {', BAR)
    self.assertIn('onCloseRequested: root.close()', BAR)
    self.assertIn('onTabRequested: function(direction) { root.moveFocus(direction) }', BAR)
    self.assertIn('onMoveRequested: function(dx, dy)', BAR)
    self.assertIn('onActivateRequested: root.activateFocusedControl()', BAR)
    self.assertIn('if (primaryAction.visible && primaryAction.enabled) primaryAction.clicked()', BAR)
    close = BAR.split("id: closeAction", 1)[1].split("Text {", 1)[0]
    self.assertIn('text: "Close controls"', close)
    self.assertIn('Accessible.description:', close)
    self.assertIn('onClicked: root.close()', close)

  def test_right_and_double_are_truthful_one_shot_controls(self):
    self.assertIn('text: "Right once"', BAR)
    self.assertIn('text: "Double once"', BAR)
    self.assertIn('Returns to left click after a confirmed click', BAR)
    self.assertIn('Choose the next click before arming.', BAR)
    self.assertIn('a safety fault also returns to Left.', BAR)

  def test_next_action_is_selectable_before_arming_without_a_mouse_button(self):
    self.assertGreaterEqual(BAR.count('root.clickableService.displayAction'), 4)
    self.assertGreaterEqual(BAR.count('!root.clickableService.runningRequested'), 3)
    self.assertIn('requestedAction = value', SERVICE)
    self.assertIn('if (requestedAction !== "left")', SERVICE)
    self.assertIn('type: "set_action", action: requestedAction', SERVICE)


if __name__ == "__main__":
  unittest.main()
