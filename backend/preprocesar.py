"""Preprocesa el tracking (8.3 M filas) a la distancia mínima rusher-QB por frame y el rusher más cercano.

Uso, desde la raíz del proyecto:
    .venv\\Scripts\\python -m backend.preprocesar        (Windows)
    .venv/bin/python -m backend.preprocesar              (macOS / Linux)
Genera data/derived/frames.csv (~12 MB, unos 10 s). La app solo lo lee; si falta, lo calcula en memoria al arrancar.
"""
from __future__ import annotations

import glob
import time
from pathlib import Path

import numpy as np
import pandas as pd

EV_SNAP = {"ball_snap", "autoevent_ballsnap"}
EV_FIN = {"pass_forward", "autoevent_passforward", "qb_sack", "qb_strip_sack", "run", "pass_shovel", "fumble"}


def calcular_frames(ds: Path) -> pd.DataFrame:
    roles = pd.read_csv(ds / "pffScoutingData.csv", usecols=["gameId", "playId", "nflId", "pff_role"], na_values="NA")
    roles = roles[roles.pff_role.isin(["Pass", "Pass Rush"])]
    salida = []
    for f in sorted(glob.glob(str(ds / "tracking" / "*.csv"))):
        t = pd.read_csv(f, usecols=["gameId", "playId", "nflId", "frameId", "x", "y", "event"], na_values="NA")
        ev = t[t.event.notna()]
        snap = ev[ev.event.isin(EV_SNAP)].groupby(["gameId", "playId"]).frameId.min().rename("snap")
        fin = ev[ev.event.isin(EV_FIN)].groupby(["gameId", "playId"]).frameId.min().rename("fin")
        t = t.merge(roles, on=["gameId", "playId", "nflId"]).join(snap, on=["gameId", "playId"]).join(fin, on=["gameId", "playId"])
        t = t[(t.frameId >= t.snap) & (t.frameId <= t.fin)]
        qb = t[t.pff_role == "Pass"][["gameId", "playId", "frameId", "x", "y"]].rename(columns={"x": "qx", "y": "qy"})
        r = t[t.pff_role == "Pass Rush"].merge(qb, on=["gameId", "playId", "frameId"])
        r["d"] = np.hypot(r.x - r.qx, r.y - r.qy)
        # por frame: distancia mínima y quién es el rusher más cercano (para atribuir la presión)
        cerca = r.loc[r.groupby(["gameId", "playId", "frameId"]).d.idxmin(), ["gameId", "playId", "frameId", "d", "nflId", "snap", "fin"]]
        salida.append(cerca.rename(columns={"d": "mind", "nflId": "rid"}))
    out = pd.concat(salida, ignore_index=True)
    out["rid"] = out["rid"].astype("int64")
    return out.sort_values(["gameId", "playId", "frameId"]).reset_index(drop=True)


if __name__ == "__main__":
    from backend.analisis import DERIVADOS, buscar_dataset

    t0 = time.time()
    fr = calcular_frames(buscar_dataset())
    DERIVADOS.mkdir(parents=True, exist_ok=True)
    fr.to_csv(DERIVADOS / "frames.csv", index=False)
    print(f"{len(fr):,} frames en {time.time() - t0:.1f} s -> {DERIVADOS / 'frames.csv'}")
