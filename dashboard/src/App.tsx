import { useEffect, useState } from 'react'
import type { Cuadrante, QB, Ranking, Reloj, Reporte, RespuestaCoach, Resumen, SegundosPocket, Validacion } from './api'
import { getJSON, pct, postJSON, signo } from './api'
import { Dato, GraficaCuadrante, GraficaRanking, GraficaReloj, GraficaSegundos, Tabla, TablaValidacion, TarjetaReporte } from './graficas'

type Pestana = 'reloj' | 'segundos' | 'qb' | 'trincheras' | 'coach'
const PESTANAS: Array<[Pestana, string]> = [
  ['reloj', '⏱ Reloj del pocket'], ['segundos', 'Segundos de pocket'], ['qb', 'Línea vs QB'],
  ['trincheras', 'Trincheras y reporte de partido'], ['coach', 'Coach IA'],
]

function useApi<T>(ruta: string | null) {
  const [datos, setDatos] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    if (!ruta) return
    let vivo = true
    setError(null)
    getJSON<T>(ruta).then((d) => vivo && setDatos(d)).catch((e: Error) => vivo && setError(e.message))
    return () => { vivo = false }
  }, [ruta])
  return { datos, error }
}

function Panel({ titulo, subtitulo, children }: { titulo: string; subtitulo?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <h2 className="text-lg font-semibold text-gray-900">{titulo}</h2>
      {subtitulo && <p className="mb-3 text-sm text-gray-600">{subtitulo}</p>}
      {children}
    </section>
  )
}

function Cargando({ error }: { error?: string | null }) {
  return <p className="py-10 text-center text-sm text-gray-500">{error ? `No se pudo cargar: ${error}` : 'Cargando…'}</p>
}

function Selector({ valor, opciones, onChange }: { valor: string; opciones: Array<[string, string]>; onChange: (v: string) => void }) {
  return (
    <div className="mb-3 flex flex-wrap gap-2">
      {opciones.map(([v, t]) => (
        <button key={v} onClick={() => onChange(v)}
          className={`rounded-full border px-3 py-1 text-sm ${valor === v ? 'border-emerald-700 bg-emerald-700 text-white' : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50'}`}>
          {t}
        </button>
      ))}
    </div>
  )
}

function Lectura({ children }: { children: React.ReactNode }) {
  return <p className="mb-2 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-900"><span className="font-semibold">Lectura: </span>{children}</p>
}

