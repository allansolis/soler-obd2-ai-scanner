import { useState, useCallback, useRef } from 'react'

type Matrix = number[][]

interface HistoryState {
  past: Matrix[]
  present: Matrix
  future: Matrix[]
}

const cloneMatrix = (m: Matrix): Matrix => m.map((row) => [...row])

export function useMapHistory(initialData: Matrix) {
  const [state, setState] = useState<HistoryState>({
    past: [],
    present: cloneMatrix(initialData),
    future: [],
  })
  const initialRef = useRef<Matrix>(cloneMatrix(initialData))

  const push = useCallback((next: Matrix) => {
    setState((s) => ({
      past: [...s.past, s.present].slice(-100),
      present: cloneMatrix(next),
      future: [],
    }))
  }, [])

  const undo = useCallback(() => {
    setState((s) => {
      if (s.past.length === 0) return s
      const previous = s.past[s.past.length - 1]
      const newPast = s.past.slice(0, -1)
      return { past: newPast, present: previous, future: [s.present, ...s.future] }
    })
  }, [])

  const redo = useCallback(() => {
    setState((s) => {
      if (s.future.length === 0) return s
      const next = s.future[0]
      const newFuture = s.future.slice(1)
      return { past: [...s.past, s.present], present: next, future: newFuture }
    })
  }, [])

  const reset = useCallback(() => {
    setState({ past: [], present: cloneMatrix(initialRef.current), future: [] })
  }, [])

  const set = useCallback((data: Matrix) => {
    setState({ past: [], present: cloneMatrix(data), future: [] })
    initialRef.current = cloneMatrix(data)
  }, [])

  return {
    current: state.present,
    canUndo: state.past.length > 0,
    canRedo: state.future.length > 0,
    push,
    undo,
    redo,
    reset,
    set,
    historySize: state.past.length,
  }
}
