# Tidal Downloader

Dashboard local (Python + HTML) que baixa faixa/álbum/playlist do Tidal em
FLAC lossless, com janela nativa (pywebview) e empacotável em `.dmg`
(PyInstaller). `LEIA-ME.md` é pro usuário; `build_mac/LEIA-ME-BUILD.md` tem a
arquitetura do empacotamento (ffmpeg vendorizado, por que o download roda
como processo separado que se re-executa, como gerar o `.dmg`) — leia aquele
antes de mexer no build. Este arquivo é só o que não está lá.

## Regra ativa — toda chamada de rede usa `token_engine._contexto_ssl()`

**Nunca chame `urllib.request.urlopen(req, timeout=N)` sem `context=`.**

Achado em 15/09/2026, custou várias rodadas de troubleshooting remoto: sem
contexto SSL explícito, `urllib` usa o trust-store padrão do sistema
operacional pra achar certificado raiz — e isso varia de máquina pra máquina.
Funcionava sempre na máquina de build (Mac mini) e falhava **calado** numa
máquina diferente (o MacBook do dono), fazendo o token parecer vencido mesmo
com um token válido de verdade no disco (confirmado lendo os mesmos arquivos
via SMB: token com `exp` futuro, e o app local mesmo assim reportando
"vencido"). Pior: o `except Exception: return None` escondia a exceção real —
o terminal ficava quieto, o que fez o diagnóstico demorar ainda mais.

Correção: `token_engine._contexto_ssl()` monta um `ssl.create_default_context(
cafile=certifi.where())` explícito, usando o certifi que já vai empacotado
via `collect_all` no `.spec`. Toda função que chama a API do Tidal
(`token_engine.validar_na_api`, `downloader.info_da_faixa`,
`downloader._faixas_de_colecao`) já usa isso — se adicionar uma chamada nova,
reusar essa função, não reinventar. E nenhuma chamada de rede aqui deve ter
`except Exception: return None` sem pelo menos um `print(..., file=sys.stderr)`
— foi exatamente isso que escondeu o bug. **Confirmado corrigido no MacBook
em 15/09/2026** (testado de verdade, não só no Mac mini de build).

## API do Tidal usada

Playlist e álbum usam o MESMO formato: `GET /v1/{playlists,albums}/{id}` +
`GET /v1/{playlists,albums}/{id}/tracks?countryCode=BR&limit=100&offset=N`
(pagina de verdade — testado até 500 numa chamada só, mas não dá pra confiar
nisso sempre). `downloader._faixas_de_colecao()` já unifica os dois.

Diferença na detecção do link: **playlist é UUID, álbum é número** —
`RE_PLAYLIST`/`RE_ALBUM` em `downloader.py` dependem só do formato do ID, sem
heurística. Um álbum de **1 faixa só** é como o Tidal representa um single
lançado fora de playlist — foi relatado pelo dono como "música solta" e
inicialmente caía em "link inválido" porque só `track`/`playlist` eram
reconhecidos (corrigido 15/09/2026).

## Token — ver docstring, não duplicar aqui

A lógica de onde o token vem, por que não renova sozinho (client_id revogado
pelo Tidal) e o que foi medido sobre quando ele de fato renova está no
docstring de `token_engine.py` (topo do arquivo) e `downloader.py` (topo do
arquivo) — leia ali antes de mexer nesse fluxo.