// ---------------------------------------------------------------- Reloj
function VistaReloj({ equipos }: { equipos: string[] }) {
  const [seg, setSeg] = useState('rushers')
  const [eq, setEq] = useState('KC')
  const ruta = `pocket-clock?segmento=${encodeURIComponent(seg === 'equipo' ? `ofensiva:${eq}` : seg)}`
  const { datos, error } = useApi<Reloj>(ruta)
  const val = useApi<Validacion>('validacion')
  const primero = datos?.resumen[0]
  const ultimo = datos?.resumen[datos.resumen.length - 1]
  return (
    <div className="space-y-5">
      <Panel titulo="¿Cuántos segundos tiene el QB antes de que llegue la presión?"
        subtitulo="Porcentaje de jugadas en las que un defensor ya llegó a menos de 2 yardas del QB antes de que soltara el balón, segundo a segundo desde el snap. Medido con el tracking a 10 cuadros por segundo; solo cuenta la presión que llega antes del pase.">
        <div className="flex flex-wrap items-center gap-3">
          <Selector valor={seg} onChange={setSeg} opciones={[['rushers', 'Por # de rushers'], ['jugada', 'Tipo de jugada'], ['cobertura', 'Man vs Zone'],
            ['down', 'Por down'], ['todas', 'Nuestro método vs cálculo simple'], ['equipo', 'Mi ofensiva vs liga']]} />
          {seg === 'equipo' && (
            <select value={eq} onChange={(e) => setEq(e.target.value)} className="mb-3 rounded border border-gray-300 px-2 py-1 text-sm">
              {equipos.map((e) => <option key={e}>{e}</option>)}
            </select>
          )}
        </div>
        {!datos ? <Cargando error={error} /> : (
          <>
            {primero && ultimo && primero !== ultimo && (
              <Lectura>
                a los 2.5 s (lo que tarda una ruta rápida) ya hay presión en el {pct(primero.a_2_5s)} de las jugadas con {primero.nombre.toLowerCase()} y
                en el {pct(ultimo.a_2_5s)} con {ultimo.nombre.toLowerCase()}.
              </Lectura>
            )}
            <GraficaReloj d={datos} />
            {datos.km_ingenuo_4s !== undefined && (
              <p className="mt-2 text-sm text-gray-600">
                El cálculo simple ignora que el QB suelta el balón <em>porque</em> llega la presión, y a los 4 s diría {pct(datos.km_ingenuo_4s)} de presión,
                cuando en realidad es {pct(datos.resumen[0].a_4_0s)}. Nosotros tratamos "presión" y "balón fuera" como dos desenlaces que compiten.
              </p>
            )}
            <div className="mt-4">
              <Tabla titulo="Resumen por segmento" cab={['Segmento', 'Jugadas', 'Presión a 2.5 s', 'a 3 s', 'a 4 s', 'Segundos hasta 25%']}
                filas={datos.resumen.map((r) => [r.nombre, r.n.toLocaleString(), pct(r.a_2_5s, 1), pct(r.a_3_0s, 1), pct(r.a_4_0s, 1), r.segundos_hasta_25pct ? `${r.segundos_hasta_25pct} s` : 'no llega'])} />
            </div>
          </>
        )}
      </Panel>
      <Panel titulo="¿Por qué 2 yardas?" subtitulo="Comparamos la presión medida con el tracking contra la que marcan los analistas de PFF (hit, hurry o sack) en cada jugada.">
        {val.datos ? <TablaValidacion v={val.datos} /> : <Cargando error={val.error} />}
      </Panel>
    </div>
  )
}

// ---------------------------------------------------------------- QB
// Describe la presión temprana de un QB respecto a lo esperado, sin afirmar más de lo que dice su intervalo
function describirProteccion(q: QB) {
  const [bajo, alto] = q.ic_temprana_sobre_esperado
  const pts = `${signo(q.temprana_sobre_esperado * 100)} pts`
  if (bajo > 0) return `recibe más presión temprana de la esperada (${pts}): su protección falla`
  if (alto < 0) return `recibe menos presión temprana de la esperada (${pts}): su protección lo cuida`
  return `recibe presión temprana dentro de lo esperado (${pts}, el intervalo incluye el cero)`
}

