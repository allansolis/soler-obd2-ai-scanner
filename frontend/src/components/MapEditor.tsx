import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { AlertTriangle } from 'lucide-react'
import MapEditorToolbar, { ViewMode } from './MapEditorToolbar'
import MapEditorStatusBar from './MapEditorStatusBar'
import MapEditor3DPlot from './MapEditor3DPlot'
import { useMapHistory } from '../hooks/useMapHistory'

export interface MapData {
  name: string
  displayName: string
  unit: string
  xAxis: { name: string; unit: string; values: number[] }
  yAxis: { name: string; unit: string; values: number[] }
  data: number[][]
  stockData: number[][]
  minValue: number
  maxValue: number
  safetyCritical: boolean
}

interface MapEditorProps {
  map: MapData
  onChange: (newData: number[][]) => void
  onSave: () => void
  readOnly?: boolean
}

interface CellRef {
  r: number
  c: number
}

interface Selection {
  anchor: CellRef
  focus: CellRef
}

const colLabel = (i: number) => {
  let s = ''
  let n = i
  do {
    s = String.fromCharCode(65 + (n % 26)) + s
    n = Math.floor(n / 26) - 1
  } while (n >= 0)
  return s
}

const inRange = (c: CellRef, sel: Selection) => {
  const r1 = Math.min(sel.anchor.r, sel.focus.r)
  const r2 = Math.max(sel.anchor.r, sel.focus.r)
  const c1 = Math.min(sel.anchor.c, sel.focus.c)
  const c2 = Math.max(sel.anchor.c, sel.focus.c)
  return c.r >= r1 && c.r <= r2 && c.c >= c1 && c.c <= c2
}

const selectionCells = (sel: Selection): CellRef[] => {
  const r1 = Math.min(sel.anchor.r, sel.focus.r)
  const r2 = Math.max(sel.anchor.r, sel.focus.r)
  const c1 = Math.min(sel.anchor.c, sel.focus.c)
  const c2 = Math.max(sel.anchor.c, sel.focus.c)
  const out: CellRef[] = []
  for (let r = r1; r <= r2; r++) for (let c = c1; c <= c2; c++) out.push({ r, c })
  return out
}

