interface SensorCardProps {
  name: string
  value: number
  unit: string
  icon?: React.ReactNode
  status?: 'normal' | 'warn' | 'danger'
  precision?: number
}

const statusColors = {
  normal: 'bg-obd-green',
  warn: 'bg-obd-yellow',
  danger: 'bg-obd-red',
}

const statusGlow = {
  normal: 'shadow-obd-green/20',
  warn: 'shadow-obd-yellow/20',
  danger: 'shadow-obd-red/20',
}

export default function SensorCard({
  name,
  value,
  unit,
  icon,
  status = 'normal',
  precision = 1,
}: SensorCardProps) {
  return (
    <div className="bg-obd-surface border border-obd-border rounded-xl p-4 hover:border-slate-600 transition-all duration-200 group">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] text-slate-500 uppercase tracking-wider font-medium">
          {name}
        </span>
        <div className="flex items-center gap-2">
          {icon && <span className="text-slate-600 group-hover:text-slate-400 transition-colors">{icon}</span>}
          <span
            className={`w-2 h-2 rounded-full ${statusColors[status]} shadow-lg ${statusGlow[status]}`}
          />
        </div>
      </div>
      <div className="flex items-baseline gap-1">
        <span className="font-mono text-2xl font-bold text-white tracking-tight">
          {typeof value === 'number' ? value.toFixed(precision) : value}
        </span>
        <span className="font-mono text-sm text-slate-500">{unit}</span>
      </div>
    </div>
  )
}
