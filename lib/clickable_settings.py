#!/usr/bin/env python3

import errno
import json
import os
from pathlib import Path
import secrets
import stat


MAX_PATH_BYTES = 4096
MAX_SETTINGS_BYTES = 1024
SETTINGS_FILENAME = "config.json"
SETTINGS_PARTS = ("omarchy", "clickable")
DWELL_VALUES = {600, 900, 1200, 1600}
TOLERANCE_VALUES = {6, 12, 20}


class SettingsError(Exception):
  def __init__(self, code, message):
    super().__init__(message)
    self.code = code
    self.message = message


def _error(code, message, cause=None):
  error = SettingsError(code, message)
  if cause is not None:
    error.__cause__ = cause
  return error


def _directory_flags():
  return os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW


def _validate_config_home(value):
  if not isinstance(value, str) or not value or "\x00" in value:
    raise _error("unsafe_settings_path", "ClickAble rejected its settings path.")
  try:
    encoded = os.fsencode(value)
  except UnicodeError as error:
    raise _error("unsafe_settings_path", "ClickAble rejected its settings path.", error)
  if len(encoded) > MAX_PATH_BYTES:
    raise _error("unsafe_settings_path", "ClickAble rejected its settings path.")

  path = Path(value)
  if not path.is_absolute() or path == Path(path.anchor):
    raise _error("unsafe_settings_path", "ClickAble requires an absolute settings directory.")
  if any(part in {".", ".."} for part in value.split(os.sep)):
    raise _error("unsafe_settings_path", "ClickAble rejected traversal in its settings path.")
  return path


def _open_or_create_path(path):
  descriptor = None
  try:
    descriptor = os.open(path.anchor, _directory_flags())
    for part in path.parts[1:]:
      try:
        next_descriptor = os.open(part, _directory_flags(), dir_fd=descriptor)
      except FileNotFoundError:
        try:
          os.mkdir(part, 0o700, dir_fd=descriptor)
        except FileExistsError:
          pass
        next_descriptor = os.open(part, _directory_flags(), dir_fd=descriptor)
      os.close(descriptor)
      descriptor = next_descriptor
    return descriptor
  except OSError as error:
    if descriptor is not None:
      os.close(descriptor)
    raise _error(
      "unsafe_settings_directory",
      "ClickAble requires a real settings directory with no symbolic links.",
      error,
    )


def _verify_directory(descriptor, expected_uid, *, private):
  try:
    metadata = os.fstat(descriptor)
  except OSError as error:
    raise _error("unsafe_settings_directory", "ClickAble could not inspect its settings directory.", error)
  if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != expected_uid:
    raise _error(
      "unsafe_settings_directory",
      "ClickAble requires a user-owned real settings directory.",
    )
  if private and stat.S_IMODE(metadata.st_mode) != 0o700:
    raise _error(
      "unsafe_settings_directory",
      "ClickAble requires its settings directory to have mode 0700.",
    )


def _open_or_create_directory(parent_descriptor, name, expected_uid, *, private):
  try:
    os.mkdir(name, 0o700, dir_fd=parent_descriptor)
  except FileExistsError:
    pass
  except OSError as error:
    raise _error("unsafe_settings_directory", "ClickAble could not create its settings directory.", error)

  try:
    descriptor = os.open(name, _directory_flags(), dir_fd=parent_descriptor)
  except OSError as error:
    raise _error(
      "unsafe_settings_directory",
      "ClickAble requires a real settings directory with no symbolic links.",
      error,
    )
  try:
    _verify_directory(descriptor, expected_uid, private=private)
  except Exception:
    os.close(descriptor)
    raise
  return descriptor


def open_settings_directory(config_home, *, expected_uid=None):
  path = _validate_config_home(config_home)
  expected_uid = os.geteuid() if expected_uid is None else expected_uid
  config_descriptor = _open_or_create_path(path)
  omarchy_descriptor = None
  try:
    _verify_directory(config_descriptor, expected_uid, private=False)
    omarchy_descriptor = _open_or_create_directory(
      config_descriptor, SETTINGS_PARTS[0], expected_uid, private=False)
    return _open_or_create_directory(
      omarchy_descriptor, SETTINGS_PARTS[1], expected_uid, private=True)
  finally:
    os.close(config_descriptor)
    if omarchy_descriptor is not None:
      os.close(omarchy_descriptor)


def _verify_regular_file(metadata, expected_uid):
  if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != expected_uid:
    raise _error(
      "unsafe_settings_file",
      "ClickAble requires a user-owned regular settings file.",
    )
  if metadata.st_nlink != 1:
    raise _error(
      "unsafe_settings_file",
      "ClickAble requires a settings file with exactly one link.",
    )
  if metadata.st_size < 0 or metadata.st_size > MAX_SETTINGS_BYTES:
    raise _error(
      "settings_too_large",
      "ClickAble rejected an oversized settings file.",
    )


def _open_existing_settings_file(directory_descriptor, expected_uid):
  try:
    before = os.stat(
      SETTINGS_FILENAME,
      dir_fd=directory_descriptor,
      follow_symlinks=False,
    )
  except FileNotFoundError:
    return None
  except OSError as error:
    raise _error("unsafe_settings_file", "ClickAble could not inspect its settings file.", error)

  _verify_regular_file(before, expected_uid)
  flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
  try:
    descriptor = os.open(SETTINGS_FILENAME, flags, dir_fd=directory_descriptor)
  except OSError as error:
    raise _error("unsafe_settings_file", "ClickAble could not safely open its settings file.", error)

  try:
    after = os.fstat(descriptor)
    _verify_regular_file(after, expected_uid)
    if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
      raise _error("unsafe_settings_file", "ClickAble's settings file changed while opening it.")
  except Exception:
    os.close(descriptor)
    raise
  return descriptor


