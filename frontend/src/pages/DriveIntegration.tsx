import { useEffect, useRef, useState } from 'react'
import {
  HardDrive,
  CheckCircle2,
  XCircle,
  Search,
  FolderOpen,
  FileText,
  Archive,
  Video,
  Image as ImageIcon,
  RefreshCw,
  Play,
  Square,
  Database,
  Loader2,
  LogOut,
  Cpu,
} from 'lucide-react'

type DriveFile = {
  file_id: string
  name: string
  mime_type: string
  size: number
  path: string
  category: string
  tags: string[]
  vehicle_tags: string[]
  preview_text: string
  automotive_score: number
}

type DriveStats = {
  total_files: number
  automotive_files: number
  total_size_bytes: number
  total_size_human: string
  pdf_count: number
  archive_count: number
  video_count: number
  image_count: number
  document_count: number
  categories: Record<string, number>
  indexed_at: string | null
  errors: number
}

type DriveStatus = {
  connected: boolean
  token_exists: boolean
  credentials_configured: boolean
  indexing: boolean
  stats: DriveStats
}

type Progress = {
  files_indexed: number
  total_estimated: number
  current_file: string
  current_path: string
  percent: number
  elapsed_seconds: number
  eta_seconds: number | null
  phase: string
}

const API = ''

function mimeIcon(mime: string) {
  if (mime === 'application/pdf') return FileText
  if (mime.startsWith('video/')) return Video
  if (mime.startsWith('image/')) return ImageIcon
  if (mime.includes('folder')) return FolderOpen
  if (mime.includes('zip') || mime.includes('rar') || mime.includes('7z'))
    return Archive
  return FileText
}

function categoryLabel(cat: string): string {
  const map: Record<string, string> = {
    workshop_manual: 'Manual de Taller',
    wiring_diagram: 'Diagrama Electrico',
    ecu_pinout: 'Pinout ECU',
    dtc_database: 'Base DTC',
    tuning_map: 'Mapa de Tuning',
    winols_damos: 'WinOLS / DAMOS',
    software_tool: 'Software',
    video_course: 'Curso en Video',
    technical_bulletin: 'Boletin Tecnico',
    miscellaneous: 'Varios',
  }
  return map[cat] ?? cat
}

