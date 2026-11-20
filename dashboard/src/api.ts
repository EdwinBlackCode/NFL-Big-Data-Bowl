// Rutas relativas SIN diagonal inicial: la app se publica en una subruta (/evento/equipo/)
export async function getJSON<T>(ruta: string): Promise<T> {
  const r = await fetch(`api/${ruta}`)
  if (!r.ok) throw new Error(`Error ${r.status} en api/${ruta}`)
  return r.json() as Promise<T>
}

export async function postJSON<T>(ruta: string, cuerpo: unknown): Promise<T> {
  const r = await fetch(`api/${ruta}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cuerpo),
  })
  if (!r.ok) throw new Error(`Error ${r.status} en api/${ruta}`)
  return r.json() as Promise<T>
}

export type Resumen = {
  jugadas: number; jugadas_reloj: number; frames_tracking: number; juegos: number
  presion_2_5s: number; presion_3s: number; presion_4s: number
  completos_sin_presion: number; completos_con_presion: number
  yardas_sin_presion: number; yardas_con_presion: number
  acuerdo_tracking_vs_pff: number; kappa_tracking_vs_pff: number; acuerdo_trivial: number
  umbral_yardas: number; alcance: string
}

export type Concordancia = { acuerdo: number; kappa: number; precision: number; recall: number; f1: number; tasa_presion: number }
export type Validacion = Concordancia & {
  umbral_yardas: number; jugadas: number; acuerdo_trivial: number
  sacks_sin_presion_tracking: number; empates_presion_y_pase: number
  sensibilidad: Array<Concordancia & { umbral_yardas: number }>
}

export type FilaReloj = { nombre: string; n: number; a_2_5s: number; a_3_0s: number; a_4_0s: number; segundos_hasta_25pct: number | null }
export type Reloj = {
  segmento: string; umbral_yardas: number; series: string[]
  puntos: Array<Record<string, number>>; resumen: FilaReloj[]; km_ingenuo_4s?: number
}

export type Jugador = {
  nflId: number; nombre: string; posicion: string; equipo: string; alineacion: string; snaps: number
  tasa_observada: number; tasa_ajustada: number; ic_bajo: number; ic_alto: number
  presiones?: number; sacks?: number; frente_comun?: string; llegadas_tracking?: number
  permitidas?: number; sacks_permitidos?: number; esperadas?: number; sobre_lo_esperado_100?: number
  ic_bajo_100?: number; ic_alto_100?: number; dificultad_rival?: number
  presiones_tracking?: number; tempranas?: number; tempranas_100?: number; t_medio_presion?: number | null
}
export type Ranking = { posicion: 'ol' | 'rushers'; orden?: string; min_snaps: number; media_liga: number; prior: number[]; jugadores: Jugador[] }

export type QB = {
  nflId: number; nombre: string; equipo: string; dropbacks: number; presionadas: number; sacks: number; scrambles: number
  tasa_presion: number; ic_presion: number[]; presion_esperada: number; presion_sobre_esperado: number; ic_sobre_esperado: number[]
  tiempo_lanzamiento: number | null
  conversion_sack: number; ic_conversion: number[]; tasa_sack: number; ic_sack: number[]
}
export type Cuadrante = {
  min_dropbacks: number; liga_presion: number; liga_conversion: number; liga_tiempo_lanzamiento: number
  n_presionadas_liga: number; qbs: QB[]
}

export type Reporte = {
  ofensiva: string; defensa: string
  presion_3s: { ofensiva_cede: number; defensa_genera: number; liga: number }
  presion_2_5s: { ofensiva_cede: number; defensa_genera: number; liga: number }
  ventanas_ruta: Array<{ ruta: string; segundos: number; ofensiva: number; liga: number }>
  fuentes_presion: Array<{ fuente: string; porcentaje: number }>
  linea_ofensiva: Array<{ nflId: number; nombre: string; alineacion: string; snaps: number; tasa_ajustada: number
    sobre_lo_esperado_100: number; ic_bajo_100: number; ic_alto_100: number; tempranas_100: number }>
  rushers_rivales: Array<{ nflId: number; nombre: string; alineacion: string; frente_comun: string; snaps: number
    presiones: number; sacks: number; tasa_ajustada: number }>
  recomendaciones: string[]
}

export type RespuestaCoach = {
  pregunta: string; respuesta: string; fuente: string
  herramienta: 'get_pocket_clock' | 'get_player_ranking' | 'get_matchup_report' | null
  datos: Reloj | Ranking | Reporte | null
  error?: string
}

export const pct = (x: number, d = 0) => `${(x * 100).toFixed(d)}%`
export const signo = (x: number, d = 1) => `${x > 0 ? '+' : ''}${x.toFixed(d)}`
