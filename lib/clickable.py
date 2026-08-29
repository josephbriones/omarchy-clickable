#!/usr/bin/env python3

import argparse
from collections import deque
import ctypes
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import sys
import time


POLL_MS = 40
POLL_SECONDS = POLL_MS / 1000

MAX_INPUT_LINE_BYTES = 4096
MAX_OUTPUT_LINE_BYTES = 4096
MAX_IPC_REQUEST_BYTES = 512
MAX_IPC_RESPONSE_BYTES = 16 * 1024
MAX_COORDINATE = 1_000_000
MAX_COMMANDS_PER_SECOND = 120
MAX_ERROR_MESSAGE = 240
MAX_ID = 2_147_483_647
IPC_TIMEOUT = 0.5

DWELL_VALUES = {600, 900, 1200, 1600}
TOLERANCE_VALUES = {6, 12, 20}
ACTION_VALUES = {"left", "right", "double"}
DEFAULT_DWELL_MS = 900
DEFAULT_TOLERANCE_PX = 12

LEFT_CLICK_REQUEST = 'dispatch hl.dsp.send_shortcut({mods = "", key = "mouse:272"})'
RIGHT_CLICK_REQUEST = 'dispatch hl.dsp.send_shortcut({mods = "", key = "mouse:273"})'

INSTANCE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,160}$", re.ASCII)
LABEL_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,47}$", re.ASCII)


class ClickAbleError(Exception):
  def __init__(self, code, message):
    super().__init__(message)
    self.code = code
    self.message = message[:MAX_ERROR_MESSAGE]


class ProtocolError(ClickAbleError):
  pass


class PartialDoubleClick(ClickAbleError):
  pass


class Cancelled(Exception):
  pass


@dataclass(frozen=True)
class Point:
  x: int
  y: int

  def distance_squared(self, other):
    return (self.x - other.x) ** 2 + (self.y - other.y) ** 2


def _unique_object(pairs):
  value = {}
  for key, field in pairs:
    if key in value:
      raise ValueError(f"duplicate field: {key}")
    value[key] = field
  return value


def _reject_constant(value):
  raise ValueError(f"invalid JSON number: {value}")


def _json_object(data, *, code, message):
  try:
    value = json.loads(
      data.decode("utf-8", "strict"),
      object_pairs_hook=_unique_object,
      parse_constant=_reject_constant,
    )
  except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
    raise ClickAbleError(code, message) from error
  if not isinstance(value, dict):
    raise ClickAbleError(code, message)
  return value


def _is_int(value):
  return isinstance(value, int) and not isinstance(value, bool)


def _valid_coordinate(value):
  return _is_int(value) and -MAX_COORDINATE <= value <= MAX_COORDINATE


def parse_cursor_response(response):
  if not response or len(response) > MAX_IPC_RESPONSE_BYTES:
    raise ClickAbleError("invalid_cursor_response", "Hyprland returned an invalid cursor position.")
  value = _json_object(
    response,
    code="invalid_cursor_response",
    message="Hyprland returned an invalid cursor position.",
  )
  if set(value) != {"x", "y"} or not _valid_coordinate(value["x"]) or not _valid_coordinate(value["y"]):
    raise ClickAbleError("invalid_cursor_response", "Hyprland returned an invalid cursor position.")
  return Point(value["x"], value["y"])


def parse_locked_response(response):
  if not response or len(response) > MAX_IPC_RESPONSE_BYTES:
    raise ClickAbleError("invalid_lock_response", "Hyprland returned an invalid lock state.")
  value = _json_object(
    response,
    code="invalid_lock_response",
    message="Hyprland returned an invalid lock state.",
  )
  if set(value) != {"locked"} or not isinstance(value["locked"], bool):
    raise ClickAbleError("invalid_lock_response", "Hyprland returned an invalid lock state.")
  return value["locked"]


