import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "lib"
SPEC = importlib.util.spec_from_file_location("clickable_backend", LIB / "clickable.py")
clickable = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = clickable
SPEC.loader.exec_module(clickable)


class FakeSocket:
  def __init__(self, reply=b"ok", *, error=None):
    self.reply = reply
    self.error = error
    self.timeout = None
    self.path = None
    self.request = None
    self.closed = False

  def settimeout(self, timeout):
    self.timeout = timeout

  def connect(self, path):
    self.path = path
    if self.error is not None:
      raise self.error

  def sendall(self, request):
    self.request = request

  def recv(self, _size):
    if self.error is not None:
      raise self.error
    return self.reply

  def close(self):
    self.closed = True


class RecordingBackend:
  def __init__(self, x=100, y=200):
    self.position = clickable.Point(x, y)
    self.locked = False
    self.clicks = []
    self.calls = []
    self.sample_error = None
    self.click_error = None

  def sample_cursor(self):
    self.calls.append(("cursor", self.position))
    if self.sample_error is not None:
      raise self.sample_error
    return self.position

  def is_locked(self):
    self.calls.append(("locked", self.locked))
    return self.locked

  def click(self, action):
    self.calls.append(("click", action))
    if self.click_error is not None:
      raise self.click_error
    self.clicks.append(action)


class ResponseParsingTests(unittest.TestCase):
  def test_cursor_parser_accepts_negative_integer_coordinates(self):
    self.assertEqual(
      clickable.parse_cursor_response(b'{"x":-1920,"y":37}\n'),
      clickable.Point(-1920, 37),
    )

  def test_cursor_parser_rejects_noncanonical_values(self):
    responses = [
      b'{"x":true,"y":0}',
      b'{"x":1.25,"y":0}',
      b'{"x":1}',
      b'{"x":1,"y":2,"extra":3}',
      b'{"x":1,"x":2,"y":3}',
      b'{"x":1000001,"y":0}',
    ]
    for response in responses:
      with self.subTest(response=response):
        with self.assertRaises(clickable.ClickAbleError) as caught:
          clickable.parse_cursor_response(response)
        self.assertEqual(caught.exception.code, "invalid_cursor_response")

  def test_locked_parser_requires_exactly_one_boolean(self):
    self.assertTrue(clickable.parse_locked_response(b'{"locked":true}'))
    self.assertFalse(clickable.parse_locked_response(b'{"locked":false}\n'))
    for response in (b'{"locked":0}', b'{"locked":false,"extra":1}', b'false'):
      with self.subTest(response=response):
        with self.assertRaises(clickable.ClickAbleError) as caught:
          clickable.parse_locked_response(response)
        self.assertEqual(caught.exception.code, "invalid_lock_response")

  def test_socket_path_uses_documented_hyprland_environment(self):
    path = clickable.socket_path_from_environment({
      "XDG_RUNTIME_DIR": "/run/user/1000",
      "HYPRLAND_INSTANCE_SIGNATURE": "abc_123-0.56.0",
    })
    self.assertEqual(path, Path("/run/user/1000/hypr/abc_123-0.56.0/.socket.sock"))

  def test_socket_path_rejects_missing_relative_and_traversing_values(self):
    environments = [
      {},
      {"XDG_RUNTIME_DIR": "run/user/1000", "HYPRLAND_INSTANCE_SIGNATURE": "abc"},
      {"XDG_RUNTIME_DIR": "/run/user/1000", "HYPRLAND_INSTANCE_SIGNATURE": "../abc"},
      {"XDG_RUNTIME_DIR": "/run/user/1000", "HYPRLAND_INSTANCE_SIGNATURE": "a/b"},
    ]
    for environment in environments:
      with self.subTest(environment=environment):
        with self.assertRaises(clickable.ClickAbleError):
          clickable.socket_path_from_environment(environment)


