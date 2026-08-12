"""The install path replaces a working application, so it is tested hard.

The failure that matters is not "the update didn't install" — it is "the
update half-installed and now nothing runs".
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from autobom.updater import installer


def fake_exe(path: Path, body: str = "", exit_code: int = 0) -> Path:
    """A runnable stand-in for AutoBOM.exe that honours --selftest."""
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"print({body!r})\n"
        f"sys.exit({exit_code} if '--selftest' in sys.argv else 0)\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IRUSR)
    return path


class TestPaths:
    def test_staging_sits_beside_the_target(self, tmp_path):
        target = tmp_path / "AutoBOM.exe"
        staged = installer.staging_path(target)
        # Same directory, so the swap is a rename and not a cross-volume copy.
        assert staged.parent == target.parent
        assert staged != target

    def test_backup_sits_beside_the_target(self, tmp_path):
        target = tmp_path / "AutoBOM.exe"
        assert installer.backup_path(target).parent == target.parent

    def test_staging_and_backup_are_distinct(self, tmp_path):
        target = tmp_path / "AutoBOM.exe"
        assert installer.staging_path(target) != installer.backup_path(target)


class TestCanInstallInPlace:
    def test_false_when_running_from_source(self):
        # No frozen executable to replace.
        assert installer.current_executable() is None
        assert installer.can_install_in_place() is False

    def test_true_for_a_writable_location(self, tmp_path):
        assert installer.can_install_in_place(tmp_path / "AutoBOM.exe") is True

    @pytest.mark.skipif(
        os.name == "nt" or getattr(os, "geteuid", lambda: 1)() == 0,
        reason="POSIX permission semantics, and root ignores them",
    )
    def test_false_for_an_unwritable_location(self, tmp_path):
        locked = tmp_path / "locked"
        locked.mkdir()
        locked.chmod(0o500)
        try:
            assert installer.can_install_in_place(locked / "AutoBOM.exe") is False
        finally:
            locked.chmod(0o700)


class TestSwapIn:
    def test_replaces_the_target(self, tmp_path):
        target = tmp_path / "AutoBOM.exe"
        target.write_text("old", encoding="utf-8")
        candidate = tmp_path / "AutoBOM.exe.new"
        candidate.write_text("new", encoding="utf-8")

        installer.swap_in(candidate, target)
        assert target.read_text(encoding="utf-8") == "new"

    def test_keeps_the_old_build_as_a_backup(self, tmp_path):
        target = tmp_path / "AutoBOM.exe"
        target.write_text("old", encoding="utf-8")
        candidate = tmp_path / "AutoBOM.exe.new"
        candidate.write_text("new", encoding="utf-8")

        backup = installer.swap_in(candidate, target)
        assert backup.read_text(encoding="utf-8") == "old"

    def test_consumes_the_staged_file(self, tmp_path):
        target = tmp_path / "AutoBOM.exe"
        target.write_text("old", encoding="utf-8")
        candidate = tmp_path / "AutoBOM.exe.new"
        candidate.write_text("new", encoding="utf-8")

        installer.swap_in(candidate, target)
        assert not candidate.exists()

    def test_replaces_a_leftover_backup(self, tmp_path):
        target = tmp_path / "AutoBOM.exe"
        target.write_text("old", encoding="utf-8")
        installer.backup_path(target).write_text("ancient", encoding="utf-8")
        candidate = tmp_path / "AutoBOM.exe.new"
        candidate.write_text("new", encoding="utf-8")

        backup = installer.swap_in(candidate, target)
        assert backup.read_text(encoding="utf-8") == "old"

    def test_a_failed_swap_leaves_a_working_application(self, tmp_path, monkeypatch):
        """The whole point: never end up with no executable at all."""
        target = tmp_path / "AutoBOM.exe"
        target.write_text("old", encoding="utf-8")
        candidate = tmp_path / "AutoBOM.exe.new"
        candidate.write_text("new", encoding="utf-8")

        def boom(self, other):
            raise OSError("disk full")

        monkeypatch.setattr(Path, "replace", boom)
        with pytest.raises(OSError):
            installer.swap_in(candidate, target)

        assert target.exists()
        assert target.read_text(encoding="utf-8") == "old"
        assert not installer.backup_path(target).exists()


class TestCleanupBackups:
    def test_removes_a_previous_build(self, tmp_path):
        target = tmp_path / "AutoBOM.exe"
        target.write_text("current", encoding="utf-8")
        installer.backup_path(target).write_text("previous", encoding="utf-8")

        installer.cleanup_backups(target)
        assert not installer.backup_path(target).exists()
        assert target.exists()

    def test_removes_an_abandoned_download(self, tmp_path):
        target = tmp_path / "AutoBOM.exe"
        target.write_text("current", encoding="utf-8")
        installer.staging_path(target).write_text("partial", encoding="utf-8")

        installer.cleanup_backups(target)
        assert not installer.staging_path(target).exists()

    def test_silent_when_there_is_nothing_to_clean(self, tmp_path):
        installer.cleanup_backups(tmp_path / "AutoBOM.exe")  # must not raise

    def test_never_raises_when_the_file_is_locked(self, tmp_path, monkeypatch):
        target = tmp_path / "AutoBOM.exe"
        target.write_text("current", encoding="utf-8")
        installer.backup_path(target).write_text("previous", encoding="utf-8")

        def locked(self, missing_ok=False):
            raise PermissionError("in use")

        monkeypatch.setattr(Path, "unlink", locked)
        installer.cleanup_backups(target)  # a stale file is not worth crashing over

    def test_no_frozen_executable_is_a_no_op(self):
        installer.cleanup_backups()  # running from source


@pytest.mark.skipif(
    os.name == "nt", reason="shebang scripts are not directly executable on Windows"
)
class TestRunSelftest:
    def test_passes_for_a_good_build(self, tmp_path):
        candidate = fake_exe(tmp_path / "good", body="SELF-TEST PASSED", exit_code=0)
        ok, detail = installer.run_selftest(candidate, timeout=60)
        assert ok is True
        assert "SELF-TEST PASSED" in detail

    def test_a_failing_build_is_rejected(self, tmp_path):
        """The reason this step exists: intact but broken must not install."""
        candidate = fake_exe(tmp_path / "bad", body="SELF-TEST FAILED", exit_code=1)
        ok, detail = installer.run_selftest(candidate, timeout=60)
        assert ok is False
        assert "FAILED" in detail

    def test_a_hanging_build_is_rejected(self, tmp_path):
        candidate = tmp_path / "hang"
        candidate.write_text(
            "#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n", encoding="utf-8"
        )
        candidate.chmod(candidate.stat().st_mode | stat.S_IEXEC)
        ok, detail = installer.run_selftest(candidate, timeout=1)
        assert ok is False
        assert detail


class TestRunSelftestErrors:
    def test_unrunnable_file_is_a_failure_not_a_crash(self, tmp_path):
        ok, detail = installer.run_selftest(tmp_path / "not-there", timeout=10)
        assert ok is False
        assert detail


@pytest.mark.skipif(os.name == "nt", reason="Windows has no executable bit")
class TestMakeExecutable:
    def test_a_downloaded_file_becomes_runnable(self, tmp_path):
        # urlopen writes a plain file with no executable bit, so the self-test
        # could not run the very binary it is meant to vet.
        candidate = tmp_path / "AutoBOM.exe.new"
        candidate.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        candidate.chmod(0o644)

        installer.make_executable(candidate)
        assert os.access(candidate, os.X_OK)

    def test_missing_file_is_not_an_error(self, tmp_path):
        installer.make_executable(tmp_path / "absent")  # must not raise
