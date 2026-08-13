#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lê a agenda do Google e grava captacoes.json.

Não usa OAuth: consome o **endereço secreto em formato iCal** da agenda,
que o Google fornece em Configurações da agenda → Integrar agenda →
"Endereço secreto no formato iCal". É uma URL longa que já autentica
sozinha, então funciona dentro do GitHub Actions sem login.

Só a biblioteca padrão do Python — nada para instalar.

Variáveis de ambiente:
  AGENDA_ICAL_URL      opcional — endereço secreto iCal da agenda principal
  AGENDA_ICAL_URL_2    opcional — uma segunda agenda, se houver
  AGENDA_DIAS_ATRAS    opcional (padrão 45)
  AGENDA_DIAS_FRENTE   opcional (padrão 60)

Se AGENDA_ICAL_URL não estiver definida, o script sai sem erro e grava
uma lista vazia — o painel continua funcionando, só sem as captações.
"""
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

TZ = timezone(timedelta(hours=-3))

# Um evento só é captação se o título contiver uma destas palavras.
# Comparação sem acento e sem maiúscula.
PALAVRAS_CAPTACAO = ("gravacao", "captacao", "cobertura", "podcast",
                     "ensaio", "filmagem")

# Palavras que desqualificam, mesmo tendo uma das de cima.
PALAVRAS_FORA = ("preparacao", "reuniao", "alinhamento", "call ",
                 "planejamento", "roteiro do")


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    return s.encode("ascii", "ignore").decode().lower().strip()


def eh_captacao(titulo):
    n = norm(titulo)
    if any(p in n for p in PALAVRAS_FORA):
        return False
    return any(p in n for p in PALAVRAS_CAPTACAO)


def desdobrar(texto):
    """iCal quebra linhas longas com um espaço no início da continuação."""
    linhas = []
    for bruta in texto.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if bruta[:1] in (" ", "\t") and linhas:
            linhas[-1] += bruta[1:]
        else:
            linhas.append(bruta)
    return linhas


def destextar(v):
    return (v.replace("\\,", ",").replace("\\;", ";")
            .replace("\\n", " ").replace("\\N", " ").replace("\\\\", "\\").strip())


def data_de(valor, params):
    """DTSTART pode vir como data pura, hora local ou UTC."""
    v = valor.strip()
    if "VALUE=DATE" in params or (len(v) == 8 and v.isdigit()):
        return date(int(v[:4]), int(v[4:6]), int(v[6:8])), None
    m = re.match(r"^(\d{8})T(\d{6})(Z?)$", v)
    if not m:
        return None, None
    d, h, z = m.groups()
    dt = datetime(int(d[:4]), int(d[4:6]), int(d[6:8]),
                  int(h[:2]), int(h[2:4]), int(h[4:6]))
    if z == "Z":
        dt = dt.replace(tzinfo=timezone.utc).astimezone(TZ)
    else:
        dt = dt.replace(tzinfo=TZ)
    return dt.date(), dt


def parse_ics(texto):
    """Extrai (data, hora, título) de cada VEVENT. Ignora recorrência —
    reunião recorrente não é captação, e captação não se repete sozinha."""
    eventos, atual = [], None
    for linha in desdobrar(texto):
        if linha == "BEGIN:VEVENT":
            atual = {}
            continue
        if linha == "END:VEVENT":
            if atual and atual.get("d") and atual.get("t"):
                eventos.append(atual)
            atual = None
            continue
        if atual is None or ":" not in linha:
            continue
        campo, valor = linha.split(":", 1)
        nome = campo.split(";")[0].upper()
        if nome == "SUMMARY":
            atual["t"] = destextar(valor)
        elif nome == "DTSTART":
            d, dt = data_de(valor, campo)
            atual["d"], atual["dt"] = d, dt
        elif nome == "STATUS" and valor.strip().upper() == "CANCELLED":
            atual["cancelado"] = True
    return [e for e in eventos if not e.get("cancelado")]


def baixar(url):
    req = urllib.request.Request(url, headers={"User-Agent": "painel-audiovisual"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        sys.exit("ERRO HTTP %s ao ler a agenda. O endereço secreto iCal expira "
                 "quando alguém o redefine no Google — vale gerar de novo." % e.code)
    except urllib.error.URLError as e:
        sys.exit("ERRO de rede ao ler a agenda: %s" % e.reason)


def cliente_de(titulo):
    """'Captação - Bea Fruet - Evolve' -> 'BEA FRUET'."""
    t = re.sub(r"(?i)^\s*(grava[çc][ãa]o|capta[çc][ãa]o|cobertura|filmagem)"
               r"\s*(de\s+v[íi]deo|v[íi]deo)?\s*[-–:]?\s*", "", titulo).strip()
    t = re.split(r"\s+[-–]\s+", t)[0]
    return t.strip().upper() or None


def main():
    urls = [u for u in (os.environ.get("AGENDA_ICAL_URL", "").strip(),
                        os.environ.get("AGENDA_ICAL_URL_2", "").strip()) if u]
    hoje = datetime.now(TZ).date()
    atras = int(os.environ.get("AGENDA_DIAS_ATRAS", "45") or 45)
    frente = int(os.environ.get("AGENDA_DIAS_FRENTE", "60") or 60)
    ini, fim = hoje - timedelta(days=atras), hoje + timedelta(days=frente)

    saida = {"gerado_em": datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S-03:00"),
             "captacoes": []}

    if not urls:
        with open("captacoes.json", "w", encoding="utf-8") as f:
            json.dump(saida, f, ensure_ascii=False, indent=1)
        print("aviso: AGENDA_ICAL_URL não definida — captacoes.json vazio, "
              "o painel segue funcionando sem as captações.")
        return

    vistos, caps = set(), []
    for url in urls:
        for e in parse_ics(baixar(url)):
            if not (ini <= e["d"] <= fim) or not eh_captacao(e["t"]):
                continue
            chave = (e["d"].isoformat(), norm(e["t"]))
            if chave in vistos:
                continue
            vistos.add(chave)
            caps.append({
                "data": e["d"].isoformat(),
                "hora": e["dt"].strftime("%H:%M") if e.get("dt") else None,
                "titulo": e["t"],
                "cliente": cliente_de(e["t"]),
            })

    caps.sort(key=lambda c: (c["data"], c["hora"] or ""))
    saida["captacoes"] = caps
    with open("captacoes.json", "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=1)

    print("ok: %d captação(ões) entre %s e %s" % (len(caps), ini, fim))
    for c in caps:
        print("   %s %s  %s" % (c["data"], c["hora"] or "     ", c["titulo"]))


if __name__ == "__main__":
    main()