def socket_path_from_environment(environment=None):
  environment = os.environ if environment is None else environment
  runtime_directory = environment.get("XDG_RUNTIME_DIR", "")
  instance = environment.get("HYPRLAND_INSTANCE_SIGNATURE", "")
  if (
    not runtime_directory
    or "\x00" in runtime_directory
    or len(runtime_directory) > 2048
    or not Path(runtime_directory).is_absolute()
    or not INSTANCE_PATTERN.fullmatch(instance)
    or instance in {".", ".."}
  ):
    raise ClickAbleError("hyprland_unavailable", "ClickAble could not find this Hyprland session.")
  return Path(runtime_directory) / "hypr" / instance / ".socket.sock"


class HyprlandIPC:
  def __init__(self, socket_path=None, *, timeout=IPC_TIMEOUT, stop_requested=lambda: False):
    self.socket_path = Path(socket_path) if socket_path is not None else socket_path_from_environment()
    if not self.socket_path.is_absolute():
      raise ClickAbleError("hyprland_unavailable", "ClickAble requires an absolute Hyprland socket path.")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0.01 <= timeout <= 5.0:
      raise ValueError("timeout must be between 0.01 and 5 seconds")
    self.timeout = float(timeout)
    self.stop_requested = stop_requested

  def request(self, command):
    try:
      payload = command.encode("ascii", "strict")
    except (AttributeError, UnicodeEncodeError) as error:
      raise ValueError("Hyprland requests must be ASCII text") from error
    if not payload or len(payload) > MAX_IPC_REQUEST_BYTES or b"\x00" in payload:
      raise ValueError("invalid Hyprland request")

    deadline = time.monotonic() + self.timeout

    def remaining_timeout():
      if self.stop_requested():
        raise Cancelled()
      remaining = deadline - time.monotonic()
      if remaining <= 0:
        raise socket.timeout("Hyprland request deadline expired")
      return remaining

    connection = None
    try:
      connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
      connection.settimeout(remaining_timeout())
      connection.connect(os.fspath(self.socket_path))
      connection.settimeout(remaining_timeout())
      connection.sendall(payload)
      response = bytearray()
      while True:
        connection.settimeout(remaining_timeout())
        chunk = connection.recv(min(4096, MAX_IPC_RESPONSE_BYTES + 1 - len(response)))
        if self.stop_requested():
          raise Cancelled()
        if time.monotonic() > deadline:
          raise socket.timeout("Hyprland request deadline expired")
        if not chunk:
          break
        response.extend(chunk)
        if len(response) > MAX_IPC_RESPONSE_BYTES:
          raise ClickAbleError(
            "hyprland_response_too_large",
            "Hyprland returned more data than ClickAble accepts.",
          )
    except socket.timeout as error:
      raise ClickAbleError("hyprland_timeout", "Hyprland did not answer ClickAble in time.") from error
    except (ConnectionError, FileNotFoundError, OSError) as error:
      raise ClickAbleError("hyprland_unavailable", "ClickAble could not reach this Hyprland session.") from error
    finally:
      if connection is not None:
        connection.close()

    if not response:
      raise ClickAbleError("hyprland_unavailable", "Hyprland closed the request without answering.")
    return bytes(response)

  def sample_cursor(self):
    return parse_cursor_response(self.request("j/cursorpos"))

  def is_locked(self):
    return parse_locked_response(self.request("j/locked"))

  def _dispatch(self, request):
    if self.stop_requested():
      raise Cancelled()
    response = self.request(request)
    try:
      result = response.decode("utf-8", "strict").strip()
    except UnicodeDecodeError as error:
      raise ClickAbleError("click_rejected", "Hyprland rejected ClickAble's click request.") from error
    if result != "ok":
      raise ClickAbleError("click_rejected", "Hyprland rejected ClickAble's click request.")

  def click(self, action):
    if action == "left":
      self._dispatch(LEFT_CLICK_REQUEST)
      return
    if action == "right":
      self._dispatch(RIGHT_CLICK_REQUEST)
      return
    if action != "double":
      raise ValueError("unknown click action")
    self._dispatch(LEFT_CLICK_REQUEST)
    try:
      self._dispatch(LEFT_CLICK_REQUEST)
    except (Cancelled, ClickAbleError) as error:
      raise PartialDoubleClick(
        "partial_double_click",
        "The first click succeeded, but Hyprland did not confirm the second click.",
      ) from error

