# -*- mode: python ; coding: utf-8 -*-
"""Spec do PyInstaller para o Tidal Downloader.

Roda com:  build_mac/venv/bin/pyinstaller build_mac/TidalDownloader.spec
(a partir da pasta do projeto — os caminhos abaixo sao relativos a ela)
"""
import os
from PyInstaller.utils.hooks import collect_all

PROJ = os.path.abspath(".")

# collect_all() devolve tuplas no formato 2-elementos que Analysis() espera
# receber PRONTO em datas=/binaries=/hiddenimports= — nao da pra anexar
# depois em a.datas (ja normalizado pra 3 elementos pelo proprio Analysis).
datas = [
    (os.path.join(PROJ, "index.html"), "."),
    (os.path.join(PROJ, "build_mac", "assets", "ffmpeg"), "ffmpeg-bin"),
]
binaries = []
hiddenimports = []

# coleta ampla de proposito: pacotes com C-extensions/dados (Crypto,
# certifi) e os que o tidal-wave usa por baixo silenciosamente costumam
# escapar da deteccao automatica do PyInstaller — melhor sobrar que faltar
# e o app quebrar so na hora do download de verdade.
for pacote in ("tidal_wave", "mutagen", "Crypto", "certifi", "cachecontrol",
               "platformdirs", "typer", "click", "requests", "rich",
               "msgpack", "filelock", "shellingham",
               "webview", "objc", "Cocoa", "WebKit", "Quartz",
               "PyObjCTools"):
    d, b, h = collect_all(pacote)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [os.path.join(PROJ, "build_mac", "app_main.py")],
    pathex=[PROJ],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TidalDownloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    target_arch="arm64",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="TidalDownloader",
)

app = BUNDLE(
    coll,
    name="Tidal Downloader.app",
    icon=os.path.join(PROJ, "build_mac", "assets", "icon.icns"),
    bundle_identifier="br.com.djmk.tidaldownloader",
    info_plist={
        "CFBundleName": "Tidal Downloader",
        "CFBundleShortVersionString": "1.0.0",
        "NSHighResolutionCapable": True,
        "LSUIElement": False,
    },
)
