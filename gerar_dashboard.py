#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerador do Painel — Audiovisual / Chess.

Uso:  python3 gerar_dashboard.py cards.json index.html

Entrada: JSON com a chave "cards" contendo o HISTÓRICO COMPLETO do banco
(o fetch_notion.py não filtra mais por mês). O Painel Diário filtra sozinho
o mês corrente; a aba "Análise por Período" recebe todos os cards embutidos
como JSON e calcula os números no navegador conforme o filtro escolhido.

Todas as datas de edição vêm do Notion em UTC (sufixo Z) e são convertidas
para UTC-3 (America/Sao_Paulo) antes de qualquer comparação de dia.
"""
import json
import statistics
import sys
from datetime import date, datetime, timedelta, timezone

TZ = timezone(timedelta(hours=-3))
DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]

FINALIZADO = {"Aprovado/Finalizado", "Drive"}
EM_APROVACAO = {"Pré Aprovação"}
EM_EXECUCAO = {"Executando", "Alteração", "Alterado"}
EM_ALTERACAO = {"Alteração", "Alterado"}

# Complexidade vira número para permitir média. Escala de 1 a 3.
# A opção "F@)&0" é erro de digitação no Notion e fica fora da conta.
PESO_COMPLEX = {"Básico": 1, "Intermediário": 2, "Avançado": 3}
NOME_COMPLEX = {1: "Básico", 2: "Intermediário", 3: "Avançado"}

# Feriados nacionais (agenda "Feriados no Brasil", Google). Só os que
# param a atividade comercial — datas comemorativas ficam de fora.
FERIADOS = {
    date(2026, 9, 7): "Independência",
    date(2026, 10, 12): "N. Sra. Aparecida",
    date(2026, 11, 2): "Finados",
    date(2026, 11, 15): "Proclamação da República",
    date(2026, 11, 20): "Consciência Negra",
    date(2026, 12, 25): "Natal",
    date(2027, 1, 1): "Confraternização Universal",
}

# Clientes que não entram no rodízio automático de publicação, e por quê.
FORA_CADENCIA = {
    "BEA FRUET": "captação não depende 100% da gente",
    "BFE": "captação não depende 100% da gente",
    "RICHARD": "captação não depende 100% da gente",
    "HOMENZ": "ainda sem captações",
    "PIKOLIN": "captações pausadas",
}

TETO_PUB_DIA = 3          # máximo de publicações no mesmo dia

# Categorias que não passam pelo calendário de publicação: assim que ficam
# prontas vão direto para a plataforma de anúncios, sem data de post.
CATEGORIAS_SEM_CALENDARIO = {"Ad"}

# Da captação até a entrega: 3 dias ÚTEIS, mais 1 dia útil a cada 3 cards
# da mesma leva — para os prazos não caírem todos no mesmo dia.
DIAS_ATE_ENTREGA = 3
CARDS_POR_DIA_DE_PRAZO = 3


def soma_uteis(d, n):
    """Avança n dias úteis a partir de d, pulando fim de semana e feriado."""
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in FERIADOS:
            n -= 1
    return d


def prazo_de_gravacao(gravado, indice):
    """Prazo previsto para o i-ésimo card de uma mesma captação."""
    return soma_uteis(gravado, DIAS_ATE_ENTREGA + indice // CARDS_POR_DIA_DE_PRAZO)

CORES_RESP = {"Maila": "var(--s1)", "Petterson": "var(--s2)",
              "Pedro": "var(--s3)", "Ex-editor": "var(--axis)"}


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


def fmt_dur(mn):
    """Minutos -> texto humano: 45min · 7h43 · 2,3 dias."""
    if mn is None:
        return "—"
    mn = round(mn)
    if mn < 60:
        return "%dmin" % mn
    if mn < 48 * 60:
        return "%dh%02d" % (mn // 60, mn % 60)
    return ("%.1f dias" % (mn / 1440.0)).replace(".", ",")


# ---------------------------------------------------------------- núcleo

def preparar(cfg):
    """Normaliza todos os cards (histórico completo)."""
    agora = parse_dt(cfg["gerado_em"]) or datetime.now(TZ)
    hoje = agora.date()
    todos = []
    for c in cfg["cards"]:
        c = dict(c)
        c["_prazo"] = parse_d(c.get("prazo"))
        c["_ini"] = parse_dt(c.get("ed_ini"))
        c["_fim"] = parse_dt(c.get("ed_fim"))
        # "Gravado" = dia da captação · "Publicação" = dia de ir ao ar.
        # data_pub é o nome antigo da chave, mantido como fallback.
        c["_grav"] = parse_d(c.get("gravado") or c.get("data_pub"))
        c["_pub"] = parse_d(c.get("publicacao"))
        c["_alt_i"] = parse_dt(c.get("alt_ini"))
        c["_alt_f"] = parse_dt(c.get("alt_fim"))
        c["_peso"] = PESO_COMPLEX.get(c.get("complexidade"))
        c["_cli"] = (c.get("cliente") or "").strip().upper()
        cats = c.get("categorias")
        if not cats:
            cats = [c["categoria"]] if c.get("categoria") else []
        c["_cats"] = cats
        c["_anuncio"] = bool(set(cats) & CATEGORIAS_SEM_CALENDARIO)
        c["_fora"] = next((m for k, m in FORA_CADENCIA.items()
                           if c["_cli"].startswith(k)), None)
        st = c.get("status") or ""
        c["_final"] = st in FINALIZADO
        c["_aprov"] = st in EM_APROVACAO
        c["_exec"] = st in EM_EXECUCAO or (c["_ini"] and not c["_fim"] and not c["_final"])
        # durações em minutos (abs: se alguém preencheu na ordem trocada,
        # os dois horários ainda delimitam o trabalho)
        c["_dur_ed"] = (abs((c["_fim"] - c["_ini"]).total_seconds()) / 60
                        if c["_ini"] and c["_fim"] else None)
        c["_dur_alt"] = (abs((c["_alt_f"] - c["_alt_i"]).total_seconds()) / 60
                         if c["_alt_i"] and c["_alt_f"] else None)
        if c["_prazo"] and c["_fim"]:
            c["_atraso"] = (c["_fim"].date() - c["_prazo"]).days
        elif c["_prazo"] and not c["_final"]:
            c["_atraso"] = (hoje - c["_prazo"]).days
        else:
            c["_atraso"] = None
        todos.append(c)

    # Prazo previsto a partir da captação, para os cards que ainda não têm
    # prazo definido. A leva é o conjunto de cards do mesmo cliente gravados
    # no mesmo dia; dentro dela, 3 cards por dia de prazo.
    levas = {}
    for c in todos:
        if c["_grav"] and not c["_prazo"]:
            levas.setdefault((c["_cli"], c["_grav"]), []).append(c)
    for chave, fila in levas.items():
        for i, c in enumerate(sorted(fila, key=lambda x: x.get("titulo") or "")):
            c["_prazo_prev"] = prazo_de_gravacao(chave[1], i)

    for c in todos:
        c.setdefault("_prazo_prev", None)
        # prazo efetivo: o definido no Notion, ou o projetado pela captação
        c["_prazo_ef"] = c["_prazo"] or c["_prazo_prev"]

    return agora, hoje, todos


def montar(cfg, agora, hoje, todos):
    """Métricas do Painel Diário — só cards com prazo no mês corrente."""
    ontem = hoje - timedelta(days=1)
    amanha = hoje + timedelta(days=1)

    ano, mes = (int(x) for x in cfg["mes_ref"].split("-"))
    prim = date(ano, mes, 1)
    ult = date(ano + (mes == 12), (mes % 12) + 1, 1) - timedelta(days=1)

    cards = [c for c in todos if c["_prazo"] and prim <= c["_prazo"] <= ult]

    du_total = dias_uteis(prim, ult)
    du_corridos = dias_uteis(prim, min(hoje, ult))

    execu = [c for c in cards if c["_exec"] and not c["_final"]]
    concluidos = [c for c in cards if c["_fim"]]
    fila = [c for c in cards if not c["_fim"] and not c["_final"]]

    # ---- ritmo
    meta = cfg.get("meta_mes", 50)
    ritmo_alvo = meta / du_total
    esperado = round(ritmo_alvo * du_corridos)
    entregue = len(concluidos)
    ritmo_real = entregue / du_corridos if du_corridos else 0
    projecao = round(ritmo_real * du_total)

    # ---- pontualidade
    com_prazo = [c for c in concluidos if c["_atraso"] is not None]
    no_prazo = [c for c in com_prazo if c["_atraso"] <= 0]
    pct_prazo = round(100 * len(no_prazo) / len(com_prazo)) if com_prazo else None

    # ---- antecedência (estado atual — vai para a aba de período)
    prontos_futuro = [c for c in concluidos if c["_prazo"] and c["_prazo"] > hoje]
    antec = max((c["_prazo"] - hoje).days for c in prontos_futuro) if prontos_futuro else 0
    horizonte = max([(c["_prazo"] - hoje).days for c in fila if c["_prazo"] and c["_prazo"] > hoje] or [0])

    # ---- tempos médios (calendário, não esforço)
    dur_ed = [c["_dur_ed"] for c in concluidos if c["_dur_ed"] is not None]
    dur_alt = [c["_dur_alt"] for c in cards if c["_dur_alt"] is not None]

    # ---- complexidade
    pesos = [c["_peso"] for c in cards if c["_peso"]]
    media_cx = sum(pesos) / len(pesos) if pesos else None
    dist_cx = {n: len([c for c in cards if c["_peso"] == p])
               for p, n in NOME_COMPLEX.items()}
    sem_cx = [c for c in cards if not c["_peso"]]
    cx_quebrada = [c for c in cards if c.get("complexidade")
                   and c.get("complexidade") not in PESO_COMPLEX]

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

    # ---- furos de tempo: o que impede medir edição e alteração
    # Edição: o card já saiu da edição (ou está finalizado) mas o par
    # Início/Fim está incompleto, então a duração não é calculável.
    sem_t_ed = [c for c in cards
                if (c["_fim"] or c["_final"]) and c["_dur_ed"] is None]
    # Alteração: o card passou por alteração (pelo status atual) ou tem
    # um dos dois campos preenchido sem o par.
    sem_t_alt = [c for c in cards
                 if ((c.get("status") in EM_ALTERACAO) or c["_alt_i"] or c["_alt_f"])
                 and c["_dur_alt"] is None]

    # ---- fluxo diário
    f_ontem = [c for c in concluidos if c["_fim"].date() == ontem]
    f_hoje_ok = [c for c in concluidos if c["_fim"].date() == hoje]
    f_amanha = [c for c in fila if c["_prazo"] == amanha]
    prox_data = min([c["_prazo"] for c in fila if c["_prazo"] and c["_prazo"] > amanha] or [None])
    f_prox = [c for c in fila if c["_prazo"] == prox_data] if prox_data else []

    # ---- série diária
    serie = []
    cur = prim
    while cur <= min(hoje, ult):
        if cur.weekday() < 5:
            serie.append({"d": cur, "n": len([c for c in concluidos if c["_fim"].date() == cur])})
        cur += timedelta(days=1)

    return dict(agora=agora, hoje=hoje, ontem=ontem, amanha=amanha, prim=prim, ult=ult,
                du_total=du_total, du_corridos=du_corridos, meta=meta, esperado=esperado,
                entregue=entregue, ritmo_real=ritmo_real, ritmo_alvo=ritmo_alvo,
                projecao=projecao, execu=execu, concluidos=concluidos, fila=fila,
                pct_prazo=pct_prazo, com_prazo=com_prazo, no_prazo=no_prazo,
                antec=antec, horizonte=horizonte, dist=dist, sem_resp=sem_resp,
                total_atr=total_atr, meta_dist=cfg["meta_dist"],
                meta_antec=cfg.get("meta_antecedencia_dias", 30),
                vence_hoje=vence_hoje, atrasados=atrasados, sem_dono=sem_dono,
                sem_t_ed=sem_t_ed, sem_t_alt=sem_t_alt, f_ontem=f_ontem,
                f_hoje_ok=f_hoje_ok, f_amanha=f_amanha, f_prox=f_prox,
                prox_data=prox_data, serie=serie, cards=cards, mes_lab=cfg["mes_ref"],
                dur_ed=dur_ed, dur_alt=dur_alt, media_cx=media_cx, dist_cx=dist_cx,
                sem_cx=sem_cx, cx_quebrada=cx_quebrada, pesos=pesos)


# ------------------------------------------------------- agenda de publicação

def eh_util(d):
    return d.weekday() < 5 and d not in FERIADOS


def prox_util(d):
    while not eh_util(d):
        d += timedelta(days=1)
    return d


def agenda_pub(todos, hoje, fim):
    """
    Propõe data de publicação para cada card que ainda não tem uma.

    Regras, na ordem:
      1. nada vai ao ar antes de estar pronto
      2. teto de TETO_PUB_DIA por dia (margem para refazer)
      3. publicações do mesmo cliente ficam espaçadas
      4. nada em fim de semana nem feriado

    Cards de clientes em FORA_CADENCIA não recebem data — a publicação
    depende de combinar com o cliente.
    """
    dias = []
    cur = hoje + timedelta(days=1)
    while cur <= fim:
        if eh_util(cur):
            dias.append(cur)
        cur += timedelta(days=1)

    inicio_mes = date(hoje.year, hoje.month, 1)
    confirmados, pendentes, fora, anuncios = [], [], [], []
    for c in todos:
        if c["_pub"]:
            if inicio_mes <= c["_pub"] <= fim:
                confirmados.append(c)
            continue
        ef = c["_fim"].date() if c["_fim"] else None
        prazo = c["_prazo_ef"]                          # inclui o previsto pela captação
        if not (ef or prazo):
            continue                                    # sem âncora de tempo
        # só o que pertence ao mês corrente: card de meses anteriores já
        # teve seu momento, e reagendá-lo agora só encheria o calendário
        recente = max([d for d in (ef, prazo) if d])
        if recente < inicio_mes:
            continue
        if c["_anuncio"]:
            anuncios.append(c)                          # sobe direto na plataforma
            continue
        if c["_fora"]:
            fora.append(c)
            continue
        # primeira data possível
        if c["_fim"]:
            base = c["_fim"].date() + timedelta(days=1)
        else:
            base = prazo + timedelta(days=2)
        c["_cedo"] = prox_util(max(base, hoje + timedelta(days=1)))
        pendentes.append(c)

    if not dias:
        return dias, {}, confirmados, [], fora, anuncios

    carga = {d: 0 for d in dias}
    for c in confirmados:
        if c["_pub"] in carga:
            carga[c["_pub"]] += 1

    por_cli = {}
    for c in pendentes:
        por_cli.setdefault(c["_cli"] or "(sem cliente)", []).append(c)

    LONGE = datetime(2099, 1, 1, tzinfo=TZ)

    def ordem_entrega(c):
        """
        A ordem da fila é a ordem em que as coisas ficaram prontas, não a
        numeração do título: se o VIDEO 08 é entregue antes do VIDEO 02, ele
        pega o slot mais cedo. Critérios, em ordem:
          1. quando o card fica publicável (para entregue, é a data de entrega)
          2. entregue antes de não-entregue, em empate
          3. data de entrega
          4. título, só para desempatar de forma estável
        """
        return (c["_cedo"], 0 if c["_fim"] else 1, c["_fim"] or LONGE, c["titulo"])

    for cli in sorted(por_cli, key=lambda k: -len(por_cli[k])):
        fila = sorted(por_cli[cli], key=ordem_entrega)
        n = len(fila)
        janela = [d for d in dias if d >= min(c["_cedo"] for c in fila)] or dias[-1:]
        # divisão real: com 8 cards em 15 dias o passo é 1,875 — arredondar
        # para 1 empilharia os oito nos primeiros oito dias
        passo_f = len(janela) / float(n)
        passo = max(1, int(round(passo_f)))
        usados = []
        for i, c in enumerate(fila):
            alvo = janela[min(len(janela) - 1, int(round(i * passo_f)))]
            escolhido = None
            for gap in (passo, max(1, passo - 1), 1):
                for d in sorted(janela, key=lambda y: (abs((y - alvo).days), y)):
                    if d < c["_cedo"]:
                        continue
                    if any(abs((d - u).days) < gap for u in usados):
                        continue
                    if carga.get(d, 0) < TETO_PUB_DIA:
                        escolhido = d
                        break
                if escolhido:
                    break
            if not escolhido:
                cand = [d for d in janela if d >= c["_cedo"]] or janela
                escolhido = min(cand, key=lambda y: carga.get(y, 0))
            c["_pub_prop"] = escolhido
            usados.append(escolhido)
            carga[escolhido] = carga.get(escolhido, 0) + 1

    return dias, carga, confirmados, pendentes, fora, anuncios


# ---------------------------------------------------------------- comentário

def comentario(m):
    """Leitura automática da saúde da operação. Regras fixas, texto curto."""
    delta = m["entregue"] - m["esperado"]
    notas = []  # pares (gravidade, texto); 0 = ok, 1 = atenção, 2 = crítico

    if delta >= 0:
        notas.append((0, "O ritmo está em dia: %d entregas contra %d esperadas até hoje, "
                      "projetando %d no fim do mês (meta %d)."
                      % (m["entregue"], m["esperado"], m["projecao"], m["meta"])))
    elif delta >= -3:
        notas.append((1, "O ritmo está %d entrega(s) abaixo do esperado — recuperável, "
                      "mas a projeção atual fecha o mês em %d de %d."
                      % (-delta, m["projecao"], m["meta"])))
    else:
        notas.append((2, "O ritmo está %d entregas abaixo do esperado e a projeção "
                      "fecha o mês em %d de %d — sem mudança de cadência, a meta não sai."
                      % (-delta, m["projecao"], m["meta"])))

    if m["atrasados"]:
        n = len(m["atrasados"])
        idade = (m["hoje"] - m["atrasados"][0]["_prazo"]).days
        notas.append((2 if (n >= 4 or idade >= 7) else 1,
                      "Há %d card(s) atrasado(s), o mais antigo há %d dia(s) — "
                      "priorizar antes de puxar coisa nova." % (n, idade)))

    if m["pct_prazo"] is not None and m["pct_prazo"] < 85:
        notas.append((2 if m["pct_prazo"] < 60 else 1,
                      "A pontualidade preocupa: %d%% das entregas do mês saíram no prazo."
                      % m["pct_prazo"]))

    gaps = []
    base = m["total_atr"]
    if base:
        for nome, alvo in m["meta_dist"].items():
            pc = round(100 * m["dist"].get(nome, 0) / base)
            if abs(pc - alvo) > 18:
                gaps.append("%s em %d%% contra meta de %d%%" % (nome, pc, alvo))
    if gaps:
        notas.append((1, "A distribuição 70/30 está torta: %s." % "; ".join(gaps)))

    if m["antec"] < m["meta_antec"]:
        notas.append((0, "Seguimos operando colados no prazo: nada pronto com mais de %d dia(s) "
                      "de folga, contra a meta de %d." % (m["antec"], m["meta_antec"])))

    furos = len(m["sem_t_ed"]) + len(m["sem_t_alt"])
    if furos:
        notas.append((1 if furos >= 4 else 0,
                      "%d card(s) do mês estão sem tempo registrado (%d de edição, %d de "
                      "alteração) — cada um desses sai das médias."
                      % (furos, len(m["sem_t_ed"]), len(m["sem_t_alt"]))))

    sev = max(s for s, _ in notas) if notas else 0
    # o pior assunto abre o comentário; ordem estável dentro da mesma gravidade
    notas.sort(key=lambda x: -x[0])
    veredito = ["<b>Saúde da operação: boa.</b>",
                "<b>Saúde da operação: exige atenção.</b>",
                "<b>Saúde da operação: crítica.</b>"][sev]
    return veredito + " " + " ".join(t for _, t in notas[:4])


# ---------------------------------------------------------------- dados p/ JS

def dados_js(cfg, hoje, todos):
    def d10(v):
        return v.isoformat() if v else None
    cards = []
    for c in todos:
        if c["_final"]:
            st = "fin"
        elif c["_aprov"]:
            st = "apr"
        elif c["_exec"]:
            st = "exe"
        else:
            st = "todo"
        cards.append({
            "t": c.get("titulo") or "(sem título)",
            "cl": c.get("cliente"),
            "r": c.get("responsavel"),
            "c": c.get("categoria"),
            "st": st,
            "p": d10(c["_prazo"]),
            "f": d10(c["_fim"].date() if c["_fim"] else None),
            "d": d10(c["_grav"]),
            "pb": d10(c["_pub"]),
            "atr": c["_atraso"],
            "cx": c["_peso"],
            "de": round(c["_dur_ed"]) if c["_dur_ed"] is not None else None,
            "da": round(c["_dur_alt"]) if c["_dur_alt"] is not None else None,
            "ad": d10(c["_alt_f"].date() if c["_alt_f"] else None),
            "u": c.get("url"),
        })
    return {"hoje": hoje.isoformat(), "cards": cards,
            "metaDist": cfg["meta_dist"],
            "cores": {"Maila": "--s1", "Petterson": "--s2", "Pedro": "--s3",
                      "Ex-editor": "--axis"}}


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
 flex-wrap:wrap;margin-bottom:18px}
.top h1{font-size:15px;font-weight:650;letter-spacing:.10em;text-transform:uppercase}
.top .sub{font-size:13px;color:var(--muted);margin-top:3px}
.stamp{font-size:12px;color:var(--muted);text-align:right}
.stamp b{display:block;font-size:19px;font-weight:600;color:var(--ink);letter-spacing:-.01em}

.tabs{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}
.tab{font:600 13px/1 system-ui;padding:9px 16px;border-radius:20px;border:1px solid var(--ring);
 background:var(--surface);color:var(--ink2);cursor:pointer}
.tab.on{background:var(--ink);color:var(--plane);border-color:var(--ink)}
section[hidden]{display:none}

.card{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:18px 20px}
.grid{display:grid;gap:14px}
.g4{grid-template-columns:repeat(4,1fr)}
.g2{grid-template-columns:1.35fr 1fr}
.g3{grid-template-columns:repeat(3,1fr)}
@media(max-width:900px){.g4{grid-template-columns:repeat(2,1fr)}.g2,.g3{grid-template-columns:1fr}}
@media(max-width:520px){.g4{grid-template-columns:1fr}}

h2{font-size:11px;font-weight:650;letter-spacing:.09em;text-transform:uppercase;
 color:var(--muted);margin-bottom:14px}

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

.bars{display:flex;align-items:flex-end;gap:6px;height:118px;margin-top:4px}
.bars .col{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;
 height:100%;position:relative;cursor:default}
.bars .bar{width:100%;max-width:34px;background:var(--s1);border-radius:4px 4px 0 0;min-height:2px;
 transition:opacity .12s}
.bars .col:hover .bar{opacity:.75}
.bars .n{font-size:11.5px;font-weight:600;color:var(--ink2);margin-bottom:4px;font-variant-numeric:tabular-nums}
.bars .col.hoje .bar{background:var(--s2)}
.xaxis{display:flex;gap:6px;border-top:1px solid var(--axis);padding-top:6px;margin-top:2px}
.xaxis span{flex:1;text-align:center;font-size:10.5px;color:var(--muted);font-variant-numeric:tabular-nums;
 overflow:hidden;text-overflow:clip;white-space:nowrap}
.xaxis span.hoje{color:var(--ink);font-weight:650}
.pace{position:relative;height:0}
.pace i{position:absolute;left:0;right:0;border-top:1px dashed var(--axis)}

.stack{display:flex;height:34px;border-radius:6px;overflow:hidden;gap:2px;margin:6px 0 12px}
.stack i{display:block;position:relative}
.stack i span{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
 font-size:12px;font-weight:650;color:#fff}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12.5px;color:var(--ink2)}
.legend b{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:6px;vertical-align:1px}
.dline{display:flex;justify-content:space-between;font-size:12.5px;color:var(--ink2);
 padding:6px 0;border-top:1px solid var(--grid);gap:10px}
.dline b{font-weight:600;color:var(--ink);font-variant-numeric:tabular-nums;white-space:nowrap}

ul{list-style:none}
.item{display:flex;gap:9px;align-items:baseline;padding:7px 0;border-top:1px solid var(--grid);font-size:13.5px}
.item:first-child{border-top:0}
.item a{color:var(--ink);text-decoration:none;font-weight:500;flex:1;min-width:0}
.item a:hover{text-decoration:underline}
.item .meta{font-size:11.5px;color:var(--muted);white-space:nowrap;font-variant-numeric:tabular-nums}
.dot{width:7px;height:7px;border-radius:50%;flex:none;position:relative;top:5px}
.d1{background:var(--s1)} .d2{background:var(--s2)} .d3{background:var(--s3)} .d0{background:var(--axis)}
.empty{font-size:13px;color:var(--muted);padding:8px 0;font-style:italic}
.count{font-weight:600;color:var(--ink);font-variant-numeric:tabular-nums}

.alert{display:flex;gap:11px;align-items:flex-start;padding:11px 0;border-top:1px solid var(--grid)}
.alert:first-child{border-top:0}
.ico{font:600 12px/18px system-ui;width:18px;height:18px;border-radius:50%;flex:none;text-align:center;color:#fff}
.i-crit{background:var(--crit)} .i-warn{background:var(--warn);color:#3a2a00} .i-info{background:var(--muted)}
.alert .txt{flex:1;font-size:13.5px;line-height:1.45}
.alert .txt b{font-weight:650}
.alert .txt em{font-style:normal;color:var(--muted);font-size:12.5px;display:block;margin-top:2px}
.btnlink{font:600 11.5px/1 system-ui;padding:5px 10px;border-radius:14px;border:1px solid var(--ring);
 background:var(--surface);color:var(--ink);cursor:pointer;white-space:nowrap;margin-left:8px}
.btnlink:hover{background:var(--grid)}

.comment{font-size:14px;line-height:1.7;color:var(--ink)}
.comment .sig{display:block;margin-top:10px;font-size:11.5px;color:var(--muted)}

/* calendário da agenda */
.cal{display:grid;grid-template-columns:repeat(7,1fr);gap:7px}
.cal .hd{font-size:10.5px;font-weight:650;letter-spacing:.07em;text-transform:uppercase;
 color:var(--muted);text-align:center;padding-bottom:4px}
.dia{border:1px solid var(--ring);border-radius:9px;padding:8px;min-height:106px;
 background:var(--surface);display:flex;flex-direction:column;gap:4px}
.dia.vazio-mes{background:transparent;border-color:transparent}
.dia.off{background:var(--plane);border-style:dashed}
.dia .num{font-size:12px;font-weight:650;font-variant-numeric:tabular-nums;color:var(--ink2);
 display:flex;justify-content:space-between;align-items:center}
.dia .n{font-size:10px;font-weight:650;padding:1px 6px;border-radius:10px;color:#fff;background:var(--s1)}
.dia .n.cheio{background:var(--s2)}
.ent{font-size:10.5px;line-height:1.3;padding:3px 5px;border-radius:5px;background:var(--plane);
 border-left:3px solid var(--axis);color:var(--ink)}
.ent.prop{border-left-style:dashed}
.ent.e-entregue{border-left-color:var(--good)}
.ent.e-aprov{border-left-color:var(--s1)}
.ent.e-exec{border-left-color:var(--warn)}
.ent.e-fazer{border-left-color:var(--muted)}
.nada{font-size:10.5px;color:var(--muted);font-style:italic;margin-top:auto}
.tag{display:inline-block;font-size:10.5px;font-weight:650;padding:1px 7px;border-radius:10px;
 border:1px solid var(--ring)}
.g-entregue{color:var(--good-ink)} .g-aprov{color:var(--s1)}
.g-exec{color:var(--serious)} .g-fazer{color:var(--muted)}

.chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.chip{font:600 12px/1 system-ui;padding:7px 12px;border-radius:16px;border:1px solid var(--ring);
 background:var(--surface);color:var(--ink2);cursor:pointer}
.chip.on{background:var(--s1);border-color:var(--s1);color:#fff}
.range{display:flex;gap:8px;align-items:center;font-size:12.5px;color:var(--ink2);flex-wrap:wrap;
 margin-bottom:16px}
.range input{font:13px system-ui;padding:6px 8px;border:1px solid var(--ring);border-radius:8px;
 background:var(--surface);color:var(--ink)}
.range .btn{font:600 12px/1 system-ui;padding:8px 14px;border-radius:8px;border:1px solid var(--ring);
 background:var(--surface);cursor:pointer;color:var(--ink)}
.range .btn:hover{background:var(--grid)}
.plabel{font-size:12.5px;color:var(--muted);margin:0 0 14px}

table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--grid)}
th{font-size:10.5px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);font-weight:650}
td.num{text-align:right;font-variant-numeric:tabular-nums}
td a{color:var(--ink);text-decoration:none}
td a:hover{text-decoration:underline}
.foot{margin-top:26px;font-size:11.5px;color:var(--muted);line-height:1.6}
"""

