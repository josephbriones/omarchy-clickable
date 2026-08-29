import json
from pathlib import Path
import re
import stat
import struct
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RepositoryTests(unittest.TestCase):
  def test_manifest_and_entry_points_are_exact(self):
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))

    self.assertEqual(manifest["schemaVersion"], 1)
    self.assertEqual(manifest["id"], "io.github.josephbriones.clickable")
    self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
    self.assertEqual(manifest["kinds"], ["service", "bar-widget"])
    self.assertIs(manifest["keepLoaded"], True)
    self.assertEqual(manifest["entryPoints"], {
      "service": "Service.qml",
      "barWidget": "BarWidget.qml",
    })
    self.assertIs(manifest["barWidget"]["allowMultiple"], False)
    for entry_point in manifest["entryPoints"].values():
      self.assertTrue((ROOT / entry_point).is_file(), entry_point)

  def test_release_tree_is_complete_and_contains_no_symlinks(self):
    required = (
      ".github/ISSUE_TEMPLATE/bug-report.yml",
      ".github/PULL_REQUEST_TEMPLATE.md",
      ".github/workflows/ci.yml",
      "assets/preview.svg",
      "bin/clickable",
      "bin/clickable-settings",
      "docs/ARCHITECTURE.md",
      "docs/COMPETITION.md",
      "docs/MARKETPLACE_SUBMISSION.md",
      "docs/RELEASE_CHECKLIST.md",
      "docs/SETUP.md",
      "docs/TESTING.md",
      "lib/clickable.py",
      "lib/clickable_settings.py",
      "scripts/acceptance-test.sh",
      "scripts/validate.sh",
      "CHANGELOG.md",
      "ClickAbleModel.js",
      "LICENSE",
      "PRIVACY.md",
      "README.md",
      "SECURITY.md",
      "Service.qml",
      "BarWidget.qml",
      "manifest.json",
      "preview.png",
    )
    for relative in required:
      self.assertTrue((ROOT / relative).is_file(), relative)
    self.assertEqual([path for path in ROOT.rglob("*") if path.is_symlink()], [])

  def test_launchers_and_acceptance_runner_are_executable(self):
    for relative in ("bin/clickable", "bin/clickable-settings", "scripts/acceptance-test.sh"):
      self.assertTrue((ROOT / relative).stat().st_mode & stat.S_IXUSR, relative)

  def test_readme_has_one_clear_job_install_remove_limits_and_license(self):
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for phrase in (
      "If you can point, you should be able to click.",
      "omarchy plugin add https://github.com/josephbriones/omarchy-clickable.git --enable",
      "omarchy plugin remove io.github.josephbriones.clickable",
      "No drag, scroll",
      "License",
    ):
      self.assertIn(phrase, readme)

  def test_root_scanner_text_has_no_privileged_or_remote_bootstrap(self):
    scanned = "\n".join(
      (ROOT / name).read_text(encoding="utf-8")
      for name in ("README.md", "manifest.json")
    ).lower()
    for forbidden in ("curl |", "curl|", "wget |", "wget|", "sudo", "pkexec",
                      "systemctl", "pacman -"):
      self.assertNotIn(forbidden, scanned)

  def test_implementation_has_no_network_client_shell_or_input_device(self):
    code = "\n".join(
      (ROOT / relative).read_text(encoding="utf-8", errors="replace")
      for relative in (
        "bin/clickable",
        "bin/clickable-settings",
        "lib/clickable.py",
        "lib/clickable_settings.py",
        "Service.qml",
        "BarWidget.qml",
      )
    )
    for forbidden in ("urllib", "requests.", "HTTPConnection", "shell=True", "Qt.openUrlExternally",
                      "/dev/uinput", "ydotool", "sudo", "pkexec"):
      self.assertNotIn(forbidden, code)

  def test_settings_helper_is_descriptor_safe_bounded_and_atomic(self):
    source = (ROOT / "lib/clickable_settings.py").read_text(encoding="utf-8")
    for contract in (
      "MAX_SETTINGS_BYTES = 1024",
      "os.O_NOFOLLOW",
      "os.O_NONBLOCK",
      "follow_symlinks=False",
      "stat.S_ISREG",
      "metadata.st_uid != expected_uid",
      "metadata.st_nlink != 1",
      "os.replace(",
      "src_dir_fd=directory_descriptor",
      "dst_dir_fd=directory_descriptor",
      "os.fsync(temporary_descriptor)",
      "os.fchmod(temporary_descriptor, 0o600)",
      "_sync_directory(directory_descriptor)",
    ):
      self.assertIn(contract, source)

  def test_preview_is_a_reviewable_1600_by_900_png(self):
    data = (ROOT / "preview.png").read_bytes()
    self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", data[16:24])
    self.assertEqual((width, height), (1600, 900))
    self.assertLess(len(data), 2_000_000)

  def test_ci_pins_actions_and_runs_arch_omarchy_contract(self):
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    uses = re.findall(r"uses:\s+[^@\s]+@([^\s#]+)", workflow)
    self.assertGreaterEqual(len(uses), 4)
    for revision in uses:
      self.assertRegex(revision, r"^[0-9a-f]{40}$")
    for contract in (
      'python-version: ["3.12", "3.14"]',
      "container: archlinux:latest",
      "git jq quickshell qt6-declarative",
      "omarchy-plugin-validate",
      "/usr/lib/qt6/bin/qmllint",
      "945549699026df6c888a6b1bd4e06fbf55a67595",
    ):
      self.assertIn(contract, workflow)

  def test_bash_uses_current_omarchy_style(self):
    for script in (ROOT / "scripts").glob("*.sh"):
      source = script.read_text(encoding="utf-8")
      self.assertTrue(source.startswith("#!/bin/bash"), script.name)
      self.assertIsNone(re.search(r"(^|[; ])\[ ", source, re.MULTILINE), script.name)

  def test_acceptance_runner_is_safe_truthful_and_cleans_up(self):
    source = (ROOT / "scripts/acceptance-test.sh").read_text(encoding="utf-8")
    for contract in (
      'bash "$ROOT/scripts/validate.sh"',
      "XDG_SESSION_TYPE:-",
      "HYPRLAND_INSTANCE_SIGNATURE:-",
      "trap cleanup EXIT",
      "trap 'exit 130' INT",
      "trap 'exit 143' TERM",
      'if [[ ! -t 0 ]]',
      "for action in left right double",
      'state.get("demo") is True',
      'state.get("state") == "rearming"',
      'state.get("running") is False',
      "Did exactly one %s action reach the item under the pointer?",
      "complete the remaining surface, display, lock, reload, stress, and Orca gates",
      "omarchy-version",
      "pacman -Q hyprland",
      "hyprctl version",
      'installed_root="$HOME/.config/omarchy/plugins/$plugin_id"',
      'candidate_sha=$(git -C "$ROOT" rev-parse --verify HEAD',
      'installed_sha=$(git -C "$installed_root" rev-parse --verify HEAD',
      'if [[ $candidate_sha != "$installed_sha" ]]',
      'status --porcelain --untracked-files=all',
      "omarchy-shell shell rescanPlugins",
      'ClickAble commit: %s',
      'if ! omarchy_release=$(omarchy-version 2>&1)',
    ):
      self.assertIn(contract, source)

  def test_release_checklist_does_not_claim_unperformed_hardware_evidence(self):
    checklist = (ROOT / "docs/RELEASE_CHECKLIST.md").read_text(encoding="utf-8")
    self.assertNotIn("- [x]", checklist.lower())
    for gate in ("XWayland", "Orca", "1,000", "lock", "reload"):
      self.assertIn(gate, checklist)

  def test_release_docs_preserve_candidate_status_and_lock_race(self):
    release_surfaces = (
      "README.md",
      "SECURITY.md",
      "docs/ARCHITECTURE.md",
      "docs/TESTING.md",
      "docs/RELEASE_CHECKLIST.md",
      "docs/COMPETITION.md",
      "CHANGELOG.md",
    )
    for relative in release_surfaces:
      with self.subTest(relative=relative):
        source = (ROOT / relative).read_text(encoding="utf-8").lower()
        self.assertIn("release candidate", source)
        self.assertIn("residual", source)
        self.assertIn("exact recorded", source)

    for relative in ("README.md", "SECURITY.md", "docs/ARCHITECTURE.md"):
      with self.subTest(preflight=relative):
        source = (ROOT / relative).read_text(encoding="utf-8").lower()
        self.assertIn("best-effort immediate preflight", source)

    for relative in (".github/PULL_REQUEST_TEMPLATE.md", "docs/MARKETPLACE_SUBMISSION.md"):
      with self.subTest(residual_surface=relative):
        source = (ROOT / relative).read_text(encoding="utf-8").lower()
        self.assertIn("observed lock", source)
        self.assertIn("residual", source)


if __name__ == "__main__":
  unittest.main()
