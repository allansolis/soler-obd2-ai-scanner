import {
  Undo2,
  Redo2,
  Save,
  Plus,
  Minus,
  X as XIcon,
  Divide,
  Equal,
  Sparkles,
  TrendingUp,
  ArrowDownToLine,
  ArrowRightToLine,
  RotateCcw,
  Hash,
  Flame,
  Box,
  Percent,
  GitCompareArrows,
  ShieldCheck,
  ShieldAlert,
  Shield,
} from 'lucide-react'
import { useState } from 'react'

export type ViewMode = 'numeric' | 'heatmap' | '3d' | 'diff' | 'percent'

interface Props {
  onUndo: () => void
  onRedo: () => void
  canUndo: boolean
  canRedo: boolean
  onSave: () => void
  onOperation: (op: string, value: number) => void
  viewMode: ViewMode
  onViewMode: (m: ViewMode) => void
  safetyLevel: 'safe' | 'warn' | 'danger'
  readOnly?: boolean
}

const IconBtn = ({
  title,
  onClick,
  disabled,
  active,
  children,
  tone,
}: {
  title: string
  onClick: () => void
  disabled?: boolean
  active?: boolean
  children: React.ReactNode
  tone?: 'accent' | 'red' | 'green' | 'yellow'
}) => (
  <button
    title={title}
    onClick={onClick}
    disabled={disabled}
    className={`group relative p-2 rounded-lg border transition-all duration-75 flex items-center justify-center ${
      disabled
        ? 'border-obd-border text-slate-700 cursor-not-allowed'
        : active
        ? `border-obd-accent bg-obd-accent/15 text-obd-accent`
        : `border-obd-border text-slate-400 hover:text-white hover:border-slate-500 hover:bg-white/5 ${
            tone === 'red'
              ? 'hover:text-obd-red'
              : tone === 'green'
              ? 'hover:text-obd-green'
              : tone === 'yellow'
              ? 'hover:text-obd-yellow'
              : 'hover:text-obd-accent'
          }`
    }`}
  >
    {children}
  </button>
)

