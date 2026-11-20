# Pocket Clock: método, validación y detalles técnicos

## Método

| Pieza | Cómo se calcula |
|---|---|
| Presión física (tracking) | Primer cuadro, a partir de 0.5 s del snap, en que algún pass rusher (rol de PFF) está a menos de **2.0 yardas** del QB. En el reloj, un sack cuenta como presión aunque ningún rusher haya llegado a 2 yd (16 casos), y si la presión y el pase caen en el mismo cuadro (433 jugadas) cuenta como presión. |
| Validación del umbral | Contra la presión de PFF (hit, hurry o sack), **solo con la distancia del tracking y sin las jugadas de sack** (7,990 jugadas). Un sack siempre es presión en PFF, así que incluirlo forzado inflaría el acuerdo. 2.0 yd da el mayor kappa (0.56) entre 1.0 y 3.0 yd. En validación cruzada por partido (5 particiones), el umbral elegido fue 2.0 yd en las 5, con kappa fuera de muestra de 0.56. Como referencia, decir siempre "sin presión" acierta el 67%. |
| Fin de la jugada | Primer evento entre `pass_forward`, `autoevent_passforward`, `qb_sack`, `qb_strip_sack`, `run`, `pass_shovel`, `fumble`. El snap une `ball_snap` y `autoevent_ballsnap`. |
| Reloj del pocket | Incidencia acumulada (Aalen-Johansen) con "balón fuera" como evento competidor, en numpy. Segmentos: down y distancia (previos al snap) y etiquetas de PFF del plan de la jugada (número de rushers, cobertura, play action, rollout diseñado). Las etiquetas de PFF se asignan viendo la jugada, así que describen el plan, no un dato que el coach conozca antes del snap. |
| Segundos de pocket sobre lo esperado (SPSE) | Por jugada, *segundos perdidos* = 4 − tiempo de la presión si llegó antes de los 4 s, o 0. Como ninguna jugada queda censurada (todas terminan en presión o balón fuera), su promedio es exactamente el área bajo la curva del reloj entre 0.5 y 4 s (comprobado: 0.3958 contra 0.3959). Lo esperado de cada jugada es el promedio del **resto de la liga** (sin el equipo evaluado) con el mismo plan: rushers (4 o menos, 5, 6 o más) × tipo de jugada × cobertura, o rushers × tipo si la celda tiene menos de 50 jugadas. SPSE = esperado − observado, por jugada y por partido, con error estándar de la media. |
| Atribución | `rid` = rusher más cercano al QB en cada cuadro (`preprocesar.py`). En el primer cuadro de presión se cruza con `pff_nflIdBlockedPlayer`. Con doble equipo, el crédito se reparte (suma exactamente 1 por jugada). "Sin bloqueador asignado" significa que PFF no registró a nadie bloqueando a ese rusher: puede ser un blitz no recogido, un stunt o un error de asignación. |
| Cuadrante QB | Eje X: presión temprana (rusher a 2 yd o sack antes de 2.5 s) menos la esperada para el mismo plan de jugada. No se condiciona en el tiempo hasta soltar el balón porque ese tiempo depende de la presión (un sack termina la jugada). Eje Y: presiones de PFF que terminan en sack. Intervalos de Wilson al 95%. QBs con 100 o más dropbacks; incluye scrambles. |
| Rankings | Tasas encogidas con Beta-Binomial (prior de la liga por método de momentos: OL Beta(6.7, 99.5), media 6.3%; rushers Beta(10.7, 81.1), media 11.7%). Mínimo 50 snaps (OL, solo T, G y C) y 100 (rushers). |
| Ajuste por rival | Presión esperada de cada snap = tasa de la liga × calidad del rusher bloqueado. La calidad se calcula sin contar los snaps contra ese mismo liniero (leave-one-out) y el total se calibra para que la liga sume lo observado. Se encoge la razón observadas/esperadas hacia 1 (Gamma-Poisson, α = 9.5). |
| Reporte de partido | Solo afirma que una ofensiva o defensa es distinta de la liga si la diferencia supera 1.96 errores estándar. "Dar ayuda" solo si el intervalo del liniero no incluye el cero. El aviso de rushers sin bloqueador también exige una diferencia significativa contra la liga. |
| Coach IA | Agente de Strands con 4 herramientas (reloj, rankings, reporte, segundos de pocket). Cada petición tiene su propio registro, Bedrock tiene timeout de red y cada cifra de la respuesta se verifica contra los datos. Si una oración nombra a un jugador, sus cifras deben venir de ese jugador. |

