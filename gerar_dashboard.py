#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerador do Painel Diário — Audiovisual / Chess.

Uso:  python3 gerar_dashboard.py cards.json dashboard.html

Entrada: JSON com a chave "cards" (ver cards.json). Todas as datas de
edição vêm do Notion em UTC (sufixo Z) e são convertidas para UTC-3
(America/Sao_Paulo) antes de qualquer comparação de dia.
"""
import json
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone

TZ = timezone(timedelta(hours=-3))
DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
MESES = ["jan", "fev", "mar", "abr", "mai", "jun",
         "jul", "ago", "set", "out", "nov", "dez"]

FINALIZADO = {"Aprovado/Finalizado", "Drive"}
EM_APROVACAO = {"Pré Aprovação"}
EM_EXECUCAO = {"Executando", "Alteração", "Alterado"}


# ---------------------------------------------------------------- helpers

def parse_dt(s):
    """ISO do Notion -> datetime local (UTC-3)."""
    if not s:
        return None
    s = s.strip().replace(" ", "T")
    if s.endswith("Z"):
        return datetime.fromisoformat(s[:-1]).replace(tzinfo=timezone.utc).astimezone(TZ)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt.astimezone(TZ) if dt.tzinfo else dt.replace(tzinfo=TZ)


def parse_d(s):
    """Prazo -> date local. Aceita data pura ou datetime."""
    if not s:
        return None
    dt = parse_dt(s)
    return dt.date() if dt else None


def fmt(d, com_dia=True):
    if not d:
        return "—"
    base = "%02d/%02d" % (d.day, d.month)
    return "%s %s" % (DIAS[d.weekday()], base) if com_dia else base


def dias_uteis(ini, fim):
    n, cur = 0, ini
    while cur <= fim:
        if cur.weekday() < 5:
            n += 1
        cur += timedelta(days=1)
    return n


def esc(t):
    return (str(t or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def slug(t):
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()
    return "".join(c if c.isalnum() else "-" for c in t.lower()).strip("-")


# ---------------------------------------------------------------- núcleo

def montar(cfg):
    agora = parse_dt(cfg["gerado_em"]) or datetime.now(TZ)
    hoje = agora.date()
    ontem = hoje - timedelta(days=1)
    amanha = hoje + timedelta(days=1)

    ano, mes = (int(x) for x in cfg["mes_ref"].split("-"))
    prim = date(ano, mes, 1)
    ult = date(ano + (mes == 12), (mes % 12) + 1, 1) - timedelta(days=1)

    du_total = dias_uteis(prim, ult)
    du_corridos = dias_uteis(prim, min(hoje, ult))

    cards = []
    for c in cfg["cards"]:
        c = dict(c)
        c["_prazo"] = parse_d(c.get("prazo"))
        c["_ini"] = parse_dt(c.get("ed_ini"))
        c["_fim"] = parse_dt(c.get("ed_fim"))
        st = c.get("status") or ""
        c["_final"] = st in FINALIZADO
        c["_aprov"] = st in EM_APROVACAO
        c["_exec"] = st in EM_EXECUCAO or (c["_ini"] and not c["_fim"] and not c["_final"])
        c["_fazer"] = st.startswith("À Fazer")
        # atraso só é calculável quando há prazo
        if c["_prazo"] and c["_fim"]:
            c["_atraso"] = (c["_fim"].date() - c["_prazo"]).days
        elif c["_prazo"] and not c["_final"]:
            c["_atraso"] = (hoje - c["_prazo"]).days
        else:
            c["_atraso"] = None
        cards.append(c)

    final = [c for c in cards if c["_final"]]
    aprov = [c for c in cards if c["_aprov"]]
    execu = [c for c in cards if c["_exec"] and not c["_final"]]
    concluidos = [c for c in cards if c["_fim"]]          # saiu da edição
    fila = [c for c in cards if not c["_fim"] and not c["_final"]]

    # ---- ritmo
    meta = cfg.get("meta_mes", 50)
    ritmo_alvo = meta / du_total
    esperado = round(ritmo_alvo * du_corridos)
    entregue = len(concluidos)
    ritmo_real = entregue / du_corridos if du_corridos else 0
    projecao = round(ritmo_real * du_total)

    # ---- pontualidade (só o que já saiu da edição e tinha prazo)
    com_prazo = [c for c in concluidos if c["_atraso"] is not None]
    no_prazo = [c for c in com_prazo if c["_atraso"] <= 0]
    pct_prazo = round(100 * len(no_prazo) / len(com_prazo)) if com_prazo else None

    # ---- antecedência
    prontos_futuro = [c for c in concluidos if c["_prazo"] and c["_prazo"] > hoje]
    antec = max((c["_prazo"] - hoje).days for c in prontos_futuro) if prontos_futuro else 0
    horizonte = max([(c["_prazo"] - hoje).days for c in fila if c["_prazo"] and c["_prazo"] > hoje] or [0])

    # ---- distribuição
    dist = {}
    for nome in cfg["meta_dist"]:
        dist[nome] = len([c for c in concluidos if c.get("responsavel") == nome])
    sem_resp = len([c for c in concluidos if not c.get("responsavel")])
    total_atr = sum(dist.values())

    # ---- alertas
    vence_hoje = [c for c in fila if c["_prazo"] == hoje]
    atrasados = sorted([c for c in fila if c["_prazo"] and c["_prazo"] < hoje],
                       key=lambda c: c["_prazo"])
    sem_dono = [c for c in cards if not c.get("responsavel") and not c["_final"]]
    sem_inicio = [c for c in cards if c["_fim"] and not c["_ini"]]
    sem_pub = [c for c in cards if not c.get("data_pub")]

    # ---- fluxo diário
    f_ontem = [c for c in concluidos if c["_fim"].date() == ontem]
    f_hoje_ok = [c for c in concluidos if c["_fim"].date() == hoje]
    f_amanha = [c for c in fila if c["_prazo"] == amanha]
    prox_data = min([c["_prazo"] for c in fila if c["_prazo"] and c["_prazo"] > amanha] or [None])
    f_prox = [c for c in fila if c["_prazo"] == prox_data] if prox_data else []

    # ---- série diária (dias úteis do mês até hoje)
    serie = []
    cur = prim
    while cur <= min(hoje, ult):
        if cur.weekday() < 5:
            serie.append({"d": cur, "n": len([c for c in concluidos if c["_fim"].date() == cur])})
        cur += timedelta(days=1)

    return dict(agora=agora, hoje=hoje, ontem=ontem, amanha=amanha, prim=prim, ult=ult,
                du_total=du_total, du_corridos=du_corridos, meta=meta, esperado=esperado,
                entregue=entregue, ritmo_real=ritmo_real, ritmo_alvo=ritmo_alvo,
                projecao=projecao, final=final, aprov=aprov, execu=execu,
                concluidos=concluidos, fila=fila, pct_prazo=pct_prazo, com_prazo=com_prazo,
                no_prazo=no_prazo, antec=antec, horizonte=horizonte, dist=dist,
                sem_resp=sem_resp, total_atr=total_atr, meta_dist=cfg["meta_dist"],
                meta_antec=cfg.get("meta_antecedencia_dias", 30),
                vence_hoje=vence_hoje, atrasados=atrasados, sem_dono=sem_dono,
                sem_inicio=sem_inicio, sem_pub=sem_pub, f_ontem=f_ontem,
                f_hoje_ok=f_hoje_ok, f_amanha=f_amanha, f_prox=f_prox,
                prox_data=prox_data, serie=serie, cards=cards)


# ---------------------------------------------------------------- render

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root,.viz{color-scheme:light;
 --surface:#fcfcfb; --plane:#f4f4f1; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
 --grid:#e1e0d9; --axis:#c3c2b7; --ring:rgba(11,11,11,.10);
 --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a;
 --good:#0ca30c; --warn:#fab219; --serious:#ec835a; --crit:#d03b3b;
 --good-ink:#006300;}
@media(prefers-color-scheme:dark){:root:where(:not([data-theme=light])),:root:where(:not([data-theme=light])) .viz{color-scheme:dark;
 --surface:#1a1a19; --plane:#0d0d0d; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
 --grid:#2c2c2a; --axis:#383835; --ring:rgba(255,255,255,.10);
 --s1:#3987e5; --s2:#d95926; --s3:#199e70; --good-ink:#0ca30c;}}
:root[data-theme=dark],:root[data-theme=dark] .viz{color-scheme:dark;
 --surface:#1a1a19; --plane:#0d0d0d; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
 --grid:#2c2c2a; --axis:#383835; --ring:rgba(255,255,255,.10);
 --s1:#3987e5; --s2:#d95926; --s3:#199e70; --good-ink:#0ca30c;}

body{background:var(--plane);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;
 color:var(--ink);-webkit-font-smoothing:antialiased}
.viz{color:var(--ink);max-width:1180px;margin:0 auto;padding:28px 20px 56px}

.top{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;
 flex-wrap:wrap;margin-bottom:22px}
.top h1{font-size:15px;font-weight:650;letter-spacing:.10em;text-transform:uppercase}
.top .sub{font-size:13px;color:var(--muted);margin-top:3px}
.stamp{font-size:12px;color:var(--muted);text-align:right}
.stamp b{display:block;font-size:19px;font-weight:600;color:var(--ink);letter-spacing:-.01em}

.card{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:18px 20px}
.grid{display:grid;gap:14px}
.g4{grid-template-columns:repeat(4,1fr)}
.g2{grid-template-columns:1.35fr 1fr}
.g3{grid-template-columns:repeat(3,1fr)}
@media(max-width:900px){.g4{grid-template-columns:repeat(2,1fr)}.g2,.g3{grid-template-columns:1fr}}
@media(max-width:520px){.g4{grid-template-columns:1fr}}

h2{font-size:11px;font-weight:650;letter-spacing:.09em;text-transform:uppercase;
 color:var(--muted);margin-bottom:14px}

/* stat tiles */
.tile .lab{font-size:11px;font-weight:650;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.tile .val{font-size:40px;font-weight:600;letter-spacing:-.025em;line-height:1.05;margin:8px 0 2px}
.tile .val small{font-size:18px;font-weight:500;color:var(--muted);letter-spacing:0}
.tile .note{font-size:12.5px;color:var(--ink2);line-height:1.4}
.meter{height:8px;background:var(--grid);border-radius:4px;margin:11px 0 9px;position:relative;overflow:hidden}
.meter i{display:block;height:100%;border-radius:4px}
.mark{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--ink2);opacity:.55}

.pill{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;font-weight:600;
 padding:2px 8px;border-radius:20px;border:1px solid var(--ring)}
.p-good{color:var(--good-ink)} .p-warn{color:var(--serious)} .p-crit{color:var(--crit)}

/* barras diárias */
.bars{display:flex;align-items:flex-end;gap:6px;height:118px;margin-top:4px}
.bars .col{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;
 height:100%;position:relative;cursor:default}
.bars .bar{width:100%;max-width:34px;background:var(--s1);border-radius:4px 4px 0 0;min-height:2px;
 transition:opacity .12s}
.bars .col:hover .bar{opacity:.75}
.bars .n{font-size:11.5px;font-weight:600;color:var(--ink2);margin-bottom:4px;font-variant-numeric:tabular-nums}
.bars .col.hoje .bar{background:var(--s2)}
.xaxis{display:flex;gap:6px;border-top:1px solid var(--axis);padding-top:6px;margin-top:2px}
.xaxis span{flex:1;text-align:center;font-size:10.5px;color:var(--muted);font-variant-numeric:tabular-nums}
.xaxis span.hoje{color:var(--ink);font-weight:650}
.pace{position:relative;height:0}
.pace i{position:absolute;left:0;right:0;border-top:1px dashed var(--axis)}
.pace b{position:absolute;right:0;top:-16px;font-size:10.5px;font-weight:500;color:var(--muted);
 background:var(--surface);padding:0 4px}

/* stack 70/30 */
.stack{display:flex;height:34px;border-radius:6px;overflow:hidden;gap:2px;margin:6px 0 12px}
.stack i{display:block;position:relative}
.stack i span{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
 font-size:12px;font-weight:650;color:#fff}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12.5px;color:var(--ink2)}
.legend b{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:6px;vertical-align:1px}
.dline{display:flex;justify-content:space-between;font-size:12.5px;color:var(--ink2);
 padding:6px 0;border-top:1px solid var(--grid)}
.dline b{font-weight:600;color:var(--ink);font-variant-numeric:tabular-nums}

/* listas de card */
ul{list-style:none}
.item{display:flex;gap:9px;align-items:baseline;padding:7px 0;border-top:1px solid var(--grid);font-size:13.5px}
.item:first-child{border-top:0}
.item a{color:var(--ink);text-decoration:none;font-weight:500;flex:1;min-width:0}
.item a:hover{text-decoration:underline}
.item .meta{font-size:11.5px;color:var(--muted);white-space:nowrap;font-variant-numeric:tabular-nums}
.dot{width:7px;height:7px;border-radius:50%;flex:none;position:relative;top:5px}
.d1{background:var(--s1)} .d2{background:var(--s2)} .d0{background:var(--axis)}
.empty{font-size:13px;color:var(--muted);padding:8px 0;font-style:italic}
.count{font-weight:600;color:var(--ink);font-variant-numeric:tabular-nums}

/* alertas */
.alert{display:flex;gap:11px;align-items:flex-start;padding:11px 0;border-top:1px solid var(--grid)}
.alert:first-child{border-top:0}
.ico{font:600 12px/18px system-ui;width:18px;height:18px;border-radius:50%;flex:none;text-align:center;color:#fff}
.i-crit{background:var(--crit)} .i-warn{background:var(--warn);color:#3a2a00} .i-info{background:var(--muted)}
.alert .txt{flex:1;font-size:13.5px;line-height:1.45}
.alert .txt b{font-weight:650}
.alert .txt em{font-style:normal;color:var(--muted);font-size:12.5px;display:block;margin-top:2px}

table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--grid)}
th{font-size:10.5px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);font-weight:650}
td.num{text-align:right;font-variant-numeric:tabular-nums}
details{margin-top:14px}
summary{font-size:12px;color:var(--muted);cursor:pointer;padding:6px 0}
.foot{margin-top:26px;font-size:11.5px;color:var(--muted);line-height:1.6}
"""


