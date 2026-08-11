"""PyInstaller entry script.

The bundle cannot use ``autobom/__main__.py`` directly: PyInstaller runs the
entry script as a top-level ``__main__`` with no package, so the relative
imports inside it fail. Importing the module by its full name keeps the
package context intact.
"""

import sys

from autobom.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
