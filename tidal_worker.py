#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Worker de 1 download — roda como PROCESSO separado, de proposito.

Por que nao chamar tidal_engine.baixar_faixa() direto na thread do servidor:
perderiamos o timeout forcado. Uma conexao que trava (socket morto, sem
timeout no lado do requests/cachecontrol que o tidal-wave usa) travaria o
worker inteiro sem jeito limpo de matar uma thread Python. Como processo
separado, o pai mata com subprocess.TimeoutExpired + kill de verdade.

Entrada:  tidal_worker.py <track_id> <pasta_destino>
Saida:    UMA linha JSON em stdout: {"ok": true, "arquivo": "..."}
                                 ou {"ok": false, "token": true|false, "erro": "..."}
Todo log do tidal-wave vai pro logging (WARNING+), nunca pro stdout — o
stdout tem que ficar limpo pra essa unica linha JSON.

Este mesmo arquivo roda em dois contextos:
  dev:       `python3 tidal_worker.py <id> <destino>`      (chamado por downloader.py)
  empacotado: o app re-executa a si mesmo com `--tidal-worker <id> <destino>`
              (ver app_main.py) — sys.executable dentro do .app NAO e um
              python de uso geral, entao nao da pra apontar pra este arquivo
              por caminho; o proprio binario do app precisa reconhecer a flag.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def rodar(track_id, destino):
    import tidal_engine
    try:
        caminho = tidal_engine.baixar_faixa(track_id, destino)
        print(json.dumps({"ok": True, "arquivo": str(caminho)}))
    except tidal_engine.ErroToken as e:
        print(json.dumps({"ok": False, "token": True, "erro": str(e)}))
    except Exception as e:
        print(json.dumps({"ok": False, "token": False, "erro": str(e)[:300]}))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(json.dumps({"ok": False, "token": False, "erro": "uso: tidal_worker.py <id> <destino>"}))
        sys.exit(1)
    rodar(sys.argv[1], sys.argv[2])
