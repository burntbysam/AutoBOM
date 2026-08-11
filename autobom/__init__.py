"""AutoBOM - CNC sheet metal BOM processor."""

from pathlib import Path

_VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"

try:
    __version__ = _VERSION_FILE.read_text(encoding="utf-8").strip()
except OSError:  # running from a frozen bundle without the source tree
    __version__ = "0.0.0"
