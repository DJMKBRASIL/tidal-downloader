# Tidal Downloader — dashboard local

Cole o link da faixa OU da playlist, baixa em FLAC lossless. Roda só em
`127.0.0.1:8777` (localhost de propósito: mexe com o token da conta, não pode
ficar exposto).

**Playlist inteira**: cole o link (`tidal.com/browse/playlist/<uuid>`) que
todas as faixas entram na fila de uma vez — cada uma passa pelo MESMO
pipeline de uma faixa avulsa (dedup contra a fila atual, retry automático se
o token vencer no meio, nome limpo `Artista - Título.flac`). Não existe
"modo playlist" separado por baixo, é só um jeito mais rápido de encher a
fila. Testado com playlists de 15 e 18 faixas, download real conferido.

**Pasta de destino**: clique em `trocar` abre o Finder de verdade (diálogo
nativo) dentro do app instalado. Em modo dev sem `pywebview` instalado, cai
pro campo de texto de sempre.

**Abrir local**: toda faixa concluída tem um botão que revela o arquivo no
Finder.

## Abrir

**App instalável (.dmg)** — `build_mac/TidalDownloader.dmg`: arrasta pro
`Applications`, abre como qualquer app. Não precisa de Python nem ffmpeg
instalado — tudo vem dentro. Só arm64 (Apple Silicon); ver
`build_mac/LEIA-ME-BUILD.md` se alguma máquina for Intel.

Ou, sem instalar nada, do jeito de sempre — duplo clique em
**`Abrir Tidal Downloader.command`** (sobe o servidor e abre o navegador
sozinho), ou pelo terminal:

```bash
python3 "/Volumes/SSD NVME 2TB/Projetos Antigravity/Tidal Downloader/servidor.py"
```

Pra fechar o modo `.command`/terminal: `Ctrl+C`. O app instalado fecha pelo
próprio menu (⌘Q) — ele roda o mesmo motor por dentro.

## O token — leia isto, é o único ponto que precisa de você

A dashboard **não renova o token sozinha**, e isso não é limitação de
implementação: é decisão.

- O `client_id` que o `tidal-wave` carrega foi **revogado pelo Tidal**
  (verificado em 08/09/2026: `/v1/oauth2/token` responde `401 invalid_client`).
  Sem client válido, não existe refresh programático.
- O app oficial do TIDAL guarda o refresh_token dele **criptografado**, com a
  chave no Keychain do macOS (`TIDAL Safe Storage`). Decifrar isso para se
  passar pelo app oficial seria contornar controle de acesso — este projeto
  **não faz isso de propósito**.

O que sobra, e é o que está implementado: o app do TIDAL emite um token quando
**toca áudio de verdade**. A dashboard lê esse token e usa.

**Medido em 15/09/2026:** abrir ou focar o app **não** renova (testado: janela
em foco + tecla espaço → token continuou com o `exp` antigo). **Tocar uma
faixa** → token novo, validade de ~1h45 a 2h.

Por isso os três estados na faixa de status:

| cor | quando | o que fazer |
|---|---|---|
| 🟢 verde | token com mais de 15 min | nada |
| 🟡 amarelo | menos de 15 min | tocar algo no TIDAL quando puder |
| 🔴 vermelho | vencido | **Abrir TIDAL e tocar uma faixa** |

Se o token vencer no meio da fila, os itens vão para `aguardando token` e o
worker **retoma sozinho** assim que um token novo aparecer — não precisa
recolocar nada.

## Arquivos

| arquivo | serve para |
|---|---|
| `servidor.py` | servidor HTTP + rotas da API |
| `token_engine.py` | acha, valida e instala o token do app do TIDAL |
| `downloader.py` | fila e worker de download |
| `tw_patch.py` | contorna o bug do `%` no `tidal-wave` (ver abaixo) |
| `index.html` | a dashboard |
| `config.json` | guarda a pasta de destino escolhida |

## O bug do `%` — não remova o `tw_patch.py`

O `tidal-wave` quebra em `track.py:740` quando o nome do álbum ou do artista
tem `%` — ele monta o comando do ffmpeg com `_cmd % tf.name` e o `%` do nome é
lido como formatação:

```
TypeError: not enough arguments for format string
```

Pegou, por exemplo, o álbum *"Meu Nome Não é Igor %"* (Mc IG) e o artista
*"DJ Mandrake 100% Original"* — 20 downloads seguidos falharam por isso em
08/09/2026. O `remux` só reembute a capa, e o FLAC **já sai completo e com
capa** antes dele; por isso neutralizar essa etapa não perde nada.

## Destino

Padrão: `/Volumes/Musicas Externas/Downloads Dashboard` se o SSD estiver
montado, senão a pasta `download/` aqui dentro. Dá para trocar clicando em
`trocar` na dashboard — fica salvo no `config.json`.

Se o SSD cair no meio, a dashboard mostra `⚠ pasta indisponível` e os
downloads falham com o motivo — não silenciosamente.

## Windows

Existe um build separado em `build_windows/`. Ele deve ser executado em uma
máquina Windows, que gera `build_windows/dist/TidalDownloader/TidalDownloader.exe`.
O primeiro teste precisa ser feito com o TIDAL para Windows instalado e uma
faixa tocada, pois o local do token pode variar conforme a versão do aplicativo.
