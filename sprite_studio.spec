# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for FNF Sprite Studio."""

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        "PIL._tkinter_finder",
        "PySide6.QtSvg",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "scipy"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="FNF-Sprite-Studio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # UPX breaks some Qt/PIL combos - keep it off
    console=False,       # GUI app - no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
