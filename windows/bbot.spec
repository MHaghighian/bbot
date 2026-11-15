# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for a standalone Windows bbot.exe (no admin/UAC required)

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None
root = Path(SPECPATH).resolve().parent

datas = []
binaries = []
hiddenimports = [
    "bbot",
    "bbot.cli",
    "bbot.scanner",
    "bbot.modules",
    "httpx",
    "httpcore",
    "anyio",
    "h11",
    "socksio",
    "tzdata",
    "yara",
    "blastdns",
    "cloudcheck",
    "radixtarget",
    "mmh3",
    "orjson",
    "zstandard",
    "setproctitle",
    "wordninja",
]

# Bundle BBOT package data (presets, wordlists, module yaml, etc.)
pkg_datas, pkg_binaries, pkg_hidden = collect_all("bbot")
datas += pkg_datas
binaries += pkg_binaries
hiddenimports += pkg_hidden

for pkg in ("tzdata", "certifi", "cloudcheck", "blastdns", "yara", "wordninja"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        hiddenimports += collect_submodules(pkg)

# wordninja ships its dictionary as package data next to the module
wordninja_dir = root / ".venv" / "Lib" / "site-packages" / "wordninja"
if wordninja_dir.is_dir():
    for f in wordninja_dir.iterdir():
        if f.is_file():
            datas.append((str(f), "wordninja"))

a = Analysis(
    [str(root / "bbot" / "cli.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(Path(SPECPATH) / "pyi_rth_bbot.py")],
    excludes=["ansible", "ansible_runner", "blasthttp", "maturin"],
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
    name="bbot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
