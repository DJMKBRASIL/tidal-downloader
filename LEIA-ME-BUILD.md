# Como gerar o .dmg

```bash
cd "/Volumes/SSD NVME 2TB/Projetos Antigravity/Tidal Downloader"

# 1. venv de build (uma vez só, ou quando as dependências mudarem)
python3 -m venv build_mac/venv
build_mac/venv/bin/pip install tidal-wave mutagen pyinstaller

# 2. empacotar
rm -rf build_mac/build build_mac/dist
build_mac/venv/bin/pyinstaller --distpath build_mac/dist --workpath build_mac/build \
  --noconfirm build_mac/TidalDownloader.spec

# 3. gerar o .dmg
rm -rf build_mac/dmg_staging build_mac/TidalDownloader.dmg
mkdir -p build_mac/dmg_staging
cp -R "build_mac/dist/Tidal Downloader.app" build_mac/dmg_staging/
ln -s /Applications build_mac/dmg_staging/Applications
hdiutil create -volname "Tidal Downloader" -srcfolder build_mac/dmg_staging \
  -ov -format UDZO build_mac/TidalDownloader.dmg
```

## Arquitetura: só arm64

O build está fixado em `target_arch="arm64"` no spec (`TidalDownloader.spec`).
**Se alguma das duas máquinas for Intel, este `.dmg` não abre nela** — precisa
gerar um build `x86_64` separado (trocar `target_arch` e rodar de novo numa
máquina Intel, ou usar `universal2` se o Python usado for universal2 — o
Python do `python3.org`/Homebrew geralmente não é).

**Testado nas duas máquinas.** No Mac mini (build): `.app` rodando de local
novo (simulando instalação), downloads reais em FLAC com ffmpeg vendorizado,
conferido pelo arquivo final. No MacBook (15/09/2026), a primeira instalação
travou em "Abrir TIDAL e tocar uma faixa" mesmo com token válido — bug de
certificado SSL específico de rodar em máquina diferente da de build, não de
arquitetura/assinatura. Ver `CLAUDE.md` (regra do `_contexto_ssl()`) antes de
supor "não testamos aí" de novo — testamos, e o bug real já está mapeado.

## Por que o app roda sem Python/ffmpeg instalados

- **Python + todas as dependências** (tidal_wave, Crypto, certifi, requests,
  cachecontrol, typer, mutagen) vão dentro do bundle via PyInstaller —
  `Contents/Frameworks/`.
- **ffmpeg vendorizado**: o `tidal_wave` PRECISA de ffmpeg pra remuxar o
  áudio decriptado (`track.py:440-462` — isso é obrigatório em toda faixa
  FLAC, não é só o bug do `%`). Em vez de vendorizar o ffmpeg do Homebrew
  (que arrasta ~20 dylibs de codecs que a gente nem usa — x264, aom, etc.,
  já que só fazemos cópia de bitstream), usamos o binário estático do pacote
  PyPI `imageio-ffmpeg`: **zero dependências externas**, só linka contra
  frameworks do próprio macOS (confirmado com `otool -L`). Extraído uma vez
  pra `build_mac/assets/ffmpeg` — não precisa reinstalar `imageio-ffmpeg`
  pra rebuildar, só se quiser atualizar a versão do ffmpeg.
- **`tidal_engine.py`** prepend a pasta do ffmpeg vendorizado no `PATH`
  quando roda empacotado (`sys._MEIPASS` existe); em modo dev usa o do
  Homebrew normalmente.

## Por que existe `tidal_worker.py` em vez de chamar tudo na thread do servidor

Rodar o download `tidal-wave` **em processo separado** (não como função
chamada direto na thread) preserva o `timeout` forçado — uma conexão que
trava não tem como ser morta de dentro de uma thread Python (não existe
`thread.kill()` limpo no stdlib). Como processo, o pai mata com
`subprocess.TimeoutExpired`.

Só que dentro do app empacotado não existe mais um `python3` genérico pra
apontar num script solto — `sys.executable` É o próprio binário do app. Por
isso `downloader.py` decide o comando do worker por `sys.frozen`:

- **dev**: `[sys.executable, "tidal_worker.py", id, destino]`
- **empacotado**: `[sys.executable, "--tidal-worker", id, destino]` — o app
  se re-executa a si mesmo, e `build_mac/app_main.py` reconhece essa flag
  ANTES de importar `servidor.py` (que cria a fila e abriria o navegador de
  novo se deixasse passar).

## Onde o app guarda estado

Dentro do bundle é conteúdo read-only (reinstalável, não é lugar de guardar
nada do usuário). `servidor.py` detecta `sys._MEIPASS` e usa
`~/Library/Application Support/Tidal Downloader/` pro `config.json` e pra
pasta de download de fallback (quando o SSD de músicas não está montado) —
padrão macOS. Em modo dev continua ao lado do próprio script, sem mudança.

## Se o build quebrar depois de atualizar tidal-wave

Antes de reinstalar a venv com uma versão nova, confira se o bug do `%`
continua no mesmo lugar e se a assinatura de `main()`/`AudioFormat` não
mudou — isso já mudou de `2025.10.1` pra `2025.11.1` durante este build sem
quebrar nada, mas não é garantido pra sempre:

```bash
grep -n "_cmd % tf.name" build_mac/venv/lib/python3.12/site-packages/tidal_wave/track.py
grep -n "^def main\|tidal_url:\|audio_format:\|output_directory:\|loglevel:\|no_extra_files:" \
  build_mac/venv/lib/python3.12/site-packages/tidal_wave/main.py
```

Se a assinatura mudou, `tidal_engine.py` (`baixar_faixa()`) precisa acompanhar.
