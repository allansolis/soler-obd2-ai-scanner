import {
  createContext,
  useContext,
  useState,
  useCallback,
  useMemo,
  useEffect,
  type ReactNode,
} from 'react'
import { AIOrchestrator } from '../services/AIOrchestrator'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Vehicle {
  vin?: string
  make?: string
  model?: string
  year?: number
  engine?: string
  ecuType?: string
}

export type AITask =
  | 'idle'
  | 'scanning'
  | 'diagnosing'
  | 'repairing'
  | 'tuning'
  | 'learning'

export interface AIAction {
  id: string
  type: 'scan' | 'repair' | 'tune' | 'clear_dtc' | 'research' | 'explain'
  label: string
  payload?: Record<string, unknown>
  timestamp: number
}

export interface AIResult {
  success: boolean
  message: string
  data?: unknown
}

export interface KnowledgeBaseStats {
  dtcCount: number
  pdfCount: number
  rulesCount: number
  lastUpdated: string
  lessonsLearned: number
}

export interface Suggestion {
  id: string
  title: string
  description: string
  action?: AIAction
  priority: 'low' | 'medium' | 'high'
}

export interface ScanResult {
  healthScore: number
  dtcCount: number
  sensorCount: number
  warnings: string[]
  nextSteps: string[]
}

export interface RepairGuide {
  dtcCode: string
  title: string
  summary: string
  steps: { order: number; title: string; description: string; image?: string }[]
  estimatedCostUsd: number
  estimatedTimeMin: number
  toolsNeeded: string[]
  difficulty: 'easy' | 'medium' | 'hard'
}

export interface TuneGuide {
  profile: string
  eligible: boolean
  reason?: string
  steps: { order: number; title: string; description: string }[]
  expectedGains: { hp: number; torque: number; mpg?: number }
  safetyWarnings: string[]
}

export interface AIState {
  isActive: boolean
  currentTask: AITask
  currentVehicle: Vehicle | null
  recentActions: AIAction[]
  knowledgeBase: KnowledgeBaseStats
  suggestions: Suggestion[]
  setVehicle: (v: Vehicle | null) => void
  setTask: (t: AITask) => void
  pushSuggestion: (s: Suggestion) => void
  clearSuggestions: () => void
  executeAction: (action: AIAction) => Promise<AIResult>
  askQuestion: (q: string) => Promise<string>
  startScan: () => Promise<ScanResult>
  guidedRepair: (dtcCode: string) => Promise<RepairGuide>
  guidedTune: (profile: string) => Promise<TuneGuide>
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const AIContextImpl = createContext<AIState | null>(null)

const defaultKnowledge: KnowledgeBaseStats = {
  dtcCount: 0,
  pdfCount: 0,
  rulesCount: 0,
  lastUpdated: new Date().toISOString(),
  lessonsLearned: 0,
}

export function AIProvider({ children }: { children: ReactNode }) {
  const [isActive, setIsActive] = useState(true)
  const [currentTask, setCurrentTask] = useState<AITask>('idle')
  const [currentVehicle, setCurrentVehicle] = useState<Vehicle | null>(null)
  const [recentActions, setRecentActions] = useState<AIAction[]>([])
  const [knowledgeBase, setKnowledgeBase] =
    useState<KnowledgeBaseStats>(defaultKnowledge)
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])

  const orchestrator = useMemo(() => new AIOrchestrator(), [])

  // Fetch KB stats on mount
  useEffect(() => {
    orchestrator
      .getKnowledgeStats()
      .then((stats) => setKnowledgeBase(stats))
      .catch(() => {
        /* offline is fine */
      })
  }, [orchestrator])

  const trackAction = useCallback((action: AIAction) => {
    setRecentActions((prev) => [action, ...prev].slice(0, 25))
  }, [])

  const executeAction = useCallback(
    async (action: AIAction): Promise<AIResult> => {
      trackAction(action)
      setIsActive(true)
      try {
        switch (action.type) {
          case 'scan':
            setCurrentTask('scanning')
            await orchestrator.performFullScan()
            return { success: true, message: 'Escaneo completado' }
          case 'repair':
            setCurrentTask('repairing')
            return { success: true, message: 'Guia de reparacion generada' }
          case 'tune':
            setCurrentTask('tuning')
            return { success: true, message: 'Guia de tuning generada' }
          case 'clear_dtc':
            setCurrentTask('diagnosing')
            await orchestrator.guidedClearDTC(
              (action.payload?.dtcCode as string) ?? ''
            )
            return { success: true, message: 'DTC analizado' }
          case 'research':
            setCurrentTask('learning')
            await orchestrator.researchOnline(
              (action.payload?.query as string) ?? '',
              currentVehicle ?? {}
            )
            return { success: true, message: 'Investigacion completada' }
          default:
            return { success: true, message: 'Accion ejecutada' }
        }
      } catch (err) {
        return {
          success: false,
          message: err instanceof Error ? err.message : 'Error desconocido',
        }
      } finally {
        setCurrentTask('idle')
      }
    },
    [orchestrator, currentVehicle, trackAction]
  )

  const askQuestion = useCallback(
    async (q: string): Promise<string> => {
      setCurrentTask('diagnosing')
      try {
        return await orchestrator.askQuestion(q, currentVehicle)
      } finally {
        setCurrentTask('idle')
      }
    },
    [orchestrator, currentVehicle]
  )

  const startScan = useCallback(async () => {
    setCurrentTask('scanning')
    try {
      return await orchestrator.performFullScan()
    } finally {
      setCurrentTask('idle')
    }
  }, [orchestrator])

  const guidedRepair = useCallback(
    async (dtcCode: string) => {
      setCurrentTask('repairing')
      try {
        return await orchestrator.guidedRepair(dtcCode, currentVehicle)
      } finally {
        setCurrentTask('idle')
      }
    },
    [orchestrator, currentVehicle]
  )

  const guidedTune = useCallback(
    async (profile: string) => {
      setCurrentTask('tuning')
      try {
        return await orchestrator.guidedTune(profile, currentVehicle)
      } finally {
        setCurrentTask('idle')
      }
    },
    [orchestrator, currentVehicle]
  )

  const pushSuggestion = useCallback((s: Suggestion) => {
    setSuggestions((prev) => {
      if (prev.some((p) => p.id === s.id)) return prev
      return [s, ...prev].slice(0, 8)
    })
  }, [])

  const clearSuggestions = useCallback(() => setSuggestions([]), [])

  const value: AIState = useMemo(
    () => ({
      isActive,
      currentTask,
      currentVehicle,
      recentActions,
      knowledgeBase,
      suggestions,
      setVehicle: setCurrentVehicle,
      setTask: setCurrentTask,
      pushSuggestion,
      clearSuggestions,
      executeAction,
      askQuestion,
      startScan,
      guidedRepair,
      guidedTune,
    }),
    [
      isActive,
      currentTask,
      currentVehicle,
      recentActions,
      knowledgeBase,
      suggestions,
      pushSuggestion,
      clearSuggestions,
      executeAction,
      askQuestion,
      startScan,
      guidedRepair,
      guidedTune,
    ]
  )

  // silence unused warning for isActive setter - it's used internally
  void setIsActive

  return <AIContextImpl.Provider value={value}>{children}</AIContextImpl.Provider>
}

export function useAI(): AIState {
  const ctx = useContext(AIContextImpl)
  if (!ctx) {
    throw new Error('useAI must be used inside <AIProvider>')
  }
  return ctx
}
