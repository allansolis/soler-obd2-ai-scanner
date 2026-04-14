import { useEffect, useMemo, useState } from 'react'
import {
  Database,
  Search,
  Cpu,
  FileText,
  HardDrive,
  Globe,
  Wrench,
  Layers,
  Car,
  AlertTriangle,
  Zap,
  RefreshCw,
  Loader2,
  BookOpen,
  CircuitBoard,
  Cog,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Tipos
// ---------------------------------------------------------------------------

type ResourceItem = {
  id: number
  name: string
  type: string
  category: string
  source: string
  source_url?: string
  size_bytes: number
  description: string
  make_tags: string[]
  system_tags: string[]
  language: string
  is_available_local: boolean
  local_path?: string
  last_indexed?: string
}

type SearchResultItem = {
  kind: string
  id: number
  title: string
  description: string
  score: number
  payload: any
}

type HubStats = {
  total_resources: number
  total_software: number
  total_vehicles: number
  total_dtcs: number
  total_diagrams: number
  total_repair_procedures: number
  total_pdfs_local: number
  total_drive: number
  total_online: number
  db_size_mb: number
  last_compiled: string | null
  by_category: Record<string, number>
  by_make: Record<string, number>
  compile_running?: boolean
  last_compile?: any
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const formatBytes = (n: number): string => {
  if (!n) return '-'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = n
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(v < 10 ? 1 : 0)} ${units[i]}`
}

const sourceMeta: Record<string, { label: string; color: string; icon: any }> = {
  google_drive: { label: 'Drive', color: 'text-blue-400', icon: HardDrive },
  local_pdf: { label: 'Local', color: 'text-emerald-400', icon: FileText },
  online: { label: 'Online', color: 'text-purple-400', icon: Globe },
  builtin: { label: 'Builtin', color: 'text-amber-400', icon: Cpu },
  github: { label: 'GitHub', color: 'text-slate-300', icon: Database },
}

const typeIcon: Record<string, any> = {
  software: Cpu,
  manual: BookOpen,
  diagram: CircuitBoard,
  pinout: Zap,
  course: FileText,
  database: Database,
  catalog: Layers,
  tuning_map_type: Cog,
  video: FileText,
}

// ---------------------------------------------------------------------------
// Componente principal
// ---------------------------------------------------------------------------

export default function KnowledgeHub() {
  const [stats, setStats] = useState<HubStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResultItem[]>([])
  const [resources, setResources] = useState<ResourceItem[]>([])
  const [searching, setSearching] = useState(false)
  const [compiling, setCompiling] = useState(false)
  const [filterMake, setFilterMake] = useState('')
  const [filterSystem, setFilterSystem] = useState('')
  const [filterType, setFilterType] = useState('')
  const [openSidebar, setOpenSidebar] = useState<Record<string, boolean>>({
    software: true,
    dtcs: true,
    tuning: true,
  })

  const loadStats = async () => {
    try {
      const res = await fetch('/api/hub/stats')
      const data = await res.json()
      setStats(data)
      setCompiling(!!data.compile_running)
    } catch (e) {
      console.error(e)
    }
  }

  const loadDefaultResources = async () => {
    try {
      const res = await fetch('/api/hub/resources?limit=60')
      const data = await res.json()
      setResources(data.items || [])
    } catch (e) {
      console.error(e)
    }
  }

  useEffect(() => {
    setLoading(true)
    Promise.all([loadStats(), loadDefaultResources()]).finally(() => setLoading(false))
  }, [])

  // Polling cuando la compilacion esta corriendo
  useEffect(() => {
    if (!compiling) return
    const interval = setInterval(loadStats, 2000)
    return () => clearInterval(interval)
  }, [compiling])

  const runSearch = async () => {
    if (!query.trim()) {
      setResults([])
      return
    }
    setSearching(true)
    try {
      const params = new URLSearchParams({ q: query })
      if (filterMake) params.set('make', filterMake)
      if (filterSystem) params.set('system', filterSystem)
      if (filterType) params.set('type', filterType)
      const res = await fetch(`/api/hub/search?${params.toString()}`)
      const data = await res.json()
      setResults(data.results || [])
    } catch (e) {
      console.error(e)
    } finally {
      setSearching(false)
    }
  }

  const triggerCompile = async () => {
    setCompiling(true)
    await fetch('/api/hub/compile', { method: 'POST' })
    setTimeout(loadStats, 1500)
  }

  const displayItems: SearchResultItem[] = useMemo(() => {
    if (results.length > 0) return results
    return resources.map(r => ({
      kind: 'resource',
      id: r.id,
      title: r.name,
      description: r.description,
      score: 1,
      payload: r,
    }))
  }, [results, resources])

  // Sidebar categories
  const sidebarSections = [
    { key: 'software', label: 'Software profesional', icon: Cpu, count: stats?.total_software || 0, type: 'software' },
    { key: 'manuals', label: 'Manuales', icon: BookOpen, count: stats?.by_category?.repair || 0, category: 'repair' },
    { key: 'dtcs', label: 'DTCs y soluciones', icon: AlertTriangle, count: stats?.total_dtcs || 0 },
    { key: 'tuning', label: 'Mapas de tuning', icon: Cog, count: stats?.by_category?.tuning || 0, category: 'tuning' },
    { key: 'diagrams', label: 'Diagramas electricos', icon: CircuitBoard, count: stats?.by_category?.electrical || 0, category: 'electrical' },
    { key: 'pinouts', label: 'Pinouts ECU', icon: Zap, count: 0, type: 'pinout' },
    { key: 'transmission', label: 'Transmisiones', icon: Wrench, count: stats?.by_category?.transmission || 0, category: 'transmission' },
    { key: 'mercedes', label: 'Mi vehiculo (Mercedes C280)', icon: Car, count: stats?.by_make?.['Mercedes-Benz'] || 0, make: 'mercedes' },
  ]

  const handleSidebarClick = (sec: any) => {
    if (sec.type) setFilterType(sec.type)
    if (sec.category) setFilterSystem('')
    if (sec.make) setFilterMake(sec.make)
    setQuery(sec.label.split(' ')[0])
  }

  return (
    <div className="flex h-full bg-obd-bg text-slate-100">
      {/* Sidebar de categorias */}
      <aside className="w-72 flex-shrink-0 border-r border-obd-border bg-obd-surface/50 p-4 overflow-y-auto">
        <div className="flex items-center gap-2 mb-4 px-2">
          <Database className="w-5 h-5 text-obd-accent" />
          <h2 className="text-sm font-bold uppercase tracking-wider text-slate-300">Categorias</h2>
        </div>
        <div className="space-y-1">
          {sidebarSections.map(sec => {
            const Icon = sec.icon
            const open = !!openSidebar[sec.key]
            return (
              <button
                key={sec.key}
                onClick={() => {
                  handleSidebarClick(sec)
                  setOpenSidebar({ ...openSidebar, [sec.key]: !open })
                }}
                className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-slate-300 hover:text-white hover:bg-white/5 transition"
              >
                {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                <Icon className="w-4 h-4 text-obd-accent" />
                <span className="flex-1 text-left">{sec.label}</span>
                <span className="text-xs text-slate-500 bg-white/5 px-2 py-0.5 rounded">{sec.count}</span>
              </button>
            )
          })}
        </div>

        <div className="mt-6 pt-4 border-t border-obd-border">
          <button
            onClick={triggerCompile}
            disabled={compiling}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-obd-accent/10 text-obd-accent hover:bg-obd-accent/20 disabled:opacity-50 transition text-sm font-medium"
          >
            {compiling ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <RefreshCw className="w-4 h-4" />
            )}
            {compiling ? 'Compilando...' : 'Recompilar Hub'}
          </button>
          {stats?.last_compiled && (
            <p className="text-[10px] text-slate-500 mt-2 text-center">
              Ultima: {new Date(stats.last_compiled).toLocaleString('es-ES')}
            </p>
          )}
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-y-auto p-6">
        {/* Header */}
        <div className="mb-6">
          <div className="flex items-center gap-3 mb-1">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-obd-accent to-obd-purple flex items-center justify-center">
              <Database className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white">KnowledgeHub</h1>
              <p className="text-xs text-slate-500 uppercase tracking-widest">El cerebro automotriz de SOLER</p>
            </div>
          </div>
        </div>

        {/* Stats cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 mb-6">
          <StatCard icon={Layers} label="Recursos" value={stats?.total_resources ?? '-'} color="text-obd-accent" />
          <StatCard icon={Car} label="Vehiculos" value={stats?.total_vehicles ?? '-'} color="text-emerald-400" />
          <StatCard icon={AlertTriangle} label="DTCs" value={stats?.total_dtcs ?? '-'} color="text-amber-400" />
          <StatCard icon={FileText} label="PDFs" value={stats?.total_pdfs_local ?? '-'} color="text-blue-400" />
          <StatCard icon={Cpu} label="Software" value={stats?.total_software ?? '-'} color="text-purple-400" />
          <StatCard icon={Cog} label="Mapas" value={stats?.by_category?.tuning ?? '-'} color="text-pink-400" />
        </div>

        {/* Search bar */}
        <div className="bg-obd-surface border border-obd-border rounded-xl p-4 mb-4">
          <div className="flex gap-3 items-stretch">
            <div className="flex-1 flex items-center gap-2 bg-obd-bg border border-obd-border rounded-lg px-3">
              <Search className="w-5 h-5 text-slate-500" />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && runSearch()}
                placeholder="Buscar manuales, DTCs, software, vehiculos, mapas..."
                className="flex-1 bg-transparent py-3 text-white placeholder-slate-500 focus:outline-none"
              />
            </div>
            <button
              onClick={runSearch}
              disabled={searching}
              className="px-5 py-3 bg-obd-accent hover:bg-obd-accent/90 text-white rounded-lg font-medium flex items-center gap-2 disabled:opacity-50"
            >
              {searching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
              Buscar
            </button>
          </div>

          {/* Filtros */}
          <div className="flex gap-2 mt-3 flex-wrap">
            <FilterSelect
              value={filterMake}
              onChange={setFilterMake}
              placeholder="Marca"
              options={Object.keys(stats?.by_make ?? {})}
            />
            <FilterSelect
              value={filterSystem}
              onChange={setFilterSystem}
              placeholder="Sistema"
              options={['engine', 'transmission', 'abs', 'airbag', 'electrical', 'tuning', 'diagnostic', 'hvac', 'emissions']}
            />
            <FilterSelect
              value={filterType}
              onChange={setFilterType}
              placeholder="Tipo"
              options={['software', 'manual', 'diagram', 'pinout', 'database', 'catalog', 'tuning_map_type']}
            />
            {(filterMake || filterSystem || filterType) && (
              <button
                onClick={() => { setFilterMake(''); setFilterSystem(''); setFilterType('') }}
                className="text-xs text-slate-400 hover:text-white px-3 py-2"
              >
                Limpiar filtros
              </button>
            )}
          </div>
        </div>

        {/* Resultados */}
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-8 h-8 text-obd-accent animate-spin" />
          </div>
        ) : displayItems.length === 0 ? (
          <div className="text-center py-20 text-slate-500">
            <Database className="w-12 h-12 mx-auto mb-3 opacity-50" />
            <p>No se encontraron resultados.</p>
            {!stats?.total_resources && (
              <button onClick={triggerCompile} className="mt-4 text-obd-accent hover:underline">
                Compilar el hub para empezar
              </button>
            )}
          </div>
        ) : (
          <>
            <div className="text-xs text-slate-400 mb-2">
              {results.length > 0
                ? `${displayItems.length} resultados para "${query}"`
                : `${displayItems.length} recursos del catalogo`}
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {displayItems.map((item) => (
                <ResultCard key={`${item.kind}-${item.id}`} item={item} />
              ))}
            </div>
          </>
        )}

        {/* DB info footer */}
        {stats && (
          <div className="mt-8 text-xs text-slate-500 text-center">
            <CheckCircle2 className="w-3 h-3 inline mr-1" />
            DB: {stats.db_size_mb} MB - {stats.total_drive} Drive - {stats.total_pdfs_local} Local - {stats.total_online} Online
          </div>
        )}
      </main>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Subcomponentes
// ---------------------------------------------------------------------------

function StatCard({ icon: Icon, label, value, color }: any) {
  return (
    <div className="bg-obd-surface border border-obd-border rounded-xl p-4">
      <Icon className={`w-5 h-5 ${color} mb-2`} />
      <div className="text-2xl font-bold text-white">{value}</div>
      <div className="text-[11px] uppercase tracking-wider text-slate-500">{label}</div>
    </div>
  )
}

function FilterSelect({ value, onChange, placeholder, options }: any) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="bg-obd-bg border border-obd-border rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-obd-accent"
    >
      <option value="">{placeholder}: todos</option>
      {options.map((o: string) => (
        <option key={o} value={o}>{o}</option>
      ))}
    </select>
  )
}

function ResultCard({ item }: { item: SearchResultItem }) {
  const payload = item.payload || {}
  const source = payload.source || (item.kind === 'dtc' ? 'builtin' : item.kind === 'vehicle' ? 'builtin' : 'builtin')
  const meta = sourceMeta[source] || sourceMeta.builtin
  const SourceIcon = meta.icon
  const TypeIcon = typeIcon[payload.type] || (item.kind === 'dtc' ? AlertTriangle : item.kind === 'vehicle' ? Car : FileText)

  return (
    <div className="bg-obd-surface border border-obd-border rounded-xl p-4 hover:border-obd-accent/50 transition group cursor-pointer">
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <TypeIcon className="w-5 h-5 text-obd-accent flex-shrink-0" />
          <h3 className="text-sm font-semibold text-white truncate group-hover:text-obd-accent" title={item.title}>
            {item.title}
          </h3>
        </div>
        <div className={`flex items-center gap-1 text-[10px] ${meta.color} flex-shrink-0`}>
          <SourceIcon className="w-3 h-3" />
          {meta.label}
        </div>
      </div>

      {item.description && (
        <p className="text-xs text-slate-400 mb-3 line-clamp-2">
          {item.description}
        </p>
      )}

      <div className="flex flex-wrap gap-1">
        {(payload.make_tags || []).slice(0, 3).map((m: string) => (
          <span key={m} className="text-[10px] bg-emerald-500/10 text-emerald-400 px-2 py-0.5 rounded">
            {m}
          </span>
        ))}
        {(payload.system_tags || []).slice(0, 3).map((s: string) => (
          <span key={s} className="text-[10px] bg-blue-500/10 text-blue-400 px-2 py-0.5 rounded">
            {s}
          </span>
        ))}
        {payload.severity && (
          <span className={`text-[10px] px-2 py-0.5 rounded ${
            payload.severity === 'high' || payload.severity === 'critical'
              ? 'bg-red-500/10 text-red-400'
              : 'bg-amber-500/10 text-amber-400'
          }`}>
            {payload.severity}
          </span>
        )}
        {payload.size_bytes > 0 && (
          <span className="text-[10px] text-slate-500 ml-auto">
            {formatBytes(payload.size_bytes)}
          </span>
        )}
      </div>
    </div>
  )
}
