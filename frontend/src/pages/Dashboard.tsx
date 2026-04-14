import {
  Thermometer,
  Zap,
  Droplets,
  Wind,
  Flame,
  Battery,
  Gauge as GaugeIcon,
  TrendingUp,
  Plug,
  Car,
} from 'lucide-react'
import Gauge from '../components/Gauge'
import SensorCard from '../components/SensorCard'
import type { SensorData } from '../hooks/useWebSocket'

interface DashboardProps {
  sensorData: SensorData
  isConnected: boolean
  onConnect: () => void
  onDisconnect: () => void
}

function getHealthScore(data: SensorData): number {
  if (!data.connected) return 0
  let score = 100
  if (data.coolant_temp > 105) score -= 30
  else if (data.coolant_temp > 95) score -= 10
  if (data.voltage < 12.0) score -= 20
  else if (data.voltage < 12.4) score -= 10
  if (data.engine_load > 90) score -= 15
  if (Math.abs(data.short_fuel_trim) > 15) score -= 10
  if (Math.abs(data.long_fuel_trim) > 10) score -= 10
  return Math.max(0, Math.min(100, score))
}

function getSensorStatus(value: number, warn: number, danger: number): 'normal' | 'warn' | 'danger' {
  if (value >= danger) return 'danger'
  if (value >= warn) return 'warn'
  return 'normal'
}

