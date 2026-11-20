"""Cálculos del proyecto Pocket Clock.

Todo se calcula en memoria al arrancar (el servidor es efímero) a partir de:
- data/derived/frames.csv: por frame, distancia mínima rusher-QB y quién es el rusher más cercano (ver preprocesar.py)
- pffScoutingData.csv, plays.csv, players.csv, games.csv del dataset original (solo lectura)
"""
from __future__ import annotations

import math
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"
DERIVADOS = DATA / "derived"

UMBRAL_YD = 2.0       # rusher a menos de 2 yd del QB = "presión física"; es el umbral con mayor kappa contra PFF (ver validacion())
UMBRALES_SENSIBILIDAD = [1.0, 1.5, 2.0, 2.5, 3.0]
INICIO_S = 0.5        # se ignora el primer medio segundo (QB bajo centro arranca pegado a la línea)
MIN_SNAPS_OL = 50
MIN_SNAPS_RUSH = 100
MIN_DROPBACKS_QB = 100
POS_OL = {"T", "G", "C"}                      # posiciones oficiales de liniero ofensivo
ALINEACION_OL = ["LT", "LG", "C", "RG", "RT"]
TEMPRANA_S = 2.5                              # presión "temprana": antes de que salga una ruta rápida
# tiempo típico para lanzar cada familia de rutas (referencia de entrenadores; aproximado)
VENTANAS_RUTA = [("rápidas (slant, hitch)", 2.5), ("intermedias (dig, out)", 3.0), ("profundas (post, go)", 3.5)]
VENTANA_S = 4.0       # ventana del pocket para "segundos perdidos por presión"
CELDA = ["grupo_rushers", "tipo_jugada", "cobertura"]   # plan de la jugada usado para la presión esperada
MIN_CELDA = 50
GRID = [round(x, 1) for x in np.arange(0.5, 5.01, 0.1)]
GRID_CV = [round(x, 2) for x in np.arange(1.0, 3.01, 0.25)]


# ---------------------------------------------------------------- utilidades
def buscar_dataset() -> Path:
    """Carpeta que contiene plays.csv dentro de data/ (el nombre de la carpeta puede variar)."""
    env = os.environ.get("NFL_DATA")
    if env and (Path(env) / "plays.csv").exists():
        return Path(env)
    for base, dirs, files in os.walk(DATA, followlinks=True):
        if "plays.csv" in files and "pffScoutingData.csv" in files:
            return Path(base)
    raise FileNotFoundError("No encontré plays.csv dentro de data/")


def wilson(k: float, n: float, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - m), min(1.0, c + m))


def prior_beta(k: pd.Series, n: pd.Series) -> tuple[float, float]:
    """Prior Beta por método de momentos, descontando el ruido binomial."""
    r = k / n
    mu = float(r.mean())
    var_entre = float(r.var()) - mu * (1 - mu) / float(n.mean())
    var_entre = max(var_entre, 1e-6)
    s = mu * (1 - mu) / var_entre - 1
    s = min(max(s, 5.0), 2000.0)
    return mu * s, (1 - mu) * s


def encoger(k: pd.Series, n: pd.Series, a: float, b: float) -> pd.DataFrame:
    """Media posterior Beta-Binomial con intervalo creíble aproximado del 95%."""
    a2, b2 = a + k, b + n - k
    media = a2 / (a2 + b2)
    sd = np.sqrt(a2 * b2 / ((a2 + b2) ** 2 * (a2 + b2 + 1)))
    return pd.DataFrame({"tasa_ajustada": media, "ic_bajo": (media - 1.96 * sd).clip(lower=0), "ic_alto": media + 1.96 * sd})


def concordancia(e: np.ndarray, y: np.ndarray) -> dict:
    """Acuerdo, kappa de Cohen, precisión y recall de la presión del tracking (e) contra la de PFF (y)."""
    e, y = np.asarray(e, int), np.asarray(y, int)
    tp, fp = int(((e == 1) & (y == 1)).sum()), int(((e == 1) & (y == 0)).sum())
    fn, tn = int(((e == 0) & (y == 1)).sum()), int(((e == 0) & (y == 0)).sum())
    n = len(y)
    po = (tp + tn) / n
    pe = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / (n * n)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return {"acuerdo": round(po, 3), "kappa": round((po - pe) / (1 - pe), 3), "precision": round(prec, 3),
            "recall": round(rec, 3), "f1": round(2 * prec * rec / (prec + rec), 3) if prec + rec else 0.0,
            "tasa_presion": round(float(e.mean()), 3)}


def incidencia_acumulada(T: np.ndarray, E: np.ndarray, grid: list[float]) -> list[float]:
    """Aalen-Johansen: probabilidad de que la presión (E=1) llegue antes de que el balón salga (E=0)."""
    orden = np.argsort(T)
    T, E = T[orden], E[orden]
    tiempos = np.unique(T)
    n_riesgo = len(T) - np.searchsorted(T, tiempos, side="left")
    d1 = np.array([((T == u) & (E == 1)).sum() for u in tiempos])
    d_tot = np.array([(T == u).sum() for u in tiempos])
    S_prev = np.concatenate([[1.0], np.cumprod(1 - d_tot / n_riesgo)[:-1]])
    F = np.cumsum(S_prev * d1 / n_riesgo)
    idx = np.searchsorted(tiempos, np.array(grid) + 1e-9, side="right") - 1
    return [float(F[i]) if i >= 0 else 0.0 for i in idx]