function VistaQB() {
  const { datos, error } = useApi<Cuadrante>('qb-cuadrante')
  const [modo, setModo] = useState('ajustada')
  const ajustada = modo === 'ajustada'
  const qb = (n: string) => datos?.qbs.find((q) => q.nombre === n)
  const [fields, allen, cousins] = [qb('Justin Fields'), qb('Josh Allen'), qb('Kirk Cousins')]
  return (
    <Panel titulo="¿Quién tiene la culpa del sack: la línea o el QB?"
      subtitulo="Eje Y: de las veces que le llega presión, cuántas terminan en sack (eso depende sobre todo del QB). Eje X, vista ajustada: presión que llega antes de 2.5 s, comparada con la esperada para el mismo plan de jugada (rushers, play action o rollout, cobertura). Antes de 2.5 s el QB casi no puede provocar la presión reteniendo el balón, así que el exceso apunta a la protección. QBs con 100 o más dropbacks; el tamaño del punto es el número de dropbacks.">
      <Selector valor={modo} onChange={setModo} opciones={[['ajustada', 'Presión temprana sobre lo esperado'], ['observada', 'Presión total observada (PFF)']]} />
      {!datos ? <Cargando error={error} /> : (
        <>
          {fields && allen && cousins && (
            <Lectura>
              Justin Fields {describirProteccion(fields)}, pero convierte el {pct(fields.conversion_sack, 1)} de sus presiones en sack (liga {pct(datos.liga_conversion, 1)}):
              sus sacks dependen más de él. Kirk Cousins {describirProteccion(cousins)}, y aun así solo convierte el {pct(cousins.conversion_sack, 1)}.
              Josh Allen {describirProteccion(allen)} y convierte apenas el {pct(allen.conversion_sack, 1)}.
            </Lectura>
          )}
          <GraficaCuadrante d={datos} ajustada={ajustada} />
          <div className="mt-4">
            <Tabla titulo="Detalle con intervalos del 95%" cab={['QB', 'Equipo', 'Dropbacks', 'Seg. para lanzar', 'Presión temprana', 'Sobre lo esperado', 'Sack por presión', 'Sack por dropback']}
              filas={datos.qbs.map((q) => [q.nombre, q.equipo, q.dropbacks, q.tiempo_lanzamiento ? `${q.tiempo_lanzamiento} s` : '–',
                `${pct(q.presion_temprana, 1)} (esp. ${pct(q.temprana_esperada, 1)})`,
                `${signo(q.temprana_sobre_esperado * 100)} pts [${signo(q.ic_temprana_sobre_esperado[0] * 100)} a ${signo(q.ic_temprana_sobre_esperado[1] * 100)}]`,
                `${pct(q.conversion_sack, 1)} [${pct(q.ic_conversion[0])}–${pct(q.ic_conversion[1])}]`,
                `${pct(q.tasa_sack, 1)} [${pct(q.ic_sack[0], 1)}–${pct(q.ic_sack[1], 1)}]`])} />
            <p className="mt-2 text-xs text-gray-500">
              Presión temprana: un rusher a menos de 2 yd antes de 2.5 s (tracking) o un sack antes de 2.5 s. Liga: {pct(datos.liga_temprana, 1)} de las jugadas.
              Tiempo mediano para lanzar de la liga: {datos.liga_tiempo_lanzamiento} s (solo descriptivo; no se usa en el ajuste porque depende de la presión).
              Son asociaciones, no efectos causales.
            </p>
          </div>
        </>
      )}
    </Panel>
  )
}

// ---------------------------------------------------------------- Segundos de pocket
function PanelSegundos() {
  const [lado, setLado] = useState('ofensiva')
  const { datos, error } = useApi<SegundosPocket>(`segundos-pocket?lado=${lado}`)
  const mejor = datos?.equipos[0]
  const peor = datos?.equipos[datos.equipos.length - 1]
  const esOf = lado === 'ofensiva'
  return (
    <Panel titulo="Segundos de pocket sobre lo esperado"
      subtitulo={`Nuestra métrica: cuántos segundos de pocket limpio compra cada protección (o roba cada defensa) por partido, comparado con lo que lograría el resto de la liga con los mismos planes de jugada (rushers, play action o rollout, cobertura). Se mide en los primeros ${datos?.ventana_s ?? 4} s de cada jugada de pase. Barras tenues = el intervalo del 95% incluye el cero.`}>
      <Selector valor={lado} onChange={setLado} opciones={[['ofensiva', 'Protecciones (ofensiva)'], ['defensa', 'Pass rush (defensa)']]} />
      {!datos ? <Cargando error={error} /> : (
        <>
          {mejor && peor && (
            <Lectura>
              {esOf
                ? `la protección de ${mejor.equipo} compra ${Math.abs(mejor.spse_por_partido).toFixed(1)} s más de pocket por partido que lo esperado; la de ${peor.equipo} pierde ${Math.abs(peor.spse_por_partido).toFixed(1)} s.`
                : `la defensa de ${mejor.equipo} le roba al QB ${Math.abs(mejor.spse_por_partido).toFixed(1)} s más de pocket por partido que lo esperado; la de ${peor.equipo} le roba ${Math.abs(peor.spse_por_partido).toFixed(1)} s menos.`}
            </Lectura>
          )}
          <GraficaSegundos d={datos} />
        </>
      )}
    </Panel>
  )
}

