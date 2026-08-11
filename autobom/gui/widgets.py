"""Reusable widgets: a drop-target file list and the blocking flag dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from ..core.models import CrossCheck


class FileDropList(QListWidget):
    """A list of CSV paths that accepts drag-and-drop from the file manager."""

    files_changed = Signal()

    def __init__(self, placeholder: str, parent=None) -> None:
        super().__init__(parent)
        self._placeholder = placeholder
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(True)

    # -- drag and drop -------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if not event.mimeData().hasUrls():
            super().dropEvent(event)
            return
        paths: list[Path] = []
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_dir():
                paths.extend(sorted(path.glob("*.csv")))
            elif path.suffix.lower() == ".csv":
                paths.append(path)
        self.add_paths(paths)
        event.acceptProposedAction()

    # -- contents ------------------------------------------------------
    def add_paths(self, paths: list[Path]) -> int:
        """Add paths, skipping duplicates. Returns how many were new."""
        existing = {str(path) for path in self.paths()}
        added = 0
        for path in paths:
            resolved = Path(path).resolve()
            if str(resolved) in existing:
                continue
            existing.add(str(resolved))
            item = QListWidgetItem(resolved.name)
            item.setData(Qt.ItemDataRole.UserRole, str(resolved))
            item.setToolTip(str(resolved))
            self.addItem(item)
            added += 1
        if added:
            self.files_changed.emit()
        return added

    def remove_selected(self) -> None:
        for item in self.selectedItems():
            self.takeItem(self.row(item))
        self.files_changed.emit()

    def clear_all(self) -> None:
        self.clear()
        self.files_changed.emit()

    def paths(self) -> list[Path]:
        return [
            Path(self.item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(self.count())
        ]

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.count() == 0:
            painter_target = self.viewport()
            from PySide6.QtGui import QPainter

            painter = QPainter(painter_target)
            painter.setPen(self.palette().placeholderText().color())
            painter.drawText(
                painter_target.rect().adjusted(12, 12, -12, -12),
                int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                self._placeholder,
            )
            painter.end()


class FlagsDialog(QDialog):
    """PHASE 3's mandatory stop, rendered as a modal the user must answer."""

    def __init__(self, cross_check: CrossCheck, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("⚠️ FLAGS — REVIEW REQUIRED")
        self.setMinimumSize(620, 420)

        layout = QVBoxLayout(self)
        heading = QLabel("⚠️ FLAGS — REVIEW REQUIRED")
        heading.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(heading)

        summary = QLabel(
            "The cross-check found assemblies that do not line up between your "
            "bus section BOMs and your IL. Nothing has been written yet."
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        detail = QTextEdit()
        detail.setReadOnly(True)
        detail.setPlainText(describe_flags(cross_check))
        layout.addWidget(detail, 1)

        buttons = QDialogButtonBox()
        self._add_files = buttons.addButton(
            "Add missing files", QDialogButtonBox.ButtonRole.RejectRole
        )
        self._ignore = buttons.addButton(
            "Ignore and continue", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._add_files.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def describe_flags(cross_check: CrossCheck) -> str:
    """Plain-language explanation of both flag types, per the SPEC."""
    blocks: list[str] = []

    if cross_check.boms_without_il:
        blocks.append(
            "FLAG 1 — Bus section BOMs with no matching assembly on the IL\n"
            "These BOM files were handed in, but no IL line references them, so "
            "there is no assembly quantity to multiply by. Their parts are NOT in "
            "the workbook.\n"
            + "\n".join(f"    • {name}" for name in cross_check.boms_without_il)
        )

    if cross_check.il_without_bom:
        blocks.append(
            "FLAG 2 — IL assemblies with no matching bus section BOM\n"
            "The IL calls for these assemblies, but no BOM file was supplied for "
            "them, so their sheet metal is NOT counted in the workbook. These are "
            "assemblies that need their own BOM — 300-series and JB parts are "
            "individual parts and are counted automatically, so they never appear "
            "here. Add the missing BOM CSVs.\n"
            + "\n".join(f"    • {name}" for name in cross_check.il_without_bom)
        )

    if not blocks:
        return "No flags."
    return "\n\n".join(blocks)