JS = r"""
function $(id){return document.getElementById(id)}
function esc(t){return String(t==null?"":t).replace(/&/g,"&amp;").replace(/</g,"&lt;")
 .replace(/>/g,"&gt;").replace(/"/g,"&quot;")}
function showTab(id,btn){
 ["diario","periodo","agenda","dados"].forEach(function(k){
  $("tab-"+k).hidden = (k!==id);
  $("btn-"+k).classList.toggle("on", k===id);
 });
 window.scrollTo(0,0);
}
/* ---------- datas (strings YYYY-MM-DD, comparação lexicográfica) ---------- */
function toD(s){var p=s.split("-");return new Date(Date.UTC(+p[0],+p[1]-1,+p[2]))}
function toS(d){return d.toISOString().slice(0,10)}
function shiftDays(s,n){var d=toD(s);d.setUTCDate(d.getUTCDate()+n);return toS(d)}
function shiftMonths(s,n){var d=toD(s);d.setUTCMonth(d.getUTCMonth()+n);return toS(d)}
function endOfMonth(s){var d=toD(s);d.setUTCMonth(d.getUTCMonth()+1);d.setUTCDate(0);return toS(d)}
function diffDays(a,b){return Math.round((toD(b)-toD(a))/864e5)}
function diasUteis(a,b){var n=0,d=toD(a),f=toD(b);while(d<=f){var w=d.getUTCDay();if(w>0&&w<6)n++;d.setUTCDate(d.getUTCDate()+1)}return n}
function fmtBR(s){return s?s.slice(8,10)+"/"+s.slice(5,7)+"/"+s.slice(0,4):"—"}
var MES=["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"];

var D=window.DATA, HOJE=D.hoje;
var MIN_DATA=HOJE;
D.cards.forEach(function(c){[c.p,c.f,c.d].forEach(function(x){if(x&&x<MIN_DATA)MIN_DATA=x})});

var PERIODOS={
 "7d":  function(){return [shiftDays(HOJE,-6),HOJE,"últimos 7 dias"]},
 "mes": function(){return [HOJE.slice(0,8)+"01",endOfMonth(HOJE),"este mês (inclui prazos até o fim do mês)"]},
 "30d": function(){return [shiftDays(HOJE,-29),HOJE,"últimos 30 dias"]},
 "2m":  function(){return [shiftMonths(HOJE,-2),HOJE,"últimos 2 meses"]},
 "3m":  function(){return [shiftMonths(HOJE,-3),HOJE,"últimos 3 meses"]},
 "6m":  function(){return [shiftMonths(HOJE,-6),HOJE,"últimos 6 meses"]},
 "ytd": function(){return [HOJE.slice(0,4)+"-01-01",HOJE,"de 1º de janeiro até hoje"]},
 "12m": function(){return [shiftMonths(HOJE,-12),HOJE,"últimos 12 meses"]},
 "tudo":function(){return [MIN_DATA,HOJE,"todo o histórico registrado"]}
};

function setChip(key){
 document.querySelectorAll(".chip").forEach(function(b){b.classList.toggle("on",b.dataset.k===key)});
}
function aplicarPeriodo(key){
 var p=PERIODOS[key]();
 setChip(key);
 $("d-ini").value=p[0]; $("d-fim").value=p[1];
 render(p[0],p[1],p[2]);
}
function aplicarCustom(){
 var a=$("d-ini").value,b=$("d-fim").value;
 if(!a||!b){return}
 if(a>b){var t=a;a=b;b=t;$("d-ini").value=a;$("d-fim").value=b}
 setChip("");
 render(a,b,"período personalizado");
}
function inR(x,a,b){return x&&x>=a&&x<=b}

function render(a,b,label){
 $("p-label").textContent="Período: "+fmtBR(a)+" a "+fmtBR(b)+" — "+label+".";
 var ent=D.cards.filter(function(c){return inR(c.f,a,b)});
 var du=Math.max(1,diasUteis(a,b));

 /* tile: entregues */
 $("t-ent").textContent=ent.length;
 $("t-ent-note").textContent=(ent.length/du).toFixed(2).replace(".",",")+" por dia útil ("+du+" dias úteis no período)";

 /* tile: pontualidade */
 var cp=ent.filter(function(c){return c.p&&c.atr!=null});
 var np=cp.filter(function(c){return c.atr<=0});
 var pct=cp.length?Math.round(100*np.length/cp.length):null;
 $("t-prz").textContent=pct==null?"—":pct+"%";
 $("t-prz").style.color=pct==null?"":(pct>=85?"var(--good)":pct>=70?"var(--warn)":"var(--crit)");
 $("t-prz-note").textContent=cp.length?np.length+" de "+cp.length+" entregas dentro do prazo":"nenhuma entrega com prazo no período";

 /* tile: dias entre a gravação (campo Data) e o fim da edição */
 var ca=ent.filter(function(c){return c.d});
 if(ca.length){
  var soma=0;ca.forEach(function(c){soma+=diffDays(c.d,c.f)});
  var med=soma/ca.length;
  $("t-ant").innerHTML=med.toFixed(0)+'<small> dias</small>';
  $("t-ant-note").textContent="média sobre "+ca.length+" entrega(s) com data de gravação preenchida";
 }else{
  $("t-ant").textContent="—";
  $("t-ant-note").textContent="nenhuma entrega do período tem data de gravação preenchida";
 }

 /* tile: antecedência de publicação (Publicação − Edição Fim) */
 var cp2=ent.filter(function(c){return c.pb});
 if(cp2.length){
  var s2=0;cp2.forEach(function(c){s2+=diffDays(c.f,c.pb)});
  var m2=s2/cp2.length;
  $("t-apub").innerHTML=m2.toFixed(0)+'<small> dias</small>';
  $("t-apub").style.color=m2<0?"var(--crit)":(m2>=7?"var(--good)":"");
  $("t-apub-note").textContent="colchão médio entre fechar a edição e ir ao ar · "+cp2.length+
   " entrega(s)"+(m2<0?" — negativo: a edição fechou DEPOIS da data de publicação":"");
 }else{
  $("t-apub").style.color="";
  $("t-apub").textContent="—";
  $("t-apub-note").textContent="campo Publicação criado em 09/08/2026 — o número aparece "+
   "sozinho assim que houver entregas com ele preenchido";
 }

 /* complexidade média — escala 1 a 3, sobre os cards com prazo no período */
 var noPer=D.cards.filter(function(c){return inR(c.p,a,b)||inR(c.f,a,b)});
 var cxs=noPer.filter(function(c){return c.cx}).map(function(c){return c.cx});
 if(cxs.length){
  var sc=0;cxs.forEach(function(x){sc+=x});
  var mc=sc/cxs.length;
  var nb=cxs.filter(function(x){return x===1}).length;
  var ni=cxs.filter(function(x){return x===2}).length;
  var na=cxs.filter(function(x){return x===3}).length;
  $("t-cx").textContent=mc.toFixed(2).replace(".",",");
  $("t-cx-note").textContent=nb+" básico · "+ni+" intermediário · "+na+" avançado · "+
   (noPer.length-cxs.length)+" sem preencher";
 }else{
  $("t-cx").textContent="—";
  $("t-cx-note").textContent="nenhum card do período tem Complexidade preenchida";
 }

 /* tempos médios */
 var ded=ent.filter(function(c){return c.de!=null}).map(function(c){return c.de});
 pintaDur("t-ded",ded,"entrega(s) com Edição Início e Fim");
 var dal=D.cards.filter(function(c){return inR(c.ad,a,b)&&c.da!=null}).map(function(c){return c.da});
 pintaDur("t-dal",dal,"alteração(ões) concluída(s) no período");

 /* distribuição por responsável */
 var por={},semR=0;
 ent.forEach(function(c){if(c.r){por[c.r]=(por[c.r]||0)+1}else{semR++}});
 var nomes=Object.keys(por).sort(function(x,y){return por[y]-por[x]});
 var base=ent.length-semR;
 var segs="",legs="",lins="";
 nomes.forEach(function(n){
  var v=por[n],pc=base?Math.round(100*v/base):0;
  var cor="var("+(D.cores[n]||"--s3")+")";
  segs+='<i style="flex:'+Math.max(v,1)+';background:'+cor+'">'+(pc>=8?'<span>'+pc+'%</span>':'')+'</i>';
  legs+='<span><b style="background:'+cor+'"></b>'+esc(n)+'</span>';
  var alvo=D.metaDist[n];
  var metaTxt=alvo!=null?' <span style="color:var(--muted);font-weight:400">/ meta '+alvo+'%</span>':'';
  lins+='<div class="dline"><span>'+esc(n)+'</span><b>'+v+' de '+base+' &nbsp;·&nbsp; '+pc+'%'+metaTxt+'</b></div>';
 });
 if(!base){segs='<i style="flex:1;background:var(--axis)"><span>sem base</span></i>'}
 if(semR){lins+='<div class="dline" style="color:var(--crit)"><span><b style="color:var(--crit)">'+semR+
  ' entrega(s) sem responsável</b> fora do cálculo</span></div>'}
 $("p-stack").innerHTML=segs; $("p-legs").innerHTML=legs; $("p-lins").innerHTML=lins;

 /* categorias */
 var cats={};
 ent.forEach(function(c){var k=c.c||"(sem categoria)";cats[k]=(cats[k]||0)+1});
 var ck=Object.keys(cats).sort(function(x,y){return cats[y]-cats[x]});
 var mx=ck.length?cats[ck[0]]:1,ch="";
 ck.forEach(function(k){
  var v=cats[k];
  ch+='<div class="dline"><span style="flex:1">'+esc(k)+
   '<span style="display:block;height:5px;border-radius:3px;background:var(--s1);opacity:.85;margin-top:4px;width:'+
   Math.max(3,Math.round(100*v/mx))+'%"></span></span><b>'+v+'</b></div>';
 });
 $("p-cats").innerHTML=ch||'<p class="empty">Nada entregue no período.</p>';

 /* gráfico de entregas ao longo do tempo */
 grafico(ent,a,b);

 /* tabela */
 var rows=D.cards.filter(function(c){return inR(c.p,a,b)||inR(c.f,a,b)||inR(c.d,a,b)});
 rows.sort(function(x,y){return (x.p||x.f||"9999")<(y.p||y.f||"9999")?-1:1});
 var EST={fin:"Finalizado",apr:"Em aprovação",exe:"Em execução",todo:"A fazer"};
 var html="";
 rows.forEach(function(c){
  var at=c.atr,atx=at==null?"—":(at<=0?"no prazo":"+"+at+" d");
  var cor=(at!=null&&at>0)?' style="color:var(--crit);font-weight:600"':'';
  html+="<tr><td><a href=\""+esc(c.u||"#")+"\" target=\"_blank\" rel=\"noopener\">"+esc(c.t)+"</a></td><td>"+
   esc(c.r||"—")+"</td><td>"+esc(c.c||"—")+"</td><td>"+EST[c.st]+"</td><td>"+fmtBR(c.p)+"</td><td>"+
   fmtBR(c.f)+"</td><td class=num"+cor+">"+atx+"</td></tr>";
 });
 $("p-tbody").innerHTML=html||'<tr><td colspan="7" class="empty">Nenhum card no período.</td></tr>';
 $("p-n").textContent=rows.length;
}

function fmtDur(mn){
 if(mn==null)return "—";
 mn=Math.round(mn);
 if(mn<60)return mn+"min";
 if(mn<2880)return Math.floor(mn/60)+"h"+("0"+(mn%60)).slice(-2);
 return (mn/1440).toFixed(1).replace(".",",")+" dias";
}
function mediana(v){
 var s=v.slice().sort(function(a,b){return a-b}),n=s.length;
 return n%2?s[(n-1)/2]:(s[n/2-1]+s[n/2])/2;
}
function pintaDur(id,v,rotulo){
 if(v.length){
  var soma=0;v.forEach(function(x){soma+=x});
  $(id).textContent=fmtDur(soma/v.length);
  $(id+"-note").textContent="mediana "+fmtDur(mediana(v))+" · "+v.length+" "+rotulo+
   " · tempo de calendário entre início e fim, não horas trabalhadas";
 }else{
  $(id).textContent="—";
  $(id+"-note").textContent="nenhuma "+rotulo.replace("(s)","").replace("(ões)","")+" no período";
 }
}

function grafico(ent,a,b){
 var span=diffDays(a,b)+1,bucket,lab;
 if(span<=40){bucket=function(s){return s};lab=function(k){return k.slice(8,10)}}
 else if(span<=200){
  bucket=function(s){var d=toD(s);var w=(d.getUTCDay()+6)%7;d.setUTCDate(d.getUTCDate()-w);return toS(d)};
  lab=function(k){return k.slice(8,10)+"/"+k.slice(5,7)};
 }else{
  bucket=function(s){return s.slice(0,7)};
  lab=function(k){return MES[+k.slice(5,7)-1]+"/"+k.slice(2,4)};
 }
 var keys=[],map={};
 var cur=bucket(a),fim=bucket(b);
 while(cur<=fim){
  keys.push(cur);map[cur]=0;
  if(span<=40)cur=shiftDays(cur,1);
  else if(span<=200)cur=shiftDays(cur,7);
  else cur=shiftMonths(cur+"-01"===cur?cur:cur+"-01",1).slice(0,7);
 }
 ent.forEach(function(c){var k=bucket(c.f);if(k in map)map[k]++});
 var mx=1;keys.forEach(function(k){if(map[k]>mx)mx=map[k]});
 var bars="",xs="";
 var passo=Math.max(1,Math.ceil(keys.length/24));
 keys.forEach(function(k,i){
  var n=map[k],h=100*n/mx;
  bars+='<div class="col" title="'+k+' — '+n+' entrega(s)"><span class="n">'+(n||"")+
   '</span><span class="bar" style="height:'+h.toFixed(1)+'%"></span></div>';
  xs+='<span>'+(i%passo===0?lab(k):"")+'</span>';
 });
 $("p-bars").innerHTML=bars;
 $("p-xaxis").innerHTML=xs;
}

document.addEventListener("DOMContentLoaded",function(){aplicarPeriodo("mes")});
"""