class DemoBackend:
  def __init__(self, x=0, y=0):
    if not _valid_coordinate(x) or not _valid_coordinate(y):
      raise ValueError("invalid demo cursor position")
    self.position = Point(x, y)
    self.locked = False
    self.clicks = []
    self.script_ticks = 0
    self.script_distance = 0
    self.script_active = False
    self.script_completed = False

  def sample_cursor(self):
    if self.script_active:
      self.script_ticks += 1
      if self.script_ticks >= 2:
        direction = -1 if self.position.x + self.script_distance > MAX_COORDINATE else 1
        self.position = Point(self.position.x + direction * self.script_distance, self.position.y)
        self.script_active = False
    return self.position

  def is_locked(self):
    return self.locked

  def click(self, action):
    if action not in ACTION_VALUES:
      raise ValueError("unknown click action")
    self.clicks.append(action)
    self.script_completed = True

  def begin_script(self, distance):
    if self.script_completed:
      return
    self.script_ticks = 0
    self.script_distance = distance
    self.script_active = True

def _event(event_type, epoch, **fields):
  return {"type": event_type, "epoch": epoch, **fields}


class DwellEngine:
  def __init__(self, backend, epoch, *, clock=time.monotonic,
               stop_requested=lambda: False, commit_blocked=lambda: False):
    self.backend = backend
    self.epoch = epoch
    self.clock = clock
    self.stop_requested = stop_requested
    self.commit_blocked = commit_blocked
    self.state = "paused"
    self.reason = "startup"
    self.action = "left"
    self.dwell_ms = DEFAULT_DWELL_MS
    self.tolerance_px = DEFAULT_TOLERANCE_PX
    self.rearm_px = max(16, 2 * self.tolerance_px)
    self.enabled = False
    self.blockers = set()
    self.input_idle = False
    self.quiet_required = True
    self.baseline = None
    self.last_position = None
    self.candidate = None
    self.dwell_started = None
    self.commit_pending = False
    self.consecutive_poll_failures = 0

  @property
  def wants_poll(self):
    return self.enabled and not self.blockers and self.state not in {
      "paused", "suspended", "faulted", "stopped",
    }

  def ready_event(self):
    return _event(
      "ready",
      self.epoch,
      capabilities={"cursor": True, "locked": True, "click": True},
      pollMs=POLL_MS,
    )

  def state_event(self, reason=None):
    if reason is not None:
      self.reason = reason
    return _event(
      "state",
      self.epoch,
      state=self.state,
      reason=self.reason,
      action=self.action,
    )

  def error_event(self, code, message, *, fatal=False):
    return _event(
      "error",
      self.epoch,
      code=code,
      message=message[:MAX_ERROR_MESSAGE],
      fatal=bool(fatal),
    )

  def frame_event(self, point, progress):
    return _event(
      "frame",
      self.epoch,
      state=self.state,
      x=point.x,
      y=point.y,
      progress=max(0.0, min(1.0, float(progress))),
      action=self.action,
    )

  def _clear_dwell(self):
    self.candidate = None
    self.dwell_started = None
    self.commit_pending = False

  def _fresh_baseline(self, reason):
    try:
      point = self.backend.sample_cursor()
    except ClickAbleError as error:
      self.enabled = False
      self.state = "paused"
      self._clear_dwell()
      self.baseline = None
      self.last_position = None
      return [
        self.error_event("cursor_unavailable", "ClickAble could not sample the pointer."),
        self.state_event(error.code),
      ]
    self.consecutive_poll_failures = 0
    self.baseline = point
    self.last_position = point
    self._clear_dwell()
    if isinstance(self.backend, DemoBackend):
      self.backend.begin_script(self.rearm_px)
      self.input_idle = True
      self.quiet_required = False
    else:
      self.input_idle = False
      self.quiet_required = True
    self.state = "require_move"
    return [self.state_event(reason)]

  def configure(self, dwell_ms, tolerance_px):
    self.dwell_ms = dwell_ms
    self.tolerance_px = tolerance_px
    self.rearm_px = max(16, 2 * tolerance_px)
    if self.enabled and not self.blockers:
      return self._fresh_baseline("configured")
    return [self.state_event("configured")]

  def resume(self):
    self.enabled = True
    self.consecutive_poll_failures = 0
    if self.blockers:
      self.state = "suspended"
      self._clear_dwell()
      return [self.state_event(sorted(self.blockers)[0])]
    return self._fresh_baseline("resumed")

  def pause(self, reason):
    self.enabled = False
    self.state = "paused"
    self._clear_dwell()
    self.baseline = None
    self.last_position = None
    return [self.state_event(reason)]

  def guard(self, name, blocked):
    if blocked:
      self.blockers.add(name)
      self._clear_dwell()
      if self.enabled:
        self.state = "suspended"
      return [self.state_event(name)]

    self.blockers.discard(name)
    if self.blockers:
      if self.enabled:
        self.state = "suspended"
      return [self.state_event(sorted(self.blockers)[0])]
    if self.enabled:
      return self._fresh_baseline(f"{name}_cleared")
    self.state = "paused"
    return [self.state_event(f"{name}_cleared")]

  def set_action(self, action):
    self.action = action
    return [self.state_event("action_selected")]

  def epoch_fault(self):
    self.enabled = False
    self.state = "faulted"
    self._clear_dwell()
    self.baseline = None
    self.last_position = None
    return [
      self.error_event(
        "epoch_mismatch",
        "ClickAble rejected a command from another session.",
        fatal=True,
      ),
      self.state_event("epoch_mismatch"),
    ]

  def _poll_failure(self, error):
    self.consecutive_poll_failures += 1
    self._clear_dwell()
    self.baseline = None
    self.last_position = None
    self.input_idle = False
    self.quiet_required = True
    if self.consecutive_poll_failures >= 3:
      self.enabled = False
      self.state = "faulted"
      return [
        self.error_event("cursor_fault", "ClickAble lost the Hyprland pointer service.", fatal=True),
        self.state_event(error.code),
      ]
    self.state = "require_move"
    return [
      self.error_event("cursor_retry", "ClickAble could not sample the pointer; no click was sent."),
      self.state_event(error.code),
    ]

  def activity(self, idle, now=None):
    now = self.clock() if now is None else now
    if isinstance(self.backend, DemoBackend):
      self.input_idle = True
      self.quiet_required = False
      return [self.state_event("demo_quiet")]
    self.input_idle = idle
    if idle:
      self.quiet_required = False
      return [self.state_event("input_quiet")]
    if not self.wants_poll:
      return [self.state_event("input_active")]

    previous = self.last_position
    try:
      point = self.backend.sample_cursor()
    except ClickAbleError as error:
      return self._poll_failure(error)
    self.consecutive_poll_failures = 0
    if previous is not None and point == previous:
      self.baseline = point
      self.last_position = point
      self._clear_dwell()
      self.quiet_required = True
      self.state = "require_move"
      return [self.state_event("non_positional_activity")]
    self._observe(point, now, emit_frame=False)
    return [self.state_event("pointer_activity")]

  def poll(self, now=None):
    if not self.wants_poll:
      return []
    now = self.clock() if now is None else now
    try:
      point = self.backend.sample_cursor()
    except ClickAbleError as error:
      return self._poll_failure(error)
    self.consecutive_poll_failures = 0
    return self._observe(point, now, emit_frame=True)

  def _observe(self, point, now, *, emit_frame):
    events = []
    self.last_position = point
    if self.baseline is None:
      self.baseline = point
      self.state = "require_move"
      self.reason = "baseline"
      if emit_frame:
        events.append(self.frame_event(point, 0))
      return events

    if self.state in {"require_move", "rearming"}:
      if point.distance_squared(self.baseline) >= self.rearm_px ** 2:
        self.candidate = point
        self.dwell_started = None
        self.state = "tracking"
        self.reason = "moved"
        events.append(self.state_event())
      if emit_frame:
        events.append(self.frame_event(point, 0))
      return events

    if self.state == "tracking":
      if self.candidate is None or point.distance_squared(self.candidate) > self.tolerance_px ** 2:
        self.candidate = point
        self.dwell_started = None
        self.commit_pending = False
      elif self.input_idle and not self.quiet_required:
        self.dwell_started = now
        self.state = "dwelling"
        self.reason = "dwelling"
        events.append(self.state_event())
      if emit_frame:
        events.append(self.frame_event(point, 0))
      return events

    if self.state != "dwelling":
      if emit_frame:
        events.append(self.frame_event(point, 0))
      return events

    if point.distance_squared(self.candidate) > self.tolerance_px ** 2:
      self.candidate = point
      self.dwell_started = None
      self.commit_pending = False
      self.state = "tracking"
      self.reason = "pointer_moved"
      events.append(self.state_event())
      if emit_frame:
        events.append(self.frame_event(point, 0))
      return events
    if self.quiet_required:
      self.dwell_started = None
      self.commit_pending = False
      self.state = "tracking"
      self.reason = "input_active"
      events.append(self.state_event())
      if emit_frame:
        events.append(self.frame_event(point, 0))
      return events

    progress = (now - self.dwell_started) / (self.dwell_ms / 1000)
    if not self.input_idle:
      # Positional activity inside the tolerance is not a keyboard/button
      # cancellation. Preserve its dwell, but wait for a quiet interval before
      # beginning the commit grace period.
      self.commit_pending = False
      if emit_frame:
        events.append(self.frame_event(point, min(progress, 1)))
      return events
    if progress < 1:
      if emit_frame:
        events.append(self.frame_event(point, progress))
      return events
    if not self.commit_pending:
      # Hold a full ring for one poll. This gives guard/activity/stop already
      # crossing the stdin pipe a deterministic chance to win before commit.
      self.commit_pending = True
      if emit_frame:
        events.append(self.frame_event(point, 1))
      return events
    return self._commit()

  def _commit(self):
    if self.stop_requested() or self.commit_blocked():
      return [self.frame_event(self.last_position, 1)]
    try:
      point = self.backend.sample_cursor()
    except ClickAbleError as error:
      return self._poll_failure(error)
    if point.distance_squared(self.candidate) > self.tolerance_px ** 2:
      self.last_position = point
      self.candidate = point
      self.dwell_started = None
      self.commit_pending = False
      self.state = "tracking"
      return [self.state_event("pointer_moved"), self.frame_event(point, 0)]

    try:
      locked = self.backend.is_locked()
    except ClickAbleError as error:
      events = [self.error_event(error.code, "ClickAble could not verify the session lock; no click was requested.")]
      events.extend(self.pause("lock_check_failed"))
      return events
    if locked:
      self.baseline = point
      self.last_position = point
      self._clear_dwell()
      self.quiet_required = True
      self.state = "require_move"
      return [
        self.error_event("session_locked", "ClickAble will not click while the session is locked."),
        self.state_event("session_locked"),
      ]

    # Check again after the synchronous safety queries. A scene/activity line
    # that arrived during either request must be handled before dispatch.
    if self.stop_requested() or self.commit_blocked():
      return [self.frame_event(point, 1)]

    performed_action = self.action
    self.state = "committing"
    events = [self.state_event("committing")]
    try:
      self.backend.click(performed_action)
    except PartialDoubleClick as error:
      self.enabled = False
      self.state = "paused"
      self._clear_dwell()
      self.baseline = None
      self.last_position = None
      events.extend([
        self.error_event("partial_double_click", error.message, fatal=True),
        self.state_event("partial_double_click"),
      ])
      return events
    except ClickAbleError as error:
      self.enabled = False
      self.state = "paused"
      self._clear_dwell()
      self.baseline = None
      self.last_position = None
      events.extend([
        self.error_event("click_unconfirmed", "ClickAble could not confirm the click; it has paused."),
        self.state_event(error.code),
      ])
      return events

    events.append(_event("clicked", self.epoch, action=performed_action, x=point.x, y=point.y))
    self.action = "left"
    self.baseline = point
    self.last_position = point
    self._clear_dwell()
    self.input_idle = False
    self.quiet_required = True
    self.state = "rearming"
    events.append(self.state_event("clicked"))
    return events

  def stop(self, reason="requested"):
    self.enabled = False
    self.state = "stopped"
    self._clear_dwell()
    self.baseline = None
    self.last_position = None
    return [self.state_event(reason)]