export default function DriveIntegration() {
  const [status, setStatus] = useState<DriveStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [authBusy, setAuthBusy] = useState(false)
  const [query, setQuery] = useState('')
  const [fileType, setFileType] = useState('')
  const [make, setMake] = useState('')
  const [results, setResults] = useState<DriveFile[]>([])
  const [searching, setSearching] = useState(false)
  const [progress, setProgress] = useState<Progress | null>(null)
  const [selected, setSelected] = useState<DriveFile | null>(null)
  const [error, setError] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  const loadStatus = async () => {
    setLoading(true)
    try {
      const r = await fetch(`${API}/api/drive/status`)
      if (r.ok) setStatus(await r.json())
    } catch (e) {
      setError(`No se pudo obtener estado: ${e}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadStatus()
  }, [])

  // WebSocket for indexing progress
  useEffect(() => {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${proto}//${window.location.host}/api/drive/ws/progress`)
    wsRef.current = ws
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data)
        if (data.phase && data.phase !== 'idle') {
          setProgress(data)
          if (data.phase === 'done') {
            setTimeout(() => {
              setProgress(null)
              loadStatus()
            }, 1500)
          }
        }
      } catch {
        /* ignore */
      }
    }
    ws.onerror = () => {
      /* best-effort */
    }
    return () => {
      ws.close()
    }
  }, [])

  const handleConnect = async () => {
    setAuthBusy(true)
    setError(null)
    try {
      const r = await fetch(`${API}/api/drive/auth`, { method: 'POST' })
      const data = await r.json()
      if (!r.ok) throw new Error(data.detail ?? 'Error de autenticacion')
      await loadStatus()
    } catch (e: any) {
      setError(e.message ?? String(e))
    } finally {
      setAuthBusy(false)
    }
  }

  const handleDisconnect = async () => {
    setAuthBusy(true)
    try {
      await fetch(`${API}/api/drive/logout`, { method: 'POST' })
      await loadStatus()
    } finally {
      setAuthBusy(false)
    }
  }

  const handleStartIndex = async () => {
    setError(null)
    try {
      const r = await fetch(`${API}/api/drive/index`, { method: 'POST' })
      if (!r.ok) {
        const data = await r.json()
        throw new Error(data.detail ?? 'Error iniciando indexacion')
      }
      setProgress({
        files_indexed: 0,
        total_estimated: 0,
        current_file: '',
        current_path: '',
        percent: 0,
        elapsed_seconds: 0,
        eta_seconds: null,
        phase: 'starting',
      })
      await loadStatus()
    } catch (e: any) {
      setError(e.message ?? String(e))
    }
  }

  const handleIncremental = async () => {
    try {
      await fetch(`${API}/api/drive/index/incremental`, { method: 'POST' })
    } catch {
      /* ignore */
    }
  }

  const handleCancel = async () => {
    try {
      await fetch(`${API}/api/drive/index/cancel`, { method: 'POST' })
    } catch {
      /* ignore */
    }
  }

  const handleSearch = async (e?: React.FormEvent) => {
    e?.preventDefault()
    if (!query.trim()) return
    setSearching(true)
    setError(null)
    try {
      const params = new URLSearchParams({ q: query, limit: '50' })
      if (fileType) params.set('type', fileType)
      if (make) params.set('make', make)
      const r = await fetch(`${API}/api/drive/search?${params}`)
      const data = await r.json()
      if (!r.ok) throw new Error(data.detail ?? 'Error buscando')
      setResults(data.results ?? [])
    } catch (e: any) {
      setError(e.message ?? String(e))
      setResults([])
    } finally {
      setSearching(false)
    }
  }

  const connected = status?.connected ?? false
  const stats = status?.stats
  const indexing = status?.indexing || progress !== null

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-obd-accent to-obd-purple flex items-center justify-center shadow-lg">
            <HardDrive className="w-7 h-7 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">Google Drive Knowledge Base</h1>
            <p className="text-sm text-slate-400">
              Tu Drive de 2TB como cerebro del AI Copilot
            </p>
          </div>
        </div>
        <button
          onClick={loadStatus}
          disabled={loading}
          className="p-3 rounded-xl bg-white/5 hover:bg-white/10 text-slate-300 transition"
          title="Recargar estado"
        >
          <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-sm">
          {error}
        </div>
      )}

      {/* Connection Card */}
      <div className="p-6 rounded-2xl bg-obd-surface border border-obd-border">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            {connected ? (
              <CheckCircle2 className="w-8 h-8 text-obd-green" />
            ) : (
              <XCircle className="w-8 h-8 text-slate-500" />
            )}
            <div>
              <h2 className="text-lg font-semibold text-white">
                {connected ? 'Conectado a Google Drive' : 'No conectado'}
              </h2>
              <p className="text-sm text-slate-400">
                {connected
                  ? 'El AI Copilot puede consultar todo tu Drive'
                  : status?.credentials_configured
                  ? 'Credenciales listas. Haz clic para conectar.'
                  : 'Necesitas configurar credenciales primero (ver guia)'}
              </p>
            </div>
          </div>
          {!connected ? (
            <button
              onClick={handleConnect}
              disabled={authBusy}
              className="px-6 py-3 rounded-xl bg-gradient-to-r from-obd-accent to-obd-purple text-white font-semibold hover:opacity-90 disabled:opacity-50 transition flex items-center gap-2"
            >
              {authBusy ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <HardDrive className="w-5 h-5" />
              )}
              Conectar Google Drive
            </button>
          ) : (
            <button
              onClick={handleDisconnect}
              disabled={authBusy}
              className="px-4 py-2 rounded-xl bg-white/5 hover:bg-red-500/20 text-slate-300 hover:text-red-300 transition flex items-center gap-2"
            >
              <LogOut className="w-4 h-4" />
              Desconectar
            </button>
          )}
        </div>
      </div>

      {/* Stats */}
      {stats && stats.total_files > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard
            icon={Database}
            label="Archivos totales"
            value={stats.total_files.toLocaleString()}
            tint="blue"
          />
          <StatCard
            icon={Cpu}
            label="Automotrices"
            value={stats.automotive_files.toLocaleString()}
            tint="purple"
          />
          <StatCard
            icon={HardDrive}
            label="Tamaño total"
            value={stats.total_size_human}
            tint="green"
          />
          <StatCard
            icon={FileText}
            label="PDFs"
            value={stats.pdf_count.toLocaleString()}
            tint="orange"
          />
        </div>
      )}

      {/* Categories breakdown */}
      {stats && Object.keys(stats.categories ?? {}).length > 0 && (
        <div className="p-5 rounded-2xl bg-obd-surface border border-obd-border">
          <h3 className="text-sm font-semibold text-slate-300 mb-3 uppercase tracking-wide">
            Categorias detectadas
          </h3>
          <div className="flex flex-wrap gap-2">
            {Object.entries(stats.categories)
              .sort((a, b) => b[1] - a[1])
              .map(([cat, n]) => (
                <span
                  key={cat}
                  className="px-3 py-1.5 rounded-lg bg-white/5 text-sm text-slate-300 border border-white/5"
                >
                  {categoryLabel(cat)}{' '}
                  <span className="text-obd-accent font-semibold ml-1">{n}</span>
                </span>
              ))}
          </div>
        </div>
      )}

      {/* Indexing controls */}
      {connected && (
        <div className="p-6 rounded-2xl bg-obd-surface border border-obd-border space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold text-white">Indexacion</h3>
            <div className="flex gap-2">
              {!indexing ? (
                <>
                  <button
                    onClick={handleIncremental}
                    className="px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-slate-300 transition flex items-center gap-2"
                  >
                    <RefreshCw className="w-4 h-4" />
                    Actualizar
                  </button>
                  <button
                    onClick={handleStartIndex}
                    className="px-4 py-2 rounded-xl bg-obd-accent/20 hover:bg-obd-accent/30 text-obd-accent border border-obd-accent/30 transition flex items-center gap-2 font-semibold"
                  >
                    <Play className="w-4 h-4" />
                    Indexar ahora
                  </button>
                </>
              ) : (
                <button
                  onClick={handleCancel}
                  className="px-4 py-2 rounded-xl bg-red-500/20 hover:bg-red-500/30 text-red-300 border border-red-500/30 transition flex items-center gap-2"
                >
                  <Square className="w-4 h-4" />
                  Cancelar
                </button>
              )}
            </div>
          </div>

          {progress && (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs text-slate-400">
                <span className="uppercase tracking-wide">
                  Fase: {progress.phase}
                </span>
                <span>
                  {progress.files_indexed.toLocaleString()} /{' '}
                  {progress.total_estimated.toLocaleString()} (
                  {progress.percent.toFixed(1)}%)
                </span>
              </div>
              <div className="h-2 w-full rounded-full bg-white/5 overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-obd-accent to-obd-purple transition-all"
                  style={{ width: `${Math.min(100, progress.percent)}%` }}
                />
              </div>
              {progress.current_file && (
                <p className="text-xs text-slate-500 truncate">
                  {progress.current_path || progress.current_file}
                </p>
              )}
              {progress.eta_seconds !== null && (
                <p className="text-xs text-slate-500">
                  ETA: {Math.round(progress.eta_seconds / 60)} min
                </p>
              )}
            </div>
          )}

          {stats?.indexed_at && !progress && (
            <p className="text-xs text-slate-500">
              Ultima indexacion: {new Date(stats.indexed_at).toLocaleString()}
            </p>
          )}
        </div>
      )}

      {/* Search */}
      {connected && stats && stats.total_files > 0 && (
        <div className="p-6 rounded-2xl bg-obd-surface border border-obd-border">
          <h3 className="text-lg font-semibold text-white mb-4">Buscar en el Drive</h3>
          <form onSubmit={handleSearch} className="space-y-3">
            <div className="relative">
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-500" />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder='Ej: "P0420 Mercedes", "winols maps", "wiring diagram Toyota"'
                className="w-full pl-12 pr-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white placeholder:text-slate-500 focus:outline-none focus:border-obd-accent/50"
              />
            </div>
            <div className="grid grid-cols-3 gap-3">
              <input
                type="text"
                value={fileType}
                onChange={(e) => setFileType(e.target.value)}
                placeholder="Tipo (pdf, rar...)"
                className="px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-white text-sm placeholder:text-slate-500"
              />
              <input
                type="text"
                value={make}
                onChange={(e) => setMake(e.target.value)}
                placeholder="Marca (bmw, mercedes...)"
                className="px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-white text-sm placeholder:text-slate-500"
              />
              <button
                type="submit"
                disabled={searching || !query.trim()}
                className="px-4 py-2 rounded-lg bg-obd-accent/20 hover:bg-obd-accent/30 text-obd-accent border border-obd-accent/30 disabled:opacity-50 transition flex items-center justify-center gap-2 font-semibold"
              >
                {searching ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Search className="w-4 h-4" />
                )}
                Buscar
              </button>
            </div>
          </form>

          {results.length > 0 && (
            <div className="mt-5 space-y-2 max-h-[520px] overflow-auto pr-2">
              {results.map((f) => {
                const Icon = mimeIcon(f.mime_type)
                return (
                  <button
                    key={f.file_id}
                    onClick={() => setSelected(f)}
                    className="w-full text-left p-3 rounded-xl bg-white/[0.03] hover:bg-white/5 border border-white/5 hover:border-obd-accent/30 transition flex items-start gap-3"
                  >
                    <Icon className="w-5 h-5 text-obd-accent flex-shrink-0 mt-0.5" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-white truncate">
                          {f.name}
                        </span>
                        <span className="px-2 py-0.5 rounded text-[10px] bg-obd-accent/10 text-obd-accent border border-obd-accent/20 flex-shrink-0">
                          {categoryLabel(f.category)}
                        </span>
                      </div>
                      <p className="text-xs text-slate-500 truncate mt-0.5">{f.path}</p>
                      {f.vehicle_tags.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1">
                          {f.vehicle_tags.slice(0, 6).map((t) => (
                            <span
                              key={t}
                              className="px-1.5 py-0.5 rounded text-[10px] bg-white/5 text-slate-400"
                            >
                              {t}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    <span className="text-xs text-slate-500 flex-shrink-0">
                      {(f.size / 1024 / 1024).toFixed(1)} MB
                    </span>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* Preview modal */}
      {selected && (
        <div
          className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4"
          onClick={() => setSelected(null)}
        >
          <div
            className="max-w-2xl w-full max-h-[80vh] overflow-auto bg-obd-surface border border-obd-border rounded-2xl p-6 space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-lg font-semibold text-white">{selected.name}</h3>
                <p className="text-xs text-slate-500 mt-1">{selected.path}</p>
              </div>
              <button
                onClick={() => setSelected(null)}
                className="text-slate-500 hover:text-white"
              >
                <XCircle className="w-6 h-6" />
              </button>
            </div>

            <div className="grid grid-cols-2 gap-3 text-sm">
              <InfoLine label="Categoria" value={categoryLabel(selected.category)} />
              <InfoLine
                label="Tamaño"
                value={`${(selected.size / 1024 / 1024).toFixed(2)} MB`}
              />
              <InfoLine label="Tipo" value={selected.mime_type} />
              <InfoLine
                label="Score"
                value={`${(selected.automotive_score * 100).toFixed(0)}%`}
              />
            </div>

            {selected.vehicle_tags.length > 0 && (
              <div>
                <p className="text-xs text-slate-400 mb-1 uppercase tracking-wide">
                  Tags
                </p>
                <div className="flex flex-wrap gap-1">
                  {selected.vehicle_tags.map((t) => (
                    <span
                      key={t}
                      className="px-2 py-0.5 rounded text-xs bg-white/5 text-slate-300"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {selected.preview_text && (
              <div>
                <p className="text-xs text-slate-400 mb-2 uppercase tracking-wide">
                  Preview
                </p>
                <div className="p-3 rounded-lg bg-black/30 border border-white/5 text-xs text-slate-300 whitespace-pre-wrap max-h-64 overflow-auto">
                  {selected.preview_text}
                </div>
              </div>
            )}

            <div className="flex gap-2 pt-2">
              <a
                href={`${API}/api/drive/files/${selected.file_id}/content`}
                target="_blank"
                rel="noreferrer"
                className="flex-1 px-4 py-2 rounded-xl bg-obd-accent/20 hover:bg-obd-accent/30 text-obd-accent border border-obd-accent/30 text-center text-sm font-semibold transition"
              >
                Descargar archivo
              </a>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function StatCard({
  icon: Icon,
  label,
  value,
  tint,
}: {
  icon: any
  label: string
  value: string
  tint: 'blue' | 'purple' | 'green' | 'orange'
}) {
  const tints: Record<string, string> = {
    blue: 'from-blue-500/20 to-blue-500/5 text-blue-300',
    purple: 'from-purple-500/20 to-purple-500/5 text-purple-300',
    green: 'from-emerald-500/20 to-emerald-500/5 text-emerald-300',
    orange: 'from-orange-500/20 to-orange-500/5 text-orange-300',
  }
  return (
    <div
      className={`p-5 rounded-2xl bg-gradient-to-br ${tints[tint]} border border-white/5`}
    >
      <div className="flex items-center gap-3 mb-2">
        <Icon className="w-5 h-5" />
        <span className="text-xs uppercase tracking-wide opacity-80">{label}</span>
      </div>
      <div className="text-2xl font-bold text-white">{value}</div>
    </div>
  )
}

function InfoLine({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-slate-500 uppercase tracking-wide">{label}</p>
      <p className="text-sm text-white truncate">{value}</p>
    </div>
  )
}
