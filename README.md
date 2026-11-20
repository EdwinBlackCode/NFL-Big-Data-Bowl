# Pocket Clock: ¿quién falla, la línea o el QB?

**Pocket Clock** es un tablero interactivo que mide, con el tracking cuadro por cuadro, cuántos segundos tiene el quarterback antes de que un defensor llegue a menos de 2 yardas de él, y quién dejó pasar a ese defensor. Revela que la presión llega pronto (en el 23% de las jugadas antes de los 3 s) y que cuesta mucho: los pases completos bajan de 65% a 35% con presión. También separa la culpa de un sack: Justin Fields no recibe más presión de la esperada para el tiempo que retiene el balón (−2.3 pts) y aun así convierte en sack el 32.9% de sus presiones, mientras que Josh Allen solo convierte el 7.4% (liga 16.8%). Un coordinador ofensivo lo usaría para decidir a qué liniero darle ayuda y qué rutas caben antes de que llegue la presión, un GM para saber si arregla la línea o el QB, y un comentarista para explicar un sack con datos. Usa el dataset oficial del evento (NFL Big Data Bowl: temporada 2021, semanas 1 a 8) y un Coach IA con Amazon Nova que responde en español con las mismas cifras.

![Reloj del pocket](docs/reloj.png)

## El hallazgo

1. **El reloj del pocket.** De 8,532 jugadas de pase, la presión ya llegó en el **11.6%** de las jugadas a los 2.5 s (lo que tarda una ruta rápida), en el **22.7%** a los 3 s y en el **30.1%** a los 4 s. Cada rusher extra adelanta el reloj: con 4 rushers el 25% de presión llega a los 3.3 s; con 6 o más, a los 2.8 s. El play action compra tiempo (17.9% de presión a los 3 s contra 25.0% en un dropback normal) y el rollout diseñado todavía más (8.3%).
2. **Medirlo bien importa.** El QB suelta el balón *porque* llega la presión, así que "presión" y "balón fuera" son desenlaces que compiten. Si se ignora eso (Kaplan-Meier tratando el pase como censura), a los 4 s parecería que hay presión en el 57% de las jugadas, casi el doble del 30% real.
3. **¿Culpa de la línea o del QB?** La presión que recibe un QB depende de su línea, pero también de cuánto retiene el balón y de cuántos rushers le mandan. Por eso comparamos cada QB contra la presión esperada para jugadas con el mismo tiempo hasta soltar el balón y el mismo número de rushers:
   - **Justin Fields:** 39.2% de presión cuando lo esperado era 41.5% (−2.3 pts, IC95 −8.9 a +4.7). Aun así convierte en sack el **32.9%** de sus presiones (IC95 23–44%). Sus sacks dependen más de él que de su línea.
   - **Josh Allen:** 43.0% de presión contra 38.9% esperado (+4.1 pts, IC95 −1.9 a +10.3). Solo el **7.4%** de sus presiones termina en sack (IC95 4–14%), contra **16.8%** de la liga (3,177 jugadas presionadas).
4. **Quién cedió la presión.** En el primer cuadro en que un rusher llega a 2 yardas, identificamos a ese rusher y al bloqueador que tenía asignado. En la liga, el 78% de esas presiones las cede la línea ofensiva, el 9% un RB o TE y el 13% llega sin bloqueador asignado (blitz o stunt mal recogido). Con eso, el reporte de partido dice si el problema de una ofensiva es un liniero o el plan de protección.
5. **Trincheras con ajuste por rival.** Rankeamos a 206 linieros (T, G y C) por presión cedida sobre lo esperado según la calidad de cada rusher que bloquearon. Solo 6 ceden claramente más de lo esperado, por ejemplo Alejandro Villanueva (BAL, +4.3 por 100 snaps, IC95 +1.0 a +7.6), y 10 claramente menos. El reporte solo recomienda "dar ayuda" cuando el intervalo no incluye el cero.

![Cuadrante línea vs QB](docs/cuadrante.png)

## Para quién es

