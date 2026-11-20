"""Coach IA: Strands Agents + Amazon Bedrock (Nova).

Reglas: las cifras SOLO salen de las herramientas (pandas). Si Bedrock falla, tarda o cita una cifra que no está en los
datos, se responde con un texto determinista armado con los mismos datos, así la app nunca depende de la IA.
"""
from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturoTimeout

from botocore.config import Config as BotocoreConfig
from strands import Agent, tool

from backend import analisis

TIMEOUT_S = float(os.environ.get("COACH_TIMEOUT_S", "15"))
MAX_JSON = 6000
_pool = ThreadPoolExecutor(max_workers=4)

SISTEMA = (
    "Eres el Coach IA de un dashboard de la NFL. Respondes en español, claro y breve (máximo 120 palabras), "
    "como un coordinador ofensivo hablando con su staff. REGLA ESTRICTA: solo puedes usar cifras que aparezcan en los "
    "datos que te dan las herramientas o el JSON del mensaje; nunca inventes números, nombres ni temporadas. "
    "Los datos son de la temporada 2021, semanas 1 a 8, solo jugadas de pase. Si te preguntan algo fuera de eso, dilo. "
    "'Presión' en el reloj del pocket = un rusher a menos de 2 yardas del QB (tracking). En rankings la presión es la de PFF "
    "(hit, hurry o sack). Si un intervalo incluye el cero, dilo: la diferencia no es concluyente. Si un jugador trae "
    "diferencia_clara=false, no digas que cede más o menos que lo esperado: di que no se distingue. Menciona el tamaño de muestra cuando sea pequeño. "
    "Para preguntas de '¿qué tan rápido presiona la defensa X?' o '¿cuánto aguanta la línea de X?' usa get_pocket_clock con "
    "segment='defensa:XXX' u 'ofensiva:XXX' (abreviatura de 3 letras: Cleveland = CLE, Kansas City = KC, Las Vegas = LV). "
    "Para '¿qué línea compra más tiempo?' o '¿qué defensa roba más tiempo?' usa get_pocket_seconds."
)


# ------------------------------------------------------------- datos compactos para el modelo
_CAMPOS_OL = ["nombre", "equipo", "alineacion", "snaps", "tasa_ajustada", "sobre_lo_esperado_100", "ic_bajo_100", "ic_alto_100", "tempranas_100"]
_CAMPOS_RUSH = ["nombre", "equipo", "alineacion", "frente_comun", "snaps", "presiones", "sacks", "tasa_ajustada", "ic_bajo", "ic_alto"]


def _compactar(nombre: str, d: dict, n_max: int = 15) -> dict:
    """Reduce los datos a lo que el modelo necesita (en lugar de cortar el JSON a la mitad)."""
    if "error" in d:
        return d
    if nombre == "get_pocket_clock":
        return {"segmento": d["segmento"], "umbral_yardas": d["umbral_yardas"], "resumen": d["resumen"]}
    if nombre == "get_pocket_seconds":
        eqs = d["equipos"]
        return {"lado": d["lado"], "ventana_s": d["ventana_s"], "equipos": eqs[:n_max] + eqs[-n_max:] if len(eqs) > 2 * n_max else eqs}
    if nombre == "get_player_ranking":
        campos = _CAMPOS_RUSH if d["posicion"] == "rushers" else _CAMPOS_OL
        jugadores = [{k: j.get(k) for k in campos} for j in d["jugadores"][:n_max]]
        if d["posicion"] == "ol":   # dato explícito para que el modelo no afirme diferencias que el intervalo no sostiene
            for j in jugadores:
                j["diferencia_clara"] = bool((j["ic_bajo_100"] or 0) > 0 or (j["ic_alto_100"] or 0) < 0)
        return {"posicion": d["posicion"], "media_liga": d["media_liga"], "min_snaps": d["min_snaps"], "jugadores": jugadores}
    return {k: d[k] for k in ["ofensiva", "defensa", "presion_3s", "ventanas_ruta", "fuentes_presion", "recomendaciones"]} | {
        "linea_ofensiva": [{k: j[k] for k in ["nombre", "alineacion", "sobre_lo_esperado_100"]} for j in d["linea_ofensiva"][:n_max]],
        "rushers_rivales": [{k: j[k] for k in ["nombre", "frente_comun", "tasa_ajustada"]} for j in d["rushers_rivales"][:n_max]]}


