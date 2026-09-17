"""Caminhos e ações dependentes do sistema operacional."""
import os
import subprocess
import sys

def app_data_dir():
    if sys.platform == "win32":
        raiz = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
    elif sys.platform == "darwin":
        raiz = os.path.expanduser("~/Library/Application Support")
    else:
        raiz = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    caminho = os.path.join(raiz, "Tidal Downloader")
    os.makedirs(caminho, exist_ok=True)
    return caminho

def tidal_app_dir():
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return os.path.join(local, "TIDAL")
    return os.path.expanduser("~/Library/Application Support/TIDAL")

def tidal_wave_token_path():
    if sys.platform == "win32":
        raiz = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
        return os.path.join(raiz, "tidal-wave", "fire_tv-tidal.token")
    return os.path.expanduser("~/Library/Application Support/tidal-wave/fire_tv-tidal.token")

def reveal_file(path):
    if sys.platform == "win32":
        subprocess.run(["explorer.exe", "/select,", os.path.normpath(path)], check=False)
    elif sys.platform == "darwin":
        subprocess.run(["open", "-R", path], check=False)
    else:
        subprocess.run(["xdg-open", os.path.dirname(path)], check=False)