- **Coordinador ofensivo:** el reporte de partido dice a qué liniero darle ayuda, qué rusher rival cuidar y contra qué puesto suele alinearse, qué familia de rutas (rápidas 2.5 s, intermedias 3 s, profundas 3.5 s) cabe antes de la presión y si la presión viene de la línea o de rushers libres.
- **GM / staff de personal:** el cuadrante ajustado separa si el problema de sacks se arregla con línea o es del QB.
- **Comentarista o aficionado:** el Coach IA responde en lenguaje natural con las mismas cifras; si cita un número que no está en los datos, se reemplaza por el resumen calculado.

## Cómo verlo

Desde la raíz del proyecto (Windows, PowerShell):

```
cd dashboard
..\.hackathon\.tools\node\npm.cmd run build     # o: npm run build, si npm está en tu PATH
cd ..
.venv\Scripts\uvicorn backend.main:app
```

Abre `http://localhost:8000`. El backend sirve la API (`/api/...`) y el dashboard compilado en el mismo puerto.

Para desarrollar con recarga en caliente: `.venv\Scripts\uvicorn backend.main:app --reload` en una terminal y `npm run dev` dentro de `dashboard/` en otra (Vite hace proxy de `/api` al puerto 8000).

El Coach IA usa Amazon Bedrock (modelo Amazon Nova vía Strands Agents). En tu computadora pon las llaves temporales del workshop en `.env` (copia `.env.example`). **Si Bedrock no está disponible, todo el dashboard sigue funcionando** y el Coach responde con un resumen calculado con los mismos datos.

## Método

| Pieza | Cómo se calcula |
|---|---|
| Presión física (tracking) | Primer cuadro, a partir de 0.5 s del snap, en que algún pass rusher (rol de PFF) está a menos de **2.0 yardas** del QB. Un sack cuenta como presión aunque ningún rusher haya llegado a 2 yd (16 casos). Si la presión y el pase caen en el mismo cuadro (433 jugadas), cuenta como presión. |
| Validación del umbral | Contra la presión de PFF (hit, hurry o sack) en 8,532 jugadas. 2.0 yd da el mayor **kappa (0.61)** y F1 (0.75) entre 1.0 y 3.0 yd: 82% de acuerdo, precisión 80%, recall 70%. Como referencia, decir siempre "sin presión" acierta el 63%. La tabla completa está en el dashboard. |
| Fin de la jugada | Primer evento entre `pass_forward`, `autoevent_passforward`, `qb_sack`, `qb_strip_sack`, `run`, `pass_shovel`, `fumble`. El snap une `ball_snap` y `autoevent_ballsnap`. |
| Reloj del pocket | Incidencia acumulada (Aalen-Johansen) con "balón fuera" como evento competidor, en numpy. Segmentos: down y distancia (previos al snap) y etiquetas de PFF del plan de la jugada (número de rushers, cobertura, play action, rollout diseñado). Las etiquetas de PFF se asignan viendo la jugada, así que describen el plan, no un dato que el coach conozca antes del snap. |
| Atribución | `rid` = rusher más cercano al QB en cada cuadro (`preprocesar.py`). En el primer cuadro de presión se cruza con `pff_nflIdBlockedPlayer`. Con doble equipo, el crédito se reparte. |
| Rankings | Tasas encogidas con Beta-Binomial (prior de la liga por método de momentos: OL Beta(6.7, 99.5), media 6.3%; rushers Beta(10.7, 81.1), media 11.7%). Mínimo 50 snaps (OL, solo T, G y C) y 100 (rushers). |
| Ajuste por rival | Presión esperada de cada snap = tasa de la liga × calidad del rusher bloqueado. La calidad se calcula **sin contar los snaps contra ese mismo liniero** (leave-one-out) y el total se calibra para que la liga sume lo observado. Se encoge la **razón observadas/esperadas** hacia 1 (Gamma-Poisson, α = 9.5), no la tasa hacia la media de la liga. Así no se premia ni se castiga a quien enfrentó rivales difíciles. |
| Cuadrante QB | Presión por dropback y sacks por presión (PFF), con intervalos de Wilson al 95%. Presión esperada = tasa de la liga para el mismo tramo de tiempo hasta soltar el balón (cortes en 2.0, 2.5, 3.0, 3.5, 4.0 y 5.0 s) y el mismo número de rushers (4 o menos, 5, 6 o más). Incluye scrambles. QBs con 100 o más dropbacks. |
| Reporte de partido | Solo afirma que una ofensiva o defensa es distinta de la liga si la diferencia a los 3 s supera 1.96 errores estándar (aproximación normal). |
| Coach IA | Agente de Strands con 3 herramientas. Cada petición tiene su propio registro (sin candado global), Bedrock tiene timeout de red y cada cifra de la respuesta se verifica contra los datos de las herramientas. |

