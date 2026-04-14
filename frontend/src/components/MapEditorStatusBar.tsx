interface MapEditorStatusBarProps {
  currentCell: string
  selectionCount: number
  min: number | null
  max: number | null
  avg: number | null
  sum: number | null
  modifiedCount: number
  unit: string
}

export default function MapEditorStatusBar({
  currentCell,
  selectionCount,
  min,
  max,
  avg,
  sum,
  modifiedCount,
  unit,
}: MapEditorStatusBarProps) {
  const fmt = (v: number | null) => (v === null || isNaN(v) ? '—' : v.toFixed(2))
  return (
    <div className="flex items-center gap-4 px-4 py-1.5 bg-obd-surface border-t border-obd-border text-[11px] font-mono text-slate-400">
      <span className="text-obd-accent font-semibold">Celda: {currentCell}</span>
      <span className="text-slate-600">|</span>
      <span>{selectionCount} celda{selectionCount === 1 ? '' : 's'} seleccionada{selectionCount === 1 ? '' : 's'}</span>
      <span className="text-slate-600">|</span>
      <span>Min: <span className="text-slate-200">{fmt(min)}</span></span>
      <span>Max: <span className="text-slate-200">{fmt(max)}</span></span>
      <span>Prom: <span className="text-slate-200">{fmt(avg)}</span></span>
      <span>Suma: <span className="text-slate-200">{fmt(sum)}</span></span>
      <span className="text-slate-600">|</span>
      <span className={modifiedCount > 0 ? 'text-obd-yellow' : 'text-slate-500'}>
        {modifiedCount} modificada{modifiedCount === 1 ? '' : 's'}
      </span>
      <span className="ml-auto text-slate-500">Unidad: {unit}</span>
    </div>
  )
}