COMMAND_FIELDS = {
  "configure": {"type", "epoch", "dwellMs", "tolerancePx"},
  "resume": {"type", "epoch"},
  "pause": {"type", "epoch", "reason"},
  "guard": {"type", "epoch", "name", "blocked"},
  "activity": {"type", "epoch", "idle"},
  "set_action": {"type", "epoch", "action"},
  "stop": {"type", "epoch"},
}


def parse_command_line(line):
  if len(line) > MAX_INPUT_LINE_BYTES:
    raise ProtocolError("input_too_large", "ClickAble received an oversized command.")
  if not line.endswith(b"\n") or b"\n" in line[:-1]:
    raise ProtocolError("invalid_jsonl", "ClickAble requires one JSON object per line.")
  try:
    command = _json_object(
      line[:-1],
      code="invalid_json",
      message="ClickAble received malformed JSON.",
    )
  except ClickAbleError as error:
    raise ProtocolError(error.code, error.message) from error

  command_type = command.get("type")
  if not isinstance(command_type, str) or command_type not in COMMAND_FIELDS:
    raise ProtocolError("invalid_command", "ClickAble received an unknown command.")
  if set(command) != COMMAND_FIELDS[command_type]:
    raise ProtocolError("invalid_command", "ClickAble received invalid command fields.")
  if not _is_int(command["epoch"]) or not 1 <= command["epoch"] <= MAX_ID:
    raise ProtocolError("invalid_command", "ClickAble received an invalid session epoch.")

  if command_type == "configure":
    if command["dwellMs"] not in DWELL_VALUES or command["tolerancePx"] not in TOLERANCE_VALUES:
      raise ProtocolError("invalid_command", "ClickAble received unsupported dwell settings.")
  elif command_type == "pause":
    if not isinstance(command["reason"], str) or not LABEL_PATTERN.fullmatch(command["reason"]):
      raise ProtocolError("invalid_command", "ClickAble received an invalid pause reason.")
  elif command_type == "guard":
    if not isinstance(command["name"], str) or not LABEL_PATTERN.fullmatch(command["name"]):
      raise ProtocolError("invalid_command", "ClickAble received an invalid guard name.")
    if not isinstance(command["blocked"], bool):
      raise ProtocolError("invalid_command", "ClickAble received an invalid guard state.")
  elif command_type == "activity":
    if not isinstance(command["idle"], bool):
      raise ProtocolError("invalid_command", "ClickAble received an invalid idle state.")
  elif command_type == "set_action":
    if command["action"] not in ACTION_VALUES:
      raise ProtocolError("invalid_command", "ClickAble received an invalid click action.")
  return command


