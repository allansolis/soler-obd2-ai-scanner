import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import {
  Sparkles,
  X,
  Minus,
  Send,
  Mic,
  Wrench,
  Search,
  Cpu,
  Zap,
  Loader2,
  MessageCircle,
} from 'lucide-react'
import { useAI } from '../contexts/AIContext'
import type { Suggestion } from '../contexts/AIContext'

interface ChatMessage {
  id: string
  role: 'user' | 'ai'
  text: string
  timestamp: number
}

interface Position {
  x: number
  y: number
}

const pageSuggestions: Record<string, Suggestion[]> = {
  '/': [
    {
      id: 'dashboard-analyze',
      title: '¿Quieres que analice la salud del auto?',
      description: 'Realizo un escaneo completo y genero un reporte instantaneo.',
      priority: 'high',
    },
    {
      id: 'dashboard-sensors',
      title: 'Insights de sensores en vivo',
      description: 'Detecto anomalias en tiempo real mientras manejas.',
      priority: 'medium',
    },
  ],
  '/dtc': [
    {
      id: 'dtc-guide',
      title: 'He detectado codigos activos. ¿Te guio para resolverlos?',
      description: 'Paso a paso hasta dejar el vehiculo sin fallas.',
      priority: 'high',
    },
  ],
  '/tuning': [
    {
      id: 'tuning-generate',
      title: '¿Quieres que genere un tune optimizado para tu vehiculo?',
      description: 'Valido cada cambio antes de flashear la ECU.',
      priority: 'high',
    },
  ],
  '/map-editor': [
    {
      id: 'map-validate',
      title: 'Validando cada celda en tiempo real',
      description: 'Te aviso si un valor puede dañar el motor.',
      priority: 'high',
    },
  ],
  '/vehicle': [
    {
      id: 'vehicle-detect',
      title: 'Detecte tu vehiculo. ¿Busco los DTCs comunes y puntos de tuning?',
      description: 'Cruzo tu modelo con la base de conocimiento global.',
      priority: 'high',
    },
  ],
}

function taskLabel(task: string): string {
  switch (task) {
    case 'scanning':
      return 'Escaneando'
    case 'diagnosing':
      return 'Diagnosticando'
    case 'repairing':
      return 'Armando reparacion'
    case 'tuning':
      return 'Generando tune'
    case 'learning':
      return 'Aprendiendo'
    default:
      return 'Listo'
  }
}