def km_ingenuo(T: np.ndarray, E: np.ndarray, grid: list[float]) -> list[float]:
    """1 - Kaplan-Meier tratando el pase como censura (sesgado; solo para contraste)."""
    tiempos = np.unique(T)
    S, res = 1.0, []
    for u in tiempos:
        n = (T >= u).sum()
        S *= 1 - ((T == u) & (E == 1)).sum() / n
        res.append(1 - S)
    res = np.array(res)
    idx = np.searchsorted(tiempos, np.array(grid) + 1e-9, side="right") - 1
    return [float(res[i]) if i >= 0 else 0.0 for i in idx]


def _curva(sub: pd.DataFrame) -> dict[float, float]:
    if len(sub) == 0:
        return {t: 0.0 for t in GRID}
    return dict(zip(GRID, incidencia_acumulada(sub["T"].to_numpy(float), sub["E"].to_numpy(int), GRID)))


def _t25(curva: dict[float, float]) -> float | None:
    return next((t for t in GRID if curva[t] >= 0.25), None)


def _esperado(base: pd.DataFrame, objetivo: pd.DataFrame, col: str) -> pd.Series:
    """Valor esperado de `col` para cada jugada de `objetivo`, según jugadas de `base` con el mismo plan
    (rushers x tipo de jugada x cobertura). Si la celda tiene menos de MIN_CELDA jugadas, usa rushers x tipo de jugada."""
    fino = base.groupby(CELDA)[col].agg(m_f="mean", n_f="size").reset_index()
    grueso = base.groupby(CELDA[:2])[col].mean().rename("m_g").reset_index()
    o = objetivo[CELDA].reset_index(drop=True).merge(fino, on=CELDA, how="left").merge(grueso, on=CELDA[:2], how="left")
    e = np.where(o.n_f >= MIN_CELDA, o.m_f, o.m_g)
    return pd.Series(e, index=objetivo.index).fillna(float(base[col].mean()))


@lru_cache(maxsize=2)
def segundos_pocket(lado: str = "ofensiva") -> dict:
    """Segundos de pocket sobre lo esperado (SPSE), por equipo.

    Por jugada, 'segundos perdidos' = cuánto antes del segundo 4 llegó la presión (0 si no llegó). Lo esperado sale de
    las jugadas del RESTO de la liga con el mismo plan (rushers, tipo de jugada, cobertura). Ofensiva: SPSE > 0 = su
    protección compra más tiempo del esperado. Defensa: SPSE > 0 = roba más tiempo del esperado.
    """
    r = datos()["reloj"]
    col = "possessionTeam" if lado == "ofensiva" else "defensiveTeam"
    out = []
    for eq in sorted(r[col].dropna().unique()):
        sub, base = r[r[col] == eq], r[r[col] != eq]
        dif = _esperado(base, sub, "perdido") - sub.perdido
        if lado != "ofensiva":
            dif = -dif
        n = len(sub)
        m, se = float(dif.mean()), float(dif.std(ddof=1) / math.sqrt(n))
        jpp = n / max(1, sub.index.get_level_values("gameId").nunique())   # jugadas de pase por partido
        out.append({"equipo": eq, "jugadas": n, "spse": round(m, 3), "ic": [round(m - 1.96 * se, 3), round(m + 1.96 * se, 3)],
                    "spse_por_partido": round(m * jpp, 2), "ic_por_partido": [round((m - 1.96 * se) * jpp, 2), round((m + 1.96 * se) * jpp, 2)],
                    "perdidos_observados": round(float(sub.perdido.mean()), 3)})
    out.sort(key=lambda x: -x["spse"])
    return {"lado": lado, "ventana_s": VENTANA_S, "liga_perdidos": round(float(r.perdido.mean()), 3), "equipos": out}


