"""AutoBOM - CNC sheet metal BOM processor."""

from .version import build_id, build_info, describe, version

__version__ = version()

__all__ = ["__version__", "build_id", "build_info", "describe", "version"]
