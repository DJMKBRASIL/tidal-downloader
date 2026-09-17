#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Servidor local da dashboard do Tidal Downloader.

Sobe em http://127.0.0.1:8777 — so escuta em localhost, de proposito: isso
aqui mexe com o token da conta do dono, nao pode ficar exposto na rede.

Rodar:  python3 servidor.py
"""
import json
import os
import socketserver
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler

# dentro do app empacotado, __file__ nao aponta pra um caminho real (o
# codigo vive compactado dentro do binario) — sys._MEIPASS e onde o
# PyInstaller extrai os `datas` (index.html, config.json vai ser criado ali).
# Em modo dev (`python3 servidor.py`), _MEIPASS nao existe e cai no caminho
# normal de sempre.
BASE = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import downloader  # noqa: E402
import token_engine  # noqa: E402
from platform_paths import app_data_dir, reveal_file  # noqa: E402

PORTA = 8777

# estado gravavel: dentro do app empacotado, BASE (=_MEIPASS) nao e lugar pra
# escrever — e conteudo da distribuicao, nao dado do usuario. Padrao macOS
# pra isso e ~/Library/Application Support/<App>. Em modo dev, continua ao
# lado do script mesmo (mais facil de inspecionar durante o desenvolvimento).
if getattr(sys, "_MEIPASS", None):
    ESTADO_DIR = app_data_dir()
else:
    ESTADO_DIR = BASE

CONFIG = os.path.join(ESTADO_DIR, "config.json")

DESTINOS_CANDIDATOS = ([
    "/Volumes/Musicas Externas/Downloads Dashboard",
    os.path.join(ESTADO_DIR, "download"),
] if sys.platform == "darwin" else [os.path.join(ESTADO_DIR, "download")])


def carregar_config():
    if os.path.exists(CONFIG):
        try:
            return json.load(open(CONFIG))
        except Exception:
            pass
    return {}


def salvar_config(cfg):
    json.dump(cfg, open(CONFIG, "w"), ensure_ascii=False, indent=1)


def destino_inicial():
    cfg = carregar_config()
    if cfg.get("destino") and os.path.isdir(os.path.dirname(cfg["destino"].rstrip("/"))):
        os.makedirs(cfg["destino"], exist_ok=True)
        return cfg["destino"]
    for cand in DESTINOS_CANDIDATOS:
        pai = os.path.dirname(cand.rstrip("/"))
        if os.path.isdir(pai):
            os.makedirs(cand, exist_ok=True)
            return cand
    os.makedirs(DESTINOS_CANDIDATOS[-1], exist_ok=True)
    return DESTINOS_CANDIDATOS[-1]


def definir_destino(novo):
    """Muda a pasta de destino e persiste no config.json. Usado tanto pelo
    diálogo nativo (/api/escolher_pasta) quanto pelo campo de texto manual
    (/api/destino) — os dois caem aqui pra não duplicar a lógica."""
    os.makedirs(novo, exist_ok=True)
    FILA.definir_destino(novo)
    cfg = carregar_config()
    cfg["destino"] = novo
    salvar_config(cfg)


FILA = downloader.Fila(destino_inicial())


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=BASE, **kw)

    def log_message(self, *a):
        pass  # silencia o log de acesso; o que importa sai na dashboard

    def _json(self, dados, status=200):
        corpo = json.dumps(dados, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            self.path = "/index.html"
            return super().do_GET()
        if self.path == "/api/estado":
            destino_ok = os.path.isdir(FILA.destino)
            return self._json({
                "token": token_engine.estado(),
                "fila": FILA.listar(),
                "destino": FILA.destino,
                "destino_ok": destino_ok,
            })
        return super().do_GET()

    def do_POST(self):
        tamanho = int(self.headers.get("Content-Length", 0))
        try:
            corpo = json.loads(self.rfile.read(tamanho).decode() or "{}")
        except Exception:
            return self._json({"erro": "JSON inválido"}, 400)

        if self.path == "/api/baixar":
            entradas = corpo.get("links", "")
            linhas = [l.strip() for l in str(entradas).splitlines() if l.strip()]
            if not linhas:
                return self._json({"erro": "Cole ao menos um link"}, 400)
            aceitos, recusados = 0, []
            for linha in linhas:
                qtd, erro = FILA.adicionar(linha)
                if qtd:
                    aceitos += qtd
                else:
                    recusados.append(f"{linha[:60]}: {erro}")
            return self._json({"aceitos": aceitos, "recusados": recusados})

        if self.path == "/api/limpar":
            FILA.limpar_concluidos()
            return self._json({"ok": True})

        if self.path == "/api/destino":
            novo = (corpo.get("destino") or "").strip()
            if not novo:
                return self._json({"erro": "Informe uma pasta"}, 400)
            try:
                definir_destino(novo)
            except OSError as e:
                return self._json({"erro": str(e)}, 400)
            return self._json({"ok": True, "destino": novo})

        if self.path == "/api/escolher_pasta":
            # dialogo NATIVO do Finder, via pywebview — so existe quando a
            # dashboard roda dentro da janela do app (nao em navegador comum).
            # o JS sabe cair pro prompt() de texto se vier "sem_janela_nativa".
            try:
                import webview
            except ImportError:
                return self._json({"erro": "sem_janela_nativa"})
            if not webview.windows:
                return self._json({"erro": "sem_janela_nativa"})
            inicial = FILA.destino if os.path.isdir(FILA.destino) else ""
            resultado = webview.windows[0].create_file_dialog(
                webview.FileDialog.FOLDER, directory=inicial,
            )
            if not resultado:
                return self._json({"ok": False, "cancelado": True})
            novo = resultado[0]
            try:
                definir_destino(novo)
            except OSError as e:
                return self._json({"erro": str(e)}, 400)
            return self._json({"ok": True, "destino": novo})

        if self.path == "/api/revelar":
            caminho = (corpo.get("arquivo") or "").strip()
            if not caminho or not os.path.exists(caminho):
                return self._json({"erro": "Arquivo não encontrado (foi movido ou apagado?)"}, 400)
            reveal_file(caminho)
            return self._json({"ok": True})

        return self._json({"erro": "rota desconhecida"}, 404)


class Servidor(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    import janela

    endereco = f"http://127.0.0.1:{PORTA}"
    print(f"Tidal Downloader em {endereco}")
    print(f"Destino: {FILA.destino}")

    def subir_servidor():
        with Servidor(("127.0.0.1", PORTA), Handler) as httpd:
            httpd.serve_forever()

    try:
        if not janela.abrir(endereco, subir_servidor):
            print("(pywebview não instalado — abrindo no navegador; "
                  "`pip install pywebview` pra janela nativa também em modo dev)")
    except KeyboardInterrupt:
        print("\nencerrado")