class HyprlandIPCTests(unittest.TestCase):
  def backend(self):
    return clickable.HyprlandIPC(Path("/run/user/1000/hypr/test/.socket.sock"))

  def test_cursor_and_lock_use_direct_json_socket_requests(self):
    cursor = FakeSocket(b'{"x":-40,"y":81}')
    locked = FakeSocket(b'{"locked":false}')
    with mock.patch.object(clickable.socket, "socket", side_effect=[cursor, locked]) as constructor:
      backend = self.backend()
      point = backend.sample_cursor()
      is_locked = backend.is_locked()

    self.assertEqual(point, clickable.Point(-40, 81))
    self.assertFalse(is_locked)
    self.assertEqual(cursor.request, b"j/cursorpos")
    self.assertEqual(locked.request, b"j/locked")
    self.assertEqual(cursor.timeout, clickable.IPC_TIMEOUT)
    self.assertEqual(locked.timeout, clickable.IPC_TIMEOUT)
    self.assertEqual(constructor.call_args_list[0].args, (socket.AF_UNIX, socket.SOCK_STREAM))
    self.assertTrue(cursor.closed and locked.closed)

  def test_left_and_right_are_exact_targetless_atomic_dispatches(self):
    left = FakeSocket()
    right = FakeSocket()
    with mock.patch.object(clickable.socket, "socket", side_effect=[left, right]):
      backend = self.backend()
      backend.click("left")
      backend.click("right")

    self.assertEqual(left.request.decode(), clickable.LEFT_CLICK_REQUEST)
    self.assertEqual(right.request.decode(), clickable.RIGHT_CLICK_REQUEST)
    self.assertEqual(
      clickable.LEFT_CLICK_REQUEST,
      'dispatch hl.dsp.send_shortcut({mods = "", key = "mouse:272"})',
    )
    self.assertNotIn("window", clickable.LEFT_CLICK_REQUEST + clickable.RIGHT_CLICK_REQUEST)
    self.assertNotIn("send_key_state", clickable.LEFT_CLICK_REQUEST + clickable.RIGHT_CLICK_REQUEST)

  def test_double_is_two_whole_left_click_dispatches(self):
    first = FakeSocket()
    second = FakeSocket()
    with mock.patch.object(clickable.socket, "socket", side_effect=[first, second]):
      self.backend().click("double")
    self.assertEqual(first.request, clickable.LEFT_CLICK_REQUEST.encode())
    self.assertEqual(second.request, clickable.LEFT_CLICK_REQUEST.encode())

  def test_second_double_failure_has_distinct_fatal_condition(self):
    first = FakeSocket()
    second = FakeSocket(b"rejected")
    with mock.patch.object(clickable.socket, "socket", side_effect=[first, second]):
      with self.assertRaises(clickable.PartialDoubleClick) as caught:
        self.backend().click("double")
    self.assertEqual(caught.exception.code, "partial_double_click")

  def test_timeout_and_response_size_are_bounded(self):
    timed_out = FakeSocket(error=socket.timeout())
    with mock.patch.object(clickable.socket, "socket", return_value=timed_out):
      with self.assertRaises(clickable.ClickAbleError) as caught:
        self.backend().sample_cursor()
    self.assertEqual(caught.exception.code, "hyprland_timeout")

    oversized = FakeSocket(b"x" * (clickable.MAX_IPC_RESPONSE_BYTES + 1))
    with mock.patch.object(clickable.socket, "socket", return_value=oversized):
      with self.assertRaises(clickable.ClickAbleError) as caught:
        self.backend().sample_cursor()
    self.assertEqual(caught.exception.code, "hyprland_response_too_large")

    with mock.patch.object(clickable.socket, "socket") as constructor:
      with self.assertRaises(ValueError):
        self.backend().request("x" * (clickable.MAX_IPC_REQUEST_BYTES + 1))
    constructor.assert_not_called()