def li(c, extra=""):
    resp = c.get("responsavel")
    d = {"Maila": "d1", "Petterson": "d2", "Pedro": "d3"}.get(resp, "d0")
    tag = resp or "sem responsável"
    return ('<li class="item"><span class="dot %s"></span>'
            '<a href="%s" target="_blank" rel="noopener">%s</a>'
            '<span class="meta">%s%s</span></li>'
            % (d, esc(c.get("url") or "#"), esc(c["titulo"]), esc(tag), extra))


def lista(cards, vazio, extra=lambda c: ""):
    if not cards:
        return '<p class="empty">%s</p>' % esc(vazio)
    return "<ul>" + "".join(li(c, extra(c)) for c in cards) + "</ul>"


MESES_EXT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
             "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _est_pub(c):
    """Estado do card para a agenda: (slug, rótulo)."""
    if c["_final"]:
        return "entregue", "Entregue"
    if c["_aprov"]:
        return "aprov", "Em aprovação"
    if c["_exec"]:
        return "exec", "Em execução"
    return "fazer", "A fazer"


def carregar_captacoes(caminho="captacoes.json"):
    """Captações vindas da agenda do Google. Ausente = painel sem o bloco."""
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f).get("captacoes", [])
    except (IOError, OSError, ValueError):
        return []


