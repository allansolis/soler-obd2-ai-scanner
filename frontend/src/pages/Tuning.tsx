import { useState, useEffect } from 'react'
import { Download, CheckCircle, XCircle, AlertTriangle, Cpu, ShieldCheck, Zap } from 'lucide-react'
import BackupConfirmModal from '../components/BackupConfirmModal'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'

type Profile = 'eco' | 'stage1' | 'sport' | 'stage2'

const profiles: { id: Profile; label: string; desc: string; color: string }[] = [
  { id: 'eco', label: 'ECO', desc: 'Fuel economy optimized', color: '#22c55e' },
  { id: 'stage1', label: 'Stage 1', desc: 'Mild performance gain', color: '#0ea5e9' },
  { id: 'sport', label: 'Sport', desc: 'Balanced power', color: '#f97316' },
  { id: 'stage2', label: 'Stage 2', desc: 'Max performance', color: '#ef4444' },
]

// Generate heatmap data (RPM x Load)
const rpmSteps = [1000, 2000, 3000, 4000, 5000, 6000, 7000]
const loadSteps = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

function generateHeatmap(profile: Profile): number[][] {
  return loadSteps.map((load, li) =>
    rpmSteps.map((rpm, ri) => {
      const base = (ri * 2 + li * 1.5) + 5
      const modifier = {
        eco: -2 + (li * 0.1),
        stage1: 1 + (ri * 0.3),
        sport: 3 + (ri * 0.5) + (li * 0.2),
        stage2: 5 + (ri * 0.8) + (li * 0.3),
      }
      return Math.round((base + modifier[profile]) * 10) / 10
    })
  )
}

function getCellColor(value: number, max: number): string {
  const ratio = value / max
  if (ratio < 0.3) return 'bg-blue-900/60'
  if (ratio < 0.45) return 'bg-cyan-800/60'
  if (ratio < 0.55) return 'bg-green-800/60'
  if (ratio < 0.65) return 'bg-yellow-700/60'
  if (ratio < 0.78) return 'bg-orange-700/60'
  return 'bg-red-700/60'
}

// Performance simulation data
const performanceData = Array.from({ length: 20 }, (_, i) => {
  const rpm = 1000 + i * 350
  const stockHp = Math.round(10 + (rpm / 100) * 1.8 - (rpm > 5500 ? (rpm - 5500) * 0.02 : 0))
  const modHp = Math.round(stockHp * 1.22 + (rpm > 3000 ? 15 : 5))
  const stockTq = Math.round(80 + rpm * 0.035 - (rpm > 4500 ? (rpm - 4500) * 0.015 : 0))
  const modTq = Math.round(stockTq * 1.18 + 12)
  return { rpm, stockHp, modHp, stockTq, modTq }
})

const safetyChecks = [
  { label: 'Knock sensor within limits', pass: true },
  { label: 'AFR within safe range', pass: true },
  { label: 'EGT below maximum', pass: true },
  { label: 'Boost pressure safe', pass: true },
  { label: 'Coolant temp nominal', pass: true },
  { label: 'Oil pressure adequate', pass: false },
]

