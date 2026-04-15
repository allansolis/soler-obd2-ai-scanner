import { useEffect, useMemo, useState } from 'react'
import {
  Brain,
  Wrench,
  Cpu,
  KeyRound,
  AlertTriangle,
  Search,
  Loader2,
  Sparkles,
  CheckCircle2,
  GitCompare,
  ListChecks,
  ShieldAlert,
  ChevronRight,
  BookOpen,
  FileText,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Tipos
// ---------------------------------------------------------------------------

type ScenarioKey = 'dtc' | 'tuning' | 'programming'

type ToolListItem = {
  id: string
  name: string
  category: string
  publisher: string
  license: string
  learning_curve: string
}

type Recommendation = {
  tool_id: string
  name: string
  category: string
  score: number
  reason_es: string
  confidence: 'alta' | 'media' | 'baja'
  workflow_summary: string
  license: string
  learning_curve: string
  alternatives: string[]
}

type WorkflowStep = { step: number; title: string; detail: string }

type Workflow = {
  tool_id: string
  tool_name: string
  task: string
  estimated_time_min: number
  difficulty: string
  steps: WorkflowStep[]
  required_hardware: string[]
  safety_notes: string[]
}

type EvidencePdf = {
  pdf: string
  title: string
  category: string
  system: string
  pages: number
  why?: string
}

type EvidencePayload = {
  available: boolean
  tool_id?: string
  dtc?: string | null
  pdfs: EvidencePdf[]
  dtc_pdfs: EvidencePdf[]
  message?: string
}

type ComparisonRow = { feature: string; values: Record<string, string> }
type ComparisonMatrix = {
  tool_ids: string[]
  tool_names: Record<string, string>
  rows: ComparisonRow[]
}

const API = ''

// ---------------------------------------------------------------------------
// Componente
// ---------------------------------------------------------------------------

export default function ExpertMode() {
  const [tab, setTab] = useState<'asesor' | 'comparador' | 'biblioteca'>('asesor')

  // Form de asesoria
  const [scenario, setScenario] = useState<ScenarioKey>('dtc')
  const [dtc, setDtc] = useState('')
  const [make, setMake] = useState('')
  const [model, setModel] = useState('')
  const [year, setYear] = useState<string>('')
  const [goal, setGoal] = useState('')
  const [task, setTask] = useState('key_programming')

  const [loading, setLoading] = useState(false)
  const [recs, setRecs] = useState<Recommendation[]>([])
  const [error, setError] = useState<string | null>(null)
  const [activeWorkflow, setActiveWorkflow] = useState<Workflow | null>(null)

  // Biblioteca / comparador
  const [tools, setTools] = useState<ToolListItem[]>([])
  const [search, setSearch] = useState('')
  const [selectedForCompare, setSelectedForCompare] = useState<string[]>([])
  const [comparison, setComparison] = useState<ComparisonMatrix | null>(null)
  const [activeProfile, setActiveProfile] = useState<any>(null)

  // Evidencia (per-tool)
  const [evidence, setEvidence] = useState<Record<string, EvidencePayload>>({})
  const [evidenceOpen, setEvidenceOpen] = useState<string | null>(null)
  const [evidenceLoading, setEvidenceLoading] = useState<string | null>(null)

  // ---- carga inicial ----
  useEffect(() => {
    fetch(`${API}/api/expert/tools`)
      .then((r) => r.json())
      .then((d) => setTools(d.tools || []))
      .catch(() => setTools([]))
  }, [])

  const filteredTools = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return tools
    return tools.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        t.category.toLowerCase().includes(q) ||
        t.publisher.toLowerCase().includes(q),
    )
  }, [tools, search])

  // ---- handlers ----

  const handleAdvise = async () => {
    setLoading(true)
    setError(null)
    setActiveWorkflow(null)
    try {
      const body: any = { scenario }
      if (scenario === 'dtc') body.dtc = dtc
      body.make = make || undefined
      body.model = model || undefined
      body.year = year ? Number(year) : undefined
      if (scenario === 'tuning') body.goal = goal || 'stage1'
      if (scenario === 'programming') body.task = task

      const res = await fetch(`${API}/api/expert/advise`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Error')
      setRecs(data.recommendations || [])
    } catch (e: any) {
      setError(e.message)
      setRecs([])
    } finally {
      setLoading(false)
    }
  }

  const loadWorkflow = async (toolId: string) => {
    const taskLabel =
      scenario === 'dtc' ? `dtc-${dtc || 'generic'}` : scenario === 'tuning' ? `tuning-${goal || 'stage1'}` : task
    const res = await fetch(`${API}/api/expert/workflow/${toolId}/${encodeURIComponent(taskLabel)}`)
    if (res.ok) setActiveWorkflow(await res.json())
  }

  const toggleCompare = (id: string) => {
    setSelectedForCompare((sel) =>
      sel.includes(id) ? sel.filter((x) => x !== id) : sel.length >= 5 ? sel : [...sel, id],
    )
  }

  const runComparison = async () => {
    if (selectedForCompare.length < 2) return
    const res = await fetch(`${API}/api/expert/compare`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool_ids: selectedForCompare }),
    })
    setComparison(await res.json())
  }

  const openProfile = async (id: string) => {
    const res = await fetch(`${API}/api/expert/tool/${id}`)
    if (res.ok) setActiveProfile(await res.json())
  }

  const loadEvidence = async (toolId: string) => {
    if (evidenceOpen === toolId) {
      setEvidenceOpen(null)
      return
    }
    setEvidenceOpen(toolId)
    if (evidence[toolId]) return // ya cacheada
    setEvidenceLoading(toolId)
    try {
      const qs = scenario === 'dtc' && dtc ? `?dtc=${encodeURIComponent(dtc)}` : ''
      const res = await fetch(`${API}/api/expert/evidence/tool/${toolId}${qs}`)
      const data: EvidencePayload = await res.json()
      setEvidence((prev) => ({ ...prev, [toolId]: data }))
    } catch {
      setEvidence((prev) => ({
        ...prev,
        [toolId]: { available: false, pdfs: [], dtc_pdfs: [], message: 'Error de red' },
      }))
    } finally {
      setEvidenceLoading(null)
    }
  }

  // ---- UI ----

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center">
            <Brain className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">Modo Experto</h1>
            <p className="text-sm text-slate-400">
              Asesor inteligente de herramientas automotrices - {tools.length} perfiles cargados
            </p>
          </div>
        </div>
      </header>

      {/* Tabs */}
      <div className="flex gap-2 border-b border-obd-border">
        {(
          [
            { key: 'asesor', label: 'Asesor', icon: Sparkles },
            { key: 'comparador', label: 'Comparador', icon: GitCompare },
            { key: 'biblioteca', label: 'Biblioteca', icon: BookOpen },
          ] as const
        ).map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition ${
              tab === key
                ? 'border-purple-500 text-purple-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      {/* TAB: ASESOR */}
      {tab === 'asesor' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Formulario */}
          <div className="lg:col-span-1 space-y-4 bg-obd-surface border border-obd-border rounded-2xl p-5">
            <h2 className="font-semibold text-white flex items-center gap-2">
              <Wrench className="w-4 h-4" /> Describe el problema
            </h2>

            <div className="grid grid-cols-3 gap-2">
              {(
                [
                  { key: 'dtc', label: 'DTC', icon: AlertTriangle },
                  { key: 'tuning', label: 'Tuning', icon: Cpu },
                  { key: 'programming', label: 'Llaves', icon: KeyRound },
                ] as const
              ).map(({ key, label, icon: Icon }) => (
                <button
                  key={key}
                  onClick={() => setScenario(key)}
                  className={`flex flex-col items-center gap-1 p-3 rounded-xl text-xs font-medium transition ${
                    scenario === key
                      ? 'bg-purple-500/20 text-purple-300 border border-purple-500/40'
                      : 'bg-white/5 text-slate-400 border border-transparent hover:bg-white/10'
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  {label}
                </button>
              ))}
            </div>

            {scenario === 'dtc' && (
              <Field label="Codigo DTC">
                <input
                  value={dtc}
                  onChange={(e) => setDtc(e.target.value.toUpperCase())}
                  placeholder="P0420, P0171, B1000..."
                  className="input"
                />
              </Field>
            )}

            <Field label="Marca">
              <input value={make} onChange={(e) => setMake(e.target.value)} placeholder="Hyundai, BMW, Toyota..." className="input" />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Modelo">
                <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="Tucson, X5, Hilux" className="input" />
              </Field>
              <Field label="Anio">
                <input value={year} onChange={(e) => setYear(e.target.value)} placeholder="2018" className="input" />
              </Field>
            </div>

            {scenario === 'tuning' && (
              <Field label="Objetivo de tuning">
                <input
                  value={goal}
                  onChange={(e) => setGoal(e.target.value)}
                  placeholder="stage1, dpf-off, e85, bench, boot..."
                  className="input"
                />
              </Field>
            )}

            {scenario === 'programming' && (
              <Field label="Tarea">
                <select value={task} onChange={(e) => setTask(e.target.value)} className="input">
                  <option value="key_programming">Programar llave</option>
                  <option value="immo_pin">Calculo PIN inmovilizador</option>
                  <option value="module_replace">Reemplazo de modulo</option>
                  <option value="ecu_clone">Clonacion de ECU</option>
                </select>
              </Field>
            )}

            <button
              onClick={handleAdvise}
              disabled={loading || (scenario === 'dtc' && !dtc) || (scenario !== 'dtc' && !make)}
              className="w-full mt-2 py-3 rounded-xl bg-gradient-to-r from-purple-500 to-pink-500 text-white font-medium disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
              Recomendar herramientas
            </button>

            {error && <p className="text-sm text-red-400">{error}</p>}
          </div>

          {/* Recomendaciones */}
          <div className="lg:col-span-2 space-y-3">
            {recs.length === 0 && !loading && (
              <div className="bg-obd-surface border border-obd-border rounded-2xl p-10 text-center text-slate-500">
                Describe un escenario para obtener recomendaciones expertas.
              </div>
            )}

            {recs.map((r) => (
              <div key={r.tool_id} className="bg-obd-surface border border-obd-border rounded-2xl p-5 space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="font-semibold text-white text-lg">{r.name}</h3>
                      <span
                        className={`text-[10px] uppercase font-bold px-2 py-0.5 rounded ${
                          r.confidence === 'alta'
                            ? 'bg-green-500/20 text-green-400'
                            : r.confidence === 'media'
                            ? 'bg-yellow-500/20 text-yellow-400'
                            : 'bg-slate-500/20 text-slate-400'
                        }`}
                      >
                        Confianza {r.confidence}
                      </span>
                    </div>
                    <p className="text-xs text-slate-500 mt-0.5">
                      {r.category} - {r.license} - Curva: {r.learning_curve}
                    </p>
                  </div>
                  <div className="text-right">
                    <div className="text-2xl font-bold text-purple-400">{r.score.toFixed(0)}</div>
                    <div className="text-[10px] text-slate-500 uppercase">score</div>
                  </div>
                </div>

                <p className="text-sm text-slate-300">{r.reason_es}</p>

                <div className="bg-black/30 border border-obd-border rounded-xl p-3">
                  <p className="text-xs text-slate-400 mb-1 uppercase tracking-wide flex items-center gap-1">
                    <ListChecks className="w-3 h-3" /> Workflow resumido
                  </p>
                  <p className="text-sm text-slate-200">{r.workflow_summary}</p>
                </div>

                <div className="flex flex-wrap gap-2 items-center">
                  <button
                    onClick={() => loadWorkflow(r.tool_id)}
                    className="text-xs px-3 py-1.5 rounded-lg bg-purple-500/10 text-purple-300 hover:bg-purple-500/20 flex items-center gap-1"
                  >
                    Ver workflow detallado <ChevronRight className="w-3 h-3" />
                  </button>
                  <button
                    onClick={() => openProfile(r.tool_id)}
                    className="text-xs px-3 py-1.5 rounded-lg bg-white/5 text-slate-300 hover:bg-white/10"
                  >
                    Perfil completo
                  </button>
                  <button
                    onClick={() => loadEvidence(r.tool_id)}
                    className="text-xs px-3 py-1.5 rounded-lg bg-amber-500/10 text-amber-300 hover:bg-amber-500/20 flex items-center gap-1"
                  >
                    <FileText className="w-3 h-3" />
                    {evidenceOpen === r.tool_id ? 'Ocultar evidencia' : 'Evidencia en manuales'}
                  </button>
                  {r.alternatives.length > 0 && (
                    <span className="text-xs text-slate-500 ml-auto">
                      Alternativas: {r.alternatives.slice(0, 3).join(', ')}
                    </span>
                  )}
                </div>

                {evidenceOpen === r.tool_id && (
                  <EvidenceBlock
                    loading={evidenceLoading === r.tool_id}
                    data={evidence[r.tool_id]}
                  />
                )}
              </div>
            ))}

            {/* Workflow modal-card */}
            {activeWorkflow && (
              <div className="bg-gradient-to-br from-purple-500/10 to-pink-500/10 border border-purple-500/30 rounded-2xl p-5 space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold text-white">
                    Workflow: {activeWorkflow.tool_name}
                  </h3>
                  <button onClick={() => setActiveWorkflow(null)} className="text-slate-400 hover:text-white text-sm">
                    Cerrar
                  </button>
                </div>
                <p className="text-xs text-slate-400">
                  Tiempo estimado: {activeWorkflow.estimated_time_min} min - Dificultad: {activeWorkflow.difficulty}
                </p>
                <ol className="space-y-2">
                  {activeWorkflow.steps.map((s) => (
                    <li key={s.step} className="flex gap-3">
                      <span className="w-6 h-6 rounded-full bg-purple-500 text-white text-xs flex items-center justify-center flex-shrink-0">
                        {s.step}
                      </span>
                      <p className="text-sm text-slate-200">{s.detail}</p>
                    </li>
                  ))}
                </ol>
                {activeWorkflow.required_hardware.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-slate-400 uppercase">Hardware requerido</p>
                    <p className="text-sm text-slate-200">{activeWorkflow.required_hardware.join(', ')}</p>
                  </div>
                )}
                {activeWorkflow.safety_notes.length > 0 && (
                  <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-3">
                    <p className="text-xs font-semibold text-red-300 uppercase flex items-center gap-1">
                      <ShieldAlert className="w-3 h-3" /> Notas de seguridad
                    </p>
                    <ul className="list-disc ml-4 text-sm text-slate-200">
                      {activeWorkflow.safety_notes.map((n, i) => (
                        <li key={i}>{n}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* TAB: COMPARADOR */}
      {tab === 'comparador' && (
        <div className="space-y-4">
          <div className="bg-obd-surface border border-obd-border rounded-2xl p-5">
            <p className="text-sm text-slate-300 mb-3">
              Selecciona 2-5 herramientas para comparar lado a lado.
            </p>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
              {tools.map((t) => (
                <button
                  key={t.id}
                  onClick={() => toggleCompare(t.id)}
                  className={`text-left p-3 rounded-xl border text-sm transition ${
                    selectedForCompare.includes(t.id)
                      ? 'bg-purple-500/20 border-purple-500/50 text-white'
                      : 'bg-white/5 border-obd-border text-slate-300 hover:bg-white/10'
                  }`}
                >
                  <div className="font-medium truncate">{t.name}</div>
                  <div className="text-[10px] text-slate-500">{t.category}</div>
                </button>
              ))}
            </div>
            <button
              onClick={runComparison}
              disabled={selectedForCompare.length < 2}
              className="mt-4 px-5 py-2 rounded-xl bg-purple-500 text-white text-sm font-medium disabled:opacity-50"
            >
              Comparar ({selectedForCompare.length})
            </button>
          </div>

          {comparison && (
            <div className="overflow-auto bg-obd-surface border border-obd-border rounded-2xl">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-obd-border">
                    <th className="text-left p-3 text-slate-400 font-medium">Caracteristica</th>
                    {comparison.tool_ids.map((tid) => (
                      <th key={tid} className="text-left p-3 text-white">
                        {comparison.tool_names[tid]}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {comparison.rows.map((r) => (
                    <tr key={r.feature} className="border-b border-obd-border/50">
                      <td className="p-3 font-medium text-slate-300">{r.feature}</td>
                      {comparison.tool_ids.map((tid) => (
                        <td key={tid} className="p-3 text-slate-200 align-top">
                          {r.values[tid] || '-'}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* TAB: BIBLIOTECA */}
      {tab === 'biblioteca' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-1 space-y-3">
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-3 text-slate-500" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Buscar herramienta..."
                className="input pl-9"
              />
            </div>
            <div className="space-y-1 max-h-[70vh] overflow-auto">
              {filteredTools.map((t) => (
                <button
                  key={t.id}
                  onClick={() => openProfile(t.id)}
                  className="w-full text-left p-3 rounded-xl hover:bg-white/5 border border-transparent hover:border-obd-border transition"
                >
                  <div className="text-sm font-medium text-white">{t.name}</div>
                  <div className="text-[11px] text-slate-500">{t.category} - {t.publisher}</div>
                </button>
              ))}
            </div>
          </div>

          <div className="lg:col-span-2">
            {!activeProfile ? (
              <div className="bg-obd-surface border border-obd-border rounded-2xl p-10 text-center text-slate-500">
                Selecciona una herramienta para ver su perfil completo.
              </div>
            ) : (
              <ProfileCard profile={activeProfile} />
            )}
          </div>
        </div>
      )}

      <style>{`
        .input {
          width: 100%;
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 0.75rem;
          padding: 0.6rem 0.8rem;
          color: white;
          font-size: 0.875rem;
        }
        .input:focus { outline: none; border-color: rgb(168 85 247 / 0.5); }
      `}</style>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Subcomponentes
// ---------------------------------------------------------------------------

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs uppercase tracking-wide text-slate-400 font-medium">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  )
}

function ProfileCard({ profile }: { profile: any }) {
  return (
    <div className="bg-obd-surface border border-obd-border rounded-2xl p-6 space-y-4">
      <header>
        <h2 className="text-xl font-bold text-white">{profile.name}</h2>
        <p className="text-sm text-slate-400">
          {profile.publisher} - {profile.category}
        </p>
      </header>

      {profile.description_es && (
        <p className="text-sm text-slate-200 leading-relaxed">{profile.description_es}</p>
      )}

      <Section title="Marcas soportadas" items={profile.supports?.brands} />
      <Section title="Protocolos" items={profile.supports?.protocols} />
      <Section title="Funciones" items={profile.supports?.functions} />
      <Section title="Hardware requerido" items={profile.hardware_required} />
      <Section title="Casos de uso" items={profile.use_cases} />
      <Section title="Fortalezas" items={profile.strengths} positive />
      <Section title="Limitaciones" items={profile.limitations} negative />

      {profile.typical_workflow && (
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-400 font-medium mb-1">Workflow tipico</p>
          <pre className="text-xs whitespace-pre-wrap bg-black/40 p-3 rounded-xl text-slate-300">
            {profile.typical_workflow}
          </pre>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-2 text-sm">
        <Stat label="Licencia" value={profile.license} />
        <Stat label="Curva" value={profile.learning_curve} />
        <Stat label="Precio" value={profile.price_range_usd || '-'} />
        <Stat label="URL" value={profile.official_url || '-'} />
      </div>

      <Section title="Alternativas" items={profile.alternatives} />
    </div>
  )
}

function Section({
  title,
  items,
  positive,
  negative,
}: {
  title: string
  items?: string[]
  positive?: boolean
  negative?: boolean
}) {
  if (!items || items.length === 0) return null
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-slate-400 font-medium mb-1">{title}</p>
      <ul className="space-y-1">
        {items.map((it, i) => (
          <li
            key={i}
            className={`text-sm flex items-start gap-2 ${
              positive ? 'text-green-300' : negative ? 'text-orange-300' : 'text-slate-300'
            }`}
          >
            {positive && <CheckCircle2 className="w-3 h-3 mt-1 flex-shrink-0" />}
            {negative && <ShieldAlert className="w-3 h-3 mt-1 flex-shrink-0" />}
            <span>{it}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-black/30 rounded-xl p-3">
      <p className="text-[10px] uppercase text-slate-500">{label}</p>
      <p className="text-xs text-slate-200 truncate">{value}</p>
    </div>
  )
}

function EvidenceBlock({
  loading,
  data,
}: {
  loading: boolean
  data?: EvidencePayload
}) {
  if (loading) {
    return (
      <div className="bg-black/30 border border-amber-500/20 rounded-xl p-3 flex items-center gap-2 text-sm text-amber-200">
        <Loader2 className="w-4 h-4 animate-spin" /> Buscando evidencia en manuales locales...
      </div>
    )
  }
  if (!data) return null
  if (!data.available) {
    return (
      <div className="bg-black/30 border border-obd-border rounded-xl p-3 text-xs text-slate-400">
        {data.message ||
          'No hay pdf_analysis.json aun. Ejecuta `python backend/knowledge_hub/pdf_analyzer.py` para indexar los manuales.'}
      </div>
    )
  }
  const total = data.pdfs.length + data.dtc_pdfs.length
  if (total === 0) {
    return (
      <div className="bg-black/30 border border-obd-border rounded-xl p-3 text-xs text-slate-400">
        Esta herramienta aun no aparece citada en los PDFs indexados.
      </div>
    )
  }
  return (
    <div className="bg-black/30 border border-amber-500/20 rounded-xl p-3 space-y-3">
      <p className="text-xs uppercase tracking-wide text-amber-300 font-medium flex items-center gap-1">
        <FileText className="w-3 h-3" /> Evidencia en manuales locales
      </p>
      {data.pdfs.length > 0 && (
        <div>
          <p className="text-[11px] text-slate-400 mb-1">Manuales que citan la herramienta:</p>
          <ul className="space-y-1">
            {data.pdfs.map((p) => (
              <EvidenceRow key={p.pdf + 'tool'} p={p} />
            ))}
          </ul>
        </div>
      )}
      {data.dtc_pdfs.length > 0 && (
        <div>
          <p className="text-[11px] text-slate-400 mb-1">
            Manuales con el DTC {data.dtc}:
          </p>
          <ul className="space-y-1">
            {data.dtc_pdfs.map((p) => (
              <EvidenceRow key={p.pdf + 'dtc'} p={p} />
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function EvidenceRow({ p }: { p: EvidencePdf }) {
  return (
    <li className="text-xs flex items-start gap-2 text-slate-200">
      <FileText className="w-3 h-3 mt-0.5 text-amber-400 flex-shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{p.title}</div>
        <div className="text-[10px] text-slate-500 truncate">
          {p.pdf} - {p.pages} pag - {p.system} - {p.category}
        </div>
        {p.why && <div className="text-[10px] text-amber-300/80">{p.why}</div>}
      </div>
    </li>
  )
}
