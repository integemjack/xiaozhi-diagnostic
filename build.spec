# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for Xiaozhi Diagnostic Center
import sys
import os

# Bundle certifi's CA root bundle so TLS verification works inside the
# frozen app even on machines whose Python lacks system root certificates.
try:
    from PyInstaller.utils.hooks import collect_data_files
    certifi_datas = collect_data_files('certifi')
except Exception:
    certifi_datas = []

block_cipher = None
name = "XiaozhiDiagnostic"

a = Analysis(
    ['src/main.py'],
    pathex=[],
    binaries=[],
    datas=certifi_datas,
    hiddenimports=['certifi'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'numpy', 'pandas', 'scipy', 'PIL'],
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
    name=name,
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
    icon=None,
)
