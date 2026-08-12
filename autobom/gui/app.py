"""AutoBOM desktop window."""

from __future__ import annotations

import sys
from html import escape
from pathlib import Path

import PySide6
from PySide6.QtCore import Qt, QThread, Signal, qVersion
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..version import build_details
from ..core import build_summary, process, select_sheets, write_workbook
from ..core.models import ProcessResult
from ..core.naming import default_workbook_name
from ..updater import installer
from ..updater.github import (
    RELEASE_PAGE,
    manifest_url,
    UpdateCancelled,
    UpdateInfo,
    check_for_update,
    download_asset,
)
from .widgets import FileDropList, FlagsDialog, describe_flags


class UpdateCheck(QThread):
    """Runs the release check off the UI thread; failures are silent.

    This subclasses QThread and overrides run() rather than using the
    worker-object-plus-moveToThread pattern. That pattern needs something to
    keep a reference to the worker: a local one is garbage collected as soon as
    the launching function returns, the C++ object goes with it, and the check
    silently never runs. Overriding run() leaves nothing to lose track of, and
    the thread reaches the end of run() so `finished` is actually emitted.
    """

    # Not named `finished`; QThread already has a signal by that name.
    checked = Signal(object)

    def run(self) -> None:
        self.checked.emit(check_for_update())


