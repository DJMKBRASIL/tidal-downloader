# -*- coding: utf-8 -*-
"""Fila de download do Tidal.

Um worker unico consome a fila em ordem. Cada item passa por:
  pendente -> baixando -> concluido | falhou | aguardando_token

`aguardando_token` nao e erro: e o item esperando o dono tocar uma faixa no
TIDAL. Quando o token volta, o worker retoma sozinho de onde parou — foi o
combinado com o dono em 15/09/2026 ("avisa e retoma sozinho no segundo
seguinte", em vez de prometer renovacao automatica que nao existe).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import deque

import token_engine

BASE = os.path.dirname(os.path.abspath(__file__))
WORKER = os.path.join(BASE, "tidal_worker.py")


def _comando_worker(track_id, destino):
    """Como invocar o worker — muda se estivermos rodando empacotado (.app).

    Empacotado, sys.executable É o proprio binario do app (nao um python de
    uso geral), entao nao da pra apontar pra tidal_worker.py por caminho —
    o app se re-executa com um sinalizador que ele mesmo reconhece
    (ver app_main.py, que despacha --tidal-worker antes de subir o servidor).
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--tidal-worker", track_id, destino]
    return [sys.executable, WORKER, track_id, destino]

# aceita tidal.com/browse/track/123, tidal.com/track/123, listen.tidal.com/track/123
RE_TRACK = re.compile(r"tidal\.com/(?:browse/)?track/(\d+)")
# playlist e identificada por UUID, nao numero: tidal.com/browse/playlist/<uuid>
RE_PLAYLIST = re.compile(
    r"tidal\.com/(?:browse/)?playlist/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)
# album — inclui singles (album de 1 faixa so, e como o Tidal representa uma
# musica "solta" lancada fora de playlist/album de verdade). Link real
# observado: tidal.com/album/547868147/u — o /u no final e sufixo de
# compartilhamento, o (?:/.*)? no fim absorve isso sem quebrar.
RE_ALBUM = re.compile(r"tidal\.com/(?:browse/)?album/(\d+)")
RE_ID_PURO = re.compile(r"^\d+$")


def extrair_alvo(entrada):
    """Devolve ('faixa', id), ('playlist', uuid), ('album', id) ou (None, None)."""
    entrada = (entrada or "").strip()
    m = RE_PLAYLIST.search(entrada)
    if m:
        return "playlist", m.group(1)
    m = RE_ALBUM.search(entrada)
    if m:
        return "album", m.group(1)
    m = RE_TRACK.search(entrada)
    if m:
        return "faixa", m.group(1)
    if RE_ID_PURO.match(entrada):
        return "faixa", entrada
    return None, None


def nome_limpo(texto):
    texto = texto.replace("/", "-").replace(":", "-")
    return re.sub(r"\s+", " ", texto).strip(" .")[:180]


def info_da_faixa(track_id):
    """Nome/artista pela API. Devolve (info, erro_legivel).

    Distinguir o 404 importa: faixa removida do catalogo do Tidal e coisa
    normal (aconteceu com a 388654883, que baixou em 11/09 e sumiu em 15/09).
    Sem isso, a tela mostrava log cru do tidal-wave e parecia bug nosso.
    """
    inst = token_engine.token_instalado()
    if not inst:
        return None, None
    tok = inst["dados"].get("access_token")
    req = urllib.request.Request(
        f"https://api.tidal.com/v1/tracks/{track_id}?countryCode=BR",
        headers={"Authorization": f"Bearer {tok}"},
    )
    try:
        d = json.loads(
            urllib.request.urlopen(req, timeout=12, context=token_engine._contexto_ssl())
            .read().decode()
        )
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, "Faixa não existe mais no Tidal (404)"
        if e.code in (401, 403):
            return None, "__token__"
        return None, f"Tidal respondeu HTTP {e.code}"
    except Exception as e:
        print(f"[downloader] info_da_faixa falhou: {type(e).__name__}: {e}", file=sys.stderr)
        return None, None
    if not d.get("streamReady", True):
        return None, "Faixa indisponível para streaming na sua região"
    return {
        "titulo": d.get("title", ""),
        "artista": ", ".join(a["name"] for a in d.get("artists", [])),
        "qualidade": d.get("audioQuality", ""),
        "duracao": d.get("duration", 0),
    }, None


def _faixas_de_colecao(tipo_api, colecao_id, rotulo):
    """Lista todas as faixas de uma playlist OU album — mesmo formato de API
    dos dois lados (/v1/{playlists,albums}/{id}[/tracks]), so muda o path.
    Pagina de verdade (testado ate 500 faixas numa chamada so, mas nao da
    pra confiar nisso pra sempre). Devolve ({"nome":..., "faixas":[...]},
    None) ou (None, erro)."""
    inst = token_engine.token_instalado()
    if not inst:
        return None, "__token__"
    tok = inst["dados"].get("access_token")

    def req(url):
        r = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
        return json.loads(
            urllib.request.urlopen(r, timeout=15, context=token_engine._contexto_ssl())
            .read().decode()
        )

    try:
        meta = req(f"https://api.tidal.com/v1/{tipo_api}/{colecao_id}?countryCode=BR")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, f"{rotulo} não existe mais no Tidal (404)"
        if e.code in (401, 403):
            return None, "__token__"
        return None, f"Tidal respondeu HTTP {e.code}"
    except Exception as e:
        return None, str(e)[:200]

    nome = meta.get("title") or rotulo
    faixas, offset, pagina = [], 0, 100
    while True:
        try:
            d = req(
                f"https://api.tidal.com/v1/{tipo_api}/{colecao_id}/tracks"
                f"?countryCode=BR&limit={pagina}&offset={offset}"
            )
        except Exception as e:
            return None, f"falhou ao listar faixas ({rotulo.lower()}): {e}"
        itens = d.get("items", [])
        faixas.extend(itens)
        offset += len(itens)
        if not itens or len(itens) < pagina or offset >= d.get("totalNumberOfItems", offset):
            break
    return {"nome": nome, "faixas": faixas}, None


def faixas_da_playlist(playlist_id):
    return _faixas_de_colecao("playlists", playlist_id, "Playlist")


def faixas_do_album(album_id):
    return _faixas_de_colecao("albums", album_id, "Álbum")


class Fila:
    def __init__(self, destino):
        self.destino = destino
        self.itens = {}
        self.ordem = deque()
        self.lock = threading.Lock()
        self.worker = threading.Thread(target=self._rodar, daemon=True)
        self.worker.start()

    # ---------- API usada pelo servidor ----------

    def adicionar(self, entrada):
        """Aceita link/ID de faixa, playlist OU album. Devolve (qtd_aceita, erro).

        Playlist/album expandem em N chamadas de _adicionar_faixa — cada
        faixa vira um item normal na fila, passando pelo MESMO pipeline de
        sempre (dedup, worker, retry em aguardando_token). Nao existe um
        "modo coleção" separado por baixo — e so um jeito mais rapido de
        encher a fila com varias faixas de uma vez. Album inclui singles
        (album de 1 faixa so) — e como o Tidal representa uma musica lançada
        fora de playlist, o que o dono chama de "música solta".
        """
        tipo, alvo = extrair_alvo(entrada)
        if tipo is None:
            return 0, "Link inválido — cole a URL de uma faixa, álbum ou playlist do Tidal"

        if tipo in ("playlist", "album"):
            buscar = faixas_da_playlist if tipo == "playlist" else faixas_do_album
            rotulo = "playlist" if tipo == "playlist" else "álbum"
            resultado, erro = buscar(alvo)
            if erro == "__token__":
                return 0, "Sessão do Tidal vencida — abra o TIDAL e toque uma faixa"
            if erro:
                return 0, erro
            aceitas = 0
            for faixa in resultado["faixas"]:
                ok, _ = self._adicionar_faixa(
                    str(faixa["id"]),
                    titulo=faixa.get("title", ""),
                    artista=", ".join(a["name"] for a in faixa.get("artists", [])),
                )
                if ok:
                    aceitas += 1
            if aceitas == 0:
                return 0, f"{rotulo} \"{resultado['nome']}\" — todas as {len(resultado['faixas'])} faixas já estavam na fila"
            return aceitas, None

        ok, erro = self._adicionar_faixa(alvo)
        return (1 if ok else 0), erro

    def _adicionar_faixa(self, track_id, titulo="", artista=""):
        with self.lock:
            for it in self.itens.values():
                if it["track_id"] == track_id and it["situacao"] in ("pendente", "baixando", "aguardando_token"):
                    return False, "Essa faixa já está na fila"
            item_id = uuid.uuid4().hex[:8]
            self.itens[item_id] = {
                "id": item_id,
                "track_id": track_id,
                "titulo": titulo,
                "artista": artista,
                "situacao": "pendente",
                "detalhe": "",
                "arquivo": "",
                "criado": time.time(),
            }
            self.ordem.append(item_id)
        return True, None

    def listar(self):
        with self.lock:
            return sorted(self.itens.values(), key=lambda x: -x["criado"])

    def limpar_concluidos(self):
        with self.lock:
            for k in [k for k, v in self.itens.items() if v["situacao"] in ("concluido", "falhou")]:
                del self.itens[k]

    def definir_destino(self, caminho):
        self.destino = caminho

    # ---------- worker ----------

    def _proximo(self):
        with self.lock:
            while self.ordem:
                item_id = self.ordem.popleft()
                it = self.itens.get(item_id)
                if it and it["situacao"] in ("pendente", "aguardando_token"):
                    return it
        return None

    def _rodar(self):
        while True:
            item = self._proximo()
            if not item:
                time.sleep(1.5)
                continue

            estado_token = token_engine.estado()
            if estado_token["situacao"] == "vencido":
                # devolve pra fila e espera o dono tocar algo no TIDAL
                with self.lock:
                    item["situacao"] = "aguardando_token"
                    item["detalhe"] = "Esperando token — abra o TIDAL e toque uma faixa"
                    self.ordem.appendleft(item["id"])
                time.sleep(10)
                continue

            self._baixar(item)

    def _baixar(self, item):
        with self.lock:
            item["situacao"] = "baixando"
            item["detalhe"] = ""

        info, erro = info_da_faixa(item["track_id"])
        if info:
            with self.lock:
                item["titulo"] = info["titulo"]
                item["artista"] = info["artista"]
        elif erro == "__token__":
            with self.lock:
                item["situacao"] = "aguardando_token"
                item["detalhe"] = "Token venceu — abra o TIDAL e toque uma faixa"
                self.ordem.appendleft(item["id"])
            return
        elif erro:
            # erro definitivo do catalogo: nao adianta chamar o tidal-wave
            with self.lock:
                item["situacao"] = "falhou"
                item["detalhe"] = erro
            return

        if not os.path.isdir(self.destino):
            with self.lock:
                item["situacao"] = "falhou"
                item["detalhe"] = f"Destino não existe: {self.destino}"
            return

        tmp = tempfile.mkdtemp(prefix="tidal_dl_")
        try:
            proc = subprocess.run(
                _comando_worker(item["track_id"], tmp),
                capture_output=True, timeout=600, text=True,
            )
            resultado = None
            # a ultima linha nao-vazia do stdout e o JSON (log do tidal-wave, se
            # algum escapar, vai antes; nunca depois — ver tidal_engine.preparar)
            for linha in reversed(proc.stdout.strip().splitlines()):
                try:
                    resultado = json.loads(linha)
                    break
                except json.JSONDecodeError:
                    continue

            if not resultado or not resultado.get("ok"):
                motivo = (resultado or {}).get("erro") or proc.stderr.strip()[-200:] or "worker não respondeu"
                token_suspeito = bool((resultado or {}).get("token"))
                with self.lock:
                    if token_suspeito:
                        item["situacao"] = "aguardando_token"
                        item["detalhe"] = "Token venceu no meio — abra o TIDAL e toque uma faixa"
                        self.ordem.appendleft(item["id"])
                    else:
                        item["situacao"] = "falhou"
                        item["detalhe"] = motivo
                return

            origem = resultado["arquivo"]
            ext = os.path.splitext(origem)[1].lower()
            if info and info["artista"]:
                base = nome_limpo(f"{info['artista']} - {info['titulo']}")
            else:
                base = nome_limpo(os.path.splitext(os.path.basename(origem))[0])
            alvo = os.path.join(self.destino, base + ext)
            if os.path.exists(alvo):
                with self.lock:
                    item["situacao"] = "concluido"
                    item["detalhe"] = "Já existia no destino"
                    item["arquivo"] = alvo
                return
            shutil.move(origem, alvo)
            with self.lock:
                item["situacao"] = "concluido"
                item["arquivo"] = alvo
                item["detalhe"] = f"{os.path.getsize(alvo) / 1048576:.1f} MB"
        except subprocess.TimeoutExpired:
            with self.lock:
                item["situacao"] = "falhou"
                item["detalhe"] = "Tempo esgotado (10 min)"
        except Exception as e:
            with self.lock:
                item["situacao"] = "falhou"
                item["detalhe"] = str(e)[:180]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