# ---------------------------------------------------------------- carga
@lru_cache(maxsize=1)
def datos() -> dict:
    ds = buscar_dataset()
    plays = pd.read_csv(ds / "plays.csv", na_values="NA")
    pff = pd.read_csv(ds / "pffScoutingData.csv", na_values="NA")
    players = pd.read_csv(ds / "players.csv", na_values="NA")
    games = pd.read_csv(ds / "games.csv")

    frames_csv = DERIVADOS / "frames.csv"
    frames = pd.read_csv(frames_csv) if frames_csv.exists() else None
    if frames is None or "rid" not in frames.columns:  # respaldo: calcularlo en memoria desde el tracking (~20 s)
        from backend.preprocesar import calcular_frames
        frames = calcular_frames(ds)

    nombres = players.set_index("nflId")["displayName"].to_dict()
    posiciones = players.set_index("nflId")["officialPosition"].to_dict()

    # ---- presión PFF por jugada
    rush = pff[pff.pff_role == "Pass Rush"].copy()
    rush["presion"] = (rush[["pff_hit", "pff_hurry", "pff_sack"]].fillna(0).sum(axis=1) > 0).astype(int)
    presion_jugada = rush.groupby(["gameId", "playId"]).presion.max().rename("presion_pff")
    n_rushers = rush.groupby(["gameId", "playId"]).size().rename("rushers")

    jugadas = plays.set_index(["gameId", "playId"]).join(presion_jugada).join(n_rushers)
    jugadas["presion_pff"] = jugadas["presion_pff"].fillna(0).astype(int)
    jugadas["rushers"] = jugadas["rushers"].fillna(0).astype(int)
    rollout = jugadas.dropBackType.fillna("").str.startswith("DESIGNED_ROLLOUT")
    jugadas["tipo_jugada"] = np.where(rollout, "Rollout diseñado", np.where(jugadas.pff_playAction == 1, "Play action", "Dropback normal"))

    # ---- tiempo hasta la presión física (tracking) y quién llegó
    fr = frames.sort_values(["gameId", "playId", "frameId"]).copy()
    fr["t"] = (fr.frameId - fr.snap) / 10
    activos = fr[fr.t >= INICIO_S]
    llegada = (activos[activos.mind < UMBRAL_YD].groupby(["gameId", "playId"])[["t", "rid"]].first()
               .rename(columns={"t": "t_presion", "rid": "rid_presion"}))
    min_dist = activos.groupby(["gameId", "playId"]).mind.min().rename("min_dist")
    reloj = fr.groupby(["gameId", "playId"]).agg(snap=("snap", "first"), fin=("fin", "first")).join(llegada).join(min_dist)
    reloj["t_fin"] = (reloj.fin - reloj.snap) / 10
    reloj = reloj[reloj.t_fin > 0]
    reloj = reloj.join(jugadas[["rushers", "pff_passCoverageType", "down", "yardsToGo", "possessionTeam", "defensiveTeam",
                                "presion_pff", "passResult", "tipo_jugada"]], how="inner")
    es_sack = reloj.passResult == "S"
    # Un sack es presión que llegó aunque el tracking no la haya visto a 2 yd: se cuenta como presión al momento del sack.
    reloj["T"] = reloj.t_presion.fillna(reloj.t_fin)
    reloj["E"] = (reloj.t_presion.notna() | es_sack).astype(int)

    # ---- variables por jugada para las métricas
    # Sin censura (toda jugada termina en presión o balón fuera), el área bajo la curva de incidencia entre 0.5 y 4 s
    # es exactamente el promedio por jugada de estos "segundos perdidos": cuánto antes de los 4 s llegó la presión.
    reloj["perdido"] = np.where(reloj.E == 1, (VENTANA_S - reloj["T"].clip(lower=INICIO_S)).clip(lower=0), 0.0)
    reloj["temprana"] = ((reloj.E == 1) & (reloj["T"] < TEMPRANA_S)).astype(int)
    reloj["grupo_rushers"] = np.select([reloj.rushers <= 4, reloj.rushers == 5], ["4 o menos", "5"], "6 o más")
    reloj["cobertura"] = reloj.pff_passCoverageType.where(reloj.pff_passCoverageType.isin(["Man", "Zone"]), "Otra")

    # ---- validación contra PFF: SOLO con la distancia del tracking y sin jugadas de sack
    # (un sack siempre es presión en PFF; incluirlo forzado como positivo inflaría el acuerdo)
    ns = (~es_sack).to_numpy()
    y = reloj.presion_pff.to_numpy()[ns]
    md = reloj.min_dist.to_numpy()[ns]
    sensibilidad = [{"umbral_yardas": u, **concordancia(md < u, y)} for u in UMBRALES_SENSIBILIDAD]
    # validación cruzada por partido: se elige el umbral en 4/5 de los partidos y se evalúa en el 1/5 restante
    juegos = reloj.index.get_level_values("gameId").to_numpy()[ns]
    unicos = np.unique(juegos)
    fold_de = dict(zip(unicos, np.random.default_rng(0).permutation(len(unicos)) % 5))
    fold = np.array([fold_de[g] for g in juegos])
    cv = []
    for k in range(5):
        tr, te = fold != k, fold == k
        mejor = max(GRID_CV, key=lambda u: concordancia(md[tr] < u, y[tr])["kappa"])
        cv.append({"particion": k + 1, "umbral_elegido": mejor, **concordancia(md[te] < mejor, y[te])})
    validacion = {
        "umbral_yardas": UMBRAL_YD, "jugadas": int(ns.sum()), **concordancia(md < UMBRAL_YD, y),
        "acuerdo_trivial": round(float(1 - y.mean()), 3),
        "kappa_con_sacks": concordancia(reloj.E.to_numpy(), reloj.presion_pff.to_numpy())["kappa"],
        "sacks_sin_presion_tracking": int((es_sack & reloj.t_presion.isna()).sum()),
        "empates_presion_y_pase": int(((reloj.t_presion == reloj.t_fin) & ~es_sack).sum()),
        "sensibilidad": sensibilidad,
        "validacion_cruzada": cv,
        "kappa_cv": round(float(np.mean([c["kappa"] for c in cv])), 3),
    }

    return dict(plays=plays, pff=pff, rush=rush, jugadas=jugadas, reloj=reloj, games=games, validacion=validacion,
                nombres=nombres, posiciones=posiciones, n_frames=len(frames))


