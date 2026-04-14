import { useState, useCallback } from 'react'

const BASE_URL = 'http://localhost:8000'

interface ApiState<T> {
  data: T | null
  loading: boolean
  error: string | null
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${BASE_URL}${path}`
  const res = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(body || `HTTP ${res.status}`)
  }
  return res.json()
}

export function useApi<T = unknown>() {
  const [state, setState] = useState<ApiState<T>>({
    data: null,
    loading: false,
    error: null,
  })

  const get = useCallback(async (path: string) => {
    setState({ data: null, loading: true, error: null })
    try {
      const data = await request<T>(path)
      setState({ data, loading: false, error: null })
      return data
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      setState({ data: null, loading: false, error: msg })
      throw err
    }
  }, [])

  const post = useCallback(async (path: string, body?: unknown) => {
    setState({ data: null, loading: true, error: null })
    try {
      const data = await request<T>(path, {
        method: 'POST',
        body: body ? JSON.stringify(body) : undefined,
      })
      setState({ data, loading: false, error: null })
      return data
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      setState({ data: null, loading: false, error: msg })
      throw err
    }
  }, [])

  return { ...state, get, post }
}

export { request as apiFetch }