export default function Dashboard({ sensorData, isConnected, onConnect, onDisconnect }: DashboardProps) {
  const health = getHealthScore(sensorData)

  const healthColor =
    health >= 80 ? '#22c55e' : health >= 50 ? '#eab308' : '#ef4444'

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Dashboard</h1>
          <p className="text-sm text-slate-500">
            {isConnected
              ? `Connected${sensorData.vehicle_info ? ` -- ${sensorData.vehicle_info.protocol}` : ''}`
              : 'No vehicle connected'}
          </p>
        </div>
        <div className="flex items-center gap-4">
          {sensorData.vehicle_info && (
            <div className="flex items-center gap-2 bg-obd-surface border border-obd-border rounded-xl px-4 py-2">
              <Car className="w-4 h-4 text-obd-accent" />
              <span className="font-mono text-xs text-slate-300">
                {sensorData.vehicle_info.vin}
              </span>
            </div>
          )}
          <button
            onClick={isConnected ? onDisconnect : onConnect}
            className={`flex items-center gap-2 px-5 py-2.5 rounded-xl font-medium text-sm transition-all duration-200 ${
              isConnected
                ? 'bg-red-500/10 text-red-400 border border-red-500/30 hover:bg-red-500/20'
                : 'bg-obd-accent text-white hover:bg-obd-accent/90 shadow-lg shadow-obd-accent/25 animate-glow'
            }`}
          >
            <Plug className="w-4 h-4" />
            {isConnected ? 'Disconnect' : 'Connect'}
          </button>
        </div>
      </div>

      {/* Health Score Bar */}
      <div className="bg-obd-surface border border-obd-border rounded-xl p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-slate-400">Vehicle Health Score</span>
          <span className="font-mono font-bold text-white" style={{ color: healthColor }}>
            {health}%
          </span>
        </div>
        <div className="w-full h-3 bg-obd-bg rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-1000 ease-out"
            style={{
              width: `${health}%`,
              background: `linear-gradient(90deg, ${healthColor}, ${healthColor}cc)`,
              boxShadow: `0 0 12px ${healthColor}40`,
            }}
          />
        </div>
      </div>

      {/* Primary Gauges */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <div className="bg-obd-surface border border-obd-border rounded-xl p-4 flex justify-center">
          <Gauge
            value={sensorData.rpm}
            min={0}
            max={8000}
            label="RPM"
            unit="rpm"
            color="#0ea5e9"
            thresholds={{ warn: 75, danger: 90 }}
            size="md"
          />
        </div>
        <div className="bg-obd-surface border border-obd-border rounded-xl p-4 flex justify-center">
          <Gauge
            value={sensorData.speed}
            min={0}
            max={240}
            label="Speed"
            unit="km/h"
            color="#6366f1"
            size="md"
          />
        </div>
        <div className="bg-obd-surface border border-obd-border rounded-xl p-4 flex justify-center">
          <Gauge
            value={sensorData.coolant_temp}
            min={0}
            max={130}
            label="Coolant"
            unit={'\u00B0C'}
            thresholds={{ warn: 70, danger: 85 }}
            size="md"
          />
        </div>
        <div className="bg-obd-surface border border-obd-border rounded-xl p-4 flex justify-center">
          <Gauge
            value={sensorData.engine_load}
            min={0}
            max={100}
            label="Load"
            unit="%"
            color="#8b5cf6"
            thresholds={{ warn: 75, danger: 90 }}
            size="md"
          />
        </div>
        <div className="bg-obd-surface border border-obd-border rounded-xl p-4 flex justify-center">
          <Gauge
            value={sensorData.throttle_pos}
            min={0}
            max={100}
            label="Throttle"
            unit="%"
            color="#f97316"
            size="md"
          />
        </div>
        <div className="bg-obd-surface border border-obd-border rounded-xl p-4 flex justify-center">
          <Gauge
            value={sensorData.voltage}
            min={10}
            max={16}
            label="Battery"
            unit="V"
            thresholds={{ warn: 20, danger: 10 }}
            size="md"
          />
        </div>
      </div>

      {/* Secondary Sensors Grid */}
      <div>
        <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-3">
          Sensor Readings
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
          <SensorCard
            name="Intake Temp"
            value={sensorData.intake_temp}
            unit={'\u00B0C'}
            icon={<Thermometer className="w-3.5 h-3.5" />}
            status={getSensorStatus(sensorData.intake_temp, 50, 70)}
          />
          <SensorCard
            name="MAF Rate"
            value={sensorData.maf_rate}
            unit="g/s"
            icon={<Wind className="w-3.5 h-3.5" />}
          />
          <SensorCard
            name="Fuel Pressure"
            value={sensorData.fuel_pressure}
            unit="kPa"
            icon={<Droplets className="w-3.5 h-3.5" />}
          />
          <SensorCard
            name="Timing Advance"
            value={sensorData.timing_advance}
            unit={'\u00B0'}
            icon={<Zap className="w-3.5 h-3.5" />}
          />
          <SensorCard
            name="Short Fuel Trim"
            value={sensorData.short_fuel_trim}
            unit="%"
            icon={<TrendingUp className="w-3.5 h-3.5" />}
            status={getSensorStatus(Math.abs(sensorData.short_fuel_trim), 10, 20)}
          />
          <SensorCard
            name="Long Fuel Trim"
            value={sensorData.long_fuel_trim}
            unit="%"
            icon={<TrendingUp className="w-3.5 h-3.5" />}
            status={getSensorStatus(Math.abs(sensorData.long_fuel_trim), 8, 15)}
          />
          <SensorCard
            name="O2 Voltage"
            value={sensorData.o2_voltage}
            unit="V"
            precision={2}
            icon={<GaugeIcon className="w-3.5 h-3.5" />}
          />
          <SensorCard
            name="Catalyst Temp"
            value={sensorData.catalyst_temp}
            unit={'\u00B0C'}
            icon={<Flame className="w-3.5 h-3.5" />}
            status={getSensorStatus(sensorData.catalyst_temp, 600, 800)}
          />
          <SensorCard
            name="Ambient Temp"
            value={sensorData.ambient_temp}
            unit={'\u00B0C'}
            icon={<Thermometer className="w-3.5 h-3.5" />}
          />
          <SensorCard
            name="Oil Temp"
            value={sensorData.oil_temp}
            unit={'\u00B0C'}
            icon={<Thermometer className="w-3.5 h-3.5" />}
            status={getSensorStatus(sensorData.oil_temp, 110, 130)}
          />
          <SensorCard
            name="Fuel Level"
            value={sensorData.fuel_level}
            unit="%"
            icon={<Droplets className="w-3.5 h-3.5" />}
            status={sensorData.fuel_level < 15 ? 'danger' : sensorData.fuel_level < 25 ? 'warn' : 'normal'}
          />
          <SensorCard
            name="Boost Pressure"
            value={sensorData.boost_pressure}
            unit="psi"
            icon={<Battery className="w-3.5 h-3.5" />}
          />
        </div>
      </div>
    </div>
  )
}