**Limitaciones:** solo semanas 1 a 8 de 2021 y solo jugadas de pase. El tracking termina poco después del pase, así que no mide recepción ni yardas después de la atrapada. Los duelos 1 contra 1 OL vs DL tienen una mediana de 2 snaps por pareja, por eso no los rankeamos. El tiempo hasta soltar el balón también depende de la presión, así que la presión esperada del QB es un ajuste descriptivo. Todas las cifras con presión son asociaciones, no efectos causales.

## Datos

Dataset oficial del evento: NFL Big Data Bowl (Next Gen Stats + Pro Football Focus), en `data/`: 122 juegos, 8,557 jugadas, 8.3 millones de filas de tracking a 10 Hz.
En el repositorio de GitHub no se sube el dataset original (pesa cerca de 1 GB); descárgalo de [nfl-big-data-bowl-regional-event-data](https://github.com/ThompsonJamesBliss/nfl-big-data-bowl-regional-event-data) y colócalo dentro de `data/`. El .zip de entrega sí lo incluye.
`data/derived/frames.csv` (274,791 cuadros) guarda la distancia mínima rusher-QB por cuadro y quién es el rusher más cercano. Se genera desde el tracking con `python -m backend.preprocesar` (unos 20 s). Si falta, el backend la calcula en memoria al arrancar.

## Estructura

```
backend/
  main.py          FastAPI: /health y API bajo /api; sirve dashboard/dist
  analisis.py      reloj del pocket, validación, atribución, rankings, cuadrante y reporte (pandas + numpy)
  coach.py         Coach IA: Strands + Bedrock (Nova), 3 herramientas, verificación de cifras y respaldo sin IA
  preprocesar.py   tracking -> data/derived/frames.csv
dashboard/src/     React + Recharts + Tailwind (App.tsx, graficas.tsx, api.ts)
data/              dataset original (solo lectura) y derived/
```

### Endpoints

| Ruta | Qué devuelve |
|---|---|
| `GET /api/resumen` | KPIs del encabezado |
| `GET /api/validacion` | acuerdo, kappa, precisión y recall contra PFF y sensibilidad del umbral |
| `GET /api/pocket-clock?segmento=rushers\|jugada\|cobertura\|down\|todas\|ofensiva:KC\|defensa:LV` | curvas y resumen del reloj |
| `GET /api/rankings/ol?equipo=&top=&orden=peor\|mejor` | linieros ofensivos ajustados por rival, con atribución del tracking |
| `GET /api/rankings/rushers?equipo=&top=` | pass rushers |
| `GET /api/qb-cuadrante` | cuadrante línea vs QB, con presión esperada y tiempo para lanzar |
| `GET /api/reporte/{ofensiva}/{defensa}` | reporte de protección para un partido |
| `GET /api/coach/preguntas`, `POST /api/coach` | Coach IA (`{"id": ...}` o `{"texto": ...}`) |

## Stack

Python 3.12.12, FastAPI 0.115.14, pandas 2.2.3, numpy 2.1.3, strands-agents 1.64.0, boto3 1.44.0; React 18.3.1, Vite 5.4.21, TypeScript 5.7.3, Tailwind 3.4.19, Recharts 3.10.1. Sin dependencias adicionales.
