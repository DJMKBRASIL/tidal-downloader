#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ponto de entrada do app empacotado (.app/.dmg).

Dois modos, despachados por sys.argv, ANTES de qualquer outra coisa:

  --tidal-worker <id> <destino>
      Modo worker: baixa 1 faixa, imprime JSON, sai. E assim que
      downloader.py invoca um download quando roda dentro do app —
      sys.executable dentro do bundle E este mesmo binario (nao um python
      generico), entao o app se re-executa com essa flag em vez de apontar
      pra um tidal_worker.py que nao existiria como arquivo solto.

  (nada)
      Modo normal: sobe o servidor da dashboard numa janela nativa
      (pywebview) — sem aba de navegador, ⌘Q fecha o app de verdade.

A ordem importa: o despacho do worker tem que vir ANTES de importar
`servidor` (que, so de ser importado, ja cria a Fila e a thread do worker —
nao queremos isso rodando dentro de um processo que deveria so baixar 1
faixa e sair).
"""
import os
import sys

BASE_FROZEN = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(sys.executable))
sys.path.insert(0, BASE_FROZEN)


def modo_worker():
    import tidal_worker
    tidal_worker.rodar(sys.argv[2], sys.argv[3])


def modo_normal():
    import servidor  # cria a Fila e registra as rotas HTTP ao importar
    # (servidor.py detecta sys._MEIPASS sozinho e resolve BASE/CONFIG certo)
    import janela

    endereco = f"http://127.0.0.1:{servidor.PORTA}"

    def subir_servidor():
        with servidor.Servidor(("127.0.0.1", servidor.PORTA), servidor.Handler) as httpd:
            httpd.serve_forever()

    # webview.start() toma conta da thread principal (exigencia do macOS);
    # o servidor HTTP sobe numa thread de fundo dentro de janela.abrir()
    janela.abrir(endereco, subir_servidor)


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--tidal-worker":
        modo_worker()
    else:
        modo_normal()