class DwellEngineTests(unittest.TestCase):
  EPOCH = 19

  def setUp(self):
    self.backend = RecordingBackend()
    self.engine = clickable.DwellEngine(self.backend, self.EPOCH)

  def move_into_tracking(self):
    self.engine.resume()
    self.backend.position = clickable.Point(124, 200)
    events = self.engine.poll(0.04)
    self.assertEqual(self.engine.state, "tracking")
    return events

  def move_into_dwelling(self, now=0.08):
    self.move_into_tracking()
    self.engine.activity(True, now=0.06)
    events = self.engine.poll(now)
    self.assertEqual(self.engine.state, "dwelling")
    return events

  def commit(self, action="left"):
    if action != "left":
      self.engine.set_action(action)
    self.move_into_dwelling()
    grace = self.engine.poll(1.1)
    self.assertEqual(grace[-1]["type"], "frame")
    self.assertEqual(grace[-1]["progress"], 1)
    self.assertEqual(self.backend.clicks, [])
    return self.engine.poll(1.14)

  def test_ready_contract_and_defaults_are_exact(self):
    self.assertEqual(self.engine.ready_event(), {
      "type": "ready",
      "epoch": self.EPOCH,
      "capabilities": {"cursor": True, "locked": True, "click": True},
      "pollMs": 40,
    })
    self.assertEqual(self.engine.dwell_ms, 900)
    self.assertEqual(self.engine.tolerance_px, 12)

  def test_resume_requires_real_movement_before_any_dwell(self):
    resumed = self.engine.resume()
    for tick in range(1, 40):
      self.engine.poll(tick * 0.04)

    self.assertEqual(resumed[0]["state"], "require_move")
    self.assertEqual(self.engine.state, "require_move")
    self.assertEqual(self.backend.clicks, [])

  def test_movement_then_quiet_starts_backend_owned_dwell(self):
    self.move_into_tracking()
    self.engine.activity(True, now=0.06)
    events = self.engine.poll(0.08)

    self.assertEqual(self.engine.state, "dwelling")
    self.assertEqual(events[-1]["type"], "frame")
    self.assertEqual(events[-1]["progress"], 0)

  def test_click_resamples_checks_lock_then_dispatches(self):
    events = self.commit()

    self.assertEqual(self.backend.calls[-3:][0][0], "cursor")
    self.assertEqual(self.backend.calls[-3:][1][0], "locked")
    self.assertEqual(self.backend.calls[-3:][2], ("click", "left"))
    self.assertEqual([event["type"] for event in events], ["state", "clicked", "state"])
    self.assertEqual(self.engine.state, "rearming")

  def test_full_dwell_has_one_poll_grace_before_commit(self):
    self.move_into_dwelling()

    grace = self.engine.poll(1.1)
    committed = self.engine.poll(1.14)

    self.assertEqual(grace[-1]["progress"], 1)
    self.assertEqual(committed[-2]["type"], "clicked")

  def test_pending_input_wins_after_lock_check_and_before_dispatch(self):
    pending = True
    self.engine.commit_blocked = lambda: pending
    self.move_into_dwelling()
    self.engine.poll(1.1)

    held = self.engine.poll(1.14)
    pending = False
    committed = self.engine.poll(1.18)

    self.assertEqual(held[-1]["progress"], 1)
    self.assertEqual(self.backend.clicks, ["left"])
    self.assertEqual(committed[-2]["type"], "clicked")

  def test_locked_preflight_never_dispatches(self):
    self.backend.locked = True
    events = self.commit()

    self.assertEqual(self.backend.clicks, [])
    self.assertEqual(events[0]["code"], "session_locked")
    self.assertEqual(self.engine.state, "require_move")

  def test_final_cursor_drift_cancels_commit(self):
    self.move_into_dwelling()
    original_sample = self.backend.sample_cursor
    samples = 0

    def moving_sample():
      nonlocal samples
      samples += 1
      if samples == 2:
        self.backend.position = clickable.Point(140, 200)
      return original_sample()

    self.backend.sample_cursor = moving_sample
    self.engine.poll(1.1)
    events = self.engine.poll(1.14)

    self.assertEqual(self.backend.clicks, [])
    self.assertEqual(events[0]["state"], "tracking")

  def test_right_and_double_are_one_shot_only_after_success(self):
    self.engine.set_action("right")
    self.engine.resume()
    self.engine.guard("lock", True)
    self.engine.guard("lock", False)
    self.assertEqual(self.engine.action, "right")
    self.backend.position = clickable.Point(124, 200)
    self.engine.poll(0.04)
    self.engine.activity(True, now=0.06)
    self.engine.poll(0.08)
    self.engine.poll(1.1)
    events = self.engine.poll(1.14)

    clicked = next(event for event in events if event["type"] == "clicked")
    self.assertEqual(clicked["action"], "right")
    self.assertEqual(self.backend.clicks, ["right"])
    self.assertEqual(self.engine.action, "left")

  def test_partial_double_click_is_fatal_and_pauses(self):
    self.backend.click_error = clickable.PartialDoubleClick(
      "partial_double_click",
      "The first click succeeded, but the second was not confirmed.",
    )
    events = self.commit("double")

    error = next(event for event in events if event["type"] == "error")
    self.assertEqual(error["code"], "partial_double_click")
    self.assertTrue(error["fatal"])
    self.assertEqual(self.engine.state, "paused")
    self.assertEqual(self.engine.action, "double")
    self.assertIsNone(self.engine.last_position)

  def test_uncertain_click_pauses_for_a_fresh_movement_baseline(self):
    self.backend.click_error = clickable.ClickAbleError("hyprland_timeout", "timeout")
    events = self.commit("right")

    error = next(event for event in events if event["type"] == "error")
    self.assertEqual(error["code"], "click_unconfirmed")
    self.assertEqual(self.engine.state, "paused")
    self.assertEqual(self.engine.action, "right")
    self.assertIsNone(self.engine.baseline)
    self.assertIsNone(self.engine.last_position)

    resumed = self.engine.resume()
    self.assertEqual(resumed[0]["state"], "require_move")
    self.assertEqual(self.engine.action, "right")

  def test_unchanged_nonpositional_activity_requires_movement_and_quiet(self):
    self.move_into_dwelling()
    events = self.engine.activity(False, now=0.1)

    self.assertEqual(events[0]["reason"], "non_positional_activity")
    self.assertEqual(self.engine.state, "require_move")
    self.assertTrue(self.engine.quiet_required)
    self.assertIsNone(self.engine.candidate)

  def test_pointer_activity_does_not_livelock_require_move(self):
    self.engine.resume()
    self.backend.position = clickable.Point(124, 200)

    events = self.engine.activity(False, now=0.04)
    self.engine.activity(True, now=0.1)

    self.assertEqual(events[0]["reason"], "pointer_activity")
    self.assertEqual(self.engine.state, "tracking")
    self.assertFalse(self.engine.quiet_required)

  def test_tolerated_pointer_activity_preserves_dwell_but_waits_for_quiet(self):
    self.move_into_dwelling()
    started = self.engine.dwell_started
    self.backend.position = clickable.Point(128, 200)

    activity = self.engine.activity(False, now=0.5)
    held = self.engine.poll(1.1)

    self.assertEqual(activity[0]["reason"], "pointer_activity")
    self.assertEqual(self.engine.state, "dwelling")
    self.assertEqual(self.engine.dwell_started, started)
    self.assertFalse(self.engine.commit_pending)
    self.assertEqual(held[-1]["progress"], 1)
    self.assertEqual(self.backend.clicks, [])

    self.engine.activity(True, now=1.11)
    grace = self.engine.poll(1.12)
    committed = self.engine.poll(1.16)

    self.assertEqual(grace[-1]["progress"], 1)
    self.assertEqual(committed[-2]["type"], "clicked")

  def test_activity_after_full_ring_requires_a_new_quiet_commit_grace(self):
    self.move_into_dwelling()
    self.engine.poll(1.1)
    self.assertTrue(self.engine.commit_pending)
    self.backend.position = clickable.Point(128, 200)

    self.engine.activity(False, now=1.11)
    held = self.engine.poll(1.14)

    self.assertFalse(self.engine.commit_pending)
    self.assertEqual(held[-1]["progress"], 1)
    self.assertEqual(self.backend.clicks, [])

    self.engine.activity(True, now=1.15)
    grace = self.engine.poll(1.18)
    committed = self.engine.poll(1.22)

    self.assertEqual(grace[-1]["progress"], 1)
    self.assertEqual(committed[-2]["type"], "clicked")

  def test_unblock_resamples_and_requires_movement_again(self):
    self.move_into_dwelling()
    self.engine.guard("lock", True)
    self.backend.position = clickable.Point(500, 500)
    events = self.engine.guard("lock", False)

    self.assertEqual(events[0]["state"], "require_move")
    self.assertEqual(self.engine.baseline, clickable.Point(500, 500))

  def test_three_consecutive_poll_failures_fault(self):
    self.engine.resume()
    self.backend.sample_error = clickable.ClickAbleError("hyprland_timeout", "timeout")
    first = self.engine.poll(0.04)
    second = self.engine.poll(0.08)
    third = self.engine.poll(0.12)

    self.assertEqual(first[0]["code"], "cursor_retry")
    self.assertEqual(second[0]["code"], "cursor_retry")
    self.assertEqual(third[0]["code"], "cursor_fault")
    self.assertTrue(third[0]["fatal"])
    self.assertEqual(self.engine.state, "faulted")

  def test_failed_fresh_baseline_pauses_without_retaining_coordinates(self):
    self.move_into_tracking()
    self.backend.sample_error = clickable.ClickAbleError("hyprland_timeout", "timeout")

    events = self.engine.configure(1200, 20)

    self.assertEqual(events[-1]["state"], "paused")
    self.assertIsNone(self.engine.baseline)
    self.assertIsNone(self.engine.last_position)
    self.assertIsNone(self.engine.candidate)

  def test_every_engine_event_has_current_epoch_and_bounded_error(self):
    events = self.engine.resume() + self.engine.pause("user")
    events.append(self.engine.error_event("test", "x" * 500))
    self.assertTrue(all(event["epoch"] == self.EPOCH for event in events))
    self.assertLessEqual(len(events[-1]["message"]), 240)

  def test_pause_and_stop_discard_all_pointer_state(self):
    self.move_into_dwelling()
    self.engine.pause("user")
    self.assertIsNone(self.engine.baseline)
    self.assertIsNone(self.engine.last_position)
    self.assertIsNone(self.engine.candidate)

    self.engine.resume()
    self.engine.stop()
    self.assertIsNone(self.engine.baseline)
    self.assertIsNone(self.engine.last_position)
    self.assertIsNone(self.engine.candidate)

  def test_demo_script_moves_dwells_and_clicks_once_without_hyprland(self):
    backend = clickable.DemoBackend(40, 80)
    engine = clickable.DwellEngine(backend, self.EPOCH)
    engine.configure(600, 12)
    engine.resume()

    events = []
    for tick in range(1, 30):
      events.extend(engine.poll(tick * 0.04))

    clicked = [event for event in events if event["type"] == "clicked"]
    self.assertEqual(len(clicked), 1)
    self.assertEqual(backend.clicks, ["left"])
    self.assertEqual(engine.state, "rearming")
    self.assertEqual(engine.backend.position, clickable.Point(64, 80))