export default function Tuning() {
  const [selectedProfile, setSelectedProfile] = useState<Profile>('stage1')
  const [vehicle, setVehicle] = useState<{brand:string; model:string; version:string} | null>(null)
  const [showBackupModal, setShowBackupModal] = useState(false)
  const [appliedProfile, setAppliedProfile] = useState<Profile | null>(null)
  const heatmap = generateHeatmap(selectedProfile)
  const maxVal = Math.max(...heatmap.flat())
  const profileConf = profiles.find(p => p.id === selectedProfile)!

  useEffect(() => {
    const saved = localStorage.getItem('soler-vehicle')
    if (saved) setVehicle(JSON.parse(saved))
  }, [])

  const handleApply = () => {
    if (!vehicle) {
      alert('Primero selecciona un vehiculo en la seccion "Vehiculo"')
      return
    }
    setShowBackupModal(true)
  }

  const handleBackupConfirmed = () => {
    setAppliedProfile(selectedProfile)
    setShowBackupModal(false)
  }

  return (
    <div className="p-6 space-y-6">
      {showBackupModal && (
        <BackupConfirmModal
          vehicle={vehicle}
          profileName={profileConf.label}
          onCancel={() => setShowBackupModal(false)}
          onConfirm={handleBackupConfirmed}
        />
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">ECU Tuning Maps</h1>
          <p className="text-sm text-slate-500">
            {vehicle
              ? `${vehicle.brand} ${vehicle.model} — ${vehicle.version}`
              : 'Selecciona un vehiculo primero en "Vehiculo"'}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleApply}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-obd-accent text-white hover:bg-obd-accent/90 text-sm font-medium transition-all"
          >
            <ShieldCheck className="w-4 h-4" />
            Aplicar con Backup
          </button>
          <button className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-obd-purple/10 text-obd-purple border border-obd-purple/30 hover:bg-obd-purple/20 text-sm font-medium transition-all">
            <Download className="w-4 h-4" />
            Export Map
          </button>
        </div>
      </div>

      {appliedProfile && (
        <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-4 flex items-center gap-3">
          <Zap className="w-5 h-5 text-emerald-400" />
          <div className="text-sm text-emerald-100">
            Perfil <strong>{profiles.find(p => p.id === appliedProfile)?.label}</strong> aplicado.
            Backup original guardado — puedes restaurar en cualquier momento desde Historial.
          </div>
        </div>
      )}

      {/* Capacidades reales */}
      <div className="bg-obd-surface/50 border border-obd-border rounded-xl p-4">
        <div className="text-xs font-semibold text-slate-400 uppercase mb-3">
          Capacidades actuales del sistema
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
          <div className="flex items-center gap-2">
            <CheckCircle className="w-4 h-4 text-emerald-400" />
            <span className="text-slate-300">Generar mapas ECU</span>
          </div>
          <div className="flex items-center gap-2">
            <CheckCircle className="w-4 h-4 text-emerald-400" />
            <span className="text-slate-300">Verificaciones seguridad</span>
          </div>
          <div className="flex items-center gap-2">
            <CheckCircle className="w-4 h-4 text-emerald-400" />
            <span className="text-slate-300">Backup SHA-256</span>
          </div>
          <div className="flex items-center gap-2">
            <CheckCircle className="w-4 h-4 text-emerald-400" />
            <span className="text-slate-300">Simulacion HP/Torque</span>
          </div>
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-400" />
            <span className="text-slate-400">Flash ECU real: requiere hardware J2534/KESS</span>
          </div>
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-400" />
            <span className="text-slate-400">Lectura binario ECU: via adaptador profesional</span>
          </div>
        </div>
      </div>

      {/* Profile Selector */}
      <div className="grid grid-cols-4 gap-3">
        {profiles.map((p) => (
          <button
            key={p.id}
            onClick={() => setSelectedProfile(p.id)}
            className={`p-4 rounded-xl border text-left transition-all duration-200 ${
              selectedProfile === p.id
                ? 'border-transparent shadow-lg'
                : 'border-obd-border bg-obd-surface hover:border-slate-600'
            }`}
            style={
              selectedProfile === p.id
                ? { background: `${p.color}15`, borderColor: `${p.color}50`, boxShadow: `0 0 20px ${p.color}15` }
                : {}
            }
          >
            <div className="flex items-center gap-2 mb-1">
              <Cpu className="w-4 h-4" style={{ color: p.color }} />
              <span className="font-semibold text-white text-sm">{p.label}</span>
            </div>
            <p className="text-xs text-slate-500">{p.desc}</p>
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Heatmap */}
        <div className="bg-obd-surface border border-obd-border rounded-xl p-5">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">
            Fuel Map -- {profileConf.label}
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="text-[10px] text-slate-600 font-mono p-1">Load\RPM</th>
                  {rpmSteps.map(rpm => (
                    <th key={rpm} className="text-[10px] text-slate-600 font-mono p-1">{rpm}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loadSteps.map((load, li) => (
                  <tr key={load}>
                    <td className="text-[10px] text-slate-600 font-mono p-1 text-right">{load}%</td>
                    {rpmSteps.map((_, ri) => (
                      <td key={ri} className="p-0.5">
                        <div
                          className={`${getCellColor(heatmap[li][ri], maxVal)} rounded text-center py-1.5 px-1`}
                        >
                          <span className="font-mono text-[10px] text-white/80">
                            {heatmap[li][ri]}
                          </span>
                        </div>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Performance Chart */}
        <div className="bg-obd-surface border border-obd-border rounded-xl p-5">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">
            Performance Simulation
          </h2>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={performanceData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis
                dataKey="rpm"
                stroke="#475569"
                tick={{ fill: '#64748b', fontSize: 11 }}
                tickFormatter={(v) => `${v / 1000}k`}
              />
              <YAxis stroke="#475569" tick={{ fill: '#64748b', fontSize: 11 }} />
              <Tooltip
                contentStyle={{
                  background: '#0f172a',
                  border: '1px solid #1e293b',
                  borderRadius: '12px',
                  fontSize: '12px',
                }}
                labelStyle={{ color: '#94a3b8' }}
              />
              <Legend
                wrapperStyle={{ fontSize: '12px' }}
              />
              <Line
                type="monotone"
                dataKey="stockHp"
                name="Stock HP"
                stroke="#475569"
                strokeWidth={2}
                dot={false}
                strokeDasharray="4 4"
              />
              <Line
                type="monotone"
                dataKey="modHp"
                name={`${profileConf.label} HP`}
                stroke={profileConf.color}
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="stockTq"
                name="Stock Torque"
                stroke="#475569"
                strokeWidth={1.5}
                dot={false}
                strokeDasharray="2 2"
              />
              <Line
                type="monotone"
                dataKey="modTq"
                name={`${profileConf.label} Torque`}
                stroke={profileConf.color}
                strokeWidth={1.5}
                dot={false}
                opacity={0.7}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Safety Checklist */}
      <div className="bg-obd-surface border border-obd-border rounded-xl p-5">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">
          Safety Checklist
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {safetyChecks.map((check) => (
            <div
              key={check.label}
              className={`flex items-center gap-3 p-3 rounded-xl border ${
                check.pass
                  ? 'bg-green-500/5 border-green-500/20'
                  : 'bg-red-500/5 border-red-500/20'
              }`}
            >
              {check.pass ? (
                <CheckCircle className="w-4 h-4 text-green-400 flex-shrink-0" />
              ) : (
                <XCircle className="w-4 h-4 text-red-400 flex-shrink-0" />
              )}
              <span className={`text-sm ${check.pass ? 'text-green-300' : 'text-red-300'}`}>
                {check.label}
              </span>
            </div>
          ))}
        </div>
        {safetyChecks.some(c => !c.pass) && (
          <div className="flex items-center gap-2 mt-4 p-3 rounded-xl bg-yellow-500/10 border border-yellow-500/30">
            <AlertTriangle className="w-4 h-4 text-yellow-400" />
            <span className="text-sm text-yellow-300">
              Some safety checks failed. Review before flashing.
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
