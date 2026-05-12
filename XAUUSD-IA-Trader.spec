# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('configs', 'configs')]
binaries = []
hiddenimports = ['xauusd_ia_trader', 'xauusd_ia_trader.ai', 'xauusd_ia_trader.broker', 'xauusd_ia_trader.cli', 'xauusd_ia_trader.config', 'xauusd_ia_trader.execution', 'xauusd_ia_trader.gui', 'xauusd_ia_trader.indicators', 'xauusd_ia_trader.models', 'xauusd_ia_trader.notifier', 'xauusd_ia_trader.regime', 'xauusd_ia_trader.risk', 'xauusd_ia_trader.state_store', 'xauusd_ia_trader.trader', 'tkinter', 'tkinter.ttk', 'yaml', 'pandas', 'numpy', 'requests', 'dotenv']
tmp_ret = collect_all('xauusd_ia_trader')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='XAUUSD-IA-Trader',
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