class JSONLProtocolTests(unittest.TestCase):
  EPOCH = 7

  def line(self, value):
    return json.dumps(value, separators=(",", ":")).encode() + b"\n"

  def test_accepts_exact_documented_commands(self):
    commands = [
      {"type": "configure", "epoch": 7, "dwellMs": 600, "tolerancePx": 6},
      {"type": "resume", "epoch": 7},
      {"type": "pause", "epoch": 7, "reason": "user"},
      {"type": "guard", "epoch": 7, "name": "lock", "blocked": True},
      {"type": "activity", "epoch": 7, "idle": False},
      {"type": "set_action", "epoch": 7, "action": "double"},
      {"type": "stop", "epoch": 7},
    ]
    for command in commands:
      with self.subTest(command=command):
        self.assertEqual(clickable.parse_command_line(self.line(command)), command)

  def test_requires_epoch_exact_fields_types_and_supported_presets(self):
    invalid = [
      {"type": "resume"},
      {"type": "resume", "epoch": True},
      {"type": "resume", "epoch": 7, "extra": 1},
      {"type": "configure", "epoch": 7, "dwellMs": 700, "tolerancePx": 6},
      {"type": "configure", "epoch": 7, "dwellMs": 900, "tolerancePx": 10},
      {"type": "pause", "epoch": 7, "reason": "user supplied metadata"},
      {"type": "guard", "epoch": 7, "name": "lock", "blocked": 1},
      {"type": "activity", "epoch": 7, "idle": 1},
      {"type": "set_action", "epoch": 7, "action": "drag"},
      {"type": "demo_move", "epoch": 7, "x": 1, "y": 2},
    ]
    for command in invalid:
      with self.subTest(command=command):
        with self.assertRaises(clickable.ProtocolError):
          clickable.parse_command_line(self.line(command))

  def test_malformed_duplicate_unterminated_and_oversized_lines_are_fatal_errors(self):
    invalid = [
      b'{"type":"resume","epoch":7}',
      b'[]\n',
      b'{"type":"resume","epoch":7,"epoch":8}\n',
      b'\xff\n',
      b"[" * 1500 + b"0" + b"]" * 1500 + b"\n",
      b"x" * (clickable.MAX_INPUT_LINE_BYTES + 1) + b"\n",
    ]
    for line in invalid:
      with self.subTest(line=line[:40]):
        with self.assertRaises(clickable.ProtocolError):
          clickable.parse_command_line(line)

  def test_command_reader_enforces_the_bounded_rate(self):
    read_descriptor, write_descriptor = os.pipe()
    try:
      os.write(write_descriptor, self.line({"type": "resume", "epoch": 7}) * 121)
      reader = clickable.CommandReader(read_descriptor)
      with self.assertRaises(clickable.ProtocolError) as caught:
        reader.next_line(0.1, lambda: False)
      self.assertEqual(caught.exception.code, "rate_limited")
    finally:
      os.close(read_descriptor)
      os.close(write_descriptor)

  def test_broken_stdout_cancels_the_protocol(self):
    stream = mock.Mock()
    stream.write.side_effect = BrokenPipeError()
    with self.assertRaises(clickable.Cancelled):
      clickable.emit(stream, {"type": "ready", "epoch": 7})