// ---------------------------------------------------------------- Trincheras
function VistaTrincheras({ equipos }: { equipos: string[] }) {
  const [vista, setVista] = useState('ol-peor')
  const [eq, setEq] = useState('')
  const filtro = eq ? `&equipo=${eq}` : ''
  const ruta = vista === 'rushers' ? `rankings/rushers?top=15${filtro}` : `rankings/ol?top=15&orden=${vista === 'ol-mejor' ? 'mejor' : 'peor'}${filtro}`
  const { datos, error } = useApi<Ranking>(ruta)
  const [of, setOf] = useState('KC')
  const [de, setDe] = useState('LV')
  const rep = useApi<Reporte>(`reporte/${of}/${de}`)
  const esOL = vista !== 'rushers'
  return (
    <div className="space-y-5">
      <Panel titulo="Reporte de protección para el próximo partido" subtitulo="Línea ofensiva de un equipo contra los pass rushers del rival. Las recomendaciones solo afirman una diferencia cuando es estadísticamente clara.">
        <div className="mb-3 flex items-center gap-2 text-sm">
          <span>Ofensiva</span>
          <select value={of} onChange={(e) => setOf(e.target.value)} className="rounded border border-gray-300 px-2 py-1">{equipos.map((e) => <option key={e}>{e}</option>)}</select>
          <span>vs defensa</span>
          <select value={de} onChange={(e) => setDe(e.target.value)} className="rounded border border-gray-300 px-2 py-1">{equipos.map((e) => <option key={e}>{e}</option>)}</select>
        </div>
        {rep.datos ? <TarjetaReporte d={rep.datos} /> : <Cargando error={rep.error} />}
      </Panel>
      <Panel titulo={esOL ? 'Linieros ofensivos: presión cedida sobre lo esperado' : 'Pass rushers: presión por snap'}
        subtitulo={esOL
          ? 'Presiones permitidas (hit, hurry o sack según PFF) menos las esperadas por la calidad de cada rusher que bloqueó, por cada 100 snaps. La calidad del rusher se mide sin contar los snaps contra ese mismo liniero. Solo T, G y C con 50 o más snaps; las barras negras son el intervalo del 95%.'
          : 'Tasa de presión por snap de pass rush, ajustada por tamaño de muestra, con intervalo del 95%. Solo jugadores con 100 o más snaps.'}>
        <div className="flex flex-wrap items-center gap-3">
          <Selector valor={vista} onChange={setVista} opciones={[['ol-peor', 'OL: más presión cedida'], ['ol-mejor', 'OL: mejores'], ['rushers', 'Pass rushers']]} />
          <select value={eq} onChange={(e) => setEq(e.target.value)} className="mb-3 rounded border border-gray-300 px-2 py-1 text-sm">
            <option value="">Todos los equipos</option>
            {equipos.map((e) => <option key={e}>{e}</option>)}
          </select>
        </div>
        {!datos ? <Cargando error={error} /> : datos.jugadores.length === 0 ? <p className="text-sm text-gray-500">Sin jugadores con suficientes snaps.</p> : (
          <>
            <GraficaRanking d={datos} />
            <p className="mt-2 text-xs text-gray-500">
              Media de la liga: {pct(datos.media_liga, 1)} por snap.
              {esOL ? ' Naranja = cede más de lo esperado; azul = cede menos.' : ''}
            </p>
            <div className="mt-3">
              {esOL ? (
                <Tabla titulo="Detalle (PFF + tracking)" cab={['Jugador', 'Pos.', 'Snaps', 'Sobre lo esperado /100', 'Dificultad de rivales', 'Presiones tempranas /100 (tracking)']}
                  filas={datos.jugadores.map((j) => [j.nombre, j.alineacion, j.snaps, signo(j.sobre_lo_esperado_100 ?? 0),
                    `${((j.dificultad_rival ?? 1) * 100).toFixed(0)}% de la media`, (j.tempranas_100 ?? 0).toFixed(1)])} />
              ) : (
                <Tabla titulo="Detalle" cab={['Jugador', 'Pos.', 'Suele enfrentar', 'Snaps', 'Presiones', 'Sacks', 'Llegadas a 2 yd (tracking)']}
                  filas={datos.jugadores.map((j) => [j.nombre, j.alineacion, j.frente_comun || '–', j.snaps, j.presiones ?? 0, j.sacks ?? 0, j.llegadas_tracking ?? 0])} />
              )}
              {esOL && <p className="mt-1 text-xs text-gray-500">Presión temprana: el rusher que este liniero bloqueaba fue el primero en llegar a 2 yd del QB, antes de 2.5 s.</p>}
            </div>
          </>
        )}
      </Panel>
    </div>
  )
}

