import { useState, useEffect, useRef, useCallback } from 'react'

export interface SensorData {
  rpm: number
  speed: number
  coolant_temp: number
  engine_load: number
  throttle_pos: number
  voltage: number
  intake_temp: number
  maf_rate: number
  fuel_pressure: number
  timing_advance: number
  short_fuel_trim: number
  long_fuel_trim: number
  o2_voltage: number
  catalyst_temp: number
  ambient_temp: number
  oil_temp: number
  fuel_level: number
  boost_pressure: number
  connected: boolean
  vehicle_info?: {
    vin: string
    protocol: string
    ecu_name: string
  }
}

const DEFAULT_SENSOR_DATA: SensorData = {
  rpm: 0,
  speed: 0,
  coolant_temp: 0,
  engine_load: 0,
  throttle_pos: 0,
  voltage: 0,
  intake_temp: 0,
  maf_rate: 0,
  fuel_pressure: 0,
  timing_advance: 0,
  short_fuel_trim: 0,
  long_fuel_trim: 0,
  o2_voltage: 0,
  catalyst_temp: 0,
  ambient_temp: 0,
  oil_temp: 0,
  fuel_level: 0,
  boost_pressure: 0,
  connected: false,
}

export function useWebSocket(url: string = 'ws://localhost:8000/api/ws/sensors') {
  const [sensorData, setSensorData] = useState<SensorData>(DEFAULT_SENSOR_DATA)
  const [isConnected, setIsConnected] = useState(false)
  const [reconnectCount, setReconnectCount] = useState(0)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>()

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    try {
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        setIsConnected(true)
        setReconnectCount(0)
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          setSensorData(prev => ({ ...prev, ...data, connected: true }))
        } catch {
          // ignore parse errors
        }
      }

      ws.onclose = () => {
        setIsConnected(false)
        setSensorData(prev => ({ ...prev, connected: false }))
        // Auto-reconnect with backoff
        const delay = Math.min(1000 * Math.pow(2, reconnectCount), 10000)
        reconnectTimeoutRef.current = setTimeout(() => {
          setReconnectCount(c => c + 1)
          connect()
        }, delay)
      }

      ws.onerror = () => {
        ws.close()
      }
    } catch {
      // connection failed, will retry
    }
  }, [url, reconnectCount])

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
    }
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    setIsConnected(false)
    setSensorData(DEFAULT_SENSOR_DATA)
  }, [])

  useEffect(() => {
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      if (wsRef.current) {
        wsRef.current.close()
      }
    }
  }, [])

  return { sensorData, isConnected, connect, disconnect }
}