def bloco_captacoes(caps, hoje, todos):
    """
    Captações futuras da agenda, com a entrega e a publicação já projetadas
    pela regra gravação + 7 dias. Serve para enxergar a carga que vem antes
    de o card existir no Notion.
    """
    grav_existentes = {c["_grav"] for c in todos if c["_grav"]}
    futuras = [c for c in caps if c["data"] >= hoje.isoformat()]
    if not futuras:
        return dict(cap_n=0, cap_lista='<p class="empty">Nenhuma captação '
                    'agendada daqui para a frente — ou a agenda do Google '
                    'ainda não foi conectada (ver AGENDA_ICAL_URL).</p>')
    linhas = []
    for c in futuras[:12]:
        d = parse_d(c["data"])
        entrega = prazo_de_gravacao(d, 0)
        pub = prox_util(entrega + timedelta(days=2))
        ja = "já tem card com esta data" if d in grav_existentes else "sem card ainda"
        linhas.append(
            "<tr><td class=num style='text-align:left;white-space:nowrap'>%s %s</td>"
            "<td>%s</td><td class=num style='text-align:left'>%s</td>"
            "<td class=num style='text-align:left'>%s</td>"
            "<td style='color:var(--muted)'>%s</td></tr>"
            % (DIAS[d.weekday()], d.strftime("%d/%m"), esc(c["titulo"]),
               entrega.strftime("%d/%m"), pub.strftime("%d/%m"), ja))
    return dict(cap_n=len(futuras),
                cap_lista="<table><thead><tr><th>Captação</th><th>Evento na agenda</th>"
                          "<th>Entrega prevista</th><th>Publicação a partir de</th>"
                          "<th>No Notion</th></tr></thead><tbody>%s</tbody></table>"
                          % "".join(linhas))


