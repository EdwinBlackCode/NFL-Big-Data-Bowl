import {
  Bar, BarChart, CartesianGrid, Cell, ErrorBar, LabelList, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from 'recharts'
import type { Cuadrante, Ranking, Reloj, Reporte, Validacion } from './api'
import { pct, signo } from './api'

// Paleta categórica validada (orden fijo, nunca rotado) y tinta de texto
export const SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100']
export const TINTA = { primaria: '#0b0b0b', secundaria: '#52514e', tenue: '#8a8983', rejilla: '#e7e6e1' }
const EJE = { stroke: TINTA.rejilla, tick: { fill: TINTA.secundaria, fontSize: 12 } }
const KM = 'Cálculo simple (exagera)'

const colorSerie = (nombre: string, i: number) =>
  nombre === KM ? TINTA.tenue : nombre === 'Liga' ? TINTA.secundaria : SERIES[i % SERIES.length]

export function GraficaReloj({ d, alto = 340 }: { d: Reloj; alto?: number }) {
  const series = [...d.series, ...(d.puntos[0] && KM in d.puntos[0] ? [KM] : [])]
  return (
    <ResponsiveContainer width="100%" height={alto}>
      <LineChart data={d.puntos} margin={{ top: 10, right: 24, bottom: 24, left: 16 }}>
        <CartesianGrid stroke={TINTA.rejilla} vertical={false} />
        <XAxis dataKey="t" type="number" domain={[0.5, 5]} ticks={[1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]} {...EJE}
          label={{ value: 'segundos desde el snap', position: 'insideBottom', offset: -14, fill: TINTA.secundaria, fontSize: 12 }} />
        <YAxis tickFormatter={(v: number) => pct(v)} domain={[0, 'auto']} {...EJE} width={56}
          label={{ value: '% de jugadas con presión ya encima', angle: -90, position: 'insideLeft', offset: -2, fill: TINTA.secundaria, fontSize: 12, dy: 110 }} />
        <ReferenceLine x={2.5} stroke={TINTA.tenue} strokeDasharray="4 4"
          label={{ value: 'ruta rápida 2.5 s', position: 'insideTopLeft', fill: TINTA.secundaria, fontSize: 11 }} />
        <ReferenceLine x={3.5} stroke={TINTA.rejilla} strokeDasharray="4 4"
          label={{ value: 'ruta profunda 3.5 s', position: 'insideBottomLeft', fill: TINTA.secundaria, fontSize: 11 }} />
        <Tooltip formatter={(v) => pct(Number(v), 1)} labelFormatter={(l) => `${l} s`} />
        <Legend verticalAlign="top" height={30} />
        {series.map((s, i) => (
          <Line key={s} dataKey={s} name={s} type="stepAfter" dot={false} strokeWidth={2}
            stroke={colorSerie(s, i)} strokeDasharray={s === KM ? '6 4' : undefined} isAnimationActive={false} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

export function GraficaRanking({ d, alto }: { d: Ranking; alto?: number }) {
  const esOL = d.posicion === 'ol'
  const filas = d.jugadores.map((j) => {
    const valor = esOL ? (j.sobre_lo_esperado_100 ?? 0) : j.tasa_ajustada * 100
    return {
      etiqueta: `${j.nombre} (${j.equipo})`,
      valor,
      error: esOL ? [valor - (j.ic_bajo_100 ?? valor), (j.ic_alto_100 ?? valor) - valor]
        : [(j.tasa_ajustada - j.ic_bajo) * 100, (j.ic_alto - j.tasa_ajustada) * 100],
      snaps: j.snaps,
    }
  })
  const h = alto ?? Math.max(220, filas.length * 30 + 50)
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart data={filas} layout="vertical" margin={{ top: 8, right: 56, bottom: 8, left: 8 }} barCategoryGap={6}>
        <CartesianGrid stroke={TINTA.rejilla} horizontal={false} />
        <XAxis type="number" {...EJE} tickFormatter={(v: number) => (esOL ? signo(v, 0) : `${v.toFixed(0)}%`)} />
        <YAxis type="category" dataKey="etiqueta" width={190} {...EJE} interval={0} />
        {esOL ? <ReferenceLine x={0} stroke={TINTA.secundaria} /> : <ReferenceLine x={d.media_liga * 100} stroke={TINTA.secundaria} strokeDasharray="4 4"
          label={{ value: `media liga ${pct(d.media_liga, 1)}`, position: 'insideTopRight', fill: TINTA.secundaria, fontSize: 11 }} />}
        <Tooltip formatter={(v, _n, p) => [esOL ? `${Number(v).toFixed(1)} presiones por 100 snaps sobre lo esperado`
          : `${Number(v).toFixed(1)}% presión ajustada`, `n = ${(p?.payload as { snaps: number }).snaps} snaps`]} />
        <Bar dataKey="valor" radius={[0, 4, 4, 0]} isAnimationActive={false}>
          {filas.map((f) => <Cell key={f.etiqueta} fill={esOL ? (f.valor >= 0 ? SERIES[1] : SERIES[0]) : SERIES[0]} />)}
          <ErrorBar dataKey="error" width={4} strokeWidth={1.5} stroke={TINTA.primaria} direction="x" />
          <LabelList dataKey="valor" position="right" fill={TINTA.secundaria} fontSize={11}
            formatter={(v) => (esOL ? signo(Number(v)) : `${Number(v).toFixed(1)}%`)} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

const DESTACADOS = new Set(['Justin Fields', 'Josh Allen', 'Tom Brady', 'Patrick Mahomes'])

export function GraficaCuadrante({ d, ajustada }: { d: Cuadrante; ajustada: boolean }) {
  const puntos = d.qbs.map((q) => ({
    ...q,
    x: (ajustada ? q.presion_sobre_esperado : q.tasa_presion) * 100,
    y: q.conversion_sack * 100,
    z: q.dropbacks,
    etiqueta: `${q.nombre} · ${pct(q.conversion_sack, 0)} sack`,
  }))
  const resto = puntos.filter((p) => !DESTACADOS.has(p.nombre))
  const dest = puntos.filter((p) => DESTACADOS.has(p.nombre))
  const xRef = ajustada ? 0 : d.liga_presion * 100
  const ejeX = ajustada
    ? 'presión sobre lo esperado (pts) según tiempo con el balón y # de rushers  →  culpa de la línea'
    : '% de dropbacks con presión  →  más presión recibida'
  return (
    <ResponsiveContainer width="100%" height={440}>
      <ScatterChart margin={{ top: 16, right: 24, bottom: 32, left: 16 }}>
        <CartesianGrid stroke={TINTA.rejilla} />
        <XAxis type="number" dataKey="x" name="Presión" domain={ajustada ? [-15, 15] : [15, 55]}
          tickFormatter={(v: number) => (ajustada ? signo(v, 0) : `${v}%`)} {...EJE}
          label={{ value: ejeX, position: 'insideBottom', offset: -18, fill: TINTA.secundaria, fontSize: 12 }} />
        <YAxis type="number" dataKey="y" name="Sacks por presión" domain={[0, 40]} tickFormatter={(v: number) => `${v}%`} {...EJE} width={56}
          label={{ value: 'presiones que terminan en sack  →  culpa del QB', angle: -90, position: 'insideLeft', offset: -2, fill: TINTA.secundaria, fontSize: 12, dy: 150 }} />
        <ZAxis type="number" dataKey="z" range={[60, 260]} />
        <ReferenceLine x={xRef} stroke={TINTA.tenue} strokeDasharray="4 4"
          label={{ value: ajustada ? 'lo esperado' : `liga ${pct(d.liga_presion)}`, position: 'insideTopLeft', fill: TINTA.secundaria, fontSize: 11 }} />
        <ReferenceLine y={d.liga_conversion * 100} stroke={TINTA.tenue} strokeDasharray="4 4"
          label={{ value: `liga ${pct(d.liga_conversion, 1)}`, position: 'insideTopRight', fill: TINTA.secundaria, fontSize: 11 }} />
        <Tooltip cursor={{ strokeDasharray: '3 3' }} content={({ payload }) => {
          const q = payload?.[0]?.payload as (typeof puntos)[number] | undefined
          if (!q) return null
          return (
            <div className="rounded-md border border-gray-200 bg-white px-3 py-2 text-xs shadow">
              <p className="font-semibold text-gray-900">{q.nombre} ({q.equipo})</p>
              <p>Presión: {pct(q.tasa_presion, 1)} [{pct(q.ic_presion[0])}–{pct(q.ic_presion[1])}] de {q.dropbacks} dropbacks</p>
              <p>Esperada por su tiempo con el balón: {pct(q.presion_esperada, 1)} ({signo(q.presion_sobre_esperado * 100)} pts)</p>
              <p>Tiempo mediano para lanzar: {q.tiempo_lanzamiento ?? '–'} s · scrambles: {q.scrambles}</p>
              <p>Sack por presión: {pct(q.conversion_sack, 1)} [{pct(q.ic_conversion[0])}–{pct(q.ic_conversion[1])}] de {q.presionadas}</p>
            </div>
          )
        }} />
        <Legend verticalAlign="top" height={28} />
        <Scatter name="Otros QBs" data={resto} fill={SERIES[0]} fillOpacity={0.55} isAnimationActive={false} />
        <Scatter name="Destacados" data={dest} fill={SERIES[1]} isAnimationActive={false}>
          <LabelList dataKey="etiqueta" position="right" fill={TINTA.primaria} fontSize={12} />
        </Scatter>
      </ScatterChart>
    </ResponsiveContainer>
  )
}

export function TarjetaReporte({ d }: { d: Reporte }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3 text-center">
        <Dato titulo={`${d.ofensiva} cede (3 s)`} valor={pct(d.presion_3s.ofensiva_cede)} />
        <Dato titulo={`${d.defensa} genera (3 s)`} valor={pct(d.presion_3s.defensa_genera)} />
        <Dato titulo="Liga (3 s)" valor={pct(d.presion_3s.liga)} />
      </div>
      <ul className="list-disc space-y-1 pl-5 text-sm text-gray-800">
        {d.recomendaciones.map((r) => <li key={r}>{r}</li>)}
      </ul>
      <div className="grid gap-4 md:grid-cols-2">
        <Tabla titulo={`¿Llega la presión antes de soltar? (${d.ofensiva})`} cab={['Familia de rutas', 'Tiempo', d.ofensiva, 'Liga']}
          filas={d.ventanas_ruta.map((v) => [v.ruta, `${v.segundos} s`, pct(v.ofensiva), pct(v.liga)])} />
        <Tabla titulo={`¿De dónde viene la presión que cede ${d.ofensiva}? (tracking)`} cab={['Origen', '% de presiones']}
          filas={d.fuentes_presion.map((f) => [f.fuente, pct(f.porcentaje)])} />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Tabla titulo={`Línea ofensiva de ${d.ofensiva}`} cab={['Jugador', 'Pos.', 'Snaps', 'Sobre lo esperado /100', 'IC95']}
          filas={d.linea_ofensiva.map((j) => [j.nombre, j.alineacion, j.snaps, signo(j.sobre_lo_esperado_100),
            `${signo(j.ic_bajo_100)} a ${signo(j.ic_alto_100)}`])} />
        <Tabla titulo={`Rushers de ${d.defensa}`} cab={['Jugador', 'Pos.', 'Suele enfrentar', 'Snaps', 'Presión ajustada']}
          filas={d.rushers_rivales.map((j) => [j.nombre, j.alineacion, j.frente_comun || '–', j.snaps, pct(j.tasa_ajustada, 1)])} />
      </div>
    </div>
  )
}

export function TablaValidacion({ v }: { v: Validacion }) {
  return (
    <div className="space-y-2">
      <Tabla titulo="Sensibilidad del umbral contra la presión de PFF" cab={['Umbral', 'Kappa', 'Acuerdo', 'Precisión', 'Recall', '% jugadas con presión']}
        filas={v.sensibilidad.map((s) => [`${s.umbral_yardas} yd${s.umbral_yardas === v.umbral_yardas ? ' (elegido)' : ''}`,
          s.kappa.toFixed(2), pct(s.acuerdo, 1), pct(s.precision), pct(s.recall), pct(s.tasa_presion)])} />
      <p className="text-xs text-gray-500">
        Decir siempre "sin presión" ya acierta el {pct(v.acuerdo_trivial)}, por eso elegimos el umbral por kappa (acuerdo corregido por azar) y no por acuerdo bruto.
        Los {v.sacks_sin_presion_tracking} sacks en los que ningún rusher llegó a {v.umbral_yardas} yd se cuentan como presión al momento del sack.
        En {v.empates_presion_y_pase} jugadas la presión y el pase ocurren en el mismo cuadro (0.1 s); se cuentan como presión.
      </p>
    </div>
  )
}

export function Dato({ titulo, valor, nota }: { titulo: string; valor: string; nota?: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-4 py-3">
      <p className="text-xs uppercase tracking-wide text-gray-500">{titulo}</p>
      <p className="text-2xl font-semibold text-gray-900">{valor}</p>
      {nota && <p className="text-xs text-gray-500">{nota}</p>}
    </div>
  )
}

export function Tabla({ titulo, cab, filas }: { titulo: string; cab: string[]; filas: Array<Array<string | number>> }) {
  return (
    <div className="overflow-x-auto">
      <p className="mb-1 text-sm font-semibold text-gray-800">{titulo}</p>
      <table className="w-full text-left text-sm">
        <thead><tr className="border-b border-gray-200 text-xs uppercase text-gray-500">{cab.map((c) => <th key={c} className="py-1 pr-3 font-medium">{c}</th>)}</tr></thead>
        <tbody>
          {filas.map((f, i) => (
            <tr key={i} className="border-b border-gray-100 text-gray-800">{f.map((c, j) => <td key={j} className="py-1 pr-3 tabular-nums">{c}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
