import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import clickable_settings as settings


VALID = '{"version":1,"dwellMs":900,"tolerancePx":12}'
UPDATED = '{"version":1,"dwellMs":1200,"tolerancePx":20}'


class SettingsPersistenceTests(unittest.TestCase):
  def setUp(self):
    real_temporary_root = "/private/tmp" if Path("/private/tmp").is_dir() else None
    self.temporary = tempfile.TemporaryDirectory(dir=real_temporary_root)
    self.root = Path(self.temporary.name)
    self.config_home = self.root / "config"

  def tearDown(self):
    self.temporary.cleanup()

  @property
  def settings_directory(self):
    return self.config_home / "omarchy" / "clickable"

  @property
  def settings_file(self):
    return self.settings_directory / "config.json"

  def assertCode(self, code, operation):
    with self.assertRaises(settings.SettingsError) as raised:
      operation()
    self.assertEqual(raised.exception.code, code)

  def test_missing_settings_create_private_real_directory_and_read_empty(self):
    self.assertEqual(settings.read_settings(str(self.config_home)), "")
    metadata = self.settings_directory.lstat()
    self.assertTrue(stat.S_ISDIR(metadata.st_mode))
    self.assertEqual(metadata.st_uid, os.geteuid())
    self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o700)
    self.assertFalse(self.settings_file.exists())

  def test_missing_nested_config_home_is_created_safely(self):
    self.config_home = self.root / "missing" / "nested" / "config"
    self.assertEqual(settings.read_settings(str(self.config_home)), "")
    for directory in (
      self.root / "missing",
      self.root / "missing" / "nested",
      self.config_home,
      self.settings_directory,
    ):
      metadata = directory.lstat()
      self.assertTrue(stat.S_ISDIR(metadata.st_mode))
      self.assertEqual(metadata.st_uid, os.geteuid())

  def test_write_atomically_replaces_owned_regular_file(self):
    settings.write_settings(str(self.config_home), VALID)
    first = self.settings_file.stat()
    self.assertEqual(stat.S_IMODE(first.st_mode), 0o600)
    self.assertEqual(first.st_uid, os.geteuid())
    self.assertEqual(json.loads(settings.read_settings(str(self.config_home))), {
      "version": 1,
      "dwellMs": 900,
      "tolerancePx": 12,
    })

    settings.write_settings(str(self.config_home), UPDATED)
    second = self.settings_file.stat()
    self.assertNotEqual((first.st_dev, first.st_ino), (second.st_dev, second.st_ino))
    self.assertEqual(json.loads(self.settings_file.read_text(encoding="utf-8")), {
      "version": 1,
      "dwellMs": 1200,
      "tolerancePx": 20,
    })
    self.assertEqual(list(self.settings_directory.glob(".*.tmp")), [])

  def test_executable_round_trip_uses_one_bounded_json_envelope(self):
    helper = ROOT / "bin" / "clickable-settings"
    write = subprocess.run(
      [str(helper), "write", str(self.config_home), VALID],
      capture_output=True,
      text=True,
      timeout=2,
      check=False,
    )
    self.assertEqual((write.returncode, write.stdout, write.stderr), (0, "", ""))

    read = subprocess.run(
      [str(helper), "read", str(self.config_home)],
      capture_output=True,
      text=True,
      timeout=2,
      check=False,
    )
    self.assertEqual((read.returncode, read.stderr), (0, ""))
    self.assertEqual(read.stdout.count("\n"), 1)
    self.assertLessEqual(len(read.stdout), 8192)
    self.assertEqual(json.loads(json.loads(read.stdout)["text"]), {
      "version": 1,
      "dwellMs": 900,
      "tolerancePx": 12,
    })

  def test_failed_atomic_replace_preserves_previous_file_and_cleans_temp(self):
    settings.write_settings(str(self.config_home), VALID)
    before = self.settings_file.read_bytes()
    with mock.patch.object(settings.os, "replace", side_effect=OSError("injected")):
      self.assertCode(
        "settings_write_failed",
        lambda: settings.write_settings(str(self.config_home), UPDATED),
      )
    self.assertEqual(self.settings_file.read_bytes(), before)
    self.assertEqual(list(self.settings_directory.glob(".*.tmp")), [])

  def test_symlinked_settings_directory_is_rejected_without_touching_target(self):
    outside = self.root / "outside"
    outside.mkdir(mode=0o700)
    self.config_home.mkdir()
    (self.config_home / "omarchy").mkdir()
    (self.config_home / "omarchy" / "clickable").symlink_to(outside, target_is_directory=True)

    self.assertCode(
      "unsafe_settings_directory",
      lambda: settings.read_settings(str(self.config_home)),
    )
    self.assertCode(
      "unsafe_settings_directory",
      lambda: settings.write_settings(str(self.config_home), VALID),
    )
    self.assertEqual(list(outside.iterdir()), [])

  def test_symlinked_config_home_is_rejected_without_touching_target(self):
    outside = self.root / "outside-config"
    outside.mkdir(mode=0o700)
    self.config_home.symlink_to(outside, target_is_directory=True)

    self.assertCode(
      "unsafe_settings_directory",
      lambda: settings.read_settings(str(self.config_home)),
    )
    self.assertCode(
      "unsafe_settings_directory",
      lambda: settings.write_settings(str(self.config_home), VALID),
    )
    self.assertEqual(list(outside.iterdir()), [])

  def test_symlinked_config_home_ancestor_is_rejected_without_touching_target(self):
    outside = self.root / "outside-ancestor"
    outside.mkdir(mode=0o700)
    linked_ancestor = self.root / "linked-ancestor"
    linked_ancestor.symlink_to(outside, target_is_directory=True)
    self.config_home = linked_ancestor / "nested" / "config"

    self.assertCode(
      "unsafe_settings_directory",
      lambda: settings.read_settings(str(self.config_home)),
    )
    self.assertCode(
      "unsafe_settings_directory",
      lambda: settings.write_settings(str(self.config_home), VALID),
    )
    self.assertEqual(list(outside.iterdir()), [])

  def test_symlinked_settings_file_is_rejected_without_touching_target(self):
    settings.read_settings(str(self.config_home))
    target = self.root / "target.json"
    target.write_text("sentinel", encoding="utf-8")
    self.settings_file.symlink_to(target)

    self.assertCode(
      "unsafe_settings_file",
      lambda: settings.read_settings(str(self.config_home)),
    )
    self.assertCode(
      "unsafe_settings_file",
      lambda: settings.write_settings(str(self.config_home), VALID),
    )
    self.assertEqual(target.read_text(encoding="utf-8"), "sentinel")

  def test_fifo_is_rejected_without_blocking(self):
    settings.read_settings(str(self.config_home))
    os.mkfifo(self.settings_file)
    started = time.monotonic()
    self.assertCode(
      "unsafe_settings_file",
      lambda: settings.read_settings(str(self.config_home)),
    )
    self.assertLess(time.monotonic() - started, 1.0)
    self.assertCode(
      "unsafe_settings_file",
      lambda: settings.write_settings(str(self.config_home), VALID),
    )

  def test_oversized_file_is_rejected_before_any_read(self):
    settings.read_settings(str(self.config_home))
    self.settings_file.write_bytes(b"x" * (settings.MAX_SETTINGS_BYTES + 1))
    with mock.patch.object(settings.os, "read") as read:
      self.assertCode(
        "settings_too_large",
        lambda: settings.read_settings(str(self.config_home)),
      )
    read.assert_not_called()

  def test_wrong_file_type_and_owner_are_rejected(self):
    settings.read_settings(str(self.config_home))
    self.settings_file.mkdir()
    self.assertCode(
      "unsafe_settings_file",
      lambda: settings.read_settings(str(self.config_home)),
    )
    self.settings_file.rmdir()
    self.settings_file.write_text(VALID, encoding="utf-8")

    directory_descriptor = settings.open_settings_directory(str(self.config_home))
    try:
      self.assertCode(
        "unsafe_settings_file",
        lambda: settings._open_existing_settings_file(
          directory_descriptor, os.geteuid() + 1),
      )
    finally:
      os.close(directory_descriptor)

  def test_multiply_linked_settings_file_is_rejected(self):
    settings.write_settings(str(self.config_home), VALID)
    linked = self.root / "linked-config.json"
    os.link(self.settings_file, linked)
    self.assertCode(
      "unsafe_settings_file",
      lambda: settings.read_settings(str(self.config_home)),
    )
    self.assertCode(
      "unsafe_settings_file",
      lambda: settings.write_settings(str(self.config_home), UPDATED),
    )

  def test_restrictive_umask_still_produces_mode_0600(self):
    settings.read_settings(str(self.config_home))
    previous_umask = os.umask(0o777)
    try:
      settings.write_settings(str(self.config_home), VALID)
    finally:
      os.umask(previous_umask)
    self.assertEqual(stat.S_IMODE(self.settings_file.stat().st_mode), 0o600)
    self.assertEqual(json.loads(settings.read_settings(str(self.config_home)))["version"], 1)

  def test_non_private_settings_directory_and_invalid_payload_fail_closed(self):
    settings.read_settings(str(self.config_home))
    self.settings_directory.chmod(0o755)
    self.assertCode(
      "unsafe_settings_directory",
      lambda: settings.read_settings(str(self.config_home)),
    )
    self.settings_directory.chmod(0o700)
    for payload in (
      "",
      "not json",
      '{"version":1,"dwellMs":901,"tolerancePx":12}',
      '{"version":1,"dwellMs":900,"tolerancePx":12,"armed":true}',
    ):
      with self.subTest(payload=payload):
        self.assertCode(
          "invalid_settings",
          lambda payload=payload: settings.write_settings(
            str(self.config_home), payload),
        )


if __name__ == "__main__":
  unittest.main()
