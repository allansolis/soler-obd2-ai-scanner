import { useState } from 'react'
import { Usb, Bluetooth, Wifi, Monitor, Save } from 'lucide-react'

type ConnectionType = 'usb' | 'bluetooth' | 'wifi' | 'simulator'

const connectionOptions: { id: ConnectionType; label: string; icon: React.ReactNode; desc: string }[] = [
  { id: 'usb', label: 'USB', icon: <Usb className="w-5 h-5" />, desc: 'Direct USB OBD2 adapter' },
  { id: 'bluetooth', label: 'Bluetooth', icon: <Bluetooth className="w-5 h-5" />, desc: 'ELM327 Bluetooth adapter' },
  { id: 'wifi', label: 'WiFi', icon: <Wifi className="w-5 h-5" />, desc: 'WiFi OBD2 adapter' },
  { id: 'simulator', label: 'Simulator', icon: <Monitor className="w-5 h-5" />, desc: 'Virtual ECU for testing' },
]

export default function Settings() {
  const [connectionType, setConnectionType] = useState<ConnectionType>('simulator')
  const [port, setPort] = useState('/dev/ttyUSB0')
  const [baudRate, setBaudRate] = useState('38400')
  const [units, setUnits] = useState<'metric' | 'imperial'>('metric')
  const [samplingRate, setSamplingRate] = useState(5)
  const [saved, setSaved] = useState(false)

  const handleSave = () => {
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="p-6 space-y-6 max-w-3xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Settings</h1>
          <p className="text-sm text-slate-500">Configure your OBD2 connection and preferences</p>
        </div>
        <button
          onClick={handleSave}
          className={`flex items-center gap-2 px-5 py-2.5 rounded-xl font-medium text-sm transition-all duration-200 ${
            saved
              ? 'bg-obd-green/20 text-obd-green border border-obd-green/30'
              : 'bg-obd-accent text-white hover:bg-obd-accent/90 shadow-lg shadow-obd-accent/25'
          }`}
        >
          <Save className="w-4 h-4" />
          {saved ? 'Saved!' : 'Save Settings'}
        </button>
      </div>

      {/* Connection Type */}
      <div className="bg-obd-surface border border-obd-border rounded-xl p-5">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">
          Connection Type
        </h2>
        <div className="grid grid-cols-2 gap-3">
          {connectionOptions.map((opt) => (
            <button
              key={opt.id}
              onClick={() => setConnectionType(opt.id)}
              className={`flex items-center gap-3 p-4 rounded-xl border text-left transition-all duration-200 ${
                connectionType === opt.id
                  ? 'bg-obd-accent/10 border-obd-accent/40 text-obd-accent'
                  : 'border-obd-border hover:border-slate-600 text-slate-400'
              }`}
            >
              {opt.icon}
              <div>
                <span className="font-medium text-sm text-white block">{opt.label}</span>
                <span className="text-xs text-slate-500">{opt.desc}</span>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Port Configuration */}
      {connectionType !== 'simulator' && (
        <div className="bg-obd-surface border border-obd-border rounded-xl p-5">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">
            Port Configuration
          </h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-slate-500 mb-2">
                {connectionType === 'usb' ? 'Serial Port' : connectionType === 'wifi' ? 'IP Address' : 'Device Address'}
              </label>
              <input
                type="text"
                value={port}
                onChange={(e) => setPort(e.target.value)}
                className="w-full bg-obd-bg border border-obd-border rounded-xl px-4 py-2.5 text-sm font-mono text-white focus:outline-none focus:border-obd-accent/50 transition-all"
              />
            </div>
            {connectionType === 'usb' && (
              <div>
                <label className="block text-xs text-slate-500 mb-2">Baud Rate</label>
                <select
                  value={baudRate}
                  onChange={(e) => setBaudRate(e.target.value)}
                  className="w-full bg-obd-bg border border-obd-border rounded-xl px-4 py-2.5 text-sm font-mono text-white focus:outline-none focus:border-obd-accent/50 transition-all"
                >
                  <option value="9600">9600</option>
                  <option value="38400">38400</option>
                  <option value="115200">115200</option>
                  <option value="500000">500000</option>
                </select>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Units */}
      <div className="bg-obd-surface border border-obd-border rounded-xl p-5">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">
          Display Units
        </h2>
        <div className="flex gap-3">
          <button
            onClick={() => setUnits('metric')}
            className={`flex-1 py-3 rounded-xl border text-sm font-medium transition-all ${
              units === 'metric'
                ? 'bg-obd-accent/10 border-obd-accent/40 text-obd-accent'
                : 'border-obd-border text-slate-400 hover:border-slate-600'
            }`}
          >
            Metric (km/h, \u00B0C)
          </button>
          <button
            onClick={() => setUnits('imperial')}
            className={`flex-1 py-3 rounded-xl border text-sm font-medium transition-all ${
              units === 'imperial'
                ? 'bg-obd-accent/10 border-obd-accent/40 text-obd-accent'
                : 'border-obd-border text-slate-400 hover:border-slate-600'
            }`}
          >
            Imperial (mph, \u00B0F)
          </button>
        </div>
      </div>

      {/* Sampling Rate */}
      <div className="bg-obd-surface border border-obd-border rounded-xl p-5">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">
          Sampling Rate
        </h2>
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm text-slate-400">Data refresh interval</span>
            <span className="font-mono text-sm text-obd-accent font-medium">{samplingRate} Hz</span>
          </div>
          <input
            type="range"
            min={1}
            max={20}
            value={samplingRate}
            onChange={(e) => setSamplingRate(Number(e.target.value))}
            className="w-full h-2 bg-obd-bg rounded-full appearance-none cursor-pointer accent-obd-accent"
          />
          <div className="flex justify-between text-[10px] text-slate-600">
            <span>1 Hz (slow)</span>
            <span>10 Hz</span>
            <span>20 Hz (fast)</span>
          </div>
        </div>
      </div>
    </div>
  )
}
