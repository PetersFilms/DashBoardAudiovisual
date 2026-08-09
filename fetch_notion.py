#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Puxa TODOS os cards do banco 🎯 Tarefas — Audiovisual (Notion)
e grava cards.json no formato que o gerar_dashboard.py espera.
O histórico completo alimenta a aba "Análise por Período";
o Painel Diário filtra sozinho o mês corrente.

Usa só a biblioteca padrão do Python — nada para instalar.

Variáveis de ambiente:
  NOTION_TOKEN        obrigatório — token da integração interna do Notion
  NOTION_DATABASE_ID  obrigatório — id do banco de tarefas
  META_MES            opcional (padrão 50)
  META_MAILA          opcional (padrão 70)
  META_PETTERSON      opcional (padrão 30)
  META_ANTECEDENCIA   opcional (padrão 30)
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

TZ = timezone(timedelta(hours=-3))          # America/Sao_Paulo
API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Fallback caso a integração não tenha permissão de ler nomes de usuário.
# Os três últimos são guests que saíram do workspace (o Notion não devolve
# mais o nome deles) — aparecem agrupados como "Ex-editor" no histórico.
PESSOAS = {
    "372d872b-594c-8166-bf2e-000209120c2d": "Maila",
    "e282b903-8b63-48fe-b198-ead0e2a0ad1b": "Petterson",
    "280d872b-594c-8152-8e83-00021bbf9ea2": "Pedro",
    "281d872b-594c-8191-8485-000236ddbf25": "Ex-editor",
    "2f5d872b-594c-8166-b06b-000283386b5b": "Ex-editor",
    "30c0c79e-ec7c-4cbe-aad8-29f7bf46ad96": "Ex-editor",
}


def env(nome, obrigatorio=True, padrao=None):
    v = os.environ.get(nome, "").strip()
    if not v:
        if obrigatorio:
            sys.exit("ERRO: variável de ambiente %s não definida." % nome)
        return padrao
    return v


def post(caminho, token, payload):
    req = urllib.request.Request(
        API + caminho,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + token,
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8", "replace")[:500]
        sys.exit("ERRO HTTP %s do Notion em %s:\n%s" % (e.code, caminho, corpo))
    except urllib.error.URLError as e:
        sys.exit("ERRO de rede ao falar com o Notion: %s" % e.reason)


# ------------------------------------------------ leitura de propriedades

def p_text(prop):
    if not prop:
        return None
    for chave in ("title", "rich_text"):
        if prop.get(chave):
            return "".join(x.get("plain_text", "") for x in prop[chave]).strip() or None
    return None


def p_select(prop):
    if not prop:
        return None
    for chave in ("select", "status"):
        v = prop.get(chave)
        if v:
            return v.get("name")
    return None


def p_multi(prop):
    if not prop or not prop.get("multi_select"):
        return None
    nomes = [x.get("name") for x in prop["multi_select"] if x.get("name")]
    return nomes[0] if nomes else None


def p_date(prop):
    if not prop or not prop.get("date"):
        return None
    return prop["date"].get("start")


def p_person(prop):
    if not prop or not prop.get("people"):
        return None
    u = prop["people"][0]
    return PESSOAS.get(u.get("id"), u.get("name") or u.get("id"))


# ------------------------------------------------------------------ main

def main():
    token = env("NOTION_TOKEN")
    db = env("NOTION_DATABASE_ID")

    agora = datetime.now(TZ)

    # Sem filtro: o histórico inteiro alimenta a aba de análise por período.
    payload = {
        "page_size": 100,
        "sorts": [{"property": "Prazo", "direction": "ascending"}],
    }

    linhas, cursor = [], None
    while True:
        if cursor:
            payload["start_cursor"] = cursor
        d = post("/databases/%s/query" % db, token, payload)
        linhas.extend(d.get("results", []))
        if not d.get("has_more"):
            break
        cursor = d.get("next_cursor")

    cards = []
    for linha in linhas:
        pr = linha.get("properties", {})
        titulo = p_text(pr.get("Title")) or p_text(pr.get("Nome")) or "(sem título)"
        m = re.match(r"^\[([^\]]+)\]", titulo)
        cards.append({
            "titulo": titulo,
            "cliente": m.group(1) if m else None,
            "status": p_select(pr.get("Status")),
            "fase": p_select(pr.get("Fase")),
            "responsavel": p_person(pr.get("Responsável")),
            "categoria": p_multi(pr.get("Categoria de vídeo")),
            "complexidade": p_select(pr.get("Complexidade")),
            "prazo": p_date(pr.get("Prazo")),
            # atenção: "Edição Fim" e "Alteração Fim" têm um espaço no fim, no Notion
            "ed_ini": p_date(pr.get("Edição Início")),
            "ed_fim": p_date(pr.get("Edição Fim ")) or p_date(pr.get("Edição Fim")),
            "alt_ini": p_date(pr.get("Alteração Início")),
            "alt_fim": p_date(pr.get("Alteração Fim ")) or p_date(pr.get("Alteração Fim")),
            "data_pub": p_date(pr.get("Data")),
            "url": linha.get("url"),
        })

    cfg = {
        "gerado_em": agora.strftime("%Y-%m-%dT%H:%M:%S-03:00"),
        "mes_ref": "%04d-%02d" % (agora.year, agora.month),
        "meta_mes": int(env("META_MES", False, "50")),
        "meta_dist": {
            "Maila": int(env("META_MAILA", False, "70")),
            "Petterson": int(env("META_PETTERSON", False, "30")),
        },
        "meta_antecedencia_dias": int(env("META_ANTECEDENCIA", False, "30")),
        "cards": cards,
    }

    if not cards:
        sys.exit("ERRO: o Notion respondeu, mas não devolveu nenhum card. "
                 "Nada foi gravado — melhor falhar do que publicar painel vazio.")

    with open("cards.json", "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)

    sem_resp = [c["titulo"] for c in cards if not c["responsavel"]]
    print("ok: %d cards de %s gravados em cards.json" % (len(cards), cfg["mes_ref"]))
    if sem_resp:
        print("aviso: %d card(s) sem responsável: %s" % (len(sem_resp), ", ".join(sem_resp[:5])))


if __name__ == "__main__":
    main()