## Limitaciones

- Solo semanas 1 a 8 de 2021 y solo jugadas de pase. El tracking termina poco después del pase: no mide recepción ni yardas después de la atrapada.
- "Llegar a 2 yardas" no distingue a un rusher que el QB esquiva de uno que lo derriba; en rollouts y scrambles el QB se mueve y la distancia es menos informativa.
- Las ventanas de ruta (2.5, 3.0 y 3.5 s) son tiempos de referencia de entrenadores, no salen de los datos.
- El ajuste por rival conserva una correlación leve con la dificultad de los rivales (r = 0.17), y los intervalos de los linieros no incluyen la incertidumbre de la presión esperada.
- Los duelos 1 contra 1 OL vs DL tienen una mediana de 2 snaps por pareja, por eso no los rankeamos.
- Todas las cifras son asociaciones, no efectos causales.

## Datos

Dataset oficial del evento: NFL Big Data Bowl (Next Gen Stats + Pro Football Focus), en `data/`: 122 juegos, 8,557 jugadas, 8.3 millones de filas de tracking a 10 Hz. En GitHub no se sube el dataset original (pesa cerca de 1 GB); descárgalo de [nfl-big-data-bowl-regional-event-data](https://github.com/ThompsonJamesBliss/nfl-big-data-bowl-regional-event-data) y colócalo dentro de `data/`. El .zip de entrega sí lo incluye.

`data/derived/frames.csv` (274,791 cuadros) guarda la distancia mínima rusher-QB por cuadro y quién es el rusher más cercano. Se genera con `python -m backend.preprocesar` (unos 20 s). Si falta, el backend lo calcula en memoria al arrancar.

## Estructura

```
backend/
  main.py          FastAPI: /health y API bajo /api; sirve dashboard/dist
  analisis.py      reloj, validación, segundos de pocket, atribución, rankings, cuadrante y reporte (pandas + numpy)
  coach.py         Coach IA: Strands + Bedrock (Nova), 4 herramientas, verificación de cifras y respaldo sin IA
  preprocesar.py   tracking -> data/derived/frames.csv
dashboard/src/     React + Recharts + Tailwind (App.tsx, graficas.tsx, api.ts)
data/              dataset original (solo lectura) y derived/
```

## Endpoints

| Ruta | Qué devuelve |
|---|---|
| `GET /api/resumen` | KPIs del encabezado |
| `GET /api/validacion` | acuerdo, kappa, precisión, recall, sensibilidad del umbral y validación cruzada |
| `GET /api/pocket-clock?segmento=rushers\|jugada\|cobertura\|down\|todas\|ofensiva:KC\|defensa:LV` | curvas y resumen del reloj |
| `GET /api/segundos-pocket?lado=ofensiva\|defensa` | segundos de pocket sobre lo esperado por equipo |
| `GET /api/rankings/ol?equipo=&top=&orden=peor\|mejor` | linieros ofensivos ajustados por rival, con atribución del tracking |
| `GET /api/rankings/rushers?equipo=&top=` | pass rushers |
| `GET /api/qb-cuadrante` | cuadrante línea vs QB |
| `GET /api/reporte/{ofensiva}/{defensa}` | reporte de protección para un partido |
| `GET /api/coach/preguntas`, `POST /api/coach` | Coach IA (`{"id": ...}` o `{"texto": ...}`) |

## Stack

Python 3.12.12, FastAPI 0.115.14, pandas 2.2.3, numpy 2.1.3, strands-agents 1.64.0, boto3 1.44.0; React 18.3.1, Vite 5.4.21, TypeScript 5.7.3, Tailwind 3.4.19, Recharts 3.10.1. Sin dependencias adicionales.