// ---------------------------------------------------------------- Coach
function VistaCoach() {
  const preguntas = useApi<Array<{ id: string; texto: string }>>('coach/preguntas')
  const [resp, setResp] = useState<RespuestaCoach | null>(null)
  const [cargando, setCargando] = useState(false)
  const [texto, setTexto] = useState('')
  const preguntar = (cuerpo: { id?: string; texto?: string }) => {
    setCargando(true)
    setResp(null)
    postJSON<RespuestaCoach>('coach', cuerpo)
      .then(setResp)
      .catch((e: Error) => setResp({ pregunta: cuerpo.texto ?? '', respuesta: e.message, fuente: 'error', herramienta: null, datos: null }))
      .finally(() => setCargando(false))
  }
  return (
    <Panel titulo="Coach IA" subtitulo="Agente de Strands con Amazon Nova (Bedrock). Solo usa cifras que salen de las herramientas del backend; revisamos cada cifra de su respuesta y, si alguna no está en los datos o la IA no responde, se muestra un resumen calculado con los mismos datos.">
      <div className="mb-3 flex flex-wrap gap-2">
        {(preguntas.datos ?? []).map((p) => (
          <button key={p.id} disabled={cargando} onClick={() => preguntar({ id: p.id })}
            className="rounded-lg border border-emerald-700 px-3 py-2 text-left text-sm text-emerald-800 hover:bg-emerald-50 disabled:opacity-50">{p.texto}</button>
        ))}
      </div>
      <form className="mb-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (texto.trim()) preguntar({ texto }) }}>
        <input value={texto} onChange={(e) => setTexto(e.target.value)} placeholder="Pregunta libre, p. ej. ¿qué tan rápido presiona la defensa de Cleveland?"
          className="flex-1 rounded border border-gray-300 px-3 py-2 text-sm" />
        <button disabled={cargando} className="rounded bg-emerald-700 px-4 py-2 text-sm text-white disabled:opacity-50">Preguntar</button>
      </form>
      {cargando && <p className="text-sm text-gray-500">Consultando los datos…</p>}
      {resp && (
        <div className="space-y-3">
          <p className="text-sm font-semibold text-gray-900">{resp.pregunta}</p>
          <p className="whitespace-pre-line text-sm text-gray-800">{resp.respuesta ?? resp.error}</p>
          <p className="text-xs text-gray-500">Fuente del texto: {resp.fuente}{resp.herramienta ? ` · datos: ${resp.herramienta}` : ''}</p>
          {resp.herramienta === 'get_pocket_clock' && resp.datos && <GraficaReloj d={resp.datos as Reloj} alto={280} />}
          {resp.herramienta === 'get_player_ranking' && resp.datos && <GraficaRanking d={resp.datos as Ranking} />}
          {resp.herramienta === 'get_matchup_report' && resp.datos && !('error' in resp.datos) && <TarjetaReporte d={resp.datos as Reporte} />}
          {resp.herramienta === 'get_pocket_seconds' && resp.datos && <GraficaSegundos d={resp.datos as SegundosPocket} />}
        </div>
      )}
    </Panel>
  )
}