def handle_command(engine, command, now=None):
  command_type = command["type"]
  if command_type == "configure":
    return engine.configure(command["dwellMs"], command["tolerancePx"]), True
  if command_type == "resume":
    return engine.resume(), True
  if command_type == "pause":
    return engine.pause(command["reason"]), True
  if command_type == "guard":
    return engine.guard(command["name"], command["blocked"]), True
  if command_type == "activity":
    return engine.activity(command["idle"], now=now), True
  if command_type == "set_action":
    return engine.set_action(command["action"]), True
  if command_type == "stop":
    return engine.stop(), False
  raise AssertionError("validated command was not handled")


def emit(stream, event):
  line = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
  if len(line) > MAX_OUTPUT_LINE_BYTES:
    raise ClickAbleError("internal_error", "ClickAble generated an oversized response.")
  try:
    stream.write(line)
    stream.flush()
  except (BrokenPipeError, OSError) as error:
    raise Cancelled() from error


NO_INPUT = object()


class CommandReader:
  def __init__(self, descriptor):
    self.descriptor = descriptor
    self.buffer = bytearray()
    self.lines = deque()
    self.command_times = deque()

  def _extract_lines(self):
    while True:
      newline = self.buffer.find(b"\n")
      if newline < 0:
        if len(self.buffer) >= MAX_INPUT_LINE_BYTES:
          raise ProtocolError("input_too_large", "ClickAble received an oversized command.")
        return
      line = bytes(self.buffer[:newline + 1])
      del self.buffer[:newline + 1]
      if len(line) > MAX_INPUT_LINE_BYTES:
        raise ProtocolError("input_too_large", "ClickAble received an oversized command.")
      now = time.monotonic()
      while self.command_times and self.command_times[0] < now - 1:
        self.command_times.popleft()
      self.command_times.append(now)
      if len(self.command_times) > MAX_COMMANDS_PER_SECOND:
        raise ProtocolError("rate_limited", "ClickAble received commands too quickly.")
      self.lines.append(line)

  def next_line(self, timeout, stop_requested):
    if stop_requested():
      raise Cancelled()
    if self.lines:
      return self.lines.popleft()
    readable, _writable, _exceptional = select.select([self.descriptor], [], [], timeout)
    if not readable:
      return NO_INPUT
    try:
      chunk = os.read(self.descriptor, 4096)
    except InterruptedError:
      return NO_INPUT
    if not chunk:
      if self.buffer:
        raise ProtocolError("invalid_jsonl", "ClickAble received an unfinished JSON line.")
      return None
    self.buffer.extend(chunk)
    self._extract_lines()
    return self.lines.popleft() if self.lines else NO_INPUT

  def has_pending_input(self):
    if self.lines or self.buffer:
      return True
    readable, _writable, _exceptional = select.select([self.descriptor], [], [], 0)
    return bool(readable)


