#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sincroniza as captações da agenda do Google com o Notion, nos dois sentidos:

  CRIAR    — captação nova na agenda vira card com Fase = Captação.
  ARQUIVAR — evento que sumiu da agenda (apagado ou cancelado) manda o card
             correspondente para a LIXEIRA do Notion — recuperável por lá.

Roda depois do fetch_agenda.py e do fetch_notion.py, lendo captacoes.json
e cards.json.

Só a biblioteca padrão do Python.

Travas contra estrago:
  1. Livro-caixa (captacoes_criadas.json, versionado): registra cada card
     criado e cada um arquivado. Captação já processada nunca duplica.
  2. Checagem no banco: se já existe card com o mesmo Gravado e o mesmo
     cliente, não cria — cobre o caso de alguém ter criado na mão.
  3. Teto por rodada: no máximo MAX_POR_RODADA criações. Se o filtro da
     agenda quebrar um dia, o estrago para em 5, não em 500.
  4. Só arquiva card que ESTE script criou e que ainda está na Fase
     Captação. Card que o time já moveu adiante virou trabalho real e
     nunca é tocado. Card criado na mão pelo time também não.
  5. Evento que voltar à agenda depois de cancelado recria o card.

Variáveis de ambiente:
  NOTION_TOKEN        obrigatório — precisa de permissão de INSERIR conteúdo
  NOTION_DATABASE_ID  obrigatório
  CRIAR_CARDS         "0" desliga a escrita (só relata o que faria)
  SYNC_A_CADA_HORAS   sincroniza só nas horas múltiplas disto (padrão 2)
  FORCAR_SYNC         "1" ignora o relógio e sincroniza agora
