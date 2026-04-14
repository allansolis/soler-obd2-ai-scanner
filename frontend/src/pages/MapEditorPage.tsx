import { useMemo, useState, useCallback } from 'react'
import { Download, FileCode2, ShieldCheck, RotateCcw, Grid3x3 } from 'lucide-react'
import MapEditor, { MapData } from '../components/MapEditor'

// 101 map types (condensed list inspired by backend/map_types.py)
const MAP_CATALOG: Array<{ name: string; displayName: string; category: string; unit: string; min: number; max: number; critical: boolean }> = [
  { name: 'fuel_main', displayName: 'Mapa principal de combustible', category: 'Combustible', unit: 'ms', min: 0, max: 30, critical: true },
  { name: 'fuel_idle', displayName: 'Combustible en ralentí', category: 'Combustible', unit: 'ms', min: 0, max: 10, critical: false },
  { name: 'fuel_cranking', displayName: 'Combustible en arranque', category: 'Combustible', unit: 'ms', min: 0, max: 40, critical: false },
  { name: 'fuel_warmup', displayName: 'Enriquecimiento en calentamiento', category: 'Combustible', unit: '%', min: 0, max: 100, critical: false },
  { name: 'ignition_main', displayName: 'Avance de encendido principal', category: 'Encendido', unit: '° BTDC', min: -10, max: 45, critical: true },
  { name: 'ignition_idle', displayName: 'Avance de encendido en ralentí', category: 'Encendido', unit: '° BTDC', min: 0, max: 30, critical: true },
  { name: 'boost_target', displayName: 'Objetivo de presión de turbo', category: 'Turbo', unit: 'bar', min: 0, max: 3, critical: true },
  { name: 'boost_wgdc', displayName: 'Duty de la wastegate', category: 'Turbo', unit: '%', min: 0, max: 100, critical: true },
  { name: 'afr_target', displayName: 'AFR objetivo', category: 'Combustible', unit: 'AFR', min: 10, max: 18, critical: true },
  { name: 'vvt_intake', displayName: 'VVT admisión', category: 'Distribución', unit: '°', min: -20, max: 60, critical: false },
  { name: 'vvt_exhaust', displayName: 'VVT escape', category: 'Distribución', unit: '°', min: -20, max: 60, critical: false },
  { name: 'torque_limit', displayName: 'Límite de par', category: 'Seguridad', unit: 'Nm', min: 0, max: 1200, critical: true },
  { name: 'rev_limit', displayName: 'Corte de revoluciones', category: 'Seguridad', unit: 'rpm', min: 5000, max: 9000, critical: true },
  { name: 'speed_limit', displayName: 'Limitador de velocidad', category: 'Seguridad', unit: 'km/h', min: 0, max: 350, critical: false },
  { name: 'launch_rpm', displayName: 'RPM del launch control', category: 'Deportivo', unit: 'rpm', min: 2000, max: 7500, critical: false },
  { name: 'tps_transfer', displayName: 'Transferencia de acelerador', category: 'Acelerador', unit: '%', min: 0, max: 100, critical: false },
]
// Pad to 101 entries for realism
while (MAP_CATALOG.length < 101) {
  const i = MAP_CATALOG.length
  MAP_CATALOG.push({
    name: `aux_map_${i}`,
    displayName: `Mapa auxiliar ${i}`,
    category: 'Auxiliares',
    unit: '—',
    min: 0,
    max: 255,
    critical: false,
  })
}

// Generate realistic 20x16 fuel map (20 rows of load 0-100% in 5% steps, 16 cols of RPM 500-8000)
function buildStockData(): number[][] {
  const rows = 20
  const cols = 16
  const data: number[][] = []
  for (let r = 0; r < rows; r++) {
    const load = (r / (rows - 1)) * 100 // 0..100
    const row: number[] = []
    for (let c = 0; c < cols; c++) {
      const rpm = 500 + c * 500
      // Realistic VE-based injection time (ms)
      const loadFactor = 0.4 + (load / 100) * 1.6
      const rpmFactor = 1 - Math.exp(-rpm / 2500) + (rpm > 6500 ? (rpm - 6500) / 12000 : 0)
      let v = 1.2 + loadFactor * rpmFactor * 4.2
      // Enrichment at high load
      if (load > 80) v *= 1.08
      row.push(+v.toFixed(2))
    }
    data.push(row)
  }
  return data
}