STOP_REQUESTED = False


def request_stop(_signum, _frame):
  global STOP_REQUESTED
  STOP_REQUESTED = True


def arm_parent_death_signal(expected_parent=None):
  if not sys.platform.startswith("linux"):
    return
  parent = os.getppid() if expected_parent is None else expected_parent
  if parent <= 1 or os.getppid() != parent:
    raise Cancelled()
  libc = ctypes.CDLL(None, use_errno=True)
  if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
    error_number = ctypes.get_errno()
    raise ClickAbleError(
      "process_ownership_failed",
      f"ClickAble could not bind itself to the Omarchy shell: errno {error_number}.",
    )
  if os.getppid() != parent:
    raise Cancelled()


def run_protocol(engine, input_stream, output_stream):
  reader = CommandReader(input_stream.fileno())
  engine.commit_blocked = reader.has_pending_input
  emit(output_stream, engine.ready_event())
  next_poll = time.monotonic() + POLL_SECONDS

  while True:
    now = time.monotonic()
    timeout = min(0.1, max(0.0, next_poll - now)) if engine.wants_poll else 0.1
    line = reader.next_line(timeout, lambda: STOP_REQUESTED)
    now = time.monotonic()
    if STOP_REQUESTED:
      raise Cancelled()

    if line is None:
      for event in engine.stop("stdin_eof"):
        emit(output_stream, event)
      return 0
    if line is not NO_INPUT:
      command = parse_command_line(line)
      if command["epoch"] != engine.epoch:
        for event in engine.epoch_fault():
          emit(output_stream, event)
        return 2
      else:
        events, keep_running = handle_command(engine, command, now=now)
        for event in events:
          emit(output_stream, event)
        if not keep_running:
          return 0

    if engine.wants_poll and now >= next_poll:
      for event in engine.poll(now):
        emit(output_stream, event)
      next_poll = now + POLL_SECONDS
    elif not engine.wants_poll:
      next_poll = now + POLL_SECONDS