export default function MapEditor({ map, onChange, onSave, readOnly }: MapEditorProps) {
  const { current: data, canUndo, canRedo, push, undo, redo, set } = useMapHistory(map.data)
  const [selection, setSelection] = useState<Selection>({
    anchor: { r: 0, c: 0 },
    focus: { r: 0, c: 0 },
  })
  const [extraSelected, setExtraSelected] = useState<CellRef[]>([])
  const [editing, setEditing] = useState<CellRef | null>(null)
  const [editValue, setEditValue] = useState('')
  const [viewMode, setViewMode] = useState<ViewMode>('numeric')
  const [dragging, setDragging] = useState(false)
  const [colWidths, setColWidths] = useState<number[]>(() =>
    Array(map.xAxis.values.length).fill(72)
  )
  const [rowHeights, setRowHeights] = useState<number[]>(() =>
    Array(map.yAxis.values.length).fill(30)
  )
  const gridRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const resizingCol = useRef<{ index: number; startX: number; startW: number } | null>(null)
  const resizingRow = useRef<{ index: number; startY: number; startH: number } | null>(null)

  // Reset data when map changes
  useEffect(() => {
    set(map.data)
    setColWidths(Array(map.xAxis.values.length).fill(72))
    setRowHeights(Array(map.yAxis.values.length).fill(30))
    setSelection({ anchor: { r: 0, c: 0 }, focus: { r: 0, c: 0 } })
  }, [map.name, map.data, map.xAxis.values.length, map.yAxis.values.length, set])

  useEffect(() => {
    onChange(data)
  }, [data, onChange])

  // Global stats
  const { minV, maxV } = useMemo(() => {
    let mn = Infinity
    let mx = -Infinity
    for (const row of data)
      for (const v of row) {
        if (v < mn) mn = v
        if (v > mx) mx = v
      }
    return { minV: isFinite(mn) ? mn : 0, maxV: isFinite(mx) ? mx : 1 }
  }, [data])

  const stockMin = useMemo(() => Math.min(...map.stockData.flat()), [map.stockData])
  const stockMax = useMemo(() => Math.max(...map.stockData.flat()), [map.stockData])

  const allSelected = useMemo(() => {
    const base = selectionCells(selection)
    const extraKeys = new Set(extraSelected.map((c) => `${c.r},${c.c}`))
    const baseKeys = new Set(base.map((c) => `${c.r},${c.c}`))
    const merged = [...base]
    for (const e of extraSelected) if (!baseKeys.has(`${e.r},${e.c}`)) merged.push(e)
    return { cells: merged, hasExtra: extraKeys.size > 0 }
  }, [selection, extraSelected])

  const selectionStats = useMemo(() => {
    const cells = allSelected.cells
    if (cells.length === 0) return { min: null, max: null, avg: null, sum: null }
    const vals = cells.map((c) => data[c.r]?.[c.c] ?? 0)
    const sum = vals.reduce((a, b) => a + b, 0)
    return {
      min: Math.min(...vals),
      max: Math.max(...vals),
      avg: sum / vals.length,
      sum,
    }
  }, [allSelected, data])

  const modifiedCount = useMemo(() => {
    let count = 0
    for (let r = 0; r < data.length; r++)
      for (let c = 0; c < data[r].length; c++)
        if (Math.abs(data[r][c] - map.stockData[r][c]) > 1e-9) count++
    return count
  }, [data, map.stockData])

  const outOfRangeCount = useMemo(() => {
    let c = 0
    for (const row of data) for (const v of row) if (v < map.minValue || v > map.maxValue) c++
    return c
  }, [data, map.minValue, map.maxValue])

  const safetyLevel: 'safe' | 'warn' | 'danger' = useMemo(() => {
    if (outOfRangeCount > 0) return 'danger'
    if (map.safetyCritical && modifiedCount > 20) return 'warn'
    if (modifiedCount > 50) return 'warn'
    return 'safe'
  }, [outOfRangeCount, map.safetyCritical, modifiedCount])

  // Cell color for heatmap / diff / percent
  const cellStyle = useCallback(
    (r: number, c: number): { bg: string; fg: string; label: string; outOfRange: boolean } => {
      const v = data[r][c]
      const stock = map.stockData[r][c]
      const outOfRange = v < map.minValue || v > map.maxValue
      const range = maxV - minV || 1

      let bg = 'transparent'
      let fg = '#e2e8f0'
      let label = v.toFixed(v % 1 === 0 ? 0 : 2)

      if (viewMode === 'heatmap') {
        const t = Math.max(0, Math.min(1, (v - minV) / range))
        const r_ = Math.floor(20 + t * 235)
        const g_ = Math.floor(100 + (1 - Math.abs(t - 0.5) * 2) * 155)
        const b_ = Math.floor(255 - t * 230)
        bg = `rgba(${r_},${g_},${b_},0.35)`
      } else if (viewMode === 'diff') {
        const diff = v - stock
        label = (diff > 0 ? '+' : '') + diff.toFixed(2)
        if (Math.abs(diff) < 1e-9) {
          fg = '#64748b'
        } else if (diff > 0) {
          bg = `rgba(34,197,94,${Math.min(0.5, Math.abs(diff) / Math.max(1, stock) * 2)})`
          fg = '#4ade80'
        } else {
          bg = `rgba(239,68,68,${Math.min(0.5, Math.abs(diff) / Math.max(1, stock) * 2)})`
          fg = '#f87171'
        }
      } else if (viewMode === 'percent') {
        const pct = stock === 0 ? 100 : (v / stock) * 100
        label = pct.toFixed(1) + '%'
        const delta = pct - 100
        if (Math.abs(delta) < 0.1) fg = '#64748b'
        else if (delta > 0) fg = '#4ade80'
        else fg = '#f87171'
      } else {
        // numeric: highlight modified
        if (Math.abs(v - stock) > 1e-9) fg = '#fbbf24'
      }

      if (outOfRange) {
        bg = 'rgba(239,68,68,0.25)'
        fg = '#fca5a5'
      }

      return { bg, fg, label, outOfRange }
    },
    [data, map.stockData, map.minValue, map.maxValue, minV, maxV, viewMode]
  )

  // Apply operation
  const applyOperation = useCallback(
    (op: string, val: number) => {
      if (readOnly) return
      const cells = allSelected.cells
      if (cells.length === 0) return
      const next = data.map((row) => [...row])

      if (op === 'smooth') {
        for (const { r, c } of cells) {
          let sum = 0
          let n = 0
          for (let dr = -1; dr <= 1; dr++) {
            for (let dc = -1; dc <= 1; dc++) {
              const rr = r + dr
              const cc = c + dc
              if (rr >= 0 && rr < data.length && cc >= 0 && cc < data[0].length) {
                sum += data[rr][cc]
                n++
              }
            }
          }
          next[r][c] = +(sum / n).toFixed(3)
        }
      } else if (op === 'interp') {
        if (cells.length < 2) return
        const first = cells[0]
        const last = cells[cells.length - 1]
        const a = data[first.r][first.c]
        const b = data[last.r][last.c]
        cells.forEach((cell, i) => {
          const t = i / (cells.length - 1)
          next[cell.r][cell.c] = +(a + (b - a) * t).toFixed(3)
        })
      } else if (op === 'filldown') {
        const rs = cells.map((c) => c.r)
        const cs = cells.map((c) => c.c)
        const rmin = Math.min(...rs)
        const colsSet = new Set(cs)
        colsSet.forEach((c) => {
          const src = data[rmin][c]
          for (const cell of cells) if (cell.c === c) next[cell.r][cell.c] = src
        })
      } else if (op === 'fillright') {
        const cs = cells.map((c) => c.c)
        const cmin = Math.min(...cs)
        const rowsSet = new Set(cells.map((c) => c.r))
        rowsSet.forEach((r) => {
          const src = data[r][cmin]
          for (const cell of cells) if (cell.r === r) next[cell.r][cell.c] = src
        })
      } else if (op === 'reset') {
        for (const { r, c } of cells) next[r][c] = map.stockData[r][c]
      } else {
        for (const { r, c } of cells) {
          const cur = next[r][c]
          let nv = cur
          if (op === 'set') nv = val
          else if (op === 'add') nv = cur + val
          else if (op === 'sub') nv = cur - val
          else if (op === 'mul') nv = cur * val
          else if (op === 'div') nv = val === 0 ? cur : cur / val
          next[r][c] = +nv.toFixed(3)
        }
      }
      push(next)
    },
    [allSelected, data, push, readOnly, map.stockData]
  )

  const commitCellEdit = useCallback(
    (value: string, cell: CellRef) => {
      const parsed = parseFloat(value)
      if (!isNaN(parsed)) {
        const next = data.map((row) => [...row])
        next[cell.r][cell.c] = +parsed.toFixed(3)
        push(next)
      }
      setEditing(null)
      setEditValue('')
    },
    [data, push]
  )

  const startEdit = (r: number, c: number) => {
    if (readOnly) return
    setEditing({ r, c })
    setEditValue(String(data[r][c]))
    setTimeout(() => inputRef.current?.select(), 0)
  }

  // Keyboard
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (editing) return
      const target = e.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return

      const rows = data.length
      const cols = data[0].length

      if (e.ctrlKey || e.metaKey) {
        if (e.key === 'z') {
          e.preventDefault()
          undo()
        } else if (e.key === 'y') {
          e.preventDefault()
          redo()
        } else if (e.key === 's') {
          e.preventDefault()
          onSave()
        } else if (e.key === 'a') {
          e.preventDefault()
          setSelection({ anchor: { r: 0, c: 0 }, focus: { r: rows - 1, c: cols - 1 } })
          setExtraSelected([])
        } else if (e.key === 'c' || e.key === 'x') {
          const cells = allSelected.cells
          if (cells.length === 0) return
          const r1 = Math.min(...cells.map((c) => c.r))
          const r2 = Math.max(...cells.map((c) => c.r))
          const c1 = Math.min(...cells.map((c) => c.c))
          const c2 = Math.max(...cells.map((c) => c.c))
          const lines: string[] = []
          for (let r = r1; r <= r2; r++) {
            const row: string[] = []
            for (let c = c1; c <= c2; c++) row.push(String(data[r][c]))
            lines.push(row.join('\t'))
          }
          navigator.clipboard?.writeText(lines.join('\n'))
          if (e.key === 'x' && !readOnly) {
            const next = data.map((row) => [...row])
            for (const cell of cells) next[cell.r][cell.c] = 0
            push(next)
          }
        } else if (e.key === 'v') {
          if (readOnly) return
          navigator.clipboard?.readText().then((text) => {
            const rowsArr = text.split(/\r?\n/).filter(Boolean)
            const next = data.map((row) => [...row])
            const start = selection.focus
            rowsArr.forEach((line, ri) => {
              const cells = line.split('\t')
              cells.forEach((cv, ci) => {
                const r = start.r + ri
                const c = start.c + ci
                if (r < rows && c < cols) {
                  const v = parseFloat(cv)
                  if (!isNaN(v)) next[r][c] = +v.toFixed(3)
                }
              })
            })
            push(next)
          })
        }
        return
      }

      if (e.key === 'F2') {
        e.preventDefault()
        startEdit(selection.focus.r, selection.focus.c)
      } else if (e.key === 'Delete') {
        if (readOnly) return
        e.preventDefault()
        const next = data.map((row) => [...row])
        for (const cell of allSelected.cells) next[cell.r][cell.c] = map.stockData[cell.r][cell.c]
        push(next)
      } else if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        const dr = e.key === 'Enter' ? 1 : 0
        const dc = e.key === 'Tab' ? 1 : 0
        const nr = Math.min(rows - 1, selection.focus.r + dr)
        const nc = Math.min(cols - 1, selection.focus.c + dc)
        setSelection({ anchor: { r: nr, c: nc }, focus: { r: nr, c: nc } })
      } else if (e.key.startsWith('Arrow')) {
        e.preventDefault()
        const f = selection.focus
        let nr = f.r
        let nc = f.c
        if (e.key === 'ArrowUp') nr = Math.max(0, f.r - 1)
        if (e.key === 'ArrowDown') nr = Math.min(rows - 1, f.r + 1)
        if (e.key === 'ArrowLeft') nc = Math.max(0, f.c - 1)
        if (e.key === 'ArrowRight') nc = Math.min(cols - 1, f.c + 1)
        if (e.shiftKey) {
          setSelection((s) => ({ ...s, focus: { r: nr, c: nc } }))
        } else {
          setSelection({ anchor: { r: nr, c: nc }, focus: { r: nr, c: nc } })
          setExtraSelected([])
        }
      } else if (/^[0-9.\-+]$/.test(e.key)) {
        startEdit(selection.focus.r, selection.focus.c)
        setEditValue(e.key)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [editing, selection, data, undo, redo, onSave, allSelected, push, readOnly, map.stockData])

  // Column resize
  useEffect(() => {
    const mm = (e: MouseEvent) => {
      if (resizingCol.current) {
        const dx = e.clientX - resizingCol.current.startX
        setColWidths((ws) => {
          const next = [...ws]
          next[resizingCol.current!.index] = Math.max(40, resizingCol.current!.startW + dx)
          return next
        })
      }
      if (resizingRow.current) {
        const dy = e.clientY - resizingRow.current.startY
        setRowHeights((hs) => {
          const next = [...hs]
          next[resizingRow.current!.index] = Math.max(20, resizingRow.current!.startH + dy)
          return next
        })
      }
    }
    const mu = () => {
      resizingCol.current = null
      resizingRow.current = null
    }
    window.addEventListener('mousemove', mm)
    window.addEventListener('mouseup', mu)
    return () => {
      window.removeEventListener('mousemove', mm)
      window.removeEventListener('mouseup', mu)
    }
  }, [])

  const focusLabel = `${colLabel(selection.focus.c)}${selection.focus.r + 1}`

  const totalWidth = colWidths.reduce((a, b) => a + b, 0) + 64

  // Render 3D mode
  if (viewMode === '3d') {
    return (
      <div className="flex flex-col h-full bg-obd-bg rounded-xl overflow-hidden border border-obd-border">
        <MapEditorToolbar
          onUndo={undo}
          onRedo={redo}
          canUndo={canUndo}
          canRedo={canRedo}
          onSave={onSave}
          onOperation={applyOperation}
          viewMode={viewMode}
          onViewMode={setViewMode}
          safetyLevel={safetyLevel}
          readOnly={readOnly}
        />
        <div className="flex-1 p-4 min-h-0">
          <MapEditor3DPlot
            data={data}
            xAxis={map.xAxis.values}
            yAxis={map.yAxis.values}
            min={minV}
            max={maxV}
          />
        </div>
        <MapEditorStatusBar
          currentCell={focusLabel}
          selectionCount={allSelected.cells.length}
          min={selectionStats.min}
          max={selectionStats.max}
          avg={selectionStats.avg}
          sum={selectionStats.sum}
          modifiedCount={modifiedCount}
          unit={map.unit}
        />
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-obd-bg rounded-xl overflow-hidden border border-obd-border">
      <MapEditorToolbar
        onUndo={undo}
        onRedo={redo}
        canUndo={canUndo}
        canRedo={canRedo}
        onSave={onSave}
        onOperation={applyOperation}
        viewMode={viewMode}
        onViewMode={setViewMode}
        safetyLevel={safetyLevel}
        readOnly={readOnly}
      />

      {outOfRangeCount > 0 && (
        <div className="flex items-center gap-2 px-3 py-1.5 bg-obd-red/10 border-b border-obd-red/30 text-[11px] text-obd-red">
          <AlertTriangle className="w-3.5 h-3.5" />
          {outOfRangeCount} celda{outOfRangeCount === 1 ? '' : 's'} fuera de rango ({map.minValue} - {map.maxValue} {map.unit})
        </div>
      )}

      <div
        ref={gridRef}
        className="flex-1 overflow-auto font-mono text-xs"
        style={{ fontFamily: 'JetBrains Mono, ui-monospace, monospace' }}
      >
        <div style={{ minWidth: totalWidth }}>
          {/* Header row */}
          <div className="flex sticky top-0 z-20 bg-obd-surface border-b border-obd-border">
            <div
              className="flex-shrink-0 flex items-center justify-center text-[10px] text-slate-500 font-semibold border-r border-obd-border bg-obd-surface"
              style={{ width: 64, height: 32 }}
              title={`${map.yAxis.name} (${map.yAxis.unit}) \\ ${map.xAxis.name} (${map.xAxis.unit})`}
            >
              {map.yAxis.unit}\{map.xAxis.unit}
            </div>
            {map.xAxis.values.map((xv, ci) => {
              const colSelected = allSelected.cells.some((c) => c.c === ci)
              return (
                <div
                  key={ci}
                  className={`relative flex-shrink-0 flex items-center justify-center text-[10px] font-semibold border-r border-obd-border select-none cursor-pointer ${
                    colSelected ? 'bg-obd-accent/15 text-obd-accent' : 'text-slate-400'
                  }`}
                  style={{ width: colWidths[ci], height: 32 }}
                  onClick={() =>
                    setSelection({
                      anchor: { r: 0, c: ci },
                      focus: { r: data.length - 1, c: ci },
                    })
                  }
                  title={`${colLabel(ci)} — ${xv} ${map.xAxis.unit}`}
                >
                  {xv}
                  <div
                    onMouseDown={(e) => {
                      e.stopPropagation()
                      e.preventDefault()
                      resizingCol.current = {
                        index: ci,
                        startX: e.clientX,
                        startW: colWidths[ci],
                      }
                    }}
                    className="absolute right-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-obd-accent"
                  />
                </div>
              )
            })}
          </div>

          {/* Data rows */}
          {data.map((row, ri) => {
            const rowSelected = allSelected.cells.some((c) => c.r === ri)
            return (
              <div key={ri} className="flex border-b border-obd-border/60">
                <div
                  className={`sticky left-0 z-10 flex-shrink-0 flex items-center justify-center text-[10px] font-semibold border-r border-obd-border select-none cursor-pointer ${
                    rowSelected ? 'bg-obd-accent/15 text-obd-accent' : 'bg-obd-surface text-slate-400'
                  }`}
                  style={{ width: 64, height: rowHeights[ri] }}
                  onClick={() =>
                    setSelection({
                      anchor: { r: ri, c: 0 },
                      focus: { r: ri, c: row.length - 1 },
                    })
                  }
                  title={`Fila ${ri + 1} — ${map.yAxis.values[ri]} ${map.yAxis.unit}`}
                >
                  {map.yAxis.values[ri]}
                  <div
                    onMouseDown={(e) => {
                      e.stopPropagation()
                      e.preventDefault()
                      resizingRow.current = {
                        index: ri,
                        startY: e.clientY,
                        startH: rowHeights[ri],
                      }
                    }}
                    className="absolute left-0 right-0 bottom-0 h-1 cursor-row-resize hover:bg-obd-accent"
                  />
                </div>
                {row.map((_, ci) => {
                  const cellR = { r: ri, c: ci }
                  const selected = inRange(cellR, selection) || extraSelected.some((e) => e.r === ri && e.c === ci)
                  const isFocus = selection.focus.r === ri && selection.focus.c === ci
                  const isEditing = editing?.r === ri && editing?.c === ci
                  const { bg, fg, label, outOfRange } = cellStyle(ri, ci)
                  const isSafetyWarn = map.safetyCritical && Math.abs(data[ri][ci] - map.stockData[ri][ci]) > Math.abs(map.stockData[ri][ci] * 0.15)

                  return (
                    <div
                      key={ci}
                      className={`relative flex-shrink-0 flex items-center justify-center border-r border-obd-border/60 transition-colors duration-75 ${
                        selected ? 'bg-obd-accent/10' : ''
                      } ${isFocus ? 'ring-1 ring-inset ring-obd-accent' : ''}`}
                      style={{
                        width: colWidths[ci],
                        height: rowHeights[ri],
                        backgroundColor: selected ? undefined : bg,
                        color: fg,
                      }}
                      onMouseDown={(e) => {
                        if (e.shiftKey) {
                          setSelection((s) => ({ ...s, focus: cellR }))
                        } else if (e.ctrlKey || e.metaKey) {
                          setExtraSelected((xs) => [...xs, cellR])
                          setSelection({ anchor: cellR, focus: cellR })
                        } else {
                          setSelection({ anchor: cellR, focus: cellR })
                          setExtraSelected([])
                          setDragging(true)
                        }
                      }}
                      onMouseEnter={() => {
                        if (dragging) setSelection((s) => ({ ...s, focus: cellR }))
                      }}
                      onMouseUp={() => setDragging(false)}
                      onDoubleClick={() => startEdit(ri, ci)}
                    >
                      {outOfRange && !isEditing && (
                        <AlertTriangle className="absolute top-0.5 left-0.5 w-2.5 h-2.5 text-obd-red" />
                      )}
                      {isSafetyWarn && !outOfRange && !isEditing && (
                        <span className="absolute top-0.5 left-0.5 w-1.5 h-1.5 rounded-full bg-obd-yellow" />
                      )}
                      {isEditing ? (
                        <input
                          ref={inputRef}
                          value={editValue}
                          onChange={(e) => setEditValue(e.target.value)}
                          onBlur={() => commitCellEdit(editValue, { r: ri, c: ci })}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              commitCellEdit(editValue, { r: ri, c: ci })
                              const nr = Math.min(data.length - 1, ri + 1)
                              setSelection({ anchor: { r: nr, c: ci }, focus: { r: nr, c: ci } })
                            } else if (e.key === 'Tab') {
                              e.preventDefault()
                              commitCellEdit(editValue, { r: ri, c: ci })
                              const nc = Math.min(data[0].length - 1, ci + 1)
                              setSelection({ anchor: { r: ri, c: nc }, focus: { r: ri, c: nc } })
                            } else if (e.key === 'Escape') {
                              setEditing(null)
                              setEditValue('')
                            }
                          }}
                          className="w-full h-full bg-obd-bg text-white text-center px-1 outline-none border-2 border-obd-accent"
                          type="number"
                          step="0.01"
                        />
                      ) : (
                        <span className="truncate px-1 pointer-events-none">{label}</span>
                      )}
                    </div>
                  )
                })}
              </div>
            )
          })}
        </div>
      </div>

      <MapEditorStatusBar
        currentCell={focusLabel}
        selectionCount={allSelected.cells.length}
        min={selectionStats.min}
        max={selectionStats.max}
        avg={selectionStats.avg}
        sum={selectionStats.sum}
        modifiedCount={modifiedCount}
        unit={map.unit}
      />
    </div>
  )
}
