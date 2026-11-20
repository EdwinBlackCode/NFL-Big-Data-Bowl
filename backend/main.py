"""Pocket Clock: ¿quién falla, la línea o el QB?

Ejecuta desde la raíz del proyecto:
    .venv\\Scripts\\uvicorn backend.main:app --reload      (Windows)
    .venv/bin/uvicorn backend.main:app --reload            (macOS / Linux)
"""
import os
from pathlib import Path


def cargar_env():
    f = Path(__file__).resolve().parent.parent / ".env"
    if f.exists():
        for linea in f.read_text(encoding="utf-8-sig").splitlines():
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                k, v = linea.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


cargar_env()

from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from backend import analisis, coach  # noqa: E402


@asynccontextmanager
async def ciclo(app: FastAPI):
    # precalcula todo al arrancar para que las respuestas sean instantáneas
    analisis.datos()
    analisis.tablas_jugadores()
    analisis.cuadrante_qb()
    analisis.resumen()
    yield


app = FastAPI(title="Pocket Clock - Hackathon NFL UNAM", lifespan=ciclo)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/resumen")
def api_resumen() -> dict:
    return analisis.resumen()


@app.get("/api/validacion")
def api_validacion() -> dict:
    return analisis.validacion()


@app.get("/api/equipos")
def api_equipos() -> list[str]:
    return analisis.equipos()


@app.get("/api/pocket-clock")
def api_pocket_clock(segmento: str = Query("rushers", description="todas | rushers | cobertura | down | jugada | ofensiva:KC | defensa:LV")) -> dict:
    return analisis.reloj_pocket(segmento)


@app.get("/api/rankings/ol")
def api_rankings_ol(equipo: str | None = None, top: int = Query(15, ge=1, le=60), orden: str = "peor") -> dict:
    return analisis.ranking("ol", equipo, top, orden)


@app.get("/api/rankings/rushers")
def api_rankings_rushers(equipo: str | None = None, top: int = Query(15, ge=1, le=60)) -> dict:
    return analisis.ranking("rushers", equipo, top)


@app.get("/api/qb-cuadrante")
def api_qb_cuadrante() -> dict:
    return analisis.cuadrante_qb()


@app.get("/api/reporte/{ofensiva}/{defensa}")
def api_reporte(ofensiva: str, defensa: str) -> dict:
    r = analisis.reporte_partido(ofensiva, defensa)
    if "error" in r:
        raise HTTPException(status_code=400, detail=r["error"])
    return r


@app.get("/api/coach/preguntas")
def api_coach_preguntas() -> list[dict]:
    return [{"id": p["id"], "texto": p["texto"]} for p in coach.PREGUNTAS]


class Pregunta(BaseModel):
    id: str | None = None
    texto: str | None = None


@app.post("/api/coach")
def api_coach(p: Pregunta) -> dict:
    return coach.responder_sugerida(p.id) if p.id else coach.responder_libre(p.texto or "")


# Sirve el dashboard compilado (dashboard/dist) en la misma URL, si existe.
_dist = Path(__file__).resolve().parent.parent / "dashboard" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="dashboard")