def bounded_pid(value):
  if not value.isascii() or not value.isdigit():
    raise argparse.ArgumentTypeError("PID must be a positive integer")
  number = int(value)
  if number < 2 or number > MAX_ID or str(number) != value:
    raise argparse.ArgumentTypeError("PID must be a positive integer")
  return number


def epoch_id(value):
  if not value.isascii() or not value.isdigit():
    raise argparse.ArgumentTypeError("epoch must be a positive integer")
  number = int(value)
  if number < 1 or number > MAX_ID or str(number) != value:
    raise argparse.ArgumentTypeError("epoch must be a positive integer")
  return number


def coordinate(value):
  try:
    number = int(value, 10)
  except ValueError as error:
    raise argparse.ArgumentTypeError("coordinate must be an integer") from error
  if str(number) != value or not _valid_coordinate(number):
    raise argparse.ArgumentTypeError("coordinate is out of range")
  return number


def parser():
  argument_parser = argparse.ArgumentParser(description="ClickAble dwell-click helper")
  argument_parser.add_argument("--launcher-pid", type=bounded_pid, required=True)
  argument_parser.add_argument("--epoch", type=epoch_id, required=True)
  argument_parser.add_argument("--demo", action="store_true")
  argument_parser.add_argument("--demo-x", type=coordinate, default=640)
  argument_parser.add_argument("--demo-y", type=coordinate, default=360)
  return argument_parser


