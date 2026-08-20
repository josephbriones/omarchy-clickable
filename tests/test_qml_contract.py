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
    for event in ("workspace", "activewindow", "openwindow", "closewindow", "openlayer",
                  "fullscreen", "changefloatingmode", "minimize", "minimized", "pin",
                  "moveworkspace", "activespecial", "configreloaded"):
      self.assertIn(f'"{event}"', SERVICE)
    self.assertIn('name: "session_lock"', SERVICE)
    self.assertIn('name: "scene_change"', SERVICE)
    self.assertIn('helper_unresponsive', SERVICE)
    self.assertIn('helper_exited', SERVICE)

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
    self.assertIn('configHome + "/omarchy/clickable"', SERVICE)
    self.assertIn('settingsDirectory + "/config.json"', SERVICE)
    self.assertIn('["mkdir", "-m", "700", "-p", "--", service.settingsDirectory]', SERVICE)
    self.assertIn('atomicWrites: true', SERVICE)
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
    self.assertIn('if (root.clickableService.runningRequested)', BAR)
    self.assertIn('root.clickableService.pause("bar")', BAR)
    self.assertIn('root.togglePopup()', BAR)
    self.assertNotIn('onPressed: root.clickableService.start()', BAR)

  def test_arm_and_pause_release_popup_grab_immediately(self):
    primary = BAR.split("id: primaryAction", 1)[1].split("PanelSeparator", 1)[0]
    self.assertIn('root.clickableService.start()', primary)
    self.assertIn('if (root.clickableService.runningRequested) root.close()', primary)
    self.assertIn('root.clickableService.pause("bar")\n            root.close()', primary)

  def test_controls_are_large_keyboard_visible_and_screen_reader_named(self):
    self.assertIn('(44 - fontSize) / 2', BAR)
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
    self.assertIn('focusTarget: primaryAction', BAR)
    self.assertNotIn('PopupCard {', BAR)
    self.assertIn('contentHeight: popup.fittedContentHeight(content.implicitHeight)', BAR)
    self.assertIn('Flickable {', BAR)
    self.assertIn('clip: true', BAR)
    self.assertIn('function revealControl(item)', BAR)
    self.assertIn('onActiveFocusChanged: if (activeFocus) root.revealControl(this)', BAR)

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
