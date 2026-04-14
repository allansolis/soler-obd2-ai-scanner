import { useState } from 'react'
import { Calendar, Car, Activity, ChevronRight, Search } from 'lucide-react'

interface ScanRecord {
  id: string
  date: string
  time: string
  vehicle: string
  vin: string
  healthScore: number
  dtcCount: number
  protocol: string
  duration: string
}

const MOCK_HISTORY: ScanRecord[] = [
  {
    id: '1',
    date: '2026-04-14',
    time: '09:32 AM',
    vehicle: '2021 Honda Civic',
    vin: 'JTDKN3DU5A0...4521',
    healthScore: 72,
    dtcCount: 4,
    protocol: 'ISO 15765-4 (CAN)',
    duration: '3m 42s',
  },
  {
    id: '2',
    date: '2026-04-12',
    time: '02:15 PM',
    vehicle: '2019 Toyota Camry',
    vin: '2HGFC2F53K...8833',
    healthScore: 94,
    dtcCount: 1,
    protocol: 'ISO 15765-4 (CAN)',
    duration: '2m 18s',
  },
  {
    id: '3',
    date: '2026-04-10',
    time: '11:48 AM',
    vehicle: '2018 BMW 330i',
    vin: 'WBA8E9C50J...7712',
    healthScore: 88,
    dtcCount: 2,
    protocol: 'ISO 14230 (KWP)',
    duration: '4m 05s',
  },
  {
    id: '4',
    date: '2026-04-07',
    time: '04:22 PM',
    vehicle: '2020 Ford F-150',
    vin: '1FTEW1EP4L...3304',
    healthScore: 45,
    dtcCount: 7,
    protocol: 'SAE J1850 VPW',
    duration: '5m 51s',
  },
  {
    id: '5',
    date: '2026-04-03',
    time: '08:50 AM',
    vehicle: '2022 Tesla Model 3',
    vin: '5YJ3E1EA8N...9901',
    healthScore: 98,
    dtcCount: 0,
    protocol: 'ISO 15765-4 (CAN)',
    duration: '1m 12s',
  },
]

function getHealthColor(score: number): string {
  if (score >= 80) return '#22c55e'
  if (score >= 50) return '#eab308'
  return '#ef4444'
}

export default function History() {
  const [search, setSearch] = useState('')
  const [selectedScan, setSelectedScan] = useState<ScanRecord | null>(null)

  const filtered = MOCK_HISTORY.filter(
    (s) =>
      s.vehicle.toLowerCase().includes(search.toLowerCase()) ||
      s.vin.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Scan History</h1>
          <p className="text-sm text-slate-500">{MOCK_HISTORY.length} scans recorded</p>
        </div>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by vehicle or VIN..."
          className="w-full bg-obd-surface border border-obd-border rounded-xl pl-11 pr-4 py-3 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-obd-accent/50 transition-all"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Scan List */}
        <div className="lg:col-span-2 space-y-3">
          {filtered.map((scan) => (
            <button
              key={scan.id}
              onClick={() => setSelectedScan(scan)}
              className={`w-full text-left p-4 rounded-xl border transition-all duration-200 ${
                selectedScan?.id === scan.id
                  ? 'bg-obd-accent/5 border-obd-accent/30'
                  : 'bg-obd-surface border-obd-border hover:border-slate-600'
              }`}
            >
              <div className="flex items-center gap-4">
                <div
                  className="w-12 h-12 rounded-xl flex items-center justify-center font-mono font-bold text-sm"
                  style={{
                    background: `${getHealthColor(scan.healthScore)}15`,
                    color: getHealthColor(scan.healthScore),
                  }}
                >
                  {scan.healthScore}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <Car className="w-4 h-4 text-obd-accent" />
                    <span className="font-medium text-white text-sm">{scan.vehicle}</span>
                  </div>
                  <div className="flex items-center gap-4 mt-1">
                    <span className="text-xs text-slate-500 flex items-center gap-1">
                      <Calendar className="w-3 h-3" /> {scan.date} {scan.time}
                    </span>
                    <span className="text-xs text-slate-500">
                      {scan.dtcCount} DTC{scan.dtcCount !== 1 ? 's' : ''}
                    </span>
                  </div>
                </div>
                <ChevronRight className="w-4 h-4 text-slate-600" />
              </div>
            </button>
          ))}
        </div>

        {/* Detail Panel */}
        <div className="bg-obd-surface border border-obd-border rounded-xl p-5">
          {selectedScan ? (
            <div className="space-y-5">
              <div className="text-center">
                <div
                  className="w-20 h-20 rounded-2xl flex items-center justify-center font-mono font-bold text-2xl mx-auto mb-3"
                  style={{
                    background: `${getHealthColor(selectedScan.healthScore)}15`,
                    color: getHealthColor(selectedScan.healthScore),
                    boxShadow: `0 0 30px ${getHealthColor(selectedScan.healthScore)}20`,
                  }}
                >
                  {selectedScan.healthScore}
                </div>
                <h3 className="font-semibold text-white">{selectedScan.vehicle}</h3>
                <p className="font-mono text-xs text-slate-500 mt-1">{selectedScan.vin}</p>
              </div>

              <div className="space-y-3">
                {[
                  { label: 'Date', value: `${selectedScan.date} ${selectedScan.time}` },
                  { label: 'Protocol', value: selectedScan.protocol },
                  { label: 'Duration', value: selectedScan.duration },
                  { label: 'DTCs Found', value: String(selectedScan.dtcCount) },
                  { label: 'Health Score', value: `${selectedScan.healthScore}%` },
                ].map((item) => (
                  <div key={item.label} className="flex justify-between py-2 border-b border-white/5">
                    <span className="text-xs text-slate-500">{item.label}</span>
                    <span className="text-xs text-white font-medium">{item.value}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-60 text-slate-600">
              <Activity className="w-8 h-8 mb-3" />
              <p className="text-sm">Select a scan to view details</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