def _json_modelo(nombre: str, d: dict) -> str:
    for n in (15, 8, 4, 2):
        s = json.dumps(_compactar(nombre, d, n), ensure_ascii=False, default=str)
        if len(s) <= MAX_JSON:
            return s
    return s


# ------------------------------------------------------------- verificación de cifras
_NUM = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?")
_CONSTANTES = ([100.0, 95.0, 50.0, 2021.0, analisis.UMBRAL_YD, analisis.INICIO_S, analisis.TEMPRANA_S, analisis.VENTANA_S]
               + [s for _, s in analisis.VENTANAS_RUTA])
_ORACION = re.compile(r"(?<=[.;!?])\s+|\n+")


def _numeros(texto: str) -> list[tuple[float, int]]:
    out = []
    for m in _NUM.findall(texto):
        s = m.replace(",", "") if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", m) else m.replace(",", ".")
        out.append((float(s), len(s.split(".")[1]) if "." in s else 0))
    return out


def _candidatos(obj, acc: list[float]) -> list[float]:
    if isinstance(obj, bool) or obj is None:
        return acc
    if isinstance(obj, (int, float)):
        acc += [abs(float(obj)), abs(float(obj)) * 100]
    elif isinstance(obj, str):
        acc += [x for x, _ in _numeros(obj)]
    elif isinstance(obj, dict):
        for v in obj.values():
            _candidatos(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _candidatos(v, acc)
    return acc


def _es_jugador(obj) -> bool:
    return isinstance(obj, dict) and bool(obj.get("nombre")) and any(k in obj for k in ("snaps", "alineacion", "frente_comun"))


def _separar(obj, globales: list[float], jugadores: list[dict]) -> None:
    """Separa las cifras generales (liga, segmentos, textos) de los registros de cada jugador."""
    if _es_jugador(obj):
        jugadores.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _separar(v, globales, jugadores)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _separar(v, globales, jugadores)
    else:
        _candidatos(obj, globales)


def cifras_verificadas(texto: str, fuentes: list) -> bool:
    """True si cada cifra del texto aparece (redondeada) en los datos de las herramientas o en la pregunta.

    Si una oración nombra a un jugador, sus cifras solo pueden venir de ese jugador o de los datos generales
    (así no pasa una cifra correcta pero de otro jugador)."""
    globales, jugadores = list(_CONSTANTES), []
    _separar(fuentes, globales, jugadores)
    todos = _candidatos(jugadores, list(globales))
    for oracion in _ORACION.split(texto):
        citados = [j for j in jugadores if str(j["nombre"]) in oracion]
        cands = globales + [c for j in citados for c in _candidatos(j, [])] if citados else todos
        for x, dec in _numeros(oracion):
            if dec == 0 and x <= 10:      # segundos, downs, número de rushers
                continue
            tol = 0.5 * 10 ** -dec + 1e-9
            if not any(abs(x - c) <= tol for c in cands):
                return False
    return True


# ------------------------------------------------------------- herramientas (una lista de registro por petición)
def _herramientas(registro: list[dict]):
    def registrar(nombre: str, d: dict) -> str:
        registro.append({"herramienta": nombre, "datos": d})
        return _json_modelo(nombre, d)

    @tool
    def get_pocket_clock(segment: str = "rushers") -> str:
        """Curva del reloj del pocket: probabilidad de que la presión llegue antes de que salga el balón, por segundo.

        Args:
            segment: 'todas', 'rushers', 'cobertura', 'down', 'jugada' (dropback normal, play action, rollout), 'ofensiva:XXX' o 'defensa:XXX' (XXX = abreviatura del equipo, p. ej. KC).
        """
        return registrar("get_pocket_clock", analisis.reloj_pocket(segment))

    @tool
    def get_player_ranking(position: str = "rushers", team: str = "", top_n: int = 10) -> str:
        """Ranking de jugadores con tasas ajustadas e intervalos del 95%.

        Args:
            position: 'rushers' (pass rushers que más presionan) u 'ol' (linieros ofensivos que más presión ceden sobre lo esperado según sus rivales).
            team: abreviatura del equipo para filtrar (opcional, p. ej. 'CLE').
            top_n: cuántos jugadores devolver (máximo 15).
        """
        pos = "rushers" if position.lower().startswith("rush") else "ol"
        return registrar("get_player_ranking", analisis.ranking(pos, team or None, max(1, min(int(top_n), 15))))

    @tool
    def get_matchup_report(offense: str, defense: str) -> str:
        """Reporte de protección para un partido: línea ofensiva de 'offense' contra los rushers de 'defense'.

        Args:
            offense: abreviatura del equipo ofensivo (p. ej. 'KC').
            defense: abreviatura del equipo defensivo (p. ej. 'LV').
        """
        return registrar("get_matchup_report", analisis.reporte_partido(offense, defense))

    @tool
    def get_pocket_seconds(side: str = "ofensiva") -> str:
        """Segundos de pocket sobre lo esperado por equipo: cuánto tiempo de pocket compra una protección (o roba una defensa)
        respecto a lo esperado para sus mismos planes de jugada. Positivo = mejor que lo esperado.

        Args:
            side: 'ofensiva' (protecciones) o 'defensa' (pass rush).
        """
        return registrar("get_pocket_seconds", analisis.segundos_pocket("defensa" if side.lower().startswith("def") else "ofensiva"))

    return [get_pocket_clock, get_player_ranking, get_matchup_report, get_pocket_seconds]


# ------------------------------------------------------------- preguntas sugeridas
PREGUNTAS = [
    {"id": "reloj", "texto": "¿Cuántos segundos tiene un QB antes de que llegue la presión?",
     "herramienta": "get_pocket_clock", "args": {"segment": "rushers"}},
    {"id": "rushers", "texto": "¿Quiénes son los pass rushers más peligrosos?",
     "herramienta": "get_player_ranking", "args": {"position": "rushers", "top_n": 10}},
    {"id": "ol", "texto": "¿Qué linieros ofensivos ceden más presión de la esperada?",
     "herramienta": "get_player_ranking", "args": {"position": "ol", "top_n": 10}},
    {"id": "kc_lv", "texto": "Reporte de protección: Kansas City contra Las Vegas",
     "herramienta": "get_matchup_report", "args": {"offense": "KC", "defense": "LV"}},
]


def _datos_herramienta(nombre: str, args: dict) -> dict:
    if nombre == "get_pocket_clock":
        return analisis.reloj_pocket(args.get("segment", "rushers"))
    if nombre == "get_player_ranking":
        pos = "rushers" if args.get("position", "rushers").startswith("rush") else "ol"
        return analisis.ranking(pos, args.get("team") or None, args.get("top_n", 10))
    return analisis.reporte_partido(args["offense"], args["defense"])


def _texto_respaldo(nombre: str, d: dict) -> str:
    """Respuesta sin IA, armada solo con los datos."""
    if "error" in d:
        return d["error"]
    if nombre == "get_pocket_clock":
        partes = [f"{r['nombre']}: {r['a_2_5s']:.0%} a los 2.5 s y {r['a_3_0s']:.0%} a los 3 s (n={r['n']:,})" for r in d["resumen"]]
        return "Probabilidad de que la presión llegue antes de que salga el balón. " + "; ".join(partes) + "."
    if nombre == "get_pocket_seconds":
        e = d["equipos"]
        quien = "protecciones" if d["lado"] == "ofensiva" else "defensas"
        return (f"Segundos de pocket sobre lo esperado ({quien}): mejores {', '.join(f'{x['equipo']} {x['spse_por_partido']:+.1f} s/partido' for x in e[:3])}; "
                f"peores {', '.join(f'{x['equipo']} {x['spse_por_partido']:+.1f} s/partido' for x in e[-3:])}.")
    if nombre == "get_player_ranking" and d["posicion"] == "rushers":
        top = d["jugadores"][:3]
        return ("Los pass rushers más peligrosos (tasa de presión por snap, ajustada por muestra): " +
                "; ".join(f"{j['nombre']} ({j['equipo']}) {j['tasa_ajustada']:.1%} en {j['snaps']} snaps" for j in top) +
                f". La media de la liga es {d['media_liga']:.1%}.")
    if nombre == "get_player_ranking":
        top = d["jugadores"][:3]
        return ("Linieros que más presión ceden sobre lo esperado según los rivales que enfrentaron: " +
                "; ".join(f"{j['nombre']} ({j['equipo']}, {j['alineacion']}) {j['sobre_lo_esperado_100']:+.1f} por 100 snaps "
                          f"(IC95 {j['ic_bajo_100']:+.1f} a {j['ic_alto_100']:+.1f})" for j in top) + ".")
    p = d["presion_3s"]
    return (f"{d['ofensiva']} cede presión en el {p['ofensiva_cede']:.0%} de sus jugadas antes de los 3 s y {d['defensa']} la genera en el "
            f"{p['defensa_genera']:.0%} (liga {p['liga']:.0%}). " + " ".join(d["recomendaciones"][:2]))


def _modelo():
    from strands.models import BedrockModel
    # timeout de red real: sin esto el hilo seguiría esperando a Bedrock después de que la API ya respondió
    cfg = BotocoreConfig(connect_timeout=5, read_timeout=int(TIMEOUT_S), retries={"max_attempts": 1})
    return BedrockModel(model_id=os.environ.get("BEDROCK_MODEL_ID", "us.amazon.nova-pro-v1:0"),
                        region_name=os.environ.get("AWS_REGION", "us-east-1"), temperature=0.2, max_tokens=500,
                        boto_client_config=cfg)


def _narrar(pregunta: str, nombre: str, d: dict) -> str:
    agente = Agent(model=_modelo(), system_prompt=SISTEMA, callback_handler=None)
    return str(agente(f"Pregunta del usuario: {pregunta}\n\nDatos de la herramienta {nombre} (JSON):\n{_json_modelo(nombre, d)}\n\n"
                      "Responde usando solo estos datos.")).strip()


def responder_sugerida(pregunta_id: str) -> dict:
    p = next((x for x in PREGUNTAS if x["id"] == pregunta_id), None)
    if p is None:
        return {"error": "Pregunta no encontrada"}
    d = _datos_herramienta(p["herramienta"], p["args"])
    base = {"pregunta": p["texto"], "herramienta": p["herramienta"], "datos": d}
    respaldo = {**base, "respuesta": _texto_respaldo(p["herramienta"], d)}
    try:
        texto = _pool.submit(_narrar, p["texto"], p["herramienta"], d).result(timeout=TIMEOUT_S + 5)
    except FuturoTimeout:
        return {**respaldo, "fuente": "respaldo sin IA (Bedrock tardó demasiado)"}
    except Exception as e:  # sin credenciales, sin red, etc.
        return {**respaldo, "fuente": f"respaldo sin IA ({type(e).__name__})"}
    if not cifras_verificadas(texto, [_compactar(p["herramienta"], d)]):
        return {**respaldo, "fuente": "respaldo sin IA (la IA citó una cifra que no está en los datos)"}
    return {**base, "respuesta": texto, "fuente": "Amazon Nova (Bedrock)"}


def _agente_libre(pregunta: str) -> tuple[str, list[dict]]:
    registro: list[dict] = []
    agente = Agent(model=_modelo(), system_prompt=SISTEMA, callback_handler=None, tools=_herramientas(registro))
    return str(agente(pregunta)).strip(), registro


def responder_libre(pregunta: str) -> dict:
    pregunta = (pregunta or "").strip()[:500]
    if not pregunta:
        return {"error": "Escribe una pregunta"}
    try:
        texto, usadas = _pool.submit(_agente_libre, pregunta).result(timeout=2 * TIMEOUT_S + 5)
    except Exception as e:
        return {"pregunta": pregunta, "respuesta": "La IA no está disponible en este momento. Prueba una de las preguntas sugeridas: "
                "funcionan aunque Bedrock falle.", "fuente": f"sin IA ({type(e).__name__})", "herramienta": None, "datos": None}
    ultima = usadas[-1] if usadas else None
    out = {"pregunta": pregunta, "respuesta": texto, "fuente": "Amazon Nova (Bedrock)",
           "herramienta": ultima["herramienta"] if ultima else None, "datos": ultima["datos"] if ultima else None}
    fuentes = [_compactar(u["herramienta"], u["datos"]) for u in usadas] + [pregunta]
    if not cifras_verificadas(texto, fuentes):
        if ultima:
            out["respuesta"] = _texto_respaldo(ultima["herramienta"], ultima["datos"])
            out["fuente"] = "respaldo sin IA (la IA citó una cifra que no está en los datos)"
        else:
            out["respuesta"] = "No tengo datos para responder eso con cifras. Prueba con una pregunta sobre presión, linieros, rushers o un partido."
            out["fuente"] = "sin datos de herramientas"
    return out
