"""The update check must actually run, and must keep working after the first.

Regression cover for a bug where "Check for updates" appeared to do nothing:
the worker object was a local with no retained reference, so Python collected
it before the thread could call it. The check never ran, the thread never
finished, and the in-flight guard then blocked every later attempt forever.
"""

from __future__ import annotations

import os
import time

import pytest

# Must be set before any Qt GUI object exists.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from autobom.gui import app as appmod  # noqa: E402
from autobom.updater.github import UpdateInfo  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.fixture
def window(qapp, monkeypatch):
    """A window whose update check is instrumented and never touches the network."""
    calls: list[tuple[object, bool]] = []
    monkeypatch.setattr(
        appmod.MainWindow,
        "_on_update_checked",
        lambda self, info, interactive: calls.append((info, interactive)),
    )
    win = appmod.MainWindow()
    win.calls = calls
    yield win
    win.close()


def pump(qapp, predicate, timeout=10.0):
    """Spin the event loop until predicate holds, or give up."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def offline(monkeypatch):
    monkeypatch.setattr(appmod, "check_for_update", lambda *a, **k: None)


def available(monkeypatch):
    info = UpdateInfo(
        current_version="1.0.0",
        current_build_id="1.aaaaaaa",
        latest_version="1.0.0",
        latest_build_id="9.bbbbbbb",
        url="https://example.invalid/AutoBOM.exe",
    )
    monkeypatch.setattr(appmod, "check_for_update", lambda *a, **k: info)
    return info


class TestAutomaticCheck:
    def test_runs_on_launch(self, qapp, monkeypatch):
        offline(monkeypatch)
        calls: list = []
        monkeypatch.setattr(
            appmod.MainWindow,
            "_on_update_checked",
            lambda self, info, interactive: calls.append((info, interactive)),
        )
        win = appmod.MainWindow()
        try:
            assert pump(qapp, lambda: len(calls) >= 1), "startup check never reported"
            assert calls[0][1] is False  # not interactive
        finally:
            win.close()

    def test_thread_is_released_afterwards(self, qapp, window, monkeypatch):
        offline(monkeypatch)
        assert pump(qapp, lambda: window._update_thread is None), (
            "the thread never finished, which wedges every later check"
        )


class TestInteractiveCheck:
    def test_menu_check_reports_a_result(self, qapp, window, monkeypatch):
        offline(monkeypatch)
        pump(qapp, lambda: window._update_thread is None)
        window.calls.clear()

        window._start_update_check(interactive=True)
        assert pump(qapp, lambda: any(c[1] for c in window.calls)), (
            "Check for updates did nothing"
        )

    def test_can_be_used_repeatedly(self, qapp, window, monkeypatch):
        offline(monkeypatch)
        pump(qapp, lambda: window._update_thread is None)

        for attempt in range(3):
            window.calls.clear()
            window._start_update_check(interactive=True)
            assert pump(qapp, lambda: any(c[1] for c in window.calls)), (
                f"check {attempt + 1} did nothing"
            )
            pump(qapp, lambda: window._update_thread is None)

    def test_passes_the_update_through(self, qapp, window, monkeypatch):
        info = available(monkeypatch)
        pump(qapp, lambda: window._update_thread is None)
        window.calls.clear()

        window._start_update_check(interactive=True)
        assert pump(qapp, lambda: any(c[1] for c in window.calls))
        delivered = [call for call in window.calls if call[1]][0][0]
        assert delivered is info
        assert delivered.available is True

    def test_a_second_check_while_one_runs_is_ignored_not_wedged(
        self, qapp, window, monkeypatch
    ):
        offline(monkeypatch)
        pump(qapp, lambda: window._update_thread is None)

        window._start_update_check(interactive=True)
        window._start_update_check(interactive=True)  # must not raise or deadlock
        assert pump(qapp, lambda: window._update_thread is None)
        # And the menu still works afterwards.
        window.calls.clear()
        window._start_update_check(interactive=True)
        assert pump(qapp, lambda: any(c[1] for c in window.calls))


class TestShutdown:
    def test_closing_during_a_check_does_not_hang(self, qapp, monkeypatch):
        offline(monkeypatch)
        win = appmod.MainWindow()
        win.show()
        win.close()  # must return promptly even with a check in flight
        assert pump(qapp, lambda: True)