def bloco_agenda(m, todos):
    """Monta calendário, tabela e contadores da aba Agenda de Publicação."""
    hoje, prim, ult = m["hoje"], m["prim"], m["ult"]
    dias, carga, conf, pend, fora, anuncios = agenda_pub(todos, hoje, ult)

    itens = []
    for c in conf:
        itens.append((c["_pub"], c, True))
    for c in pend:
        itens.append((c.get("_pub_prop"), c, False))
    itens = [(d, c, fixo) for d, c, fixo in itens if d]

    porta = {}
    for d, c, fixo in itens:
        porta.setdefault(d, []).append((c, fixo))

    # calendário do mês corrente
    cel = []
    cur = prim - timedelta(days=prim.weekday())
    lim = ult + timedelta(days=(6 - ult.weekday()))
    while cur <= lim:
        if cur.month != prim.month:
            cel.append('<div class="dia vazio-mes"></div>')
        else:
            lista_d = porta.get(cur, [])
            passou = cur <= hoje
            off = not eh_util(cur)
            n = len(lista_d)
            badge = ('<span class="n%s">%d</span>' % (" cheio" if n >= TETO_PUB_DIA else "", n)) if n else ""
            corpo = "".join(
                '<div class="ent e-%s%s" title="%s">%s</div>'
                % (_est_pub(c)[0], "" if fixo else " prop", esc(c["titulo"]), esc(c["titulo"]))
                for c, fixo in lista_d)
            if not corpo:
                if passou:
                    corpo = '<div class="nada">já passou</div>'
                elif cur in FERIADOS:
                    corpo = '<div class="nada">%s</div>' % esc(FERIADOS[cur])
                elif off:
                    corpo = '<div class="nada">fim de semana</div>'
                else:
                    corpo = '<div class="nada">livre</div>'
            cel.append('<div class="dia%s"><div class="num"><span>%d</span>%s</div>%s</div>'
                       % (" off" if (off or passou) else "", cur.day, badge, corpo))
        cur += timedelta(days=1)

    # tabela
    linhas = []
    for d, c, fixo in sorted(itens, key=lambda x: (x[0], x[1]["titulo"])):
        slug, rot = _est_pub(c)
        ef = c["_fim"].strftime("%d/%m") if c["_fim"] else "—"
        origem = ('<span style="color:var(--good-ink)">no Notion</span>' if fixo
                  else '<span style="color:var(--muted)">proposta</span>')
        linhas.append(
            '<tr><td class="num" style="text-align:left;white-space:nowrap">%s %s</td>'
            '<td><a href="%s" target="_blank" rel="noopener">%s</a></td>'
            '<td><span class="tag g-%s">%s</span></td>'
            '<td class="num" style="text-align:left">%s</td><td>%s</td></tr>'
            % (DIAS[d.weekday()], d.strftime("%d/%m"), esc(c.get("url") or "#"),
               esc(c["titulo"]), slug, rot, ef, origem))

    l_fora = lista(sorted(fora, key=lambda c: c["titulo"]),
                   "Nenhum card de cliente fora da cadência neste mês.",
                   extra=lambda c: " · %s" % c["_fora"])

    def _quando_ad(c):
        if c["_fim"]:
            return " · pronto em %s" % c["_fim"].strftime("%d/%m")
        return " · prazo %s" % fmt(c["_prazo"], False)

    l_ads = lista(sorted(anuncios, key=lambda c: (c["_fim"] or datetime(2099, 1, 1, tzinfo=TZ),
                                                  c["titulo"])),
                  "Nenhum anúncio no mês.", extra=_quando_ad)

    pico = max(carga.values()) if carga else 0
    return dict(
        ag_n=len(itens), ag_conf=len(conf), ag_prop=len([x for x in itens if not x[2]]),
        ag_dias=len(dias), ag_media=len(itens) / len(dias) if dias else 0,
        ag_pico=pico, ag_fora=len(fora), ag_ads=len(anuncios), ag_lads=l_ads,
        ag_cor="var(--good)" if pico <= TETO_PUB_DIA else "var(--crit)",
        ag_hd="".join('<div class="hd">%s</div>' % x for x in DIAS),
        ag_cel="".join(cel), ag_tab="".join(linhas) or
        '<tr><td colspan="5" class="empty">Nada a publicar até o fim do mês.</td></tr>',
        ag_lfora=l_fora, teto=TETO_PUB_DIA)


