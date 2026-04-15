import { NavLink, Outlet } from 'react-router-dom'
import {
  Gauge,
  AlertTriangle,
  Cpu,
  MessageSquare,
  History,
  Settings,
  Activity,
  Wifi,
  WifiOff,
  Car,
  Grid3x3,
  HardDrive,
  Database,
  Brain,
} from 'lucide-react'

interface LayoutProps {
  isConnected: boolean
}

const navItems = [
  { to: '/', icon: Gauge, label: 'Dashboard' },
  { to: '/vehicle', icon: Car, label: 'Vehiculo' },
  { to: '/dtc', icon: AlertTriangle, label: 'Diagnostics' },
  { to: '/tuning', icon: Cpu, label: 'ECU Maps' },
  { to: '/map-editor', icon: Grid3x3, label: 'Editor' },
  { to: '/ai', icon: MessageSquare, label: 'AI Chat' },
  { to: '/drive', icon: HardDrive, label: 'Drive' },
  { to: '/hub', icon: Database, label: 'Hub' },
  { to: '/expert', icon: Brain, label: 'Experto' },
  { to: '/history', icon: History, label: 'History' },
  { to: '/settings', icon: Settings, label: 'Settings' },
]

export default function Layout({ isConnected }: LayoutProps) {
  return (
    <div className="flex h-full bg-obd-bg">
      {/* Sidebar */}
      <aside className="w-64 flex-shrink-0 bg-obd-surface border-r border-obd-border flex flex-col">
        {/* Logo */}
        <div className="p-5 border-b border-obd-border">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-obd-accent to-obd-purple flex items-center justify-center">
              <Activity className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-white tracking-tight">SOLER</h1>
              <p className="text-[10px] text-slate-500 uppercase tracking-[0.2em]">OBD2 AI Scanner</p>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 p-3 space-y-1">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all duration-200 ${
                  isActive
                    ? 'bg-obd-accent/10 text-obd-accent shadow-lg shadow-obd-accent/5'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-white/5'
                }`
              }
            >
              <Icon className="w-5 h-5" />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Connection Status */}
        <div className="p-4 border-t border-obd-border">
          <div className="flex items-center gap-2 text-xs">
            {isConnected ? (
              <>
                <Wifi className="w-4 h-4 text-obd-green" />
                <span className="text-obd-green font-medium">Connected</span>
                <span className="ml-auto w-2 h-2 rounded-full bg-obd-green animate-pulse-glow" />
              </>
            ) : (
              <>
                <WifiOff className="w-4 h-4 text-slate-500" />
                <span className="text-slate-500">Disconnected</span>
                <span className="ml-auto w-2 h-2 rounded-full bg-slate-600" />
              </>
            )}
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
