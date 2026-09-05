#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lê o banco 📓 LOG — Audiovisual (Notion) e grava logs.json.

Cada página do banco vira uma caixinha na aba LOG do painel: o título é o
nome da caixinha, e o conteúdo da página aparece quando ela é aberta.

Só a biblioteca padrão do Python — nada para instalar.

Variáveis de ambiente:
  NOTION_TOKEN    obrigatório — o mesmo token da integração do painel
  NOTION_LOG_DB   opcional — id do banco de LOG; sem ele, o script sai sem
                  erro e grava uma lista vazia (o painel segue funcionando,
                  a aba LOG só aparece vazia)

Tolerante por desenho: qualquer erro grava logs.json vazio e sai com
código 1 — o passo fica vermelho no GitHub, mas o painel continua de pé.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=-3))
API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

MAX_LOGS = 200          # caixinhas no painel
MAX_BLOCOS = 150        # blocos lidos por página — o suficiente para uma nota


def req(metodo, caminho, token, payload=None):
    dados = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(
        API + caminho, data=dados, method=metodo,
        headers={"Authorization": "Bearer " + token,
                 "Notion-Version": NOTION_VERSION,
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=60) as resp:
        return json.loads(resp.read().decode())


def texto_rico(rt):
    return "".join(x.get("plain_text", "") for x in (rt or []))


def texto_do_bloco(b):
    """Extrai o texto de um bloco. Tipos sem texto voltam None."""
    t = b.get("type")
    corpo = b.get(t) or {}
    if t in ("paragraph", "quote", "callout", "toggle",
             "bulleted_list_item", "numbered_list_item", "to_do"):
        txt = texto_rico(corpo.get("rich_text"))
        if t in ("bulleted_list_item", "numbered_list_item"):
            txt = "• " + txt if txt else txt
        if t == "to_do":
            txt = ("☑ " if corpo.get("checked") else "☐ ") + txt
        return txt or None
    if t in ("heading_1", "heading_2", "heading_3"):
        txt = texto_rico(corpo.get("rich_text"))
        return ("§ " + txt) if txt else None
    if t == "divider":
        return "―――"
    if t == "code":
        return texto_rico(corpo.get("rich_text")) or None
    return None


def corpo_da_pagina(pid, token):
    linhas, cursor, lidos = [], None, 0
    while lidos < MAX_BLOCOS:
        caminho = "/blocks/%s/children?page_size=100" % pid
        if cursor:
            caminho += "&start_cursor=" + cursor
        d = req("GET", caminho, token)
        for b in d.get("results", []):
            lidos += 1
            txt = texto_do_bloco(b)
            if txt:
                linhas.append(txt)
        if not d.get("has_more"):
            break
        cursor = d.get("next_cursor")
    return "\n".join(linhas)


def main():
    token = os.environ.get("NOTION_TOKEN", "").strip()
    db = os.environ.get("NOTION_LOG_DB", "").strip()

    saida = {"gerado_em": datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S-03:00"),
             "logs": []}

    def gravar():
        with open("logs.json", "w", encoding="utf-8") as f:
            json.dump(saida, f, ensure_ascii=False, indent=1)

    if not db:
        gravar()
        print("aviso: NOTION_LOG_DB não definido — logs.json vazio, "
              "a aba LOG do painel fica vazia até o secret ser criado.")
        return
    if not token:
        gravar()
        sys.exit("ERRO: NOTION_TOKEN não definido. logs.json vazio gravado.")

    try:
        linhas, cursor = [], None
        while True:
            payload = {"page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            d = req("POST", "/databases/%s/query" % db, token, payload)
            linhas.extend(d.get("results", []))
            if not d.get("has_more"):
                break
            cursor = d.get("next_cursor")

        logs = []
        for p in linhas[:MAX_LOGS]:
            pr = p.get("properties", {})
            titulo = None
            data = None
            for prop in pr.values():
                if prop.get("type") == "title":
                    titulo = texto_rico(prop.get("title")) or None
                elif prop.get("type") == "date" and prop.get("date"):
                    data = prop["date"].get("start")
            criado = p.get("created_time")
            logs.append({
                "titulo": titulo or "(sem título)",
                "data": (data or criado or "")[:10] or None,
                "url": p.get("url"),
                "texto": corpo_da_pagina(p["id"], token),
            })
        logs.sort(key=lambda x: x["data"] or "", reverse=True)
        saida["logs"] = logs
        gravar()
        print("ok: %d log(s) gravados em logs.json" % len(logs))

    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8", "replace")[:300]
        gravar()
        if e.code in (403, 404):
            sys.exit("ERRO HTTP %s ao ler o banco de LOG: a integração do painel "
                     "precisa ser conectada ao banco 📓 LOG — Audiovisual "
                     "(⋯ → Conexões, no Notion). Detalhe: %s" % (e.code, corpo))
        sys.exit("ERRO HTTP %s do Notion ao ler o LOG:\n%s" % (e.code, corpo))
    except urllib.error.URLError as e:
        gravar()
        sys.exit("ERRO de rede ao ler o LOG: %s" % e.reason)


if __name__ == "__main__":
    main()