def fatal_event(epoch, error):
  return _event(
    "error",
    epoch,
    code=error.code,
    message=error.message[:MAX_ERROR_MESSAGE],
    fatal=True,
  )


def main(argv=None):
  global STOP_REQUESTED
  arguments = parser().parse_args(argv)
  STOP_REQUESTED = False
  previous_sigterm = signal.signal(signal.SIGTERM, request_stop)
  previous_sigint = signal.signal(signal.SIGINT, request_stop)
  output_stream = sys.stdout.buffer

  try:
    arm_parent_death_signal(arguments.launcher_pid)
    if not sys.platform.startswith("linux") and not arguments.demo:
      raise ClickAbleError("unsupported_platform", "ClickAble requires Linux and Hyprland.")
    backend = DemoBackend(arguments.demo_x, arguments.demo_y) if arguments.demo else HyprlandIPC(
      stop_requested=lambda: STOP_REQUESTED,
    )
    engine = DwellEngine(
      backend,
      arguments.epoch,
      stop_requested=lambda: STOP_REQUESTED,
    )
    return run_protocol(engine, sys.stdin.buffer, output_stream)
  except ProtocolError as error:
    try:
      emit(output_stream, fatal_event(arguments.epoch, error))
    except Cancelled:
      pass
    return 2
  except Cancelled:
    try:
      if "engine" in locals():
        for event in engine.stop("signal"):
          emit(output_stream, event)
    except Cancelled:
      pass
    return 130
  except ClickAbleError as error:
    try:
      emit(output_stream, fatal_event(arguments.epoch, error))
    except Cancelled:
      pass
    return 1
  finally:
    signal.signal(signal.SIGTERM, previous_sigterm)
    signal.signal(signal.SIGINT, previous_sigint)


if __name__ == "__main__":
  raise SystemExit(main())
