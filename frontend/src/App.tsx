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
import MapEditorPage from './pages/MapEditorPage'
import AICopilot from './components/AICopilot'
import { AIProvider } from './contexts/AIContext'

export default function App() {
  const { sensorData, isConnected, connect, disconnect } = useWebSocket()

  return (
    <AIProvider>
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
          <Route path="/map-editor" element={<MapEditorPage />} />
        </Route>
      </Routes>
      <AICopilot />
    </AIProvider>
  )
}