class UpdateInstall(QThread):
    """Download, verify, self-test and swap in a new build.

    Same QThread-subclass shape as UpdateCheck, and for the same reason: a
    worker object with no retained reference gets collected and the work
    silently never happens.
    """

    stage = Signal(str)
    progress = Signal(int, int)  # received, total
    succeeded = Signal(str)  # path of the installed executable
    failed = Signal(str)

    def __init__(self, info: UpdateInfo, target: Path, parent=None) -> None:
        super().__init__(parent)
        self._info = info
        self._target = Path(target)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        staging = installer.staging_path(self._target)
        try:
            self.stage.emit("Downloading…")
            download_asset(
                self._info,
                staging,
                on_progress=lambda got, total: self.progress.emit(got, total),
                should_cancel=lambda: self._cancelled,
            )

            # Checksum is already verified inside download_asset; the self-test
            # is what catches a build that is intact but broken.
            self.stage.emit("Checking the new version…")
            ok, detail = installer.run_selftest(staging)
            if not ok:
                staging.unlink(missing_ok=True)
                self.failed.emit(
                    "The downloaded version failed its own self-test, so it was "
                    "not installed and your current copy is untouched.\n\n" + detail
                )
                return

            self.stage.emit("Installing…")
            installer.swap_in(staging, self._target)
        except UpdateCancelled:
            self.failed.emit("")  # cancelled: no error to report
            return
        except Exception as exc:  # noqa: BLE001 - surface anything, never crash
            Path(staging).unlink(missing_ok=True)
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(str(self._target))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"AutoBOM {__version__}")
        self.resize(1000, 680)
        self._result: ProcessResult | None = None
        self._update_thread: QThread | None = None
        self._install_thread: QThread | None = None
        # An update leaves the previous build beside the new one; it cannot
        # be deleted while it is still running, so it is cleared on launch.
        installer.cleanup_backups()

        self._build_menu()
        self._build_body()
        self._update_ready_state()
        self._start_update_check()

    # -- construction --------------------------------------------------
    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu("&Help")
        update_action = QAction("Check for &updates…", self)
        update_action.triggered.connect(lambda: self._start_update_check(interactive=True))
        help_menu.addAction(update_action)
        about_action = QAction("&About AutoBOM", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _build_body(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)

        intro = QLabel(
            "Drop your bus section BOMs and your IL CSV(s) below, then press "
            "<b>Process</b>. Sheet aluminium is filtered, quantities are multiplied "
            "out, and you get the usual 5-sheet workbook."
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)

        lists = QHBoxLayout()
        self.bom_list = FileDropList(
            "Drop bus section BOMs here\n(8701-01101-I.csv)"
        )
        self.il_list = FileDropList("Drop IL CSVs here\n(IL-8701-011.csv)")
        lists.addWidget(self._file_group("Bus section BOMs", self.bom_list, self._add_boms))
        lists.addWidget(self._file_group("IL CSVs", self.il_list, self._add_ils))
        outer.addLayout(lists, 1)

        controls = QHBoxLayout()
        self.ignore_flags = QCheckBox("Write the workbook even if cross-check flags appear")
        controls.addWidget(self.ignore_flags)
        controls.addStretch(1)
        self.process_button = QPushButton("Process → Save workbook")
        self.process_button.setMinimumWidth(220)
        self.process_button.clicked.connect(self._process)
        controls.addWidget(self.process_button)
        outer.addLayout(controls)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(200)
        self.log.setPlaceholderText("Results and flags appear here.")
        outer.addWidget(self.log)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Ready")

        self.bom_list.files_changed.connect(self._update_ready_state)
        self.il_list.files_changed.connect(self._update_ready_state)

    def _file_group(self, title: str, widget: FileDropList, add_slot) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.addWidget(widget, 1)
        buttons = QHBoxLayout()
        add = QPushButton("Add files…")
        add.clicked.connect(add_slot)
        remove = QPushButton("Remove selected")
        remove.clicked.connect(widget.remove_selected)
        clear = QPushButton("Clear")
        clear.clicked.connect(widget.clear_all)
        for button in (add, remove, clear):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        return group

    # -- file collection -----------------------------------------------
    def _pick(self, caption: str) -> list[Path]:
        names, _ = QFileDialog.getOpenFileNames(self, caption, "", "CSV files (*.csv)")
        return [Path(name) for name in names]

    def _add_boms(self) -> None:
        self.bom_list.add_paths(self._pick("Select bus section BOM CSVs"))

    def _add_ils(self) -> None:
        self.il_list.add_paths(self._pick("Select IL CSVs"))

    def _update_ready_state(self) -> None:
        ready = self.bom_list.count() > 0 and self.il_list.count() > 0
        self.process_button.setEnabled(ready)
        if ready:
            self.statusBar().showMessage(
                f"{self.bom_list.count()} BOM file(s), {self.il_list.count()} IL file(s) loaded"
            )
        elif self.bom_list.count() == 0:
            self.statusBar().showMessage("Add at least one bus section BOM")
        else:
            self.statusBar().showMessage("Add at least one IL CSV")

    # -- processing ----------------------------------------------------
    def _process(self) -> None:
        bom_paths = self.bom_list.paths()
        il_paths = self.il_list.paths()
        self.log.clear()

        try:
            result = process(bom_paths, il_paths)
        except OSError as exc:
            QMessageBox.critical(self, "Could not read files", str(exc))
            return

        self._result = result

        for issue in result.issues:
            self._append(
                f"Skipped {issue.source_file} line {issue.line_number}: {issue.detail}"
            )
        for row in result.excluded:
            self._append(
                f"Excluded {row.source_file} line {row.line_number}: {row.detail}"
            )

        if result.cross_check.has_flags:
            self._append(describe_flags(result.cross_check))
            if not self.ignore_flags.isChecked():
                dialog = FlagsDialog(result.cross_check, self)
                # Blocking: nothing is written until the user answers.
                if dialog.exec() != int(FlagsDialog.DialogCode.Accepted):
                    self.statusBar().showMessage(
                        "Stopped for review — add the missing files and process again"
                    )
                    return

        if not result.parts:
            QMessageBox.warning(
                self,
                "Nothing to write",
                "No sheet aluminium parts survived filtering, so no workbook was created.",
            )
            return

        if result.other_parts:
            self._append(
                f"{len(result.other_parts)} part(s) fell outside the 1/8\" and 3/16\" "
                "windows and are on the Other sheet — please review."
            )

        self._save(result)

    def _default_name(self, result: ProcessResult) -> str:
        """Name the workbook after the job number when every file agrees on one."""
        return default_workbook_name(result.bom_files)

    def _save(self, result: ProcessResult) -> None:
        suggested = str(Path.home() / self._default_name(result))
        name, _ = QFileDialog.getSaveFileName(
            self, "Save workbook", suggested, "Excel workbook (*.xlsx)"
        )
        if not name:
            self.statusBar().showMessage("Save cancelled — nothing was written")
            return
        destination = Path(name)
        if destination.suffix.lower() != ".xlsx":
            destination = destination.with_suffix(".xlsx")

        try:
            write_workbook(result.parts, destination)
        except OSError as exc:
            QMessageBox.critical(self, "Could not save workbook", str(exc))
            return

        counts = {sheet: len(rows) for sheet, rows in select_sheets(result.parts).items()}
        self._append(
            "Wrote " + str(destination) + "\n  "
            + "\n  ".join(f"{sheet}: {count} row(s)" for sheet, count in counts.items())
        )
        self._append("")
        self._append(f"{'Category':<24}{'Line items':>12}{'Pieces':>10}")
        for label, line_items, pieces in build_summary(result.parts):
            self._append(f"{label:<24}{line_items:>12}{pieces:>10}")
        self.statusBar().showMessage(f"Saved {destination.name}")

        box = QMessageBox(self)
        box.setWindowTitle("All done")
        box.setText(
            "All done! Here's your workbook — 5 sheets as usual.\n"
            "Let me know if anything looks off or if you want to run another set."
        )
        box.setInformativeText(str(destination))
        open_folder = box.addButton("Open folder", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is open_folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(destination.parent)))

    def _append(self, text: str) -> None:
        self.log.appendPlainText(text)

    # -- updates -------------------------------------------------------
    def _start_update_check(self, interactive: bool = False) -> None:
        # Only an actually-running check blocks a new one. Testing the
        # attribute alone would wedge the menu item forever if a thread ever
        # failed to report that it had finished.
        if self._update_thread is not None and self._update_thread.isRunning():
            if interactive:
                self.statusBar().showMessage("Already checking for updates…", 4000)
            return

        thread = UpdateCheck(self)
        thread.checked.connect(
            lambda info: self._on_update_checked(info, interactive)
        )
        thread.finished.connect(self._clear_update_thread)
        # Parented to the window and held here, so nothing can be collected
        # while the check is in flight.
        self._update_thread = thread
        thread.start()

    def _clear_update_thread(self) -> None:
        thread, self._update_thread = self._update_thread, None
        if thread is not None:
            thread.deleteLater()

    def _on_update_checked(self, info: UpdateInfo | None, interactive: bool) -> None:
        if info is None:
            if interactive:
                QMessageBox.information(
                    self,
                    "Check for updates",
                    "Could not reach GitHub to check for updates.\n"
                    "AutoBOM works fine offline — this only affects update checks.",
                )
            return
        if not info.available:
            if interactive:
                QMessageBox.information(
                    self, "Check for updates", f"AutoBOM {__version__} is up to date."
                )
            return

        target = installer.current_executable()
        can_install = installer.can_install_in_place(target)

        box = QMessageBox(self)
        box.setWindowTitle("Update available")
        box.setText(
            f"AutoBOM {info.latest_version} is available (you have {__version__})."
        )
        if can_install:
            box.setInformativeText(
                "AutoBOM can download and install it for you, then restart. "
                "The new version is checked and tested before it replaces this one."
            )
        if info.notes:
            box.setDetailedText(info.notes)

        install = None
        if can_install:
            install = box.addButton("Update now", QMessageBox.ButtonRole.AcceptRole)
        open_page = box.addButton(
            "Open download page", QMessageBox.ButtonRole.ActionRole
        )
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        if install is not None:
            box.setDefaultButton(install)
        box.exec()

        clicked = box.clickedButton()
        if install is not None and clicked is install:
            self._install_update(info, target)
        elif clicked is open_page:
            QDesktopServices.openUrl(QUrl(info.release_page or RELEASE_PAGE))

    def _install_update(self, info: UpdateInfo, target: Path) -> None:
        progress = QProgressDialog("Starting…", "Cancel", 0, 100, self)
        progress.setWindowTitle("Updating AutoBOM")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setMinimumDuration(0)

        thread = UpdateInstall(info, target, self)

        def on_progress(received: int, total: int) -> None:
            if total > 0:
                progress.setMaximum(100)
                progress.setValue(int(received * 100 / total))
            else:
                progress.setMaximum(0)  # indeterminate
            progress.setLabelText(
                f"Downloading… {received / 1_048_576:.0f} of {total / 1_048_576:.0f} MB"
                if total
                else f"Downloading… {received / 1_048_576:.0f} MB"
            )

        def on_stage(text: str) -> None:
            progress.setLabelText(text)
            if not text.startswith("Downloading"):
                # Verifying and installing have no measurable progress.
                progress.setMaximum(0)

        def on_failed(message: str) -> None:
            progress.close()
            self._install_thread = None
            if message:  # empty means the user cancelled
                QMessageBox.warning(self, "Update not installed", message)
            else:
                self.statusBar().showMessage("Update cancelled", 4000)

        def on_succeeded(path: str) -> None:
            progress.close()
            self._install_thread = None
            answer = QMessageBox.question(
                self,
                "Update installed",
                f"AutoBOM {info.latest_version} is installed.\n\n"
                "Restart now to use it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                # survived() deliberately waits a moment, so say why.
                self.statusBar().showMessage("Restarting AutoBOM…")
                QApplication.processEvents()
                try:
                    process = installer.relaunch(Path(path))
                except OSError as exc:
                    QMessageBox.warning(
                        self,
                        "Could not restart",
                        "The update is installed — please start AutoBOM again "
                        f"yourself.\n\n{exc}",
                    )
                    return
                if not installer.survived(process):
                    # Already installed, so this is not a failed update; the
                    # user just has to start it themselves.
                    QMessageBox.warning(
                        self,
                        "Could not restart",
                        "The update is installed, but the new version did not "
                        "stay running when it was started automatically.\n\n"
                        "Close AutoBOM and start it again from "
                        f"{Path(path).name}.",
                    )
                    return
                self.close()
                QApplication.quit()

        thread.progress.connect(on_progress)
        thread.stage.connect(on_stage)
        thread.failed.connect(on_failed)
        thread.succeeded.connect(on_succeeded)
        progress.canceled.connect(thread.cancel)

        self._install_thread = thread
        thread.start()

    def closeEvent(self, event) -> None:
        """Let in-flight background work finish so Qt does not warn on teardown."""
        # run() returns on its own once each job completes or times out; quit()
        # would only affect an event loop, which these threads do not run.
        for thread in (self._update_thread, self._install_thread):
            if thread is not None and thread.isRunning():
                thread.wait(3000)
        super().closeEvent(event)

    def about_rows(self) -> list[tuple[str, str]]:
        """Everything identifying this copy, for the About box and support."""
        rows = list(build_details())
        rows.append(("Qt", f"PySide6 {PySide6.__version__} / Qt {qVersion()}"))
        rows.append(("Updates", manifest_url()))
        return rows

    def _show_about(self) -> None:
        rows = self.about_rows()
        table = "".join(
            "<tr>"
            f"<td style='padding-right:14px; vertical-align:top'><b>{escape(label)}</b></td>"
            f"<td style='vertical-align:top'>{escape(value)}</td>"
            "</tr>"
            for label, value in rows
        )

        box = QMessageBox(self)
        box.setWindowTitle("About AutoBOM")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(
            f"<b>AutoBOM {escape(__version__)}</b><br><br>"
            "CNC sheet metal BOM processor.<br>"
            "Filters SHEET,AL rows, multiplies by IL assembly quantities, "
            "classifies by thickness and Trumpf fit, and writes the 5-sheet "
            "workbook.<br><br>"
            f"<table style='font-size:small'>{table}</table>"
        )
        copy = box.addButton("Copy details", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.setDefaultButton(QMessageBox.StandardButton.Ok)
        box.exec()

        if box.clickedButton() is copy:
            # Plain text, so it can be pasted into an email when something is
            # wrong and the question is "which build are you on?".
            QApplication.clipboard().setText(
                "\n".join(f"{label}: {value}" for label, value in rows)
            )
            self.statusBar().showMessage("Build details copied to the clipboard", 4000)


def main(argv: list[str] | None = None) -> int:
    QGuiApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, False)
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("AutoBOM")
    app.setApplicationVersion(__version__)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