class HelperIntegrationTests(unittest.TestCase):
  EPOCH = 41

  def start_helper(self):
    return subprocess.Popen(
      [
        sys.executable,
        str(LIB / "clickable.py"),
        "--launcher-pid", str(os.getpid()),
        "--epoch", str(self.EPOCH),
        "--demo", "--demo-x", "40", "--demo-y", "80",
      ],
      stdin=subprocess.PIPE,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
    )

  def start_launcher(self):
    return subprocess.Popen(
      [
        str(ROOT / "bin" / "clickable"),
        "--shell-pid", str(os.getpid()),
        "--epoch", str(self.EPOCH),
        "--demo", "--demo-x", "40", "--demo-y", "80",
      ],
      stdin=subprocess.PIPE,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
    )

  def event(self, process):
    line = process.stdout.readline()
    if not line:
      self.fail(process.stderr.read().decode("utf-8", "replace"))
    self.assertLessEqual(len(line), clickable.MAX_OUTPUT_LINE_BYTES)
    event = json.loads(line)
    self.assertEqual(event["epoch"], self.EPOCH)
    return event

  def send(self, process, command):
    process.stdin.write(json.dumps(command, separators=(",", ":")).encode() + b"\n")
    process.stdin.flush()
    return self.event(process)

  def close(self, process):
    if process.poll() is None:
      try:
        process.stdin.close()
      except OSError:
        pass
      try:
        process.wait(timeout=2)
      except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=2)
    for stream in (process.stdin, process.stdout, process.stderr):
      if stream is not None and not stream.closed:
        stream.close()

  def test_demo_starts_paused_and_requires_epoch_and_explicit_resume(self):
    process = self.start_helper()
    try:
      ready = self.event(process)
      configured = self.send(process, {
        "type": "configure", "epoch": self.EPOCH, "dwellMs": 900, "tolerancePx": 12,
      })
      resumed = self.send(process, {"type": "resume", "epoch": self.EPOCH})
      paused = self.send(process, {"type": "pause", "epoch": self.EPOCH, "reason": "user"})
      stopped = self.send(process, {"type": "stop", "epoch": self.EPOCH})
      process.wait(timeout=2)
    finally:
      self.close(process)

    self.assertEqual(ready["pollMs"], 40)
    self.assertEqual(configured["state"], "paused")
    self.assertEqual(resumed["state"], "require_move")
    self.assertEqual(paused["state"], "paused")
    self.assertEqual(stopped["state"], "stopped")
    self.assertEqual(process.returncode, 0)

  def test_mismatched_epoch_faults_and_exits(self):
    process = self.start_helper()
    try:
      self.event(process)
      error = self.send(process, {"type": "resume", "epoch": self.EPOCH + 1})
      state = self.event(process)
      process.wait(timeout=2)
    finally:
      self.close(process)

    self.assertEqual(error["code"], "epoch_mismatch")
    self.assertTrue(error["fatal"])
    self.assertEqual(state["state"], "faulted")
    self.assertEqual(process.returncode, 2)

  def test_demo_exercises_real_countdown_then_rearms_without_dispatch(self):
    process = self.start_helper()
    try:
      self.event(process)
      self.send(process, {
        "type": "configure", "epoch": self.EPOCH, "dwellMs": 600, "tolerancePx": 12,
      })
      self.send(process, {"type": "resume", "epoch": self.EPOCH})

      clicked = None
      deadline = time.monotonic() + 2
      while time.monotonic() < deadline and clicked is None:
        event = self.event(process)
        if event["type"] == "clicked":
          clicked = event
      self.assertIsNotNone(clicked)
      self.assertEqual(clicked["action"], "left")
      self.assertEqual((clicked["x"], clicked["y"]), (64, 80))

      process.stdin.write(json.dumps({
        "type": "stop", "epoch": self.EPOCH,
      }, separators=(",", ":")).encode() + b"\n")
      process.stdin.flush()
      stopped = None
      while stopped is None:
        event = self.event(process)
        if event["type"] == "state" and event["state"] == "stopped":
          stopped = event
      process.wait(timeout=2)
    finally:
      self.close(process)

    self.assertEqual(process.returncode, 0)

  def test_malformed_json_is_fatal_and_bounded(self):
    process = self.start_helper()
    try:
      self.event(process)
      process.stdin.write(b"not json\n")
      process.stdin.flush()
      error = self.event(process)
      process.wait(timeout=2)
    finally:
      self.close(process)

    self.assertEqual(error["code"], "invalid_json")
    self.assertTrue(error["fatal"])
    self.assertEqual(process.returncode, 2)

  def test_eof_stops_cleanly(self):
    process = self.start_helper()
    try:
      self.event(process)
      process.stdin.close()
      stopped = self.event(process)
      process.wait(timeout=2)
    finally:
      self.close(process)
    self.assertEqual(stopped["state"], "stopped")
    self.assertEqual(stopped["reason"], "stdin_eof")

  def test_signal_cancels_launcher_and_worker_and_emits_stopped(self):
    process = self.start_launcher()
    try:
      self.event(process)
      process.send_signal(signal.SIGTERM)
      stopped = self.event(process)
      process.wait(timeout=2)
    finally:
      self.close(process)

    self.assertEqual(stopped["state"], "stopped")
    self.assertEqual(stopped["reason"], "signal")
    self.assertEqual(process.returncode, 130)

  def test_launcher_rejects_invalid_shell_parent(self):
    result = subprocess.run(
      [str(ROOT / "bin" / "clickable"), "--shell-pid", "01", "--epoch", "1", "--demo"],
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      timeout=2,
    )
    self.assertEqual(result.returncode, 2)
    self.assertIn(b"invalid shell process ID", result.stderr)

  def test_worker_rejects_unexpected_parent_on_linux(self):
    if not sys.platform.startswith("linux"):
      self.skipTest("requires Linux parent-death signals")
    with mock.patch.object(clickable.os, "getppid", return_value=222):
      with self.assertRaises(clickable.Cancelled):
        clickable.arm_parent_death_signal(expected_parent=333)

  def test_linux_shell_death_cleans_launcher_and_worker(self):
    if not sys.platform.startswith("linux"):
      self.skipTest("requires Linux parent-death signals and procfs")

    shell_script = (
      "import os,subprocess,sys,time;"
      "launcher=subprocess.Popen([sys.argv[1],'--shell-pid',str(os.getpid()),"
      "'--epoch','1','--demo'],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,"
      "stderr=subprocess.DEVNULL);"
      "print(launcher.pid,flush=True);time.sleep(30)"
    )
    shell = subprocess.Popen(
      [sys.executable, "-c", shell_script, str(ROOT / "bin" / "clickable")],
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      text=True,
    )
    launcher_pid = None
    worker_pid = None
    try:
      launcher_pid = int(shell.stdout.readline().strip())
      children_path = Path(f"/proc/{launcher_pid}/task/{launcher_pid}/children")
      deadline = time.monotonic() + 2
      while time.monotonic() < deadline and worker_pid is None:
        try:
          children = children_path.read_text(encoding="ascii").split()
        except FileNotFoundError:
          children = []
        if children:
          worker_pid = int(children[0])
          break
        time.sleep(0.02)
      self.assertIsNotNone(worker_pid, "launcher did not create its worker")

      shell.kill()
      shell.wait(timeout=2)
      deadline = time.monotonic() + 3
      while time.monotonic() < deadline:
        if not Path(f"/proc/{launcher_pid}").exists() and not Path(f"/proc/{worker_pid}").exists():
          break
        time.sleep(0.02)
      self.assertFalse(Path(f"/proc/{launcher_pid}").exists())
      self.assertFalse(Path(f"/proc/{worker_pid}").exists())
    finally:
      if shell.poll() is None:
        shell.kill()
        shell.wait(timeout=2)
      for pid in (worker_pid, launcher_pid):
        if pid is not None and Path(f"/proc/{pid}").exists():
          try:
            os.kill(pid, signal.SIGKILL)
          except ProcessLookupError:
            pass


if __name__ == "__main__":
  unittest.main()
