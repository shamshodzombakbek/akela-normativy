# -*- mode: python ; coding: utf-8 -*-
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

block_cipher = None

hidden = [
    "pandas",
    "openpyxl",
    "xlrd",
    "google.oauth2",
    "google.auth",
    "google.auth.transport.requests",
    "requests",
    "tzdata",
    "zoneinfo",
    "bitrix_api",
    "bitrix_disk",
    "bitrix_fetch",
    "shared_store",
    "google_store",
    "schedule",
    "utils",
    "bitrix_selenium",
    "selenium",
    "webdriver_manager",
    "desktop_sync",
    "desktop_sync.config_store",
    "desktop_sync.worker",
    "desktop_sync.background",
    "desktop_sync.gui",
]

a = Analysis(
    [os.path.join(ROOT, "desktop_sync", "gui.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, "data"), "data"),
    ],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["streamlit", "matplotlib", "plotly", "tkinter.test"],
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
    name="AkelaNormativSync",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
