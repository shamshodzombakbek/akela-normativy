# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

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
    "desktop_sync",
    "desktop_sync.config_store",
    "desktop_sync.worker",
    "desktop_sync.background",
    "desktop_sync.gui",
    # Selenium 4 lazy-imports — без явного списка exe падает на webdriver.Chrome
    "selenium",
    "selenium.webdriver",
    "selenium.webdriver.chrome",
    "selenium.webdriver.chrome.webdriver",
    "selenium.webdriver.chrome.options",
    "selenium.webdriver.chrome.service",
    "selenium.webdriver.chrome.remote_connection",
    "selenium.webdriver.common",
    "selenium.webdriver.common.by",
    "selenium.webdriver.common.keys",
    "selenium.webdriver.common.service",
    "selenium.webdriver.common.options",
    "selenium.webdriver.common.desired_capabilities",
    "selenium.webdriver.remote",
    "selenium.webdriver.remote.webdriver",
    "selenium.webdriver.remote.remote_connection",
    "selenium.webdriver.remote.webelement",
    "webdriver_manager",
    "webdriver_manager.chrome",
    "webdriver_manager.core",
    "webdriver_manager.core.driver_cache",
    "webdriver_manager.core.manager",
    "webdriver_manager.core.os_manager",
]

datas = [
    (os.path.join(ROOT, "data"), "data"),
]
binaries = []

for pkg in ("selenium", "webdriver_manager", "certifi"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas += pkg_datas
        binaries += pkg_binaries
        hidden += pkg_hidden
    except Exception:
        hidden += collect_submodules(pkg)

# unique, preserve order
_seen = set()
hidden_unique = []
for name in hidden:
    if name not in _seen:
        _seen.add(name)
        hidden_unique.append(name)
hidden = hidden_unique

a = Analysis(
    [os.path.join(ROOT, "desktop_sync", "gui.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
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
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
