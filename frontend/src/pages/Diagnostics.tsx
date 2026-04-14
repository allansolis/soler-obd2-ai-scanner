import { useState } from 'react'
import {
  AlertTriangle,
  Trash2,
  RefreshCw,
  Bot,
  ShieldCheck,
  ShieldAlert,
} from 'lucide-react'
import DTCCard from '../components/DTCCard'
import type { DTCData } from '../components/DTCCard'

const MOCK_DTCS: DTCData[] = [
  {
    code: 'P0300',
    description: 'Random/Multiple Cylinder Misfire Detected',
    severity: 'critical',
    probable_causes: [
      'Worn or fouled spark plugs',
      'Faulty ignition coils',
      'Vacuum leak in intake manifold',
      'Low fuel pressure',
    ],
    corrective_actions: [
      'Inspect and replace spark plugs if worn',
      'Test ignition coils with multimeter',
      'Check intake manifold gaskets for leaks',
      'Test fuel pressure at the rail',
    ],
    freeze_frame: {
      RPM: '2450',
      Speed: '65 km/h',
      'Engine Load': '72%',
      'Coolant Temp': '92\u00B0C',
      'Fuel Trim': '+8.5%',
    },
  },
  {
    code: 'P0171',
    description: 'System Too Lean (Bank 1)',
    severity: 'high',
    probable_causes: [
      'Vacuum leak',
      'Faulty MAF sensor',
      'Weak fuel pump',
      'Clogged fuel injectors',
    ],
    corrective_actions: [
      'Smoke test for vacuum leaks',
      'Clean or replace MAF sensor',
      'Check fuel pump pressure output',
      'Run fuel injector cleaning service',
    ],
    freeze_frame: {
      RPM: '1800',
      'Fuel Trim': '+18.2%',
      MAF: '4.2 g/s',
      O2: '0.12V',
    },
  },
  {
    code: 'P0420',
    description: 'Catalyst System Efficiency Below Threshold (Bank 1)',
    severity: 'medium',
    probable_causes: [
      'Aging catalytic converter',
      'Exhaust leak before catalyst',
      'Faulty downstream O2 sensor',
    ],
    corrective_actions: [
      'Inspect catalytic converter for damage',
      'Check for exhaust leaks',
      'Compare upstream and downstream O2 sensor readings',
    ],
  },
  {
    code: 'P0456',
    description: 'Evaporative Emission System Leak Detected (very small leak)',
    severity: 'low',
    probable_causes: [
      'Loose or cracked gas cap',
      'Small leak in EVAP hose',
      'Faulty purge valve',
    ],
    corrective_actions: [
      'Inspect and tighten gas cap',
      'Check EVAP system hoses',
      'Test purge valve operation',
    ],
  },
]

const AI_SUMMARY = `Based on the active DTCs, I've identified a pattern suggesting potential intake/fuel system issues. The P0300 (misfire) combined with P0171 (lean condition) indicates the engine may not be receiving adequate fuel mixture. Priority recommendation: Start with a smoke test for vacuum leaks, then inspect the MAF sensor. The P0420 catalyst code may be secondary to the lean running condition.`

export default function Diagnostics() {
  const [dtcs] = useState<DTCData[]>(MOCK_DTCS)
  const [showClearConfirm, setShowClearConfirm] = useState(false)
  const [scanning, setScanning] = useState(false)

  const handleScan = () => {
    setScanning(true)
    setTimeout(() => setScanning(false), 2000)
  }

  const criticalCount = dtcs.filter(d => d.severity === 'critical').length
  const highCount = dtcs.filter(d => d.severity === 'high').length

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Diagnostics</h1>
          <p className="text-sm text-slate-500">
            {dtcs.length} active DTC{dtcs.length !== 1 ? 's' : ''} detected
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={handleScan}
            disabled={scanning}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-obd-accent/10 text-obd-accent border border-obd-accent/30 hover:bg-obd-accent/20 text-sm font-medium transition-all disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${scanning ? 'animate-spin' : ''}`} />
            {scanning ? 'Scanning...' : 'Scan DTCs'}
          </button>
          <button
            onClick={() => setShowClearConfirm(true)}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-red-500/10 text-red-400 border border-red-500/30 hover:bg-red-500/20 text-sm font-medium transition-all"
          >
            <Trash2 className="w-4 h-4" />
            Clear DTCs
          </button>
        </div>
      </div>

      {/* Summary badges */}
      <div className="flex gap-3">
        {criticalCount > 0 && (
          <div className="flex items-center gap-2 bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-2">
            <ShieldAlert className="w-4 h-4 text-red-400" />
            <span className="text-sm text-red-400 font-medium">
              {criticalCount} Critical
            </span>
          </div>
        )}
        {highCount > 0 && (
          <div className="flex items-center gap-2 bg-orange-500/10 border border-orange-500/30 rounded-xl px-4 py-2">
            <AlertTriangle className="w-4 h-4 text-orange-400" />
            <span className="text-sm text-orange-400 font-medium">
              {highCount} High
            </span>
          </div>
        )}
        <div className="flex items-center gap-2 bg-green-500/10 border border-green-500/30 rounded-xl px-4 py-2">
          <ShieldCheck className="w-4 h-4 text-green-400" />
          <span className="text-sm text-green-400 font-medium">
            {dtcs.length - criticalCount - highCount} Other
          </span>
        </div>
      </div>

      {/* AI Diagnosis Panel */}
      <div className="bg-gradient-to-br from-obd-purple/10 to-obd-accent/10 border border-obd-purple/30 rounded-xl p-5">
        <div className="flex items-center gap-2 mb-3">
          <Bot className="w-5 h-5 text-obd-purple" />
          <h2 className="text-sm font-semibold text-obd-purple uppercase tracking-wider">
            AI Diagnosis Summary
          </h2>
        </div>
        <p className="text-sm text-slate-300 leading-relaxed">{AI_SUMMARY}</p>
      </div>

      {/* DTC List */}
      <div className="space-y-3">
        {dtcs.map((dtc) => (
          <DTCCard key={dtc.code} dtc={dtc} />
        ))}
      </div>

      {/* Clear Confirmation Dialog */}
      {showClearConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-obd-surface border border-obd-border rounded-2xl p-6 max-w-md mx-4">
            <h3 className="text-lg font-bold text-white mb-2">Clear All DTCs?</h3>
            <p className="text-sm text-slate-400 mb-6">
              This will send a clear command to the ECU. Stored freeze frame data will be lost.
              DTCs may return if the underlying issue is not resolved.
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowClearConfirm(false)}
                className="px-4 py-2 rounded-xl bg-obd-surface-2 text-slate-300 text-sm font-medium hover:bg-slate-700 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => setShowClearConfirm(false)}
                className="px-4 py-2 rounded-xl bg-red-500 text-white text-sm font-medium hover:bg-red-600 transition-colors"
              >
                Clear DTCs
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
