import { useState } from 'react'
import { ChevronDown, ChevronUp, AlertCircle } from 'lucide-react'

export interface DTCData {
  code: string
  description: string
  severity: 'critical' | 'high' | 'medium' | 'low'
  probable_causes?: string[]
  corrective_actions?: string[]
  freeze_frame?: Record<string, string | number>
}

const severityConfig = {
  critical: {
    bg: 'bg-red-500/10',
    border: 'border-red-500/30',
    badge: 'bg-red-500/20 text-red-400',
    icon: 'text-red-400',
  },
  high: {
    bg: 'bg-orange-500/10',
    border: 'border-orange-500/30',
    badge: 'bg-orange-500/20 text-orange-400',
    icon: 'text-orange-400',
  },
  medium: {
    bg: 'bg-yellow-500/10',
    border: 'border-yellow-500/30',
    badge: 'bg-yellow-500/20 text-yellow-400',
    icon: 'text-yellow-400',
  },
  low: {
    bg: 'bg-blue-500/10',
    border: 'border-blue-500/30',
    badge: 'bg-blue-500/20 text-blue-400',
    icon: 'text-blue-400',
  },
}

export default function DTCCard({ dtc }: { dtc: DTCData }) {
  const [expanded, setExpanded] = useState(false)
  const config = severityConfig[dtc.severity]

  return (
    <div
      className={`${config.bg} border ${config.border} rounded-xl overflow-hidden transition-all duration-200`}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-4 p-4 text-left hover:bg-white/5 transition-colors"
      >
        <AlertCircle className={`w-5 h-5 flex-shrink-0 ${config.icon}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3">
            <span className="font-mono font-bold text-white text-sm">{dtc.code}</span>
            <span
              className={`px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider ${config.badge}`}
            >
              {dtc.severity}
            </span>
          </div>
          <p className="text-sm text-slate-400 mt-0.5 truncate">{dtc.description}</p>
        </div>
        {expanded ? (
          <ChevronUp className="w-4 h-4 text-slate-500" />
        ) : (
          <ChevronDown className="w-4 h-4 text-slate-500" />
        )}
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-4 border-t border-white/5">
          {dtc.probable_causes && dtc.probable_causes.length > 0 && (
            <div className="mt-3">
              <h4 className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
                Probable Causes
              </h4>
              <ul className="space-y-1">
                {dtc.probable_causes.map((cause, i) => (
                  <li key={i} className="text-sm text-slate-300 flex items-start gap-2">
                    <span className="text-slate-600 mt-1">--</span>
                    {cause}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {dtc.corrective_actions && dtc.corrective_actions.length > 0 && (
            <div>
              <h4 className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
                Corrective Actions
              </h4>
              <ul className="space-y-1">
                {dtc.corrective_actions.map((action, i) => (
                  <li key={i} className="text-sm text-slate-300 flex items-start gap-2">
                    <span className="font-mono text-obd-accent text-xs mt-0.5">{i + 1}.</span>
                    {action}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {dtc.freeze_frame && Object.keys(dtc.freeze_frame).length > 0 && (
            <div>
              <h4 className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
                Freeze Frame Data
              </h4>
              <div className="grid grid-cols-2 gap-2">
                {Object.entries(dtc.freeze_frame).map(([key, val]) => (
                  <div key={key} className="flex justify-between bg-black/20 rounded-lg px-3 py-1.5">
                    <span className="text-xs text-slate-500">{key}</span>
                    <span className="font-mono text-xs text-white">{val}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