def bloco_complexidade(m):
    """Tile, barra e linhas da complexidade média."""
    cores = {"Básico": "var(--s3)", "Intermediário": "var(--s1)", "Avançado": "var(--s2)"}
    total = sum(m["dist_cx"].values())
    segs, legs, linhas = [], [], []
    for nome in ("Básico", "Intermediário", "Avançado"):
        n = m["dist_cx"].get(nome, 0)
        pc = round(100 * n / total) if total else 0
        if n:
            segs.append('<i style="flex:%d;background:%s"><span>%d%%</span></i>'
                        % (n, cores[nome], pc))
        legs.append('<span><b style="background:%s"></b>%s</span>' % (cores[nome], nome))
        linhas.append('<div class="dline"><span>%s <span style="color:var(--muted)">'
                      '(peso %d)</span></span><b>%d de %d &nbsp;·&nbsp; %d%%</b></div>'
                      % (nome, PESO_COMPLEX[nome], n, total, pc))
    if not total:
        segs.append('<i style="flex:1;background:var(--axis)"><span>sem base</span></i>')
    if m["sem_cx"]:
        linhas.append('<div class="dline" style="color:var(--crit)"><span>'
                      '<b style="color:var(--crit)">%d card(s) sem Complexidade</b> '
                      'ficam fora da média</span><b style="color:var(--crit)">%s</b></div>'
                      % (len(m["sem_cx"]),
                         esc(" · ".join(c["titulo"] for c in m["sem_cx"][:3]))))
    if m["cx_quebrada"]:
        linhas.append('<div class="dline" style="color:var(--crit)"><span>'
                      '<b style="color:var(--crit)">%d card(s) com a opção quebrada</b> '
                      'do select — corrigir no Notion</span><b style="color:var(--crit)">%s</b></div>'
                      % (len(m["cx_quebrada"]),
                         esc(" · ".join(c["titulo"] for c in m["cx_quebrada"][:3]))))

    mc = m["media_cx"]
    if mc is None:
        cx_txt, cx_note, cx_cor, cx_pct = "—", "nenhum card do mês tem Complexidade preenchida", "", 0
    else:
        cx_txt = ("%.2f" % mc).replace(".", ",")
        prox = NOME_COMPLEX[min(3, max(1, int(round(mc))))]
        cx_note = ("escala 1 a 3 · o mês está perto de <b>%s</b> · %d de %d cards preenchidos"
                   % (prox, len(m["pesos"]), len(m["cards"])))
        cx_cor = ("var(--s3)" if mc < 1.5 else
                  "var(--s1)" if mc < 2.5 else "var(--s2)")
        cx_pct = 100 * (mc - 1) / 2.0
    return dict(cx_txt=cx_txt, cx_note=cx_note, cx_cor=cx_cor or "var(--s1)", cx_pct=cx_pct,
                cx_segs="".join(segs), cx_legs="".join(legs), cx_linhas="".join(linhas))