// ---------------------------------------------------------------- App
export default function App() {
  // la pestaña vive en el hash (#qb, #trincheras...) para poder compartir un enlace directo;
  // con "-captura" (#qb-captura) se oculta el encabezado para tomar capturas limpias del panel
  const hash = window.location.hash.slice(1)
  const captura = hash.endsWith('-captura')
  const inicial = hash.replace('-captura', '') as Pestana
  const [pestana, setPestanaEstado] = useState<Pestana>(PESTANAS.some(([id]) => id === inicial) ? inicial : 'reloj')
  const setPestana = (p: Pestana) => { setPestanaEstado(p); window.history.replaceState(null, '', `#${p}`) }
  const resumen = useApi<Resumen>('resumen')
  const equipos = useApi<string[]>('equipos')
  const cuadrante = useApi<Cuadrante>('qb-cuadrante')
  const r = resumen.datos
  const eqs = equipos.datos ?? []
  const fields = cuadrante.datos?.qbs.find((q) => q.nombre === 'Justin Fields')
  const allen = cuadrante.datos?.qbs.find((q) => q.nombre === 'Josh Allen')
  const contenido = (
    <>
      {pestana === 'reloj' && <VistaReloj equipos={eqs} />}
      {pestana === 'segundos' && <PanelSegundos />}
      {pestana === 'qb' && <VistaQB />}
      {pestana === 'trincheras' && <VistaTrincheras equipos={eqs} />}
      {pestana === 'coach' && <VistaCoach />}
    </>
  )
  if (captura) {
    return (
      <div className="min-h-screen bg-stone-50">
        <main className="mx-auto max-w-6xl space-y-5 px-5 py-4">
          <p className="text-xs font-semibold uppercase tracking-widest text-emerald-700">Pocket Clock · NFL Big Data Bowl · temporada 2021, semanas 1 a 8</p>
          {contenido}
        </main>
      </div>
    )
  }
  return (
    <div className="min-h-screen bg-stone-50">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto max-w-6xl px-5 py-5">
          <p className="text-xs font-semibold uppercase tracking-widest text-emerald-700">NFL Big Data Bowl · Hackathon UNAM 2026</p>
          <h1 className="text-3xl font-bold text-gray-900">Pocket Clock: ¿quién falla, la línea o el QB?</h1>
          <p className="mt-1 max-w-3xl text-sm text-gray-600">
            Medimos con el tracking cuántos segundos tiene el QB antes de que llegue la presión, cuántos segundos de pocket compra cada línea
            y cuánto de cada sack es culpa de la protección y cuánto del QB.
            {r && ` ${r.alcance}`}
          </p>
          {r && (
            <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
              <Dato titulo="Pases completos" valor={`${pct(r.completos_con_presion)} vs ${pct(r.completos_sin_presion)}`} nota="con presión vs sin presión" />
              <Dato titulo="Yardas por jugada" valor={`${r.yardas_con_presion} vs ${r.yardas_sin_presion}`} nota="con presión vs sin presión" />
              <Dato titulo="Presión antes de 3 s" valor={pct(r.presion_3s, 1)} nota={`${pct(r.presion_2_5s, 1)} antes de 2.5 s`} />
              {fields && allen
                ? <Dato titulo="Presiones que terminan en sack" valor={`${pct(fields.conversion_sack)} vs ${pct(allen.conversion_sack)}`} nota="Justin Fields vs Josh Allen" />
                : <Dato titulo="Presión antes de 4 s" valor={pct(r.presion_4s, 1)} />}
            </div>
          )}
        </div>
        <nav className="mx-auto flex max-w-6xl flex-wrap gap-1 px-5">
          {PESTANAS.map(([id, t]) => (
            <button key={id} onClick={() => setPestana(id)}
              className={`border-b-2 px-4 py-2 text-sm font-medium ${pestana === id ? 'border-emerald-700 text-emerald-800' : 'border-transparent text-gray-600 hover:text-gray-900'}`}>{t}</button>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-6xl space-y-5 px-5 py-6">{contenido}</main>
      <footer className="mx-auto max-w-6xl px-5 pb-8 text-xs text-gray-500">
        Datos: dataset oficial del evento, NFL Big Data Bowl (Next Gen Stats + PFF), temporada 2021, semanas 1 a 8.
        Presión física = rusher a menos de 2 yardas del QB después de 0.5 s del snap.
      </footer>
    </div>
  )
}