"""
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=-3))
API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

LIVRO = "captacoes_criadas.json"
MAX_POR_RODADA = 5
DIAS_ATRAS = 7            # captação de ontem ainda vira card
DIAS_FRENTE = 45          # não adianta criar card de gravação de dois meses


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    return re.sub(r"\s+", " ", s.encode("ascii", "ignore").decode().lower()).strip()


def api(metodo, caminho, token, payload=None):
    req = urllib.request.Request(
        API + caminho,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": "Bearer " + token,
                 "Notion-Version": NOTION_VERSION,
                 "Content-Type": "application/json"},
        method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8", "replace")[:400]
        if e.code == 403:
            sys.exit("ERRO 403 do Notion. A integração está sem a permissão "
                     "necessária — habilite 'Inserir conteúdo' e 'Atualizar "
                     "conteúdo' nas capacidades dela.\n%s" % corpo)
        sys.exit("ERRO HTTP %s do Notion em %s %s:\n%s"
                 % (e.code, metodo, caminho, corpo))
    except urllib.error.URLError as e:
        sys.exit("ERRO de rede ao falar com o Notion: %s" % e.reason)


def post(caminho, token, payload):
    return api("POST", caminho, token, payload)


def id_da_url(url):
    m = re.search(r"([0-9a-f]{32})", (url or "").replace("-", ""))
    return m.group(1) if m else None


def fase_do_card(page_id, token):
    """(fase, arquivado) do card — ou (None, None) se não deu para ler."""
    try:
        p = api("GET", "/pages/%s" % page_id, token)
    except SystemExit:
        return None, None
    sel = (p.get("properties", {}).get("Fase", {}) or {}).get("select") or {}
    return sel.get("name"), p.get("archived", False)


def carregar(caminho, padrao):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (IOError, OSError, ValueError):
        return padrao


# Clientes que existem no banco Clientes 360 mas ainda não têm nenhum card
# com o nome entre colchetes — o matcher não teria como descobri-los sozinho.
# O Evolve, por exemplo, sempre entrou como "[BEA FRUET] EVOLVE".
CLIENTES_EXTRA = ["EVOLVE", "HOMENZ", "IMAGRILL", "MACRO IMÓVEIS", "RCL",
                  "GUSTAVO PELISSARI", "VIVERE", "DR. LEANDRO",
                  "JARDIM ESTOFADOS", "CUNHA HORTIFRUIT"]


def clientes_conhecidos(cards):
    """Clientes já usados entre colchetes nos títulos, mais os do 360."""
    nomes = set(CLIENTES_EXTRA)
    nomes.update(x.strip() for x in
                 os.environ.get("CLIENTES_EXTRA", "").split(",") if x.strip())
    for c in cards:
        m = re.match(r"^\[([^\]]+)\]", c.get("titulo") or "")
        if m:
            nomes.add(m.group(1).strip())
    return sorted(nomes, key=len, reverse=True)   # o mais específico primeiro


def achar_cliente(titulo_evento, conhecidos):
    """
    Casa o título do evento contra a lista de clientes que já existem no
    banco. 'Cobertura - Inauguração Evolve' casa com EVOLVE. Título que não
    casa com ninguém vira card sem colchete, para o time nomear depois —
    melhor um card sem cliente do que um cliente inventado.
    """
    alvo = norm(titulo_evento)
    for nome in conhecidos:
        if norm(nome) and norm(nome) in alvo:
            return nome
    return None


def titulo_do_card(cap, cliente):
    corpo = re.sub(r"(?i)^\s*(grava[çc][ãa]o|capta[çc][ãa]o|cobertura|filmagem)"
                   r"\s*(de\s+v[íi]deo|v[íi]deo)?\s*[-–:]?\s*", "", cap["titulo"]).strip()
    corpo = corpo or cap["titulo"]
    if cliente:
        if norm(cliente) in norm(corpo):
            corpo = re.sub(r"(?i)" + re.escape(cliente), "", corpo).strip(" -–:")
        return "[%s] CAPTAÇÃO%s" % (cliente.upper(), (" " + corpo.upper()) if corpo else "")
    return "CAPTAÇÃO — %s" % cap["titulo"]


def main():
    token = os.environ.get("NOTION_TOKEN", "").strip()
    db = os.environ.get("NOTION_DATABASE_ID", "").strip()
    ligado = os.environ.get("CRIAR_CARDS", "1").strip() != "0"
    if not token or not db:
        sys.exit("ERRO: NOTION_TOKEN e NOTION_DATABASE_ID são obrigatórios.")

    # O workflow roda de hora em hora; a sincronização com o Notion acontece
    # a cada SYNC_A_CADA_HORAS. Rodada manual (FORCAR_SYNC=1) ignora o relógio.
    freq = max(1, int(os.environ.get("SYNC_A_CADA_HORAS", "2") or 2))
    forcar = os.environ.get("FORCAR_SYNC", "0").strip() == "1"
    hora = datetime.now(TZ).hour
    if not forcar and hora % freq != 0:
        print("fora do horário de sincronização (%dh; sincroniza a cada %dh) — nada a fazer."
              % (hora, freq))
        return

    caps = carregar("captacoes.json", {}).get("captacoes", [])
    cards = carregar("cards.json", {}).get("cards", [])
    livro = carregar(LIVRO, {"criados": []})
    # entradas arquivadas ficam fora do dedup: se o evento voltar à agenda
    # depois de cancelado, o card é recriado
    ja_feitas = {x["chave"] for x in livro["criados"] if not x.get("arquivado")}

    hoje = datetime.now(TZ).date()
    ini = (hoje - timedelta(days=DIAS_ATRAS)).isoformat()
    fim = (hoje + timedelta(days=DIAS_FRENTE)).isoformat()

    conhecidos = clientes_conhecidos(cards)
    # (gravado, cliente) que já existem no banco
    existentes = set()
    for c in cards:
        if c.get("gravado"):
            existentes.add((c["gravado"][:10], (c.get("cliente") or "").strip().upper()))

    novos, pulados = [], []
    for cap in caps:
        chave = "%s|%s" % (cap["data"], norm(cap["titulo"]))
        if not (ini <= cap["data"] <= fim):
            continue
        if chave in ja_feitas:
            continue
        cliente = achar_cliente(cap["titulo"], conhecidos)
        if (cap["data"], (cliente or "").upper()) in existentes:
            pulados.append((cap, "já existe card com este Gravado e cliente"))
            ja_feitas.add(chave)
            livro["criados"].append({"chave": chave, "card": None,
                                     "motivo": "já existia no banco"})
            continue
        novos.append((cap, cliente, chave))

    if len(novos) > MAX_POR_RODADA:
        print("aviso: %d captações novas, criando só as %d primeiras nesta rodada."
              % (len(novos), MAX_POR_RODADA))
        novos = novos[:MAX_POR_RODADA]

    criados = 0
    for cap, cliente, chave in novos:
        titulo = titulo_do_card(cap, cliente)
        if not ligado:
            print("   [simulação] criaria: %s  (Gravado %s)" % (titulo, cap["data"]))
            continue
        r = post("/pages", token, {
            "parent": {"database_id": db},
            "properties": {
                "Title": {"title": [{"text": {"content": titulo[:200]}}]},
                "Fase": {"select": {"name": "Captação"}},
                "Gravado": {"date": {"start": cap["data"]}},
            }})
        criados += 1
        livro["criados"].append({"chave": chave, "card": r.get("url"),
                                 "titulo": titulo, "gravado": cap["data"],
                                 "em": datetime.now(TZ).strftime("%Y-%m-%d %H:%M")})
        print("   criado: %s  ->  %s" % (titulo, r.get("url")))

    # ---- arquivar cards de eventos que sumiram da agenda -------------------
    # Um evento apagado simplesmente desaparece do feed iCal; um cancelado
    # ganha STATUS:CANCELLED e o fetch_agenda o descarta. Nos dois casos a
    # chave dele some de captacoes.json — e o card correspondente vai para a
    # lixeira do Notion, desde que ainda esteja na Fase Captação.
    chaves_atuais = {"%s|%s" % (c["data"], norm(c["titulo"]))
                     for c in caps if ini <= c["data"] <= fim}
    arquivados = 0
    for ent in livro["criados"]:
        if ent.get("arquivado") or ent.get("mantido") or not ent.get("card"):
            continue
        data = ent["chave"].split("|")[0]
        if not (ini <= data <= fim):
            continue                        # fora da janela que o feed cobre
        if ent["chave"] in chaves_atuais:
            continue                        # evento segue na agenda
        pid = id_da_url(ent["card"])
        if not pid:
            continue
        if not ligado:
            print("   [simulação] arquivaria: %s (evento sumiu da agenda)" % ent.get("titulo"))
            continue
        fase, ja_arq = fase_do_card(pid, token)
        if ja_arq:
            ent["arquivado"] = "já estava na lixeira"
            continue
        if fase != "Captação":
            # o time moveu o card adiante — virou trabalho real, não se toca
            ent["mantido"] = "evento sumiu da agenda, mas o card já está em '%s'" % fase
            print("   mantido: %s — já avançou para %s" % (ent.get("titulo"), fase))
            continue
        api("PATCH", "/pages/%s" % pid, token, {"archived": True})
        ent["arquivado"] = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
        ent["motivo_arquivo"] = "evento cancelado/apagado na agenda"
        arquivados += 1
        print("   arquivado: %s (evento sumiu da agenda) -> lixeira do Notion"
              % ent.get("titulo"))

    with open(LIVRO, "w", encoding="utf-8") as f:
        json.dump(livro, f, ensure_ascii=False, indent=1)

    for cap, motivo in pulados:
        print("   pulado: %s (%s) — %s" % (cap["titulo"], cap["data"], motivo))
    print("ok: %d criado(s), %d arquivado(s), %d pulado(s), %d captação(ões) na janela."
          % (criados, arquivados, len(pulados),
             len([c for c in caps if ini <= c["data"] <= fim])))


if __name__ == "__main__":
    main()