def render(m, dados, todos):
    A = m["agora"]
    ano, mes = (int(x) for x in m["mes_lab"].split("-"))
    mes_nome = "%s/%d" % (MESES_EXT[mes - 1], ano)

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

    # --- 70/30
    base = m["total_atr"]
    segs, legs, linhas = [], [], []
    for nome, alvo in m["meta_dist"].items():
        n = m["dist"].get(nome, 0)
        pc = 100 * n / base if base else 0
        if n:
            segs.append('<i style="flex:%d;background:%s"><span>%d%%</span></i>'
                        % (max(n, 1), CORES_RESP.get(nome, "var(--s3)"), round(pc)))
        legs.append('<span><b style="background:%s"></b>%s</span>'
                    % (CORES_RESP.get(nome, "var(--s3)"), esc(nome)))
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
    if m["sem_dono"]:
        al.append(('i-warn', '~', "<b>%d card(s) sem responsável</b> — não entram no cálculo do 70/30."
                   "<em>%s</em>" % (len(m["sem_dono"]),
                                    esc(" · ".join(c["titulo"] for c in m["sem_dono"][:5])))))
    if m["sem_t_ed"]:
        al.append(('i-warn', '~', "<b>%d card(s) sem tempo de edição</b> — falta Edição Início "
                   "ou Edição Fim, então a duração não entra na média."
                   '<button class="btnlink" onclick="showTab(\'dados\')">ver quais →</button>'
                   "<em>%s</em>"
                   % (len(m["sem_t_ed"]), esc(" · ".join(c["titulo"] for c in m["sem_t_ed"][:5])))))
    if m["sem_t_alt"]:
        al.append(('i-warn', '~', "<b>%d card(s) sem tempo de alteração</b> — passaram por "
                   "alteração mas o par Início/Fim está incompleto."
                   '<button class="btnlink" onclick="showTab(\'dados\')">ver quais →</button>'
                   "<em>%s</em>"
                   % (len(m["sem_t_alt"]), esc(" · ".join(c["titulo"] for c in m["sem_t_alt"][:5])))))
    if not al:
        al.append(('i-info', '✓', "<b>Nada exigindo ação hoje.</b><em>Sem vencimentos, sem atrasos, "
                   "sem furo de preenchimento.</em>"))

    alertas = "".join('<div class="alert"><span class="ico %s">%s</span>'
                      '<span class="txt">%s</span></div>' % a for a in al)

    # --- fluxo amanhã
    amanha_lab = fmt(m["amanha"])
    if m["f_amanha"]:
        bloco_amanha = lista(m["f_amanha"], "")
    elif m["prox_data"]:
        bloco_amanha = ('<p class="empty">Nada previsto para %s.</p>'
                        '<h2 style="margin:14px 0 8px">Próximo lote · %s</h2>%s'
                        % (amanha_lab, fmt(m["prox_data"]), lista(m["f_prox"], "")))
    else:
        bloco_amanha = '<p class="empty">Nada previsto para %s nem adiante.</p>' % amanha_lab

    prazo_txt = ("%d%%" % m["pct_prazo"]) if m["pct_prazo"] is not None else "—"
    prazo_note = ("%d de %d entregas dentro da data" % (len(m["no_prazo"]), len(m["com_prazo"]))
                  if m["com_prazo"] else "sem base de comparação ainda")
    prazo_cor = "var(--good)" if (m["pct_prazo"] or 0) >= 85 else (
        "var(--warn)" if (m["pct_prazo"] or 0) >= 70 else "var(--crit)")

    # --- furos de tempo
    def _ord(cs):
        return sorted(cs, key=lambda c: (c["_prazo"] or date(2099, 1, 1), c["titulo"]))

    def _falta_ed(c):
        if not c["_ini"] and not c["_fim"]:
            return "falta Início e Fim"
        return "falta Edição Início" if not c["_ini"] else "falta Edição Fim"

    def _falta_alt(c):
        if not c["_alt_i"] and not c["_alt_f"]:
            return "falta Início e Fim"
        return "falta Alteração Início" if not c["_alt_i"] else "falta Alteração Fim"

    lista_ed = lista(_ord(m["sem_t_ed"]),
                     "Todo card entregue no mês tem Edição Início e Fim preenchidos. 🎉",
                     extra=lambda c: " · %s" % _falta_ed(c))
    lista_alt = lista(_ord(m["sem_t_alt"]),
                      "Nenhuma alteração do mês está com o par incompleto. 🎉",
                      extra=lambda c: " · %s" % _falta_alt(c))

    return """<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive,nosnippet">
<meta name="googlebot" content="noindex,nofollow">
<title>Painel — Audiovisual · %(dtitulo)s</title>
<style>%(css)s</style></head>
<body><div class="viz">

<div class="top">
  <div>
    <h1>Audiovisual · Painel</h1>
    <div class="sub">Chess · %(mes_nome)s · dia útil %(duc)d de %(dut)d</div>
  </div>
  <div class="stamp"><b>%(dtitulo)s</b>atualizado %(hora)s</div>
</div>

<div class="tabs">
  <button class="tab on" id="btn-diario" onclick="showTab('diario')">Painel Diário</button>
  <button class="tab" id="btn-periodo" onclick="showTab('periodo')">Análise por Período</button>
  <button class="tab" id="btn-agenda" onclick="showTab('agenda')">Agenda de Publicação</button>
  <button class="tab" id="btn-dados" onclick="showTab('dados')">Sem Tempo Registrado</button>
</div>

<!-- ==================== PAINEL DIÁRIO ==================== -->
<section id="tab-diario">

<div class="grid g3" style="margin-bottom:14px">
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
    <div class="lab">Em aberto no mês</div>
    <div class="val">%(n_fila)d</div>
    <div class="note">%(n_exec)d em execução · %(n_fazer)d a fazer.<br>
      Leitura por período fica na aba <b>Análise por Período</b>.</div>
  </div>
  <div class="card tile">
    <div class="lab">Tempo médio por edição</div>
    <div class="val">%(dur_ed_txt)s</div>
    <div class="note">%(dur_ed_note)s</div>
  </div>
  <div class="card tile">
    <div class="lab">Tempo médio por alteração</div>
    <div class="val">%(dur_alt_txt)s</div>
    <div class="note">%(dur_alt_note)s</div>
  </div>
  <div class="card tile">
    <div class="lab">Complexidade média</div>
    <div class="val" style="color:%(cx_cor)s">%(cx_txt)s</div>
    <div class="meter"><i style="width:%(cx_pct).1f%%;background:%(cx_cor)s"></i></div>
    <div class="note">%(cx_note)s</div>
  </div>
</div>

<div class="card" style="margin-bottom:14px">
  <h2>Complexidade das demandas do mês</h2>
  <div class="stack">%(cx_segs)s</div>
  <div class="legend" style="margin-bottom:10px">%(cx_legs)s</div>
  %(cx_linhas)s
  <p style="font-size:12.5px;color:var(--ink2);margin-top:12px;line-height:1.55">
  A média usa a escala <b>Básico = 1 · Intermediário = 2 · Avançado = 3</b>. Serve para
  comparar meses: um mês com a mesma quantidade de entregas mas média mais alta consumiu
  mais do time. Cards sem Complexidade preenchida ficam fora da conta.</p>
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

<div class="card" style="margin-bottom:14px">
  <h2>Comentário</h2>
  <p class="comment">%(comentario)s
  <span class="sig">— Claude · leitura automática gerada a cada atualização do painel, a partir de
  regras fixas sobre ritmo, prazo, distribuição e preenchimento.</span></p>
</div>

<div class="grid g3">
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

</section>

<!-- ==================== ANÁLISE POR PERÍODO ==================== -->
<section id="tab-periodo" hidden>

<div class="chips">
  <button class="chip" data-k="7d"  onclick="aplicarPeriodo('7d')">1 semana</button>
  <button class="chip" data-k="mes" onclick="aplicarPeriodo('mes')">Este mês</button>
  <button class="chip" data-k="30d" onclick="aplicarPeriodo('30d')">30 dias</button>
  <button class="chip" data-k="2m"  onclick="aplicarPeriodo('2m')">2 meses</button>
  <button class="chip" data-k="3m"  onclick="aplicarPeriodo('3m')">3 meses</button>
  <button class="chip" data-k="6m"  onclick="aplicarPeriodo('6m')">6 meses</button>
  <button class="chip" data-k="ytd" onclick="aplicarPeriodo('ytd')">Ano até hoje</button>
  <button class="chip" data-k="12m" onclick="aplicarPeriodo('12m')">12 meses</button>
  <button class="chip" data-k="tudo" onclick="aplicarPeriodo('tudo')">Tudo</button>
</div>
<div class="range">
  <span>Personalizado:</span>
  <input type="date" id="d-ini"> <span>até</span> <input type="date" id="d-fim">
  <button class="btn" onclick="aplicarCustom()">Aplicar</button>
</div>
<p class="plabel" id="p-label"></p>

<div class="grid g3" style="margin-bottom:14px">
  <div class="card tile">
    <div class="lab">Entregues no período</div>
    <div class="val" id="t-ent">—</div>
    <div class="note" id="t-ent-note"></div>
  </div>
  <div class="card tile">
    <div class="lab">Entregas no prazo</div>
    <div class="val" id="t-prz">—</div>
    <div class="note" id="t-prz-note"></div>
  </div>
  <div class="card tile">
    <div class="lab">Gravação → entrega</div>
    <div class="val" id="t-ant">—</div>
    <div class="note" id="t-ant-note"></div>
  </div>
  <div class="card tile">
    <div class="lab">Folga sobre o prazo</div>
    <div class="val">%(antec)d<small> dias</small></div>
    <div class="meter"><i style="width:%(pct_antec).1f%%;background:%(antec_cor)s"></i></div>
    <div class="note">o card pronto mais adiantado está %(antec)d dia(s) à frente do prazo ·
      meta %(meta_antec)d · retrato de agora, não varia com o filtro</div>
  </div>
  <div class="card tile">
    <div class="lab">Tempo médio por edição</div>
    <div class="val" id="t-ded">—</div>
    <div class="note" id="t-ded-note"></div>
  </div>
  <div class="card tile">
    <div class="lab">Tempo médio por alteração</div>
    <div class="val" id="t-dal">—</div>
    <div class="note" id="t-dal-note"></div>
  </div>
  <div class="card tile">
    <div class="lab">Antecedência de publicação</div>
    <div class="val" id="t-apub">—</div>
    <div class="note" id="t-apub-note"></div>
  </div>
  <div class="card tile">
    <div class="lab">Complexidade média</div>
    <div class="val" id="t-cx">—</div>
    <div class="note" id="t-cx-note"></div>
  </div>
</div>

<div class="grid g2" style="margin-bottom:14px">
  <div class="card">
    <h2>Entregas ao longo do período</h2>
    <div class="bars" id="p-bars"></div>
    <div class="xaxis" id="p-xaxis"></div>
  </div>
  <div class="card">
    <h2>Distribuição por responsável</h2>
    <div class="stack" id="p-stack"></div>
    <div class="legend" style="margin-bottom:10px" id="p-legs"></div>
    <div id="p-lins"></div>
  </div>
</div>

<div class="card" style="margin-bottom:14px">
  <h2>Entregas por categoria</h2>
  <div id="p-cats"></div>
</div>

<div class="card">
  <h2>Cards do período <span class="count" id="p-n">—</span></h2>
  <table><thead><tr><th>Card</th><th>Responsável</th><th>Categoria</th>
    <th>Estado</th><th>Prazo</th><th>Entrega</th><th class=num>Pontualidade</th></tr></thead>
    <tbody id="p-tbody"></tbody></table>
</div>

</section>

<!-- ==================== AGENDA DE PUBLICAÇÃO ==================== -->
<section id="tab-agenda" hidden>

<div class="grid g4" style="margin-bottom:14px">
  <div class="card tile">
    <div class="lab">A publicar até o fim do mês</div>
    <div class="val">%(ag_n)d</div>
    <div class="note">%(ag_conf)d com data já definida no Notion ·
      %(ag_prop)d com data proposta aqui</div>
  </div>
  <div class="card tile">
    <div class="lab">Dias úteis restantes</div>
    <div class="val">%(ag_dias)d</div>
    <div class="note">%(ag_media).1f publicações por dia, em média</div>
  </div>
  <div class="card tile">
    <div class="lab">Pico em um dia</div>
    <div class="val" style="color:%(ag_cor)s">%(ag_pico)d</div>
    <div class="note">teto de %(teto)d — é a margem para quando um vídeo precisa voltar</div>
  </div>
  <div class="card tile">
    <div class="lab">Fora do calendário</div>
    <div class="val">%(ag_ads)d<small> anúncios</small></div>
    <div class="note">%(ag_fora)d card(s) de clientes cuja captação não depende só da gente</div>
  </div>
</div>

<div class="card" style="margin-bottom:14px">
  <h2>%(mes_nome)s</h2>
  <div class="cal">%(ag_hd)s%(ag_cel)s</div>
  <div class="legend" style="margin-top:12px">
    <span><b style="background:var(--good)"></b>Entregue</span>
    <span><b style="background:var(--s1)"></b>Em aprovação</span>
    <span><b style="background:var(--warn)"></b>Em execução</span>
    <span><b style="background:var(--muted)"></b>A fazer</span>
    <span style="color:var(--muted)">borda cheia = data já no Notion · tracejada = proposta</span>
  </div>
</div>

<div class="card" style="margin-bottom:14px">
  <h2>Data por card <span class="count">%(ag_n)d</span></h2>
  <table><thead><tr><th>Publicar em</th><th>Card</th><th>Estado hoje</th>
    <th>Edição fim</th><th>Origem</th></tr></thead>
    <tbody>%(ag_tab)s</tbody></table>
</div>

<div class="card" style="margin-bottom:14px">
  <h2>Captações que vêm por aí <span class="count">%(cap_n)d</span></h2>
  <p style="font-size:13px;color:var(--ink2);margin-bottom:12px;line-height:1.55">
  Lidas direto da agenda do Google. A entrega é projetada pela regra
  <b>captação + %(dias_entrega)d dias úteis</b>, e a publicação abre dois dias depois disso.
  Serve para enxergar a carga que vem <b>antes</b> de o card existir no Notion — quando
  ele for criado e ganhar o campo Gravado, entra sozinho no calendário acima.</p>
  %(cap_lista)s
</div>

<div class="grid g2" style="margin-bottom:14px">
  <div class="card">
    <h2>Anúncios · sem data de publicação <span class="count">%(ag_ads)d</span></h2>
    <p style="font-size:13px;color:var(--ink2);margin-bottom:10px;line-height:1.55">
    Card com categoria <b>Ad</b> não entra no calendário: assim que fica pronto sobe direto
    na plataforma de anúncios. Continua contando como entrega no Painel Diário — só não
    disputa espaço no rodízio de publicação.</p>
    %(ag_lads)s
  </div>
  <div class="card">
    <h2>Fora da cadência automática <span class="count">%(ag_fora)d</span></h2>
    <p style="font-size:13px;color:var(--ink2);margin-bottom:10px;line-height:1.55">
    Estes ficam sem data automática — a publicação depende de combinar com o cliente.
    Continuam prontos, só não entram no rodízio.</p>
    %(ag_lfora)s
  </div>
</div>

<div class="card">
  <h2>Como esta agenda é montada</h2>
  <p style="font-size:13px;color:var(--ink2);line-height:1.65">
  Parte dos <b>cards que existem no Notion</b>, não do volume de contrato.
  Card que já tem <b>Publicação</b> preenchida aparece como está; os demais recebem a
  primeira data possível respeitando quatro regras:<br><br>
  <b>1.</b> Nada vai ao ar antes de estar pronto. Card com Edição Fim preenchida libera no
  dia seguinte; card ainda em execução ou a fazer libera dois dias depois do prazo, para
  caber a aprovação.<br>
  <b>2.</b> Teto de <b>%(teto)d publicações por dia</b>.<br>
  <b>3.</b> Publicações do mesmo cliente ficam espaçadas.<br>
  <b>4.</b> Nada em fim de semana nem feriado nacional.<br>
  <b>5.</b> A ordem da fila é a <b>ordem em que as coisas ficaram prontas</b>, não a numeração
  do título — se o VIDEO 08 é entregue antes do VIDEO 02, ele pega o slot mais cedo.<br>
  <b>6.</b> Card com categoria <b>Ad</b> fica fora: vai direto para a plataforma de anúncios.<br>
  <b>7.</b> Card <b>gravado mas ainda sem prazo</b> entra assim mesmo: o prazo é projetado
  em captação + %(dias_entrega)d dias úteis, mais 1 dia útil a cada 3 cards da mesma leva. Preencher
  o campo <b>Gravado</b> já remodela o calendário inteiro, sem precisar definir prazo.<br><br>
  <span style="color:var(--muted)">A agenda é recalculada a cada atualização do painel.
  Preencher o campo Publicação no Notion fixa a data e tira o card do cálculo.</span></p>
</div>

</section>

<!-- ==================== SEM TEMPO REGISTRADO ==================== -->
<section id="tab-dados" hidden>

<p class="plabel">Cards de %(mes_nome)s em que não dá para medir quanto tempo o trabalho levou.
Cada um deles fica de fora das médias de tempo do painel. Clique para abrir no Notion e preencher.</p>

<div class="card" style="margin-bottom:14px">
  <h2>Sem tempo de edição <span class="count">%(n_sed)d</span></h2>
  <p style="font-size:13px;color:var(--ink2);margin-bottom:10px;line-height:1.55">
  O card já saiu da edição (ou está finalizado), mas falta <b>Edição Início</b> ou
  <b>Edição Fim</b> — sem os dois não há duração.</p>
  %(lista_ed)s
</div>

<div class="card">
  <h2>Sem tempo de alteração <span class="count">%(n_salt)d</span></h2>
  <p style="font-size:13px;color:var(--ink2);margin-bottom:10px;line-height:1.55">
  O card passou por alteração — pelo status atual ou porque um dos campos foi preenchido —
  mas falta <b>Alteração Início</b> ou <b>Alteração Fim</b>.
  <span style="color:var(--muted)">Observação: o painel só enxerga alteração pelo status
  atual do card ou por campo preenchido pela metade. Uma alteração antiga, num card que já
  voltou para outro status sem nada preenchido, passa despercebida.</span></p>
  %(lista_alt)s
</div>

</section>

<p class="foot">Fonte: banco 🎯 Tarefas — Audiovisual (Notion) · %(n_cards)d cards com prazo em %(mes_nome)s ·
%(n_todos)d cards no histórico completo (desde o primeiro registro).
Horários convertidos para America/São_Paulo (UTC−3). &quot;Entregues&quot; = cards com Edição Fim preenchida,
incluindo os que aguardam aprovação. Pontualidade compara Edição Fim com Prazo.<br>
Gerado automaticamente em %(dtitulo)s às %(hora)s.</p>

</div>
<script>window.DATA=%(dados)s;</script>
<script>%(js)s</script>
</body></html>""" % dict(
        css=CSS, js=JS, dados=json.dumps(dados, ensure_ascii=False, separators=(",", ":")),
        dtitulo=fmt(m["hoje"]) + "/%d" % m["hoje"].year, hora=A.strftime("%H:%M"),
        mes_nome=mes_nome,
        duc=m["du_corridos"], dut=m["du_total"], entregue=m["entregue"], meta=m["meta"],
        pct_meta=pct_meta, pct_esp=pct_esp, ritmo_pill=ritmo_pill, esperado=m["esperado"],
        projecao=m["projecao"], ritmo_real=m["ritmo_real"], ritmo_alvo=m["ritmo_alvo"],
        prazo_txt=prazo_txt, prazo_note=prazo_note, prazo_cor=prazo_cor,
        antec=m["antec"], meta_antec=m["meta_antec"],
        pct_antec=min(100, 100 * m["antec"] / m["meta_antec"]),
        antec_cor="var(--good)" if m["antec"] >= m["meta_antec"] else "var(--crit)",
        n_fila=len(m["fila"]), n_fazer=len([c for c in m["fila"] if not c["_exec"]]),
        dur_ed_txt=fmt_dur(sum(m["dur_ed"]) / len(m["dur_ed"]) if m["dur_ed"] else None),
        dur_ed_note=("mediana %s · %d entrega(s) com Edição Início e Fim · tempo de "
                     "calendário, não horas trabalhadas"
                     % (fmt_dur(statistics.median(m["dur_ed"])), len(m["dur_ed"]))
                     if m["dur_ed"] else "nenhuma entrega do mês tem Edição Início e Fim preenchidos"),
        dur_alt_txt=fmt_dur(sum(m["dur_alt"]) / len(m["dur_alt"]) if m["dur_alt"] else None),
        dur_alt_note=("mediana %s · %d alteração(ões) concluída(s) no mês · tempo de "
                      "calendário, não horas trabalhadas"
                      % (fmt_dur(statistics.median(m["dur_alt"])), len(m["dur_alt"]))
                      if m["dur_alt"] else "nenhum card do mês tem Alteração Início e Fim preenchidos"),
        bars="".join(bars), xs="".join(xs), pace_top=max(0, pace_top),
        segs="".join(segs), legs="".join(legs), linhas="".join(linhas), alertas=alertas,
        comentario=comentario(m),
        lab_ontem=fmt(m["ontem"]), n_ontem=len(m["f_ontem"]),
        l_ontem=lista(m["f_ontem"], "Nenhuma entrega concluída ontem."),
        n_exec=len(m["execu"]), l_exec=lista(m["execu"], "Nenhum card em execução."),
        n_hoje=len(m["f_hoje_ok"]), l_hoje=lista(m["f_hoje_ok"], "Nada concluído hoje ainda."),
        lab_amanha=fmt(m["amanha"]), n_amanha=len(m["f_amanha"]), b_amanha=bloco_amanha,
        n_sed=len(m["sem_t_ed"]), lista_ed=lista_ed,
        n_salt=len(m["sem_t_alt"]), lista_alt=lista_alt,
        n_cards=len(m["cards"]), n_todos=len(dados["cards"]),
        dias_entrega=DIAS_ATE_ENTREGA,
        **bloco_agenda(m, todos), **bloco_complexidade(m),
        **bloco_captacoes(carregar_captacoes(), m["hoje"], todos))


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "cards.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "dashboard.html"
    with open(src, encoding="utf-8") as f:
        cfg = json.load(f)
    agora, hoje, todos = preparar(cfg)
    m = montar(cfg, agora, hoje, todos)
    html = render(m, dados_js(cfg, hoje, todos), todos)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(html)
    print("ok ->", dst, len(html), "bytes ·", len(m["cards"]), "cards no mês ·",
          len(todos), "no histórico")