export default function AICopilot() {
  const location = useLocation()
  const { currentTask, suggestions, pushSuggestion, askQuestion, executeAction } =
    useAI()

  const [open, setOpen] = useState(false)
  const [minimized, setMinimized] = useState(false)
  const [position, setPosition] = useState<Position>({ x: 24, y: 24 })
  const [dragging, setDragging] = useState(false)
  const dragStart = useRef<{ mx: number; my: number; px: number; py: number } | null>(
    null
  )

  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'ai',
      text: 'Hola, soy tu copiloto SOLER. Estoy aqui para ayudarte a escanear, diagnosticar, reparar y tunear tu vehiculo.',
      timestamp: Date.now(),
    },
  ])
  const [input, setInput] = useState('')
  const [thinking, setThinking] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Note: page-aware suggestions are already rendered via contextualSuggestions below.
  // We do NOT push them to global state to avoid infinite re-render loops.

  // Auto scroll chat
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [messages, thinking])

  // Drag handlers
  useEffect(() => {
    if (!dragging) return
    function onMove(e: MouseEvent) {
      if (!dragStart.current) return
      const dx = e.clientX - dragStart.current.mx
      const dy = e.clientY - dragStart.current.my
      setPosition({
        x: Math.max(8, dragStart.current.px - dx),
        y: Math.max(8, dragStart.current.py - dy),
      })
    }
    function onUp() {
      setDragging(false)
      dragStart.current = null
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [dragging])

  const busy = currentTask !== 'idle'

  const contextualSuggestions = useMemo(() => {
    const pageOnes = pageSuggestions[location.pathname] ?? []
    const merged = [...pageOnes, ...suggestions]
    const seen = new Set<string>()
    return merged.filter((s) => {
      if (seen.has(s.id)) return false
      seen.add(s.id)
      return true
    })
  }, [location.pathname, suggestions])

  async function handleSend() {
    const text = input.trim()
    if (!text || thinking) return
    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: 'user',
      text,
      timestamp: Date.now(),
    }
    setMessages((m) => [...m, userMsg])
    setInput('')
    setThinking(true)
    try {
      const answer = await askQuestion(text)
      setMessages((m) => [
        ...m,
        {
          id: `a-${Date.now()}`,
          role: 'ai',
          text: answer,
          timestamp: Date.now(),
        },
      ])
    } finally {
      setThinking(false)
    }
  }

  async function handleQuickAction(
    type: 'scan' | 'repair' | 'tune' | 'explain'
  ) {
    const label =
      type === 'scan'
        ? 'Escaneando vehiculo...'
        : type === 'repair'
          ? 'Preparando guia de reparacion...'
          : type === 'tune'
            ? 'Generando tune optimizado...'
            : 'Explicando DTC...'
    setMessages((m) => [
      ...m,
      {
        id: `sys-${Date.now()}`,
        role: 'ai',
        text: label,
        timestamp: Date.now(),
      },
    ])
    const res = await executeAction({
      id: `act-${Date.now()}`,
      type:
        type === 'scan'
          ? 'scan'
          : type === 'repair'
            ? 'repair'
            : type === 'tune'
              ? 'tune'
              : 'explain',
      label,
      timestamp: Date.now(),
    })
    setMessages((m) => [
      ...m,
      {
        id: `res-${Date.now()}`,
        role: 'ai',
        text: res.message,
        timestamp: Date.now(),
      },
    ])
  }

  // ---------------------------------------------------------------------
  // Floating badge (collapsed)
  // ---------------------------------------------------------------------
  if (!open) {
    return (
      <button
        onClick={() => {
          setOpen(true)
          setMinimized(false)
        }}
        aria-label="Abrir copiloto AI"
        className="fixed z-50 group"
        style={{ right: position.x, bottom: position.y }}
      >
        <span className="relative flex items-center justify-center w-14 h-14 rounded-full bg-gradient-to-br from-obd-accent to-obd-purple shadow-xl shadow-obd-accent/40">
          <Sparkles className="w-6 h-6 text-white" />
          <span className="absolute inset-0 rounded-full bg-obd-accent/40 animate-ping" />
          {busy && (
            <span className="absolute -top-1 -right-1 w-3 h-3 rounded-full bg-obd-green animate-pulse ring-2 ring-obd-bg" />
          )}
        </span>
        <span className="absolute right-full mr-3 top-1/2 -translate-y-1/2 bg-obd-surface border border-obd-border rounded-lg px-3 py-1.5 text-xs text-slate-200 whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
          Copiloto AI — {taskLabel(currentTask)}
        </span>
      </button>
    )
  }

  // ---------------------------------------------------------------------
  // Minimized bar
  // ---------------------------------------------------------------------
  if (minimized) {
    return (
      <div
        className="fixed z-50 bg-obd-surface border border-obd-border rounded-xl shadow-2xl px-4 py-3 flex items-center gap-3"
        style={{ right: position.x, bottom: position.y }}
      >
        <Sparkles className="w-4 h-4 text-obd-accent" />
        <span className="text-xs text-slate-300">
          Copiloto · {taskLabel(currentTask)}
        </span>
        <button
          onClick={() => setMinimized(false)}
          className="text-slate-400 hover:text-white text-xs"
        >
          Abrir
        </button>
        <button
          onClick={() => setOpen(false)}
          className="text-slate-500 hover:text-slate-300"
          aria-label="Cerrar"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    )
  }

  // ---------------------------------------------------------------------
  // Full panel
  // ---------------------------------------------------------------------
  return (
    <div
      className="fixed z-50 w-[400px] h-[600px] flex flex-col bg-obd-surface border border-obd-border rounded-2xl shadow-2xl overflow-hidden"
      style={{ right: position.x, bottom: position.y }}
    >
      {/* Header (drag handle) */}
      <div
        className="flex items-center gap-3 px-4 py-3 border-b border-obd-border bg-gradient-to-r from-obd-accent/10 to-obd-purple/10 cursor-move select-none"
        onMouseDown={(e) => {
          dragStart.current = {
            mx: e.clientX,
            my: e.clientY,
            px: position.x,
            py: position.y,
          }
          setDragging(true)
        }}
      >
        <div className="relative w-9 h-9 rounded-lg bg-gradient-to-br from-obd-accent to-obd-purple flex items-center justify-center">
          <Sparkles className="w-4 h-4 text-white" />
          {busy && (
            <span className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-obd-green animate-pulse ring-2 ring-obd-surface" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-white">Copiloto SOLER</p>
          <p className="text-[10px] uppercase tracking-widest text-slate-400 flex items-center gap-1.5">
            {busy ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <span className="w-1.5 h-1.5 rounded-full bg-obd-green" />
            )}
            {taskLabel(currentTask)}
          </p>
        </div>
        <button
          onClick={() => setMinimized(true)}
          className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/5"
          aria-label="Minimizar"
        >
          <Minus className="w-4 h-4" />
        </button>
        <button
          onClick={() => setOpen(false)}
          className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/5"
          aria-label="Cerrar"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Contextual suggestions */}
      {contextualSuggestions.length > 0 && (
        <div className="px-4 py-3 border-b border-obd-border bg-obd-bg/40 max-h-[130px] overflow-y-auto">
          <p className="text-[10px] uppercase tracking-widest text-slate-500 mb-2">
            Sugerencias
          </p>
          <div className="space-y-2">
            {contextualSuggestions.slice(0, 3).map((s) => (
              <div
                key={s.id}
                className="p-2.5 rounded-lg bg-obd-surface border border-obd-border/60 hover:border-obd-accent/40 transition-colors"
              >
                <p className="text-xs font-medium text-slate-200">{s.title}</p>
                <p className="text-[11px] text-slate-500 mt-0.5">
                  {s.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Chat */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.map((m) => (
          <div
            key={m.id}
            className={`flex ${
              m.role === 'user' ? 'justify-end' : 'justify-start'
            }`}
          >
            <div
              className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed ${
                m.role === 'user'
                  ? 'bg-obd-accent text-white rounded-br-sm'
                  : 'bg-obd-bg border border-obd-border text-slate-200 rounded-bl-sm'
              }`}
            >
              {m.role === 'ai' && (
                <div className="flex items-center gap-1.5 mb-1 text-[10px] uppercase tracking-widest text-obd-accent">
                  <MessageCircle className="w-3 h-3" /> AI
                </div>
              )}
              <p>{m.text}</p>
            </div>
          </div>
        ))}
        {thinking && (
          <div className="flex justify-start">
            <div className="bg-obd-bg border border-obd-border rounded-2xl px-3.5 py-2 text-sm text-slate-400 flex items-center gap-2">
              <Loader2 className="w-3 h-3 animate-spin" /> Pensando...
            </div>
          </div>
        )}
      </div>

      {/* Quick actions */}
      <div className="px-3 py-2 border-t border-obd-border grid grid-cols-4 gap-1.5">
        <QuickAction
          icon={Search}
          label="Escanear"
          onClick={() => handleQuickAction('scan')}
          disabled={busy}
        />
        <QuickAction
          icon={Wrench}
          label="Reparar"
          onClick={() => handleQuickAction('repair')}
          disabled={busy}
        />
        <QuickAction
          icon={Cpu}
          label="Tunear"
          onClick={() => handleQuickAction('tune')}
          disabled={busy}
        />
        <QuickAction
          icon={Zap}
          label="Explicar"
          onClick={() => handleQuickAction('explain')}
          disabled={busy}
        />
      </div>

      {/* Input */}
      <div className="px-3 py-3 border-t border-obd-border flex items-center gap-2">
        <button
          className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-white/5"
          title="Entrada de voz (proximamente)"
          aria-label="Entrada de voz"
        >
          <Mic className="w-4 h-4" />
        </button>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              handleSend()
            }
          }}
          placeholder="Pregunta algo al copiloto..."
          className="flex-1 bg-obd-bg border border-obd-border rounded-lg px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-obd-accent/60"
        />
        <button
          onClick={handleSend}
          disabled={thinking || !input.trim()}
          className="p-2 rounded-lg bg-obd-accent text-white hover:bg-obd-accent/90 disabled:opacity-40 disabled:cursor-not-allowed"
          aria-label="Enviar"
        >
          <Send className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}

function QuickAction({
  icon: Icon,
  label,
  onClick,
  disabled,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="flex flex-col items-center gap-1 py-2 rounded-lg text-[11px] text-slate-300 hover:bg-white/5 disabled:opacity-40 disabled:cursor-not-allowed"
    >
      <Icon className="w-4 h-4 text-obd-accent" />
      {label}
    </button>
  )
}