export default function MapEditorToolbar({
  onUndo,
  onRedo,
  canUndo,
  canRedo,
  onSave,
  onOperation,
  viewMode,
  onViewMode,
  safetyLevel,
  readOnly,
}: Props) {
  const [opValue, setOpValue] = useState('1.05')

  const v = parseFloat(opValue) || 0

  const SafetyIcon =
    safetyLevel === 'safe' ? ShieldCheck : safetyLevel === 'warn' ? Shield : ShieldAlert
  const safetyColor =
    safetyLevel === 'safe'
      ? 'text-obd-green border-obd-green/40 bg-obd-green/5'
      : safetyLevel === 'warn'
      ? 'text-obd-yellow border-obd-yellow/40 bg-obd-yellow/5'
      : 'text-obd-red border-obd-red/40 bg-obd-red/5'
  const safetyLabel =
    safetyLevel === 'safe' ? 'Seguro' : safetyLevel === 'warn' ? 'Precaución' : 'Peligro'

  return (
    <div className="flex items-center gap-2 px-3 py-2 bg-obd-surface border-b border-obd-border flex-wrap">
      <div className="flex items-center gap-1">
        <IconBtn title="Deshacer (Ctrl+Z)" onClick={onUndo} disabled={!canUndo || readOnly}>
          <Undo2 className="w-4 h-4" />
        </IconBtn>
        <IconBtn title="Rehacer (Ctrl+Y)" onClick={onRedo} disabled={!canRedo || readOnly}>
          <Redo2 className="w-4 h-4" />
        </IconBtn>
      </div>

      <div className="w-px h-6 bg-obd-border" />

      <div className="flex items-center gap-1">
        <input
          type="number"
          step="0.01"
          value={opValue}
          onChange={(e) => setOpValue(e.target.value)}
          disabled={readOnly}
          className="w-20 px-2 py-1.5 bg-obd-bg border border-obd-border rounded-lg text-xs text-white font-mono focus:border-obd-accent focus:outline-none"
          title="Valor para las operaciones"
        />
        <IconBtn title="Fijar valor exacto a la selección" onClick={() => onOperation('set', v)} disabled={readOnly}>
          <Equal className="w-4 h-4" />
        </IconBtn>
        <IconBtn title="Sumar valor a cada celda" onClick={() => onOperation('add', v)} disabled={readOnly}>
          <Plus className="w-4 h-4" />
        </IconBtn>
        <IconBtn title="Restar valor a cada celda" onClick={() => onOperation('sub', v)} disabled={readOnly}>
          <Minus className="w-4 h-4" />
        </IconBtn>
        <IconBtn title="Multiplicar por factor (ej. 1.05 = +5%)" onClick={() => onOperation('mul', v)} disabled={readOnly}>
          <XIcon className="w-4 h-4" />
        </IconBtn>
        <IconBtn title="Dividir por factor" onClick={() => onOperation('div', v)} disabled={readOnly}>
          <Divide className="w-4 h-4" />
        </IconBtn>
      </div>

      <div className="w-px h-6 bg-obd-border" />

      <div className="flex items-center gap-1">
        <IconBtn title="Suavizar (promedio con vecinos)" onClick={() => onOperation('smooth', 0)} disabled={readOnly}>
          <Sparkles className="w-4 h-4" />
        </IconBtn>
        <IconBtn title="Interpolar linealmente entre extremos" onClick={() => onOperation('interp', 0)} disabled={readOnly}>
          <TrendingUp className="w-4 h-4" />
        </IconBtn>
        <IconBtn title="Rellenar hacia abajo" onClick={() => onOperation('filldown', 0)} disabled={readOnly}>
          <ArrowDownToLine className="w-4 h-4" />
        </IconBtn>
        <IconBtn title="Rellenar hacia la derecha" onClick={() => onOperation('fillright', 0)} disabled={readOnly}>
          <ArrowRightToLine className="w-4 h-4" />
        </IconBtn>
        <IconBtn title="Restaurar a valores de stock" onClick={() => onOperation('reset', 0)} disabled={readOnly} tone="red">
          <RotateCcw className="w-4 h-4" />
        </IconBtn>
      </div>

      <div className="w-px h-6 bg-obd-border" />

      <div className="flex items-center gap-1">
        <IconBtn title="Modo numérico" onClick={() => onViewMode('numeric')} active={viewMode === 'numeric'}>
          <Hash className="w-4 h-4" />
        </IconBtn>
        <IconBtn title="Mapa de calor" onClick={() => onViewMode('heatmap')} active={viewMode === 'heatmap'}>
          <Flame className="w-4 h-4" />
        </IconBtn>
        <IconBtn title="Vista 3D" onClick={() => onViewMode('3d')} active={viewMode === '3d'}>
          <Box className="w-4 h-4" />
        </IconBtn>
        <IconBtn title="Diferencia vs stock" onClick={() => onViewMode('diff')} active={viewMode === 'diff'}>
          <GitCompareArrows className="w-4 h-4" />
        </IconBtn>
        <IconBtn title="Porcentaje del stock" onClick={() => onViewMode('percent')} active={viewMode === 'percent'}>
          <Percent className="w-4 h-4" />
        </IconBtn>
      </div>

      <div className="ml-auto flex items-center gap-2">
        <div
          className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-[11px] font-medium ${safetyColor}`}
          title={`Estado de seguridad: ${safetyLabel}`}
        >
          <SafetyIcon className="w-3.5 h-3.5" />
          {safetyLabel}
        </div>
        <button
          onClick={onSave}
          disabled={readOnly}
          title="Guardar mapa (Ctrl+S)"
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-obd-accent hover:bg-obd-accent/80 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-semibold transition-colors"
        >
          <Save className="w-4 h-4" />
          Guardar
        </button>
      </div>
    </div>
  )
}
