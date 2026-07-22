# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec para sa SportsBet Pro (dual-panel Polymarket + Kalshi).

Build:
    .\\venv\\Scripts\\python.exe -m PyInstaller --noconfirm SportsBetPro.spec

Bago mag-build (isang beses lang):
    .\\venv\\Scripts\\python.exe -m pip install pyinstaller
    .\\venv\\Scripts\\python.exe -m pip uninstall -y PyQt6 PyQt6-Qt6 PyQt6_sip
    (Ang finplot ay humihila ng PyQt6 — tanggalin; ayaw ng PyInstaller ng
     dalawang Qt binding, at baka doon kumapit ang qtawesome sa runtime.)

Output: dist/SportsBetPro/  (i-zip ang buong folder para i-distribute)
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = []
# finplot: nagre-register ng pandas plotting backend via dynamic import
hiddenimports += collect_submodules('finplot')
# cryptography: Kalshi RSA-PSS signing (mga backend modules)
hiddenimports += collect_submodules('cryptography')
# Polymarket CLOB V2 client
hiddenimports += collect_submodules('py_clob_client_v2')
# keyring Windows backend + win32ctypes (Credential Manager)
hiddenimports += [
    'keyring.backends.Windows',
    'keyring.backends.chainer',
    'win32ctypes.core',
    'win32ctypes.core.cffi',
]

datas = [
    ('icon_square.png', '.'),
    ('assets', 'assets'),
]
datas += collect_data_files('qtawesome')  # Font Awesome glyph fonts
datas += collect_data_files('tzdata')     # ET timezone (zoneinfo sa Windows)


a = Analysis(
    ['src\\main.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt6', 'PyQt5'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SportsBetPro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SportsBetPro',
)
