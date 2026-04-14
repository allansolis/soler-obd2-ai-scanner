import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import {
  Sparkles,
  X,
  CheckCircle2,
  Circle,
  ChevronRight,
  Info,
} from 'lucide-react'
import { useAI } from '../contexts/AIContext'

interface GuidanceStep {
  order: number
  title: string
  description: string
  done: boolean
}

const pageGuidance: Record<
  string,
  { headline: string; body: string; steps: GuidanceStep[] }
> = {
  '/': {
    headline: 'Analiza la salud de tu vehiculo',
    body: 'Te recomiendo ejecutar un escaneo completo antes de conducir.',
    steps: [
      { order: 1, title: 'Conectar adaptador OBD2', description: 'Enchufa el ELM327 al puerto OBD2.', done: false },
      { order: 2, title: 'Iniciar escaneo', description: 'Lectura de sensores y DTCs.', done: false },
      { order: 3, title: 'Revisar diagnostico', description: 'Analizo codigos y sugiero acciones.', done: false },
    ],
  },
  '/dtc': {
    headline: 'Guia de reparacion paso a paso',
    body: 'Puedo guiarte para resolver cada codigo detectado.',
    steps: [
      { order: 1, title: 'Seleccionar DTC', description: 'Elige un codigo para analizar.', done: false },
      { order: 2, title: 'Revisar procedimiento', description: 'Cruzo PDFs y base de conocimiento.', done: false },
      { order: 3, title: 'Aplicar reparacion', description: 'Sigo contigo paso a paso.', done: false },
      { order: 4, title: 'Verificar resultado', description: 'Borro DTC y monitoreo.', done: false },
    ],
  },
  '/tuning': {
    headline: 'Tune seguro y validado',
    body: 'Valido cada cambio antes de flashear la ECU.',
    steps: [
      { order: 1, title: 'Chequeo de salud', description: 'Verifico que el motor este en condiciones.', done: false },
      { order: 2, title: 'Backup de ECU', description: 'Creo respaldo automatico.', done: false },
      { order: 3, title: 'Generar mapa', description: 'Optimizo segun tu perfil.', done: false },
      { order: 4, title: 'Validacion de seguridad', description: 'Reviso limites criticos.', done: false },
      { order: 5, title: 'Flashear y verificar', description: 'Aplico y monitoreo resultados.', done: false },
    ],
  },
  '/vehicle': {
    headline: 'Configuracion de vehiculo',
    body: 'Con tu VIN puedo buscar DTCs comunes y oportunidades de tuning.',
    steps: [
      { order: 1, title: 'Ingresar VIN o modelo', description: 'Identifico tu vehiculo.', done: false },
      { order: 2, title: 'Cargar perfil', description: 'Extraigo datos tecnicos.', done: false },
      { order: 3, title: 'Recomendaciones', description: 'Sugerencias especificas para tu auto.', done: false },
    ],
  },
  '/map-editor': {
    headline: 'Edicion segura de mapas',
    body: 'Valido cada celda en tiempo real y te aviso de valores peligrosos.',
    steps: [
      { order: 1, title: 'Cargar mapa actual', description: 'Leo desde ECU o backup.', done: false },
      { order: 2, title: 'Editar celdas', description: 'Controlo limites en vivo.', done: false },
      { order: 3, title: 'Validar y exportar', description: 'Genero archivo seguro.', done: false },
    ],
  },
}

export default function AIGuidancePanel() {
  const location = useLocation()
  const { currentTask } = useAI()
  const guidance = pageGuidance[location.pathname]
  const [visible, setVisible] = useState(true)
  const [steps, setSteps] = useState<GuidanceStep[]>(guidance?.steps ?? [])

  useEffect(() => {
    setSteps(guidance?.steps ?? [])
    setVisible(true)
  }, [location.pathname, guidance])

  if (!guidance || !visible) return null

  function toggleStep(order: number) {
    setSteps((prev) =>
      prev.map((s) => (s.order === order ? { ...s, done: !s.done } : s))
    )
  }

  const completed = steps.filter((s) => s.done).length
  const pct = steps.length ? Math.round((completed / steps.length) * 100) : 0

  return (
    <div className="bg-obd-surface border border-obd-border rounded-2xl overflow-hidden shadow-lg animate-in fade-in slide-in-from-bottom-2 duration-300">
      <div className="flex items-start gap-3 p-4 bg-gradient-to-r from-obd-accent/10 to-obd-purple/10 border-b border-obd-border">
        <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-obd-accent to-obd-purple flex items-center justify-center flex-shrink-0">
          <Sparkles className="w-4 h-4 text-white" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-white">{guidance.headline}</p>
          <p className="text-xs text-slate-400 mt-0.5">{guidance.body}</p>
        </div>
        <button
          onClick={() => setVisible(false)}
          className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/5"
          aria-label="Ocultar guia"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="px-4 py-3 border-b border-obd-border flex items-center gap-3">
        <div className="flex-1 h-2 rounded-full bg-obd-bg overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-obd-accent to-obd-purple transition-all duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="text-xs text-slate-400 tabular-nums">
          {completed}/{steps.length}
        </span>
      </div>

      <ul className="p-2">
        {steps.map((s) => (
          <li key={s.order}>
            <button
              onClick={() => toggleStep(s.order)}
              className={`w-full flex items-start gap-3 px-3 py-2.5 rounded-xl text-left transition-colors ${
                s.done
                  ? 'bg-obd-accent/5'
                  : 'hover:bg-white/5'
              }`}
            >
              {s.done ? (
                <CheckCircle2 className="w-5 h-5 text-obd-green flex-shrink-0 mt-0.5" />
              ) : (
                <Circle className="w-5 h-5 text-slate-500 flex-shrink-0 mt-0.5" />
              )}
              <div className="flex-1 min-w-0">
                <p
                  className={`text-sm font-medium ${
                    s.done ? 'text-slate-500 line-through' : 'text-slate-200'
                  }`}
                >
                  {s.title}
                </p>
                <p className="text-xs text-slate-500 mt-0.5">{s.description}</p>
              </div>
              <ChevronRight className="w-4 h-4 text-slate-600 flex-shrink-0 mt-1" />
            </button>
          </li>
        ))}
      </ul>

      {currentTask !== 'idle' && (
        <div className="px-4 py-2 border-t border-obd-border bg-obd-bg/40 flex items-center gap-2 text-xs text-obd-accent">
          <Info className="w-3.5 h-3.5" />
          AI trabajando: {currentTask}
        </div>
      )}
    </div>
  )
}
