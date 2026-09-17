# -*- coding: utf-8 -*-
"""Motor de download do Tidal — chama o tidal-wave EM PROCESSO, sem subprocess.

Por que em processo: um app empacotado (.app/.dmg) nao tem um "python3" generico
para invocar via subprocess.run([sys.executable, ...]) como fazia a versao
anterior (tw_patch.py chamado por fora) — sys.executable dentro do bundle É o
proprio executavel nativo do app, nao um interpretador de uso geral. Chamar
tidal_wave.main.main() direto funciona igual em modo dev (`python3 servidor.py`)
e dentro do app empacotado — mesmo codigo, dois contextos.

Dois ajustes obrigatorios antes de qualquer download, feitos por preparar():

1. Remux neutralizado (bug do '%' — ver README): tidal_wave/track.py:740 monta
   `_cmd % tf.name` para reembutir a capa via ffmpeg; quebra quando o nome do
   album ou artista tem '%' (ex.: albuns "Meu Nome Nao e Igor %",
   "DJ Mandrake 100% Original" — 20 downloads seguidos falharam por isso em
   08/09/2026). O FLAC ja sai completo e com capa (gravada pelo mutagen) ANTES
   do remux, entao desligar essa etapa nao perde nada.

2. ffmpeg no PATH: tidal_wave/track.py:440-462 usa ffmpeg (via `import ffmpeg`,
   o pacote ffmpeg-python) para remuxar o audio decriptado — isso e OBRIGATORIO
   em toda faixa FLAC, nao e so o bug do '%'. Em modo dev o ffmpeg do Homebrew
   ja esta no PATH do sistema. No app empacotado, vendorizamos o binario
   estatico do pacote `imageio-ffmpeg` (zero dependencias externas — testado
   em 15/09/2026, so linka contra frameworks do proprio macOS) dentro de
   Resources/ffmpeg-bin/, e prependemos essa pasta ao PATH aqui.
"""
import os
import sys
import logging
from pathlib import Path

_PREPARADO = False


def _dir_ffmpeg_vendorizado():
    """Onde o ffmpeg embutido fica dentro do app empacotado, se existir."""
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        # modo dev (python3 servidor.py direto) — nao ha vendorizado, usa o do sistema
        return None
    candidato = os.path.join(base, "ffmpeg-bin")
    return candidato if os.path.isdir(candidato) else None


def preparar():
    """Monkeypatch do remux + PATH do ffmpeg. Idempotente — chame quantas vezes quiser."""
    global _PREPARADO
    if _PREPARADO:
        return
    from tidal_wave import track as tw_track
    tw_track.Track.remux = lambda self, *a, **k: None

    vendorizado = _dir_ffmpeg_vendorizado()
    if vendorizado:
        os.environ["PATH"] = vendorizado + os.pathsep + os.environ.get("PATH", "")

    logging.basicConfig(
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        level=logging.WARNING,  # so queremos erro/aviso real, nao o debug do tidal-wave
    )
    _PREPARADO = True


class ErroToken(Exception):
    """Sinaliza que a falha parece ser de autenticacao — quem chama decide o que fazer."""


def baixar_faixa(track_id, destino_dir):
    """Baixa 1 faixa em FLAC lossless para destino_dir. Devolve o Path do arquivo.

    Levanta ErroToken se a falha cheira a autenticacao (login() devolveu sessao
    nula, ou nem existe token instalado), ou RuntimeError com o motivo, para
    qualquer outra falha.
    """
    preparar()

    # confere pela NOSSA fonte de verdade antes de chamar o tidal-wave: sem
    # isso, token ausente (primeira execucao, ou apagado no meio) faz o
    # tidal-wave tentar um fluxo de login interativo por conta propria e
    # quebrar com uma excecao dificil de distinguir (visto em teste real,
    # 15/09/2026 — token ausente gerou FileNotFoundError la dentro, sem
    # chegar a virar um "sessao invalida" limpo).
    import token_engine
    if not token_engine.token_instalado():
        raise ErroToken("nenhum token instalado")

    import typer
    from tidal_wave.login import AudioFormat, LogLevel
    from tidal_wave.main import main as tw_main

    antes = _listar_flacs(destino_dir)
    try:
        tw_main(
            tidal_url=f"https://tidal.com/browse/track/{track_id}",
            audio_format=AudioFormat.lossless,
            output_directory=Path(destino_dir),
            loglevel=LogLevel.warning,
            no_extra_files=True,
        )
    except typer.Exit as e:
        if e.exit_code not in (0, None):
            raise ErroToken(f"tidal-wave saiu com código {e.exit_code} — provável sessão vencida")
    except Exception as e:
        raise RuntimeError(str(e)) from e

    depois = _listar_flacs(destino_dir)
    novos = depois - antes
    if not novos:
        raise RuntimeError("tidal-wave não gerou nenhum arquivo novo")
    # pode ter mais de um novo se a pasta ja tinha coisa sendo escrita em paralelo;
    # pega o mais recente
    return Path(max(novos, key=os.path.getmtime))


def _listar_flacs(destino_dir):
    out = set()
    for raiz, _, arquivos in os.walk(destino_dir):
        for f in arquivos:
            if f.lower().endswith((".flac", ".m4a", ".mp3")):
                out.add(os.path.join(raiz, f))
    return out