def li(c, extra=""):
    resp = c.get("responsavel")
    d = {"Maila": "d1", "Petterson": "d2"}.get(resp, "d0")
    tag = resp or "sem responsável"
    return ('<li class="item"><span class="dot %s"></span>'
            '<a href="%s" target="_blank" rel="noopener">%s</a>'
            '<span class="meta">%s%s</span></li>'
            % (d, esc(c.get("url") or "#"), esc(c["titulo"]), esc(tag), extra))


def lista(cards, vazio, extra=lambda c: ""):
    if not cards:
        return '<p class="empty">%s</p>' % esc(vazio)
    return "<ul>" + "".join(li(c, extra(c)) for c in cards) + "</ul>"


def render(m):
    A = m["agora"]
    pct_meta = min(100, 100 * m["entregue"] / m["meta"])
    pct_esp = min(100, 100 * m["esperado"] / m["meta"])
    delta = m["entregue"] - m["esperado"]

    if delta >= 0:
        ritmo_pill = '<span class="pill p-good">▲ %+d vs. ritmo</span>' % delta
    elif delta >= -3:
        ritmo_pill = '<span class="pill p-warn">▼ %+d vs. ritmo</span>' % delta
    else:
        ritmo_pill = '<span class="pill p-crit">▼ %+d vs. ritmo</span>' % delta

    # --- barras diárias
    mx = max([s["n"] for s in m["serie"]] + [1])
    alvo_dia = m["ritmo_alvo"]
    bars, xs = [], []
    for s in m["serie"]:
        eh_hoje = s["d"] == m["hoje"]
        h = 100 * s["n"] / mx
        bars.append(
            '<div class="col%s" title="%s — %d entrega(s)">'
            '<span class="n">%s</span><span class="bar" style="height:%.1f%%"></span></div>'
            % (" hoje" if eh_hoje else "", fmt(s["d"]), s["n"], s["n"] or "", h))
        xs.append('<span class="%s">%02d</span>' % ("hoje" if eh_hoje else "", s["d"].day))
    pace_top = 100 - (100 * alvo_dia / mx)

    # --- 70/30 (calculado só sobre o que tem responsável)
    base = m["total_atr"]
    segs, legs, linhas = [], [], []
    cores = {"Maila": "var(--s1)", "Petterson": "var(--s2)"}
    for nome, alvo in m["meta_dist"].items():
        n = m["dist"].get(nome, 0)
        pc = 100 * n / base if base else 0
        if n:
            segs.append('<i style="flex:%d;background:%s"><span>%d%%</span></i>'
                        % (max(n, 1), cores.get(nome, "var(--s3)"), round(pc)))
        legs.append('<span><b style="background:%s"></b>%s</span>' % (cores.get(nome, "var(--s3)"), esc(nome)))
        gap = round(pc) - alvo
        sinal = "p-good" if abs(gap) <= 8 else ("p-warn" if abs(gap) <= 18 else "p-crit")
        linhas.append('<div class="dline"><span>%s <span class="pill %s">%+d p.p.</span></span>'
                      '<b>%d de %d &nbsp;·&nbsp; %d%% <span style="color:var(--muted);font-weight:400">'
                      '/ meta %d%%</span></b></div>' % (esc(nome), sinal, gap, n, base, round(pc), alvo))
    if not base:
        segs.append('<i style="flex:1;background:var(--axis)"><span>sem base</span></i>')
    if m["sem_resp"]:
        linhas.append('<div class="dline" style="color:var(--crit)"><span>'
                      '<b style="color:var(--crit)">%d card(s) sem responsável</b> ficam fora deste cálculo'
                      '</span><b style="color:var(--crit)">%d de %d entregas</b></div>'
                      % (m["sem_resp"], m["sem_resp"], base + m["sem_resp"]))

    # --- alertas
    al = []
    if m["vence_hoje"]:
        al.append(('i-crit', '!', "<b>%d card(s) vencem hoje</b> e ainda não saíram da edição."
                   "<em>%s</em>" % (len(m["vence_hoje"]),
                                    esc(" · ".join(c["titulo"] for c in m["vence_hoje"])))))
    if m["atrasados"]:
        pior = m["atrasados"][0]
        al.append(('i-crit', '!', "<b>%d card(s) atrasados</b>, o mais antigo há %d dia(s)."
                   "<em>%s — prazo %s</em>" % (len(m["atrasados"]),
                                               (m["hoje"] - pior["_prazo"]).days,
                                               esc(pior["titulo"]), fmt(pior["_prazo"]))))
    if m["antec"] < m["meta_antec"]:
        al.append(('i-warn', '~', "<b>Antecedência em %d dia(s)</b> contra meta de %d."
                   "<em>Nada pronto com prazo futuro. Fila cobre %d dia(s) à frente.</em>"
                   % (m["antec"], m["meta_antec"], m["horizonte"])))
    if m["sem_dono"]:
        al.append(('i-warn', '~', "<b>%d card(s) sem responsável</b> — não entram no cálculo do 70/30."
                   "<em>%s</em>" % (len(m["sem_dono"]),
                                    esc(" · ".join(c["titulo"] for c in m["sem_dono"][:5])))))
    if m["sem_inicio"]:
        al.append(('i-info', 'i', "<b>%d card(s) concluídos sem Edição Início</b> — ficam fora da "
                   "leitura de ciclo.<em>%s</em>"
                   % (len(m["sem_inicio"]), esc(" · ".join(c["titulo"] for c in m["sem_inicio"][:5])))))
    if m["sem_pub"]:
        al.append(('i-info', 'i', "<b>%d de %d cards sem Data de Publicação</b> — é o campo que "
                   "automatiza a leitura de antecedência.<em>Preencher no ato da criação do card.</em>"
                   % (len(m["sem_pub"]), len(m["cards"]))))
    if not al:
        al.append(('i-info', '✓', "<b>Nada exigindo ação hoje.</b><em>Sem vencimentos, sem atrasos, "
                   "sem furo de preenchimento.</em>"))

    alertas = "".join('<div class="alert"><span class="ico %s">%s</span>'
                      '<span class="txt">%s</span></div>' % a for a in al)

    # --- tabela completa
    linhas_tab = []
    for c in sorted(m["cards"], key=lambda x: (x["_prazo"] or date(2099, 1, 1), x["titulo"])):
        if c["_final"]:
            est = "Finalizado"
        elif c["_aprov"]:
            est = "Em aprovação"
        elif c["_exec"]:
            est = "Em execução"
        else:
            est = "A fazer"
        atr = c["_atraso"]
        atr_txt = "—" if atr is None else ("no prazo" if atr <= 0 else "+%d d" % atr)
        cor = "" if (atr is None or atr <= 0) else ' style="color:var(--crit);font-weight:600"'
        linhas_tab.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td class=num%s>%s</td></tr>"
            % (esc(c["titulo"]), esc(c.get("responsavel") or "—"), esc(c.get("categoria") or "—"),
               est, fmt(c["_prazo"], False), cor, atr_txt))

    prazo_txt = ("%d%%" % m["pct_prazo"]) if m["pct_prazo"] is not None else "—"
    prazo_note = ("%d de %d entregas dentro da data" % (len(m["no_prazo"]), len(m["com_prazo"]))
                  if m["com_prazo"] else "sem base de comparação ainda")
    prazo_cor = "var(--good)" if (m["pct_prazo"] or 0) >= 85 else (
        "var(--warn)" if (m["pct_prazo"] or 0) >= 70 else "var(--crit)")

    amanha_lab = fmt(m["amanha"])
    if m["f_amanha"]:
        bloco_amanha = lista(m["f_amanha"], "")
    elif m["prox_data"]:
        bloco_amanha = ('<p class="empty">Nada previsto para %s.</p>'
                        '<h2 style="margin:14px 0 8px">Próximo lote · %s</h2>%s'
                        % (amanha_lab, fmt(m["prox_data"]), lista(m["f_prox"], "")))
    else:
        bloco_amanha = '<p class="empty">Nada previsto para %s nem adiante.</p>' % amanha_lab

    return """<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive,nosnippet">
<meta name="googlebot" content="noindex,nofollow">
<title>Painel Diário — Audiovisual · %(dtitulo)s</title>
<style>%(css)s</style></head>
<body><div class="viz">

<div class="top">
  <div>
    <h1>Audiovisual · Painel Diário</h1>
    <div class="sub">Chess · agosto/2026 · dia útil %(duc)d de %(dut)d</div>
  </div>
  <div class="stamp"><b>%(dtitulo)s</b>atualizado %(hora)s</div>
</div>

<div class="grid g4" style="margin-bottom:14px">
  <div class="card tile">
    <div class="lab">Entregues no mês</div>
    <div class="val">%(entregue)d<small> / %(meta)d</small></div>
    <div class="meter"><i style="width:%(pct_meta).1f%%;background:var(--s1)"></i>
      <span class="mark" style="left:%(pct_esp).1f%%"></span></div>
    <div class="note">%(ritmo_pill)s<br>marca = onde deveríamos estar hoje (%(esperado)d)</div>
  </div>
  <div class="card tile">
    <div class="lab">Projeção do mês</div>
    <div class="val">%(projecao)d</div>
    <div class="note">no ritmo de <b>%(ritmo_real).1f</b> card/dia útil.<br>
      Meta pede %(ritmo_alvo).1f/dia.</div>
  </div>
  <div class="card tile">
    <div class="lab">Entregas no prazo</div>
    <div class="val" style="color:%(prazo_cor)s">%(prazo_txt)s</div>
    <div class="note">%(prazo_note)s</div>
  </div>
  <div class="card tile">
    <div class="lab">Antecedência</div>
    <div class="val">%(antec)d<small> dias</small></div>
    <div class="meter"><i style="width:%(pct_antec).1f%%;background:var(--crit)"></i></div>
    <div class="note">meta base %(meta_antec)d dias · fila cobre %(horizonte)d dia(s)</div>
  </div>
</div>

<div class="grid g2" style="margin-bottom:14px">
  <div class="card">
    <h2>Ritmo do mês · entregas por dia útil</h2>
    <div class="pace"><i style="top:%(pace_top).1f%%"></i></div>
    <div class="bars">%(bars)s</div>
    <div class="xaxis">%(xs)s</div>
    <div class="legend" style="margin-top:12px">
      <span><b style="background:var(--s1)"></b>dias anteriores</span>
      <span><b style="background:var(--s2)"></b>hoje</span>
      <span style="color:var(--muted)">– – – ritmo necessário (%(ritmo_alvo).1f/dia)</span>
    </div>
  </div>
  <div class="card">
    <h2>Distribuição de edições · meta 70/30</h2>
    <div class="stack">%(segs)s</div>
    <div class="legend" style="margin-bottom:10px">%(legs)s</div>
    %(linhas)s
  </div>
</div>

<div class="card" style="margin-bottom:14px">
  <h2>Alertas do dia</h2>
  %(alertas)s
</div>

<div class="grid g3" style="margin-bottom:14px">
  <div class="card">
    <h2>Entregue ontem · %(lab_ontem)s <span class="count">%(n_ontem)d</span></h2>
    %(l_ontem)s
  </div>
  <div class="card">
    <h2>Em execução agora <span class="count">%(n_exec)d</span></h2>
    %(l_exec)s
    <h2 style="margin:16px 0 8px">Concluído hoje <span class="count">%(n_hoje)d</span></h2>
    %(l_hoje)s
  </div>
  <div class="card">
    <h2>Previsto amanhã · %(lab_amanha)s <span class="count">%(n_amanha)d</span></h2>
    %(b_amanha)s
  </div>
</div>

<div class="card">
  <h2>Todos os cards de agosto <span class="count">%(n_cards)d</span></h2>
  <table><thead><tr><th>Card</th><th>Responsável</th><th>Categoria</th>
    <th>Estado</th><th>Prazo</th><th class=num>Pontualidade</th></tr></thead>
    <tbody>%(tabela)s</tbody></table>
</div>

<p class="foot">Fonte: banco 🎯 Tarefas — Audiovisual (Notion) · %(n_cards)d cards com prazo em agosto/2026.
Horários convertidos para America/São_Paulo (UTC−3). &quot;Entregues&quot; = cards com Edição Fim preenchida,
incluindo os que aguardam aprovação. Pontualidade compara Edição Fim com Prazo.<br>
Gerado automaticamente em %(dtitulo)s às %(hora)s.</p>

</div></body></html>""" % dict(
        css=CSS, dtitulo=fmt(m["hoje"]) + "/2026", hora=A.strftime("%H:%M"),
        duc=m["du_corridos"], dut=m["du_total"], entregue=m["entregue"], meta=m["meta"],
        pct_meta=pct_meta, pct_esp=pct_esp, ritmo_pill=ritmo_pill, esperado=m["esperado"],
        projecao=m["projecao"], ritmo_real=m["ritmo_real"], ritmo_alvo=m["ritmo_alvo"],
        prazo_txt=prazo_txt, prazo_note=prazo_note, prazo_cor=prazo_cor,
        antec=m["antec"], meta_antec=m["meta_antec"], horizonte=m["horizonte"],
        pct_antec=min(100, 100 * m["antec"] / m["meta_antec"]),
        bars="".join(bars), xs="".join(xs), pace_top=max(0, pace_top),
        segs="".join(segs), legs="".join(legs), linhas="".join(linhas), alertas=alertas,
        lab_ontem=fmt(m["ontem"]), n_ontem=len(m["f_ontem"]),
        l_ontem=lista(m["f_ontem"], "Nenhuma entrega concluída ontem."),
        n_exec=len(m["execu"]), l_exec=lista(m["execu"], "Nenhum card em execução."),
        n_hoje=len(m["f_hoje_ok"]), l_hoje=lista(m["f_hoje_ok"], "Nada concluído hoje ainda."),
        lab_amanha=fmt(m["amanha"]), n_amanha=len(m["f_amanha"]), b_amanha=bloco_amanha,
        n_cards=len(m["cards"]), tabela="".join(linhas_tab))


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "cards.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "dashboard.html"
    with open(src, encoding="utf-8") as f:
        cfg = json.load(f)
    html = render(montar(cfg))
    with open(dst, "w", encoding="utf-8") as f:
        f.write(html)
    print("ok ->", dst, len(html), "bytes")
