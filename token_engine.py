# -*- coding: utf-8 -*-
"""Motor de token do Tidal.

O QUE ESTE ARQUIVO FAZ E O QUE NAO FAZ — leia antes de mexer:

  FAZ:  le o access_token que o proprio app do TIDAL ja emitiu para a sessao
        do dono (fica no storage local do app), confere a validade, e instala
        no formato que o tidal-wave espera.

  NAO FAZ: renovar token sozinho. O client_id que o tidal-wave carrega foi
        revogado pelo Tidal (confirmado em 08/09/2026: o endpoint
        /v1/oauth2/token devolve 401 invalid_client). Sem client valido nao
        existe refresh programatico — e decifrar o segredo do app oficial
        no Keychain para se passar por ele seria contornar controle de
        acesso, coisa que este projeto deliberadamente nao faz.

  CONSEQUENCIA PRATICA: o token so aparece/renova quando o dono TOCA UMA
        FAIXA no app do TIDAL. Medido em 15/09/2026: abrir/focar o app NAO
        renova (janela em foco + tecla espaco => token continuou com o exp
        antigo). Tocar audio de verdade => token novo, validade ~1h45-2h.
        Por isso a dashboard avisa "Abrir TIDAL e tocar uma faixa".
"""
import base64
import datetime
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from platform_paths import tidal_app_dir, tidal_wave_token_path

APP_TIDAL = tidal_app_dir()
TOKEN_TW = tidal_wave_token_path()
JWT = re.compile(rb"eyJ[A-Za-z0-9_\-\.]{60,}")
LIMITE_ARQUIVO = 60 * 1024 * 1024


def _contexto_ssl():
    """Contexto SSL explicito com o certifi que a gente ja empacota.

    Achado em 15/09/2026: `urllib.request` sem isso usa o trust store padrao
    do sistema operacional pra achar certificado raiz — e isso varia de
    maquina pra maquina. Funcionava na maquina de build e falhava calado
    (excecao engolida) numa maquina diferente (o MacBook do dono), fazendo
    o token parecer "vencido" mesmo com um token valido no disco. Apontar
    pro certifi.where() remove essa dependencia do ambiente.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _claims(token):
    """Decodifica o payload do JWT sem validar assinatura (so queremos o exp)."""
    try:
        p = token.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p))
    except Exception:
        return None


def varrer_tokens_do_app():
    """Todos os JWT que o app do TIDAL deixou no storage, do mais novo pro mais velho."""
    achados = {}
    for raiz, _, arquivos in os.walk(APP_TIDAL):
        for nome in arquivos:
            caminho = os.path.join(raiz, nome)
            try:
                if os.path.getsize(caminho) > LIMITE_ARQUIVO:
                    continue
                bruto = open(caminho, "rb").read()
            except OSError:
                continue
            for m in JWT.finditer(bruto):
                t = m.group(0).decode("ascii", "ignore")
                if len(t) >= 200:
                    achados.setdefault(t, os.path.getmtime(caminho))
    return achados


def melhor_token():
    """O token valido com maior validade restante. None se nao houver nenhum."""
    agora = datetime.datetime.now()
    candidatos = []
    for token in varrer_tokens_do_app():
        c = _claims(token)
        if not c or "exp" not in c:
            continue
        exp = datetime.datetime.fromtimestamp(c["exp"])
        if exp > agora:
            candidatos.append((exp, token))
    if not candidatos:
        return None
    candidatos.sort(key=lambda x: x[0], reverse=True)
    exp, token = candidatos[0]
    return {"access_token": token, "expira": exp}


def validar_na_api(token):
    """Confirma na API que o token funciona de verdade. Devolve dados da sessao.

    NUNCA engole a excecao calado — so imprime em stderr (aparece quando o
    app roda pelo Terminal) e devolve None. Foi engolir sem avisar que
    escondeu o bug de certificado SSL do dono por varias rodadas de teste.
    """
    req = urllib.request.Request(
        "https://api.tidal.com/v1/sessions",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        return json.loads(
            urllib.request.urlopen(req, timeout=12, context=_contexto_ssl()).read().decode()
        )
    except Exception as e:
        print(f"[token_engine] validar_na_api falhou: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def token_instalado():
    """Le o token que esta instalado para o tidal-wave. None se nao houver."""
    if not os.path.exists(TOKEN_TW):
        return None
    try:
        d = json.loads(base64.b64decode(open(TOKEN_TW).read().strip()).decode())
    except Exception:
        return None
    exp = d.get("expiration")
    if not exp:
        return None
    try:
        e = datetime.datetime.fromisoformat(exp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return {"expira": e.astimezone().replace(tzinfo=None), "dados": d}


def instalar(token, exp, sessao):
    """Grava o token no formato do tidal-wave.

    O campo `expiration` precisa ser real e futuro: o tidal-wave checa ele antes
    de usar e, se achar que venceu, tenta o refresh — que falha com o client
    revogado e derruba o download inteiro.
    """
    os.makedirs(os.path.dirname(TOKEN_TW), exist_ok=True)
    payload = {
        "access_token": token,
        "client_name": sessao.get("client", {}).get("name", ""),
        "expiration": exp.astimezone(datetime.timezone.utc).isoformat(),
        "refresh_token": "",
        "user_id": sessao.get("userId"),
        "user_name": "",
    }
    with open(TOKEN_TW, "w") as fh:
        fh.write(base64.b64encode(json.dumps(payload).encode()).decode())
    return payload


def estado(margem_minutos=15):
    """Estado do token para a dashboard.

    Devolve sempre um dict com:
      situacao: 'ok' | 'acabando' | 'vencido'
      minutos:  quanto falta (0 se vencido)
      mensagem: o que mostrar na tela
    """
    agora = datetime.datetime.now()
    instalado = token_instalado()

    # se o instalado ainda tem folga, nao precisa mexer em nada
    if instalado and instalado["expira"] > agora + datetime.timedelta(minutes=margem_minutos):
        restante = int((instalado["expira"] - agora).total_seconds() // 60)
        return {
            "situacao": "ok",
            "minutos": restante,
            "expira": instalado["expira"].strftime("%H:%M"),
            "mensagem": f"Token válido até {instalado['expira'].strftime('%H:%M')}",
        }

    # senao, procura um mais novo no app do TIDAL
    novo = melhor_token()
    if novo:
        sessao = validar_na_api(novo["access_token"])
        if sessao:
            instalar(novo["access_token"], novo["expira"], sessao)
            restante = int((novo["expira"] - agora).total_seconds() // 60)
            situacao = "ok" if restante > margem_minutos else "acabando"
            return {
                "situacao": situacao,
                "minutos": restante,
                "expira": novo["expira"].strftime("%H:%M"),
                "mensagem": f"Token válido até {novo['expira'].strftime('%H:%M')}",
            }

    # nao ha token utilizavel — so o dono resolve
    if instalado and instalado["expira"] > agora:
        restante = int((instalado["expira"] - agora).total_seconds() // 60)
        return {
            "situacao": "acabando",
            "minutos": restante,
            "expira": instalado["expira"].strftime("%H:%M"),
            "mensagem": f"Token vence em {restante} min — abra o TIDAL e toque uma faixa",
        }
    return {
        "situacao": "vencido",
        "minutos": 0,
        "expira": None,
        "mensagem": "Abrir TIDAL e tocar uma faixa",
    }
