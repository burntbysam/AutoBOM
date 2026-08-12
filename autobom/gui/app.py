"""AutoBOM desktop window."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
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
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..core import build_summary, process, select_sheets, write_workbook
from ..core.models import ProcessResult
from ..updater.github import RELEASE_PAGE, UpdateInfo, check_for_update
from .widgets import FileDropList, FlagsDialog, describe_flags


class UpdateWorker(QObject):
    """Runs the release check off the UI thread; failures are silent."""

    finished = Signal(object)

    def run(self) -> None:
        self.finished.emit(check_for_update())


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"AutoBOM {__version__}")
        self.resize(1000, 680)
        self._result: ProcessResult | None = None
        self._update_thread: QThread | None = None

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
        jobs = {Path(name).stem.split("-")[0] for name in result.bom_files}
        if len(jobs) == 1:
            return f"{jobs.pop()}_BOM_Quantities.xlsx"
        return "BOM_Quantities.xlsx"

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
        if self._update_thread is not None:
            return
        thread = QThread(self)
        worker = UpdateWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda info: self._on_update_checked(info, interactive))
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._clear_update_thread)
        self._update_thread = thread
        thread.start()

    def _clear_update_thread(self) -> None:
        if self._update_thread is not None:
            self._update_thread.deleteLater()
        self._update_thread = None

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

        box = QMessageBox(self)
        box.setWindowTitle("Update available")
        box.setText(
            f"AutoBOM {info.latest_version} is available (you have {__version__})."
        )
        if info.notes:
            box.setDetailedText(info.notes)
        open_page = box.addButton("Open download page", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_page:
            QDesktopServices.openUrl(QUrl(info.release_page or RELEASE_PAGE))

    def closeEvent(self, event) -> None:
        """Let an in-flight update check finish so Qt does not warn on teardown."""
        thread = self._update_thread
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(2000)
        super().closeEvent(event)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About AutoBOM",
            f"<b>AutoBOM {__version__}</b><br><br>"
            "CNC sheet metal BOM processor.<br>"
            "Filters SHEET,AL rows, multiplies by IL assembly quantities, "
            "classifies by thickness and Trumpf fit, and writes the 5-sheet workbook.",
        )


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
