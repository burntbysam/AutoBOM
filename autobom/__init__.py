"""AutoBOM - CNC sheet metal BOM processor."""

# Deliberately does NOT re-export a name `version`: that would shadow the
# `autobom.version` submodule, so `from autobom import version` would hand back
# a function and `version.build_info` would fail confusingly.
from .version import build_details, build_id, build_info, describe, version as _version

__version__ = _version()

__all__ = ["__version__", "build_details", "build_id", "build_info", "describe"]
