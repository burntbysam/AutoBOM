"""Replace the running executable with a downloaded build.

A bad update is worse than no update: this tool's output goes to a saw. So a
downloaded binary is never swapped in until it has matched the published
SHA256 *and* passed its own ``--selftest``. A build that shipped a broken
classifier would quietly produce the wrong cut list, which no checksum can
catch.

Windows will not let a running process overwrite its own image, but it will
let it be *renamed*. So the live exe is renamed aside, the new one takes its
place, and the stale copy is deleted on the next launch -- no helper script to
leave behind, and one rename to undo if the swap fails.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

BACKUP_SUFFIX = ".old"
STAGING_SUFFIX = ".new"
SELFTEST_TIMEOUT = 180

# Windows process-creation flags.
_CREATE_NO_WINDOW = 0x08000000
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def current_executable() -> Path | None:
    """The running .exe, or None when running from source."""
    if not is_frozen():
        return None
    try:
        return Path(sys.executable).resolve()
    except OSError:  # pragma: no cover - defensive
        return None


def can_install_in_place(target: Path | None = None) -> bool:
    """True when an in-place update is possible.

    False from a source checkout (there is no single file to replace) and
    false when the executable sits somewhere unwritable, such as Program Files
    without elevation -- in which case the download page is still offered.
    """
    target = target or current_executable()
    if target is None:
        return False
    return os.access(target.parent, os.W_OK)


def staging_path(target: Path) -> Path:
    """Where the download lands: beside the target, so the swap is a rename."""
    target = Path(target)
    return target.with_name(target.name + STAGING_SUFFIX)


def backup_path(target: Path) -> Path:
    return Path(target).with_name(Path(target).name + BACKUP_SUFFIX)


def make_executable(candidate: Path) -> None:
    """Restore the executable bit, which a download does not carry on POSIX.

    Windows infers executability from the extension, so this is a no-op there.
    """
    if os.name == "nt":
        return
    try:
        mode = candidate.stat().st_mode
        candidate.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


def run_selftest(candidate: Path, timeout: int = SELFTEST_TIMEOUT) -> tuple[bool, str]:
    """Run the downloaded binary's own self-test. Never raises."""
    candidate = Path(candidate)
    make_executable(candidate)
    kwargs = {}
    if os.name == "nt":
        # Do not flash a console window in the user's face.
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    try:
        finished = subprocess.run(
            [str(candidate), "--selftest"],
            capture_output=True,
            timeout=timeout,
            **kwargs,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"could not run the downloaded build: {exc}"
    output = (finished.stdout or b"").decode("utf-8", "replace").strip()
    if finished.returncode != 0:
        detail = output or (finished.stderr or b"").decode("utf-8", "replace").strip()
        return False, detail or f"self-test exited {finished.returncode}"
    return True, output


def swap_in(candidate: Path, target: Path) -> Path:
    """Put ``candidate`` in ``target``'s place, returning the backup path.

    The rename is what makes this work while the target is running. If the
    second step fails the first is undone, so a failed update leaves a working
    application rather than none at all.
    """
    candidate, target = Path(candidate), Path(target)
    backup = backup_path(target)

    if backup.exists():
        try:
            backup.unlink()
        except OSError:
            # A previous copy may still be locked by an exiting process; the
            # rename below will fail cleanly if it truly cannot be replaced.
            pass

    target.rename(backup)
    try:
        candidate.replace(target)
    except OSError:
        backup.rename(target)
        raise
    return backup


def cleanup_backups(target: Path | None = None) -> None:
    """Delete the previous build left behind by an update. Never raises."""
    target = target or current_executable()
    if target is None:
        return
    for stale in (backup_path(target), staging_path(target)):
        try:
            if stale.exists():
                stale.unlink()
        except OSError:
            # Still locked, or not ours to remove. It is a few tens of MB and
            # the next launch will try again; failing here would be worse.
            pass


def relaunch(target: Path) -> None:
    """Start the new build detached, so it survives this process exiting."""
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([str(target)], close_fds=True, **kwargs)
