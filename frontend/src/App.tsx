import { Routes, Route } from 'react-router-dom'
import { useWebSocket } from './hooks/useWebSocket'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Diagnostics from './pages/Diagnostics'
import Tuning from './pages/Tuning'
import AIChat from './pages/AIChat'
import History from './pages/History'
import Settings from './pages/Settings'
import VehicleSelect from './pages/VehicleSelect'

export default function App() {
  const { sensorData, isConnected, connect, disconnect } = useWebSocket()

  return (
    <Routes>
      <Route element={<Layout isConnected={isConnected} />}>
        <Route
          index
          element={
            <Dashboard
              sensorData={sensorData}
              isConnected={isConnected}
              onConnect={connect}
              onDisconnect={disconnect}
            />
          }
        />
        <Route path="/vehicle" element={<VehicleSelect />} />
        <Route path="/dtc" element={<Diagnostics />} />
        <Route path="/tuning" element={<Tuning />} />
        <Route path="/ai" element={<AIChat />} />
        <Route path="/history" element={<History />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
    </Routes>
  )
}
