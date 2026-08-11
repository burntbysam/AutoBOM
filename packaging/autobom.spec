# PyInstaller spec for AutoBOM.
#
# Build a Windows executable ON WINDOWS (PyInstaller does not cross-compile):
#     pip install -r requirements.txt pyinstaller
#     pyinstaller packaging/autobom.spec
# The result is dist/AutoBOM.exe -- a single file the shop can copy anywhere.

from pathlib import Path

block_cipher = None

ROOT = Path(SPECPATH).resolve().parent

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    # VERSION ships inside the bundle so the updater can compare against it.
    datas=[(str(ROOT / "VERSION"), ".")],
    hiddenimports=["autobom.gui.app", "autobom.cli"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Qt modules the app never touches; excluding them roughly halves the bundle.
    excludes=[
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuick3D",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtMultimedia",
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="AutoBOM",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # Windowed: no console flashes up behind the GUI.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