export default function MapEditorPage() {
  const [selectedIndex, setSelectedIndex] = useState(0)
  const selectedMeta = MAP_CATALOG[selectedIndex]

  const stockData = useMemo(() => buildStockData(), [])

  const [currentData, setCurrentData] = useState<number[][]>(() =>
    stockData.map((row) => [...row])
  )

  const map: MapData = useMemo(
    () => ({
      name: selectedMeta.name,
      displayName: selectedMeta.displayName,
      unit: selectedMeta.unit,
      xAxis: {
        name: 'RPM',
        unit: 'rpm',
        values: Array.from({ length: 16 }, (_, i) => 500 + i * 500),
      },
      yAxis: {
        name: 'Carga',
        unit: '%',
        values: Array.from({ length: 20 }, (_, i) => +(i * (100 / 19)).toFixed(1)),
      },
      data: currentData,
      stockData,
      minValue: selectedMeta.min,
      maxValue: selectedMeta.max,
      safetyCritical: selectedMeta.critical,
    }),
    [selectedMeta, currentData, stockData]
  )

  const handleChange = useCallback((next: number[][]) => {
    setCurrentData(next)
  }, [])

  const handleSave = useCallback(() => {
    // Placeholder - would call API
    const flash = document.getElementById('save-toast')
    if (flash) {
      flash.classList.remove('opacity-0')
      flash.classList.add('opacity-100')
      setTimeout(() => {
        flash.classList.remove('opacity-100')
        flash.classList.add('opacity-0')
      }, 1800)
    }
  }, [])

  const exportCSV = () => {
    const lines: string[] = []
    lines.push(['', ...map.xAxis.values.map(String)].join(','))
    map.data.forEach((row, ri) => {
      lines.push([map.yAxis.values[ri], ...row.map(String)].join(','))
    })
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${map.name}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const exportBIN = () => {
    const flat = map.data.flat()
    const buf = new ArrayBuffer(flat.length * 4)
    const view = new DataView(buf)
    flat.forEach((v, i) => view.setFloat32(i * 4, v, true))
    const blob = new Blob([buf], { type: 'application/octet-stream' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${map.name}.bin`
    a.click()
    URL.revokeObjectURL(url)
  }

  const revertAll = () => {
    if (confirm('¿Revertir todos los cambios a stock? Esta acción no se puede deshacer.')) {
      setCurrentData(stockData.map((r) => [...r]))
    }
  }

  const verifySafety = () => {
    const issues: string[] = []
    let oor = 0
    for (const row of currentData) for (const v of row) if (v < map.minValue || v > map.maxValue) oor++
    if (oor > 0) issues.push(`${oor} celdas fuera de rango`)
    if (map.safetyCritical) {
      let big = 0
      for (let r = 0; r < currentData.length; r++)
        for (let c = 0; c < currentData[r].length; c++)
          if (Math.abs(currentData[r][c] - stockData[r][c]) > Math.abs(stockData[r][c]) * 0.2) big++
      if (big > 0) issues.push(`${big} celdas con desviación > 20% en mapa crítico`)
    }
    alert(issues.length === 0 ? '✓ Verificación de seguridad OK' : '⚠ Problemas:\n' + issues.join('\n'))
  }

  // Diff stats
  const diffStats = useMemo(() => {
    let modified = 0
    let maxDelta = 0
    let avgDelta = 0
    let sumDelta = 0
    for (let r = 0; r < currentData.length; r++) {
      for (let c = 0; c < currentData[r].length; c++) {
        const d = currentData[r][c] - stockData[r][c]
        if (Math.abs(d) > 1e-9) modified++
        if (Math.abs(d) > Math.abs(maxDelta)) maxDelta = d
        sumDelta += d
      }
    }
    const total = currentData.length * currentData[0].length
    avgDelta = sumDelta / total
    return { modified, maxDelta, avgDelta, total }
  }, [currentData, stockData])

  const categories = [...new Set(MAP_CATALOG.map((m) => m.category))]

  return (
    <div className="flex flex-col h-full p-6 gap-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl bg-obd-accent/15 flex items-center justify-center">
            <Grid3x3 className="w-5 h-5 text-obd-accent" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white tracking-tight">{map.displayName}</h1>
            <div className="flex items-center gap-2 text-xs text-slate-400 mt-0.5">
              <span className="px-2 py-0.5 rounded bg-obd-surface border border-obd-border">
                {selectedMeta.category}
              </span>
              <span>•</span>
              <span>Vehículo: VW Golf GTI Mk7 2.0 TSI</span>
              <span>•</span>
              <span className="font-mono">{map.name}</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <select
            value={selectedIndex}
            onChange={(e) => setSelectedIndex(Number(e.target.value))}
            className="px-3 py-2 bg-obd-surface border border-obd-border rounded-lg text-sm text-white focus:border-obd-accent focus:outline-none"
            title="Seleccionar mapa"
          >
            {categories.map((cat) => (
              <optgroup key={cat} label={cat}>
                {MAP_CATALOG.map((m, i) =>
                  m.category === cat ? (
                    <option key={m.name} value={i}>
                      {m.displayName}
                    </option>
                  ) : null
                )}
              </optgroup>
            ))}
          </select>
        </div>
      </div>

      {/* Main layout */}
      <div className="flex-1 flex gap-4 min-h-0">
        <div className="flex-1 min-w-0">
          <MapEditor map={map} onChange={handleChange} onSave={handleSave} />
        </div>

        {/* Side panel */}
        <aside className="w-72 flex-shrink-0 flex flex-col gap-3">
          <div className="bg-obd-surface border border-obd-border rounded-xl p-4">
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Resumen</h3>
            <dl className="space-y-2 text-xs">
              <div className="flex justify-between">
                <dt className="text-slate-400">Celdas totales</dt>
                <dd className="text-white font-mono">{diffStats.total}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-400">Modificadas</dt>
                <dd className="text-obd-yellow font-mono">{diffStats.modified}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-400">Cambio máx</dt>
                <dd className={`font-mono ${diffStats.maxDelta >= 0 ? 'text-obd-green' : 'text-obd-red'}`}>
                  {diffStats.maxDelta >= 0 ? '+' : ''}
                  {diffStats.maxDelta.toFixed(2)} {map.unit}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-400">Cambio prom</dt>
                <dd className="text-white font-mono">
                  {diffStats.avgDelta >= 0 ? '+' : ''}
                  {diffStats.avgDelta.toFixed(3)} {map.unit}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-400">Rango</dt>
                <dd className="text-slate-300 font-mono">
                  {map.minValue}–{map.maxValue}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-400">Crítico</dt>
                <dd className={map.safetyCritical ? 'text-obd-red' : 'text-obd-green'}>
                  {map.safetyCritical ? 'Sí' : 'No'}
                </dd>
              </div>
            </dl>
          </div>

          <div className="bg-obd-surface border border-obd-border rounded-xl p-4">
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Acciones</h3>
            <div className="space-y-2">
              <button
                onClick={verifySafety}
                title="Verificar valores contra límites de seguridad"
                className="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-obd-green/10 hover:bg-obd-green/20 border border-obd-green/30 text-obd-green text-xs font-medium transition-colors"
              >
                <ShieldCheck className="w-4 h-4" />
                Verificar seguridad
              </button>
              <button
                onClick={exportCSV}
                title="Exportar mapa como CSV"
                className="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-obd-bg hover:bg-white/5 border border-obd-border text-slate-200 text-xs font-medium transition-colors"
              >
                <Download className="w-4 h-4" />
                Exportar CSV
              </button>
              <button
                onClick={exportBIN}
                title="Exportar mapa como binario"
                className="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-obd-bg hover:bg-white/5 border border-obd-border text-slate-200 text-xs font-medium transition-colors"
              >
                <FileCode2 className="w-4 h-4" />
                Exportar BIN
              </button>
              <button
                onClick={revertAll}
                title="Revertir todos los cambios a stock"
                className="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-obd-red/10 hover:bg-obd-red/20 border border-obd-red/30 text-obd-red text-xs font-medium transition-colors"
              >
                <RotateCcw className="w-4 h-4" />
                Revertir todo
              </button>
            </div>
          </div>

          <div className="bg-obd-surface border border-obd-border rounded-xl p-4 text-[11px] text-slate-500 leading-relaxed">
            <p className="font-semibold text-slate-300 mb-1">Atajos</p>
            <p>Flechas: navegar • F2: editar • Delete: restaurar • Ctrl+C/V/X: copiar/pegar/cortar • Ctrl+Z/Y: deshacer/rehacer • Ctrl+A: seleccionar todo • Ctrl+S: guardar</p>
          </div>
        </aside>
      </div>

      <div
        id="save-toast"
        className="fixed bottom-6 right-6 px-4 py-2 rounded-lg bg-obd-green text-white text-sm font-semibold shadow-lg opacity-0 transition-opacity duration-300 pointer-events-none"
      >
        ✓ Mapa guardado
      </div>
    </div>
  )
}