def read_settings(config_home, *, expected_uid=None):
  expected_uid = os.geteuid() if expected_uid is None else expected_uid
  directory_descriptor = open_settings_directory(config_home, expected_uid=expected_uid)
  file_descriptor = None
  try:
    file_descriptor = _open_existing_settings_file(directory_descriptor, expected_uid)
    if file_descriptor is None:
      return ""

    chunks = []
    total = 0
    while total <= MAX_SETTINGS_BYTES:
      try:
        chunk = os.read(file_descriptor, min(256, MAX_SETTINGS_BYTES + 1 - total))
      except BlockingIOError as error:
        raise _error("unsafe_settings_file", "ClickAble refused a blocking settings file.", error)
      if not chunk:
        break
      chunks.append(chunk)
      total += len(chunk)
    if total > MAX_SETTINGS_BYTES:
      raise _error("settings_too_large", "ClickAble rejected an oversized settings file.")
    return b"".join(chunks).decode("utf-8", "replace")
  finally:
    if file_descriptor is not None:
      os.close(file_descriptor)
    os.close(directory_descriptor)


def _canonical_settings(text):
  if not isinstance(text, str):
    raise _error("invalid_settings", "ClickAble rejected invalid settings data.")
  try:
    encoded = text.encode("utf-8", "strict")
  except UnicodeError as error:
    raise _error("invalid_settings", "ClickAble rejected invalid settings data.", error)
  if not encoded or len(encoded) > MAX_SETTINGS_BYTES:
    raise _error("invalid_settings", "ClickAble rejected invalid settings data.")

  try:
    value = json.loads(text)
  except (json.JSONDecodeError, RecursionError) as error:
    raise _error("invalid_settings", "ClickAble rejected invalid settings data.", error)
  if (
    not isinstance(value, dict)
    or set(value) != {"version", "dwellMs", "tolerancePx"}
    or value.get("version") != 1
    or isinstance(value.get("dwellMs"), bool)
    or value.get("dwellMs") not in DWELL_VALUES
    or isinstance(value.get("tolerancePx"), bool)
    or value.get("tolerancePx") not in TOLERANCE_VALUES
  ):
    raise _error("invalid_settings", "ClickAble rejected invalid settings data.")
  return (json.dumps(value, indent=2) + "\n").encode("utf-8")


def _open_temporary_file(directory_descriptor):
  flags = os.O_WRONLY | os.O_CLOEXEC | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
  for _attempt in range(8):
    name = f".{SETTINGS_FILENAME}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    try:
      return name, os.open(name, flags, 0o600, dir_fd=directory_descriptor)
    except FileExistsError:
      continue
    except OSError as error:
      raise _error("settings_write_failed", "ClickAble could not create a settings update.", error)
  raise _error("settings_write_failed", "ClickAble could not create a unique settings update.")


def _write_all(descriptor, payload):
  offset = 0
  while offset < len(payload):
    try:
      written = os.write(descriptor, payload[offset:])
    except OSError as error:
      raise _error("settings_write_failed", "ClickAble could not write its settings update.", error)
    if written <= 0:
      raise _error("settings_write_failed", "ClickAble could not complete its settings update.")
    offset += written


def _sync_directory(descriptor):
  try:
    os.fsync(descriptor)
  except OSError as error:
    if error.errno not in {errno.EINVAL, getattr(errno, "ENOTSUP", errno.EINVAL)}:
      raise


def write_settings(config_home, text, *, expected_uid=None):
  payload = _canonical_settings(text)
  expected_uid = os.geteuid() if expected_uid is None else expected_uid
  directory_descriptor = open_settings_directory(config_home, expected_uid=expected_uid)
  existing_descriptor = None
  temporary_descriptor = None
  temporary_name = None
  replaced = False
  try:
    existing_descriptor = _open_existing_settings_file(directory_descriptor, expected_uid)
    if existing_descriptor is not None:
      os.close(existing_descriptor)
      existing_descriptor = None

    temporary_name, temporary_descriptor = _open_temporary_file(directory_descriptor)
    _write_all(temporary_descriptor, payload)
    os.fchmod(temporary_descriptor, 0o600)
    os.fsync(temporary_descriptor)
    os.close(temporary_descriptor)
    temporary_descriptor = None
    os.replace(
      temporary_name,
      SETTINGS_FILENAME,
      src_dir_fd=directory_descriptor,
      dst_dir_fd=directory_descriptor,
    )
    replaced = True
    _sync_directory(directory_descriptor)
  except SettingsError:
    raise
  except OSError as error:
    raise _error("settings_write_failed", "ClickAble could not atomically save its settings.", error)
  finally:
    if existing_descriptor is not None:
      os.close(existing_descriptor)
    if temporary_descriptor is not None:
      os.close(temporary_descriptor)
    if temporary_name is not None and not replaced:
      try:
        os.unlink(temporary_name, dir_fd=directory_descriptor)
      except FileNotFoundError:
        pass
      except OSError:
        pass
    os.close(directory_descriptor)
