# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all
PROJ = os.path.abspath(os.path.dirname(SPEC))
datas = [(os.path.join(PROJ, "index.html"), "."), (os.path.join(PROJ, "ffmpeg.exe"), "ffmpeg-bin")]
binaries, hiddenimports = [], []
for pacote in ("tidal_wave", "mutagen", "Crypto", "certifi", "cachecontrol", "platformdirs", "typer", "click", "requests", "rich", "msgpack", "filelock", "shellingham", "webview"):
    d, b, h = collect_all(pacote)
    datas += d; binaries += b; hiddenimports += h
a = Analysis([os.path.join(PROJ, "app_main.py")], pathex=[PROJ], binaries=binaries, datas=datas, hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="TidalDownloader", debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="TidalDownloader")
