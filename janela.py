# -*- coding: utf-8 -*-
"""Abre a dashboard numa janela nativa (pywebview) em vez de aba de navegador.

Se o pywebview nao estiver instalado (caso raro: modo dev sem a dependencia
extra), cai pro navegador padrao — nunca quebra o app por causa disso, so
perde o acabamento de janela propria. No app empacotado (.dmg), o pywebview
sempre esta la, entao sempre abre como app de verdade.

Importante: webview.start() PRECISA rodar na THREAD PRINCIPAL — e exigencia
do macOS pro loop de eventos da UI nativa (Cocoa), nao e escolha nossa. Por
isso quem chama esta funcao deve subir o servidor HTTP numa thread separada
ANTES de chamar abrir(), e deixar abrir() tomar conta da thread principal.
"""
import threading


def abrir(endereco, subir_servidor, titulo="Tidal Downloader"):
    """subir_servidor: funcao sem argumento que sobe o servidor (blocking) —
    roda numa thread de fundo. abrir() so retorna quando a janela/processo fecha."""
    thread_servidor = threading.Thread(target=subir_servidor, daemon=True)
    thread_servidor.start()

    try:
        import webview
    except ImportError:
        import time
        import webbrowser
        time.sleep(0.6)  # da tempo do servidor subir antes de abrir a aba
        webbrowser.open(endereco)
        # sem janela pra esperar, a thread do servidor e daemon (morre com o
        # processo) — precisa bloquear a principal aqui mesmo, senao o
        # processo encerra na hora e leva o servidor junto. join() numa
        # serve_forever() bloqueia ate o processo ser morto (Ctrl+C/kill),
        # que e exatamente o comportamento que um servidor precisa.
        thread_servidor.join()
        return False

    janela = webview.create_window(
        titulo, endereco,
        width=980, height=820, min_size=(760, 640),
        background_color="#0b0d11",  # mesmo tom do design — evita flash branco ao abrir
    )
    webview.start()
    return True