# ---------------------------------------------------------------- 1. Reloj del pocket
def _segmentos(segmento: str, r: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if segmento == "rushers":
        return {"3 o menos": r[r.rushers <= 3], "4": r[r.rushers == 4], "5": r[r.rushers == 5], "6 o más": r[r.rushers >= 6]}
    if segmento == "cobertura":
        return {"Man": r[r.pff_passCoverageType == "Man"], "Zone": r[r.pff_passCoverageType == "Zone"]}
    if segmento == "down":
        largo = r.yardsToGo >= 7
        return {"1er down": r[r.down == 1], "2do down": r[r.down == 2],
                "3ro y corto (<7)": r[(r.down == 3) & ~largo], "3ro y largo (7+)": r[(r.down == 3) & largo]}
    if segmento == "jugada":
        return {t: r[r.tipo_jugada == t] for t in ["Dropback normal", "Play action", "Rollout diseñado"]}
    if segmento.startswith("ofensiva:"):
        eq = segmento.split(":", 1)[1].upper()
        return {eq: r[r.possessionTeam == eq], "Liga": r}
    if segmento.startswith("defensa:"):
        eq = segmento.split(":", 1)[1].upper()
        return {eq: r[r.defensiveTeam == eq], "Liga": r}
    return {"Todas": r}


def reloj_pocket(segmento: str = "todas") -> dict:
    d = datos()
    r = d["reloj"]
    series, resumen = [], []
    for nombre, sub in _segmentos(segmento, r).items():
        if len(sub) == 0:
            continue
        curva = incidencia_acumulada(sub["T"].to_numpy(float), sub["E"].to_numpy(int), GRID)
        series.append({"nombre": nombre, "n": int(len(sub)), "curva": [round(v, 4) for v in curva]})
        g = dict(zip(GRID, curva))
        resumen.append({"nombre": nombre, "n": int(len(sub)), "a_2_5s": round(g[2.5], 3), "a_3_0s": round(g[3.0], 3),
                        "a_4_0s": round(g[4.0], 3), "segundos_hasta_25pct": _t25(g)})
    puntos = [{"t": t, **{s["nombre"]: s["curva"][i] for s in series}} for i, t in enumerate(GRID)]
    extra = {}
    if segmento in ("todas", ""):
        ing = km_ingenuo(r["T"].to_numpy(float), r["E"].to_numpy(int), GRID)
        for i, p in enumerate(puntos):
            p["Cálculo simple (exagera)"] = round(ing[i], 4)
        extra["km_ingenuo_4s"] = round(dict(zip(GRID, ing))[4.0], 3)
    return {"segmento": segmento, "umbral_yardas": UMBRAL_YD, "series": [s["nombre"] for s in series],
            "puntos": puntos, "resumen": resumen, **extra}


# ---------------------------------------------------------------- 2. Rankings
@lru_cache(maxsize=1)
def tablas_jugadores() -> dict:
    d = datos()
    pff, rush, nombres, posiciones = d["pff"], d["rush"], d["nombres"], d["posiciones"]
    plays = d["plays"][["gameId", "playId", "possessionTeam", "defensiveTeam"]]

    # ---- rushers
    rush = rush.merge(plays, on=["gameId", "playId"])
    r = rush.groupby("nflId").agg(snaps=("presion", "size"), presiones=("presion", "sum"),
                                  sacks=("pff_sack", lambda s: int(s.fillna(0).sum())),
                                  equipo=("defensiveTeam", lambda s: s.mode().iat[0]),
                                  alineacion=("pff_positionLinedUp", lambda s: s.mode().iat[0] if s.notna().any() else ""))
    base_r = r[r.snaps >= MIN_SNAPS_RUSH]
    a_r, b_r = prior_beta(base_r.presiones, base_r.snaps)
    r = r.join(encoger(r.presiones, r.snaps, a_r, b_r))
    r["tasa_observada"] = r.presiones / r.snaps
    liga_rush = a_r / (a_r + b_r)

    # ---- todos los bloqueadores (OL, TE, RB) y el rusher que bloquearon
    bl = pff[pff.pff_role == "Pass Block"].merge(plays, on=["gameId", "playId"]).copy()
    bl["permitida"] = (bl[["pff_hitAllowed", "pff_hurryAllowed", "pff_sackAllowed"]].fillna(0).sum(axis=1) > 0).astype(int)
    bl["pos_oficial"] = bl.nflId.map(posiciones)
    bl["es_ol"] = bl.pos_oficial.isin(POS_OL)
    rp = rush[["gameId", "playId", "nflId", "presion"]].rename(columns={"nflId": "rival", "presion": "pres_rival"})
    rp["rival"] = rp.rival.astype(float)
    bl = bl.merge(rp, left_on=["gameId", "playId", "pff_nflIdBlockedPlayer"], right_on=["gameId", "playId", "rival"], how="left")

    # frente más común de cada rusher (qué puesto de la OL lo bloquea más seguido)
    fr_ol = bl[bl.pff_positionLinedUp.isin(ALINEACION_OL)].dropna(subset=["pff_nflIdBlockedPlayer"])
    frente = fr_ol.groupby("pff_nflIdBlockedPlayer").pff_positionLinedUp.agg(lambda s: s.mode().iat[0])
    frente.index = frente.index.astype("int64")
    r["frente_comun"] = r.index.map(frente).fillna("")

    # calidad del rusher bloqueado SIN contar los snaps contra este mismo bloqueador (leave-one-out),
    # para que el liniero no "se ajuste a sí mismo"
    par = bl.dropna(subset=["pff_nflIdBlockedPlayer"]).groupby(["nflId", "pff_nflIdBlockedPlayer"]).agg(
        n_par=("permitida", "size"), k_par=("pres_rival", "sum")).reset_index()
    bl = bl.merge(par, on=["nflId", "pff_nflIdBlockedPlayer"], how="left")
    snaps_r = {float(k): v for k, v in r.snaps.items()}
    pres_r = {float(k): v for k, v in r.presiones.items()}
    s_j = bl.pff_nflIdBlockedPlayer.map(snaps_r)
    p_j = bl.pff_nflIdBlockedPlayer.map(pres_r)
    loo = (p_j - bl.k_par.fillna(0) + a_r) / (s_j - bl.n_par.fillna(0) + a_r + b_r)
    bl["calidad"] = (loo / liga_rush).fillna(1.0)   # sin rival identificado (3%) = rusher promedio

    # ---- linieros ofensivos (solo T, G, C)
    ol = bl[bl.es_ol].copy()
    o = ol.groupby("nflId").agg(snaps=("permitida", "size"), permitidas=("permitida", "sum"),
                                sacks_permitidos=("pff_sackAllowed", lambda s: int(s.fillna(0).sum())),
                                equipo=("possessionTeam", lambda s: s.mode().iat[0]),
                                alineacion=("pff_positionLinedUp", lambda s: s.mode().iat[0] if s.notna().any() else ""),
                                sin_rival=("pff_nflIdBlockedPlayer", lambda s: float(s.isna().mean())))
    base_o = o[o.snaps >= MIN_SNAPS_OL]
    a_o, b_o = prior_beta(base_o.permitidas, base_o.snaps)
    o = o.join(encoger(o.permitidas, o.snaps, a_o, b_o))
    o["tasa_observada"] = o.permitidas / o.snaps
    liga_ol = a_o / (a_o + b_o)

    # presión esperada según la calidad de cada rusher bloqueado, calibrada para que la liga sume lo observado
    ol["esperada"] = liga_ol * ol.calidad
    esp = ol.groupby("nflId").esperada.sum()
    calib = float(o.permitidas.sum() / esp.sum())
    o["esperadas"] = esp * calib
    o["dificultad_rival"] = esp / (o.snaps * liga_ol)
    # Gamma-Poisson: se encoge la RAZÓN observadas/esperadas hacia 1 (no la tasa hacia la media de la liga),
    # así el encogimiento no premia ni castiga a quien enfrentó rivales difíciles
    b = o[o.snaps >= MIN_SNAPS_OL]
    var_entre = float((b.permitidas / b.esperadas).var() - (1 / b.esperadas).mean())
    alfa = float(np.clip(1 / var_entre, 2.0, 500.0)) if var_entre > 0 else 500.0
    post = (o.permitidas + alfa) / (o.esperadas + alfa)
    sd = np.sqrt(o.permitidas + alfa) / (o.esperadas + alfa)
    tasa_esp = o.esperadas / o.snaps
    o["razon_ajustada"] = post
    o["sobre_lo_esperado_100"] = (post - 1) * tasa_esp * 100
    o["ic_bajo_100"] = (post - 1.96 * sd - 1) * tasa_esp * 100
    o["ic_alto_100"] = (post + 1.96 * sd - 1) * tasa_esp * 100

    # ---- atribución con el tracking: ¿a quién le ganó el rusher que llegó primero a 2 yd?
    rl = d["reloj"]
    pt = rl[rl.t_presion.notna()][["t_presion", "rid_presion", "possessionTeam"]].reset_index()
    pt["rid_presion"] = pt.rid_presion.astype(float)
    cand = bl.dropna(subset=["pff_nflIdBlockedPlayer"])[["gameId", "playId", "nflId", "pff_nflIdBlockedPlayer", "es_ol", "pos_oficial"]]
    at = pt.merge(cand, left_on=["gameId", "playId", "rid_presion"], right_on=["gameId", "playId", "pff_nflIdBlockedPlayer"], how="left")
    n_bloq = at.groupby(["gameId", "playId"]).nflId.transform("count")
    at["credito"] = np.where(n_bloq > 0, 1 / n_bloq.clip(lower=1), 1.0)
    at["fuente"] = np.where(at.nflId.isna(), "Sin bloqueador asignado", np.where(at.es_ol.eq(True), "Línea ofensiva", "RB / TE"))
    at["temprana"] = at.t_presion < TEMPRANA_S
    a_ol = at[at.fuente == "Línea ofensiva"].assign(nflId=lambda x: x.nflId.astype("int64"))
    g_at = a_ol.groupby("nflId")
    o["presiones_tracking"] = g_at.credito.sum()
    o["tempranas"] = a_ol[a_ol.temprana].groupby("nflId").credito.sum()
    o[["presiones_tracking", "tempranas"]] = o[["presiones_tracking", "tempranas"]].fillna(0.0)
    o["tempranas_100"] = o.tempranas / o.snaps * 100
    o["t_medio_presion"] = g_at.apply(lambda x: float(np.average(x.t_presion, weights=x.credito)))
    llegadas = pt.groupby("rid_presion").size()
    llegadas.index = llegadas.index.astype("int64")
    r["llegadas_tracking"] = r.index.map(llegadas).fillna(0).astype(int)

    for t in (r, o):
        t["nombre"] = t.index.map(nombres)
        t["posicion"] = t.index.map(posiciones)

    return dict(rushers=r, ol=o, atribucion=at, liga_rush=liga_rush, liga_ol=liga_ol, prior_rush=(a_r, b_r),
                prior_ol=(a_o, b_o), alfa_razon=alfa)


def _limpio(v):
    if isinstance(v, (float, np.floating)):
        return None if math.isnan(float(v)) else round(float(v), 4)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def _filas(df: pd.DataFrame, cols: list[str]) -> list[dict]:
    return [{"nflId": int(nflId), **{c: _limpio(fila[c]) for c in cols}} for nflId, fila in df[cols].iterrows()]


COLS_OL = ["nombre", "posicion", "equipo", "alineacion", "snaps", "permitidas", "sacks_permitidos", "tasa_observada", "tasa_ajustada",
           "ic_bajo", "ic_alto", "esperadas", "sobre_lo_esperado_100", "ic_bajo_100", "ic_alto_100", "dificultad_rival",
           "presiones_tracking", "tempranas", "tempranas_100", "t_medio_presion"]
COLS_RUSH = ["nombre", "posicion", "equipo", "alineacion", "frente_comun", "snaps", "presiones", "sacks", "llegadas_tracking",
             "tasa_observada", "tasa_ajustada", "ic_bajo", "ic_alto"]


def ranking(posicion: str = "ol", equipo: str | None = None, top: int = 15, orden: str = "peor") -> dict:
    t = tablas_jugadores()
    if posicion == "rushers":
        df = t["rushers"]
        df = df[df.snaps >= MIN_SNAPS_RUSH]
        if equipo:
            df = df[df.equipo == equipo.upper()]
        df = df.sort_values("tasa_ajustada", ascending=False).head(top)
        return {"posicion": "rushers", "min_snaps": MIN_SNAPS_RUSH, "media_liga": round(t["liga_rush"], 4),
                "prior": [round(x, 1) for x in t["prior_rush"]], "jugadores": _filas(df, COLS_RUSH)}
    df = t["ol"]
    df = df[df.snaps >= MIN_SNAPS_OL]
    if equipo:
        df = df[df.equipo == equipo.upper()]
    df = df.sort_values("sobre_lo_esperado_100", ascending=orden == "mejor").head(top)
    return {"posicion": "ol", "orden": orden, "min_snaps": MIN_SNAPS_OL, "media_liga": round(t["liga_ol"], 4),
            "prior": [round(x, 1) for x in t["prior_ol"]], "jugadores": _filas(df, COLS_OL)}


# ---------------------------------------------------------------- 3. Cuadrante línea vs QB
@lru_cache(maxsize=1)
def cuadrante_qb() -> dict:
    d = datos()
    pff, jug, nombres = d["pff"], d["jugadas"], d["nombres"]
    r = d["reloj"]
    qb = pff[pff.pff_role == "Pass"][["gameId", "playId", "nflId"]].join(
        jug[["presion_pff", "passResult", "possessionTeam"]], on=["gameId", "playId"])
    qb = qb.join(r[["t_fin", "temprana"] + CELDA], on=["gameId", "playId"])
    qb["sack"] = (qb.passResult == "S").astype(int)
    qb["sack_bajo_presion"] = ((qb.passResult == "S") & (qb.presion_pff == 1)).astype(int)
    qb["lanzado"] = qb.passResult.isin(["C", "I", "IN"])
    liga_presion = float(qb.presion_pff.mean())

    # Eje X: presión TEMPRANA (tracking, antes de 2.5 s) contra la esperada para el mismo plan de jugada
    # (rushers, tipo de jugada, cobertura). Antes de 2.5 s el QB casi no puede provocar la presión reteniendo el balón,
    # así que el exceso apunta a la protección. No se condiciona en el tiempo hasta soltar, que depende de la presión.
    con_t = qb.dropna(subset=["temprana"]).copy()
    con_t["esp_temprana"] = _esperado(r, con_t, "temprana")
    t = con_t.groupby("nflId").agg(n_t=("temprana", "size"), tempranas=("temprana", "sum"), esp_temprana=("esp_temprana", "mean"))

    g = qb.groupby("nflId").agg(dropbacks=("sack", "size"), presionadas=("presion_pff", "sum"), sacks=("sack", "sum"),
                                sacks_bajo_presion=("sack_bajo_presion", "sum"),
                                scrambles=("passResult", lambda s: int((s == "R").sum())),
                                equipo=("possessionTeam", lambda s: s.mode().iat[0])).join(t)
    g["tiempo_lanzamiento"] = qb[qb.lanzado].groupby("nflId").t_fin.median()
    liga_conv = float(qb.sack_bajo_presion.sum() / qb.presion_pff.sum())
    liga_tiempo = float(qb[qb.lanzado].t_fin.median())
    g = g[g.dropbacks >= MIN_DROPBACKS_QB]
    out = []
    for nflId, f in g.iterrows():
        tp = f.presionadas / f.dropbacks
        tc = f.sacks_bajo_presion / f.presionadas if f.presionadas else 0
        tt = f.tempranas / f.n_t
        ict = wilson(f.tempranas, f.n_t)
        out.append({"nflId": int(nflId), "nombre": nombres.get(nflId, str(nflId)), "equipo": f.equipo,
                    "dropbacks": int(f.dropbacks), "presionadas": int(f.presionadas), "sacks": int(f.sacks), "scrambles": int(f.scrambles),
                    "tasa_presion": round(tp, 4), "ic_presion": [round(x, 4) for x in wilson(f.presionadas, f.dropbacks)],
                    "presion_temprana": round(tt, 4), "temprana_esperada": round(float(f.esp_temprana), 4),
                    "temprana_sobre_esperado": round(tt - float(f.esp_temprana), 4),
                    "ic_temprana_sobre_esperado": [round(x - float(f.esp_temprana), 4) for x in ict],
                    "tiempo_lanzamiento": _limpio(f.tiempo_lanzamiento),
                    "conversion_sack": round(tc, 4), "ic_conversion": [round(x, 4) for x in wilson(f.sacks_bajo_presion, f.presionadas)],
                    "tasa_sack": round(f.sacks / f.dropbacks, 4), "ic_sack": [round(x, 4) for x in wilson(f.sacks, f.dropbacks)]})
    out.sort(key=lambda x: -x["conversion_sack"])
    return {"min_dropbacks": MIN_DROPBACKS_QB, "liga_presion": round(liga_presion, 4), "liga_conversion": round(liga_conv, 4),
            "liga_tiempo_lanzamiento": round(liga_tiempo, 2), "liga_temprana": round(float(r.temprana.mean()), 4),
            "n_presionadas_liga": int(qb.presion_pff.sum()), "qbs": out}


# ---------------------------------------------------------------- 4. Reporte por partido
def equipos() -> list[str]:
    g = datos()["games"]
    return sorted(set(g.homeTeamAbbr) | set(g.visitorTeamAbbr))


def _comparar(p: float, n: int, liga: float) -> int:
    """+1 si p está significativamente por encima de la liga, -1 si por debajo, 0 si no se distingue (aprox. normal)."""
    if n == 0:
        return 0
    se = math.sqrt(max(p * (1 - p), 1e-6) / n)
    return 1 if p - liga > 1.96 * se else -1 if liga - p > 1.96 * se else 0


def reporte_partido(ofensiva: str, defensa: str) -> dict:
    ofensiva, defensa = ofensiva.upper(), defensa.upper()
    validos = equipos()
    if ofensiva not in validos or defensa not in validos:
        return {"error": f"Equipo no válido. Usa abreviaturas como {', '.join(validos[:6])}…"}
    t = tablas_jugadores()
    ol, rushers, at = t["ol"], t["rushers"], t["atribucion"]
    linea = ol[(ol.equipo == ofensiva) & (ol.snaps >= MIN_SNAPS_OL)].sort_values("sobre_lo_esperado_100", ascending=False)
    rivales = rushers[(rushers.equipo == defensa) & (rushers.snaps >= MIN_SNAPS_RUSH)].sort_values("tasa_ajustada", ascending=False)
    r = datos()["reloj"]
    of, de = r[r.possessionTeam == ofensiva], r[r.defensiveTeam == defensa]
    go, gd, gl = _curva(of), _curva(de), _curva(r)

    rec = []
    # 1. ¿a quién ayudar? solo si el intervalo no cruza el cero
    if len(linea):
        debil = linea.iloc[0]
        if debil.ic_bajo_100 > 0:
            rec.append(f"Dar ayuda (chip del RB o TE extra) a {debil.nombre} ({debil.alineacion}): cede {debil.sobre_lo_esperado_100:+.1f} "
                       f"presiones por cada 100 snaps sobre lo esperado según sus rivales (IC95 {debil.ic_bajo_100:+.1f} a {debil.ic_alto_100:+.1f}).")
        else:
            rec.append(f"Ningún liniero de {ofensiva} cede presión claramente por encima de lo esperado. El más expuesto es "
                       f"{debil.nombre} ({debil.alineacion}, {debil.sobre_lo_esperado_100:+.1f} por 100 snaps), pero su intervalo incluye el cero.")
    # 2. duelo clave: el mejor rusher rival contra el liniero que suele enfrentar ese puesto
    if len(rivales):
        top = rivales.iloc[0]
        rival_ol = linea[linea.alineacion == top.frente_comun] if top.frente_comun else linea.iloc[0:0]
        txt = (f"El rusher más peligroso de {defensa} es {top.nombre}: {top.tasa_ajustada:.1%} de presión ajustada por snap "
               f"(liga {t['liga_rush']:.1%}).")
        if len(rival_ol):
            j = rival_ol.iloc[0]
            txt += (f" Lo bloquea sobre todo el {top.frente_comun}; en {ofensiva} ese puesto es {j.nombre} "
                    f"({j.sobre_lo_esperado_100:+.1f} por 100 snaps sobre lo esperado).")
        rec.append(txt)
    # 3. plan de rutas según el reloj de la ofensiva, solo si se distingue de la liga
    signo = _comparar(go[3.0], len(of), gl[3.0])
    # mismo redondeo (mitad hacia arriba) que la tabla del dashboard, para que texto y tabla digan lo mismo
    p0 = lambda x: f"{math.floor(round(x, 3) * 100 + 0.5)}%"
    ventanas = "; ".join(f"{nombre} ~{s} s: {p0(go[s])}" for nombre, s in VENTANAS_RUTA)
    if signo > 0:
        rec.append(f"La protección de {ofensiva} cede presión más rápido que la liga ({go[3.0]:.0%} vs {gl[3.0]:.0%} a los 3 s, diferencia "
                   f"significativa). Presión que ya llegó al momento de soltar: {ventanas}. Priorizar rutas rápidas.")
    elif signo < 0:
        rec.append(f"La protección de {ofensiva} aguanta más que la liga ({go[3.0]:.0%} vs {gl[3.0]:.0%} a los 3 s, diferencia "
                   f"significativa). Presión al momento de soltar: {ventanas}. Hay margen para rutas profundas.")
    else:
        rec.append(f"La protección de {ofensiva} no se distingue de la liga ({go[3.0]:.0%} vs {gl[3.0]:.0%} a los 3 s). "
                   f"Presión al momento de soltar: {ventanas}.")
    sd = _comparar(gd[3.0], len(de), gl[3.0])
    if sd != 0:
        rec.append(f"La defensa de {defensa} genera presión {'más' if sd > 0 else 'menos'} rápido que la liga "
                   f"({gd[3.0]:.0%} vs {gl[3.0]:.0%} a los 3 s).")
    # 4. ¿de dónde viene la presión que cede la ofensiva?
    at_of = at[at.possessionTeam == ofensiva]
    fuentes = []
    if len(at_of):
        tot = at_of.drop_duplicates(["gameId", "playId"]).shape[0]
        comp = (at_of.groupby("fuente").credito.sum() / tot).sort_values(ascending=False)
        fuentes = [{"fuente": k, "porcentaje": round(float(v), 3)} for k, v in comp.items()]
        libre = float(comp.get("Sin bloqueador asignado", 0.0))
        liga_libre = float(at[at.fuente == "Sin bloqueador asignado"].credito.sum() / at.drop_duplicates(["gameId", "playId"]).shape[0])
        if _comparar(libre, tot, liga_libre) > 0:
            rec.append(f"El {libre:.0%} de las presiones que llegan al QB de {ofensiva} vienen de un rusher que no tenía bloqueador asignado "
                       f"(liga {liga_libre:.0%}, diferencia significativa). Puede ser un blitz no recogido, un stunt o un error de asignación: "
                       f"revisar en video las llamadas de protección antes de culpar a un liniero.")
    # 5. segundos de pocket sobre lo esperado (métrica propia)
    spse_of = next(x for x in segundos_pocket("ofensiva")["equipos"] if x["equipo"] == ofensiva)
    spse_de = next(x for x in segundos_pocket("defensa")["equipos"] if x["equipo"] == defensa)
    if spse_of["ic"][0] > 0 or spse_of["ic"][1] < 0:
        gana = spse_of["spse"] > 0
        rec.append(f"Segundos de pocket: la protección de {ofensiva} {'compra' if gana else 'pierde'} {abs(spse_of['spse_por_partido']):.1f} s "
                   f"de pocket por partido respecto a lo esperado para sus mismos planes de jugada ({spse_of['spse']:+.3f} s por jugada).")

    cols_ol = ["nombre", "alineacion", "snaps", "tasa_ajustada", "sobre_lo_esperado_100", "ic_bajo_100", "ic_alto_100", "tempranas_100"]
    cols_r = ["nombre", "alineacion", "frente_comun", "snaps", "presiones", "sacks", "tasa_ajustada"]
    return {"ofensiva": ofensiva, "defensa": defensa,
            "presion_3s": {"ofensiva_cede": round(go[3.0], 3), "defensa_genera": round(gd[3.0], 3), "liga": round(gl[3.0], 3)},
            "presion_2_5s": {"ofensiva_cede": round(go[2.5], 3), "defensa_genera": round(gd[2.5], 3), "liga": round(gl[2.5], 3)},
            "ventanas_ruta": [{"ruta": nombre, "segundos": s, "ofensiva": round(go[s], 3), "liga": round(gl[s], 3)} for nombre, s in VENTANAS_RUTA],
            "spse_ofensiva": spse_of, "spse_defensa": spse_de,
            "fuentes_presion": fuentes,
            "linea_ofensiva": _filas(linea, cols_ol), "rushers_rivales": _filas(rivales.head(5), cols_r),
            "recomendaciones": rec}


# ---------------------------------------------------------------- KPIs y validación
def validacion() -> dict:
    return datos()["validacion"]


@lru_cache(maxsize=1)
def resumen() -> dict:
    d = datos()
    r, jug, v = d["reloj"], d["jugadas"], d["validacion"]
    curva = _curva(r)
    con = jug[jug.presion_pff == 1]
    sin = jug[jug.presion_pff == 0]
    comp = lambda df: float((df.passResult == "C").mean())
    return {"jugadas": int(len(jug)), "jugadas_reloj": int(len(r)), "frames_tracking": int(d["n_frames"]), "juegos": int(d["games"].shape[0]),
            "presion_2_5s": round(curva[2.5], 3), "presion_3s": round(curva[3.0], 3), "presion_4s": round(curva[4.0], 3),
            "completos_sin_presion": round(comp(sin), 3), "completos_con_presion": round(comp(con), 3),
            "yardas_sin_presion": round(float(sin.playResult.mean()), 2), "yardas_con_presion": round(float(con.playResult.mean()), 2),
            "acuerdo_tracking_vs_pff": v["acuerdo"], "kappa_tracking_vs_pff": v["kappa"], "acuerdo_trivial": v["acuerdo_trivial"],
            "umbral_yardas": UMBRAL_YD,
            "alcance": "Dataset oficial del evento: temporada 2021, semanas 1 a 8, solo jugadas de pase (NFL Big Data Bowl)."}
