/**
 * AIOrchestrator - Frontend orchestration layer for the SOLER AI Copilot.
 *
 * Executes complete workflows (scan, diagnose, repair, tune, research, learn)
 * by calling backend AI endpoints. Falls back to sensible local defaults when
 * the backend is unreachable so the UI always remains helpful.
 */

import type {
  Vehicle,
  ScanResult,
  RepairGuide,
  TuneGuide,
  KnowledgeBaseStats,
} from '../contexts/AIContext'

export interface ClearResult {
  cleared: boolean
  safeToClear: boolean
  warnings: string[]
  followUp: string
}

export interface ResearchResult {
  query: string
  sources: { url: string; title: string; snippet: string }[]
  summary: string
}

export interface SessionData {
  sessionId: string
  vehicle: Vehicle | null
  actions: { type: string; timestamp: number; payload?: unknown }[]
  outcome: 'success' | 'failure' | 'partial'
  notes?: string
}

const API_BASE =
  (typeof window !== 'undefined' &&
    (window as unknown as { __API_BASE__?: string }).__API_BASE__) ||
  '/api'

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status} on ${path}`)
  return (await res.json()) as T
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) throw new Error(`HTTP ${res.status} on ${path}`)
  return (await res.json()) as T
}

export class AIOrchestrator {
  // -------------------------------------------------------------------------
  // Scan
  // -------------------------------------------------------------------------
  async performFullScan(): Promise<ScanResult> {
    try {
      return await postJSON<ScanResult>('/ai/scan-full', {})
    } catch {
      return {
        healthScore: 0,
        dtcCount: 0,
        sensorCount: 0,
        warnings: ['No se pudo conectar al backend. Revisa la conexion OBD.'],
        nextSteps: ['Verificar adaptador ELM327', 'Reintentar escaneo'],
      }
    }
  }

  // -------------------------------------------------------------------------
  // Repair
  // -------------------------------------------------------------------------
  async guidedRepair(
    dtcCode: string,
    vehicle: Vehicle | null
  ): Promise<RepairGuide> {
    try {
      return await postJSON<RepairGuide>('/ai/repair-guide', {
        dtc_code: dtcCode,
        vehicle,
      })
    } catch {
      return this.fallbackRepairGuide(dtcCode)
    }
  }

  private fallbackRepairGuide(dtcCode: string): RepairGuide {
    return {
      dtcCode,
      title: `Guia de reparacion para ${dtcCode}`,
      summary:
        'Guia generica. Conecta el backend para obtener el procedimiento exacto.',
      steps: [
        {
          order: 1,
          title: 'Verificar el codigo',
          description: `Confirma el codigo ${dtcCode} con un segundo escaneo.`,
        },
        {
          order: 2,
          title: 'Inspeccion visual',
          description: 'Revisa cableado, conectores y fusibles relacionados.',
        },
        {
          order: 3,
          title: 'Medir sensores asociados',
          description:
            'Monitorea los PIDs en vivo para detectar lecturas fuera de rango.',
        },
        {
          order: 4,
          title: 'Reemplazar componente sospechoso',
          description: 'Sustituye el sensor o actuador defectuoso.',
        },
        {
          order: 5,
          title: 'Borrar DTC y verificar',
          description: 'Limpia el codigo y realiza una prueba de ruta.',
        },
      ],
      estimatedCostUsd: 120,
      estimatedTimeMin: 90,
      toolsNeeded: ['Escaner OBD2', 'Multimetro', 'Llaves combinadas'],
      difficulty: 'medium',
    }
  }

  // -------------------------------------------------------------------------
  // Tune
  // -------------------------------------------------------------------------
  async guidedTune(
    profile: string,
    vehicle: Vehicle | null
  ): Promise<TuneGuide> {
    try {
      return await postJSON<TuneGuide>('/ai/tune-guide', { profile, vehicle })
    } catch {
      return {
        profile,
        eligible: false,
        reason:
          'No se pudo validar el estado del vehiculo. Realiza un escaneo primero.',
        steps: [],
        expectedGains: { hp: 0, torque: 0 },
        safetyWarnings: [
          'No se pudo contactar al backend de seguridad.',
          'No flashear sin validacion completa.',
        ],
      }
    }
  }

  // -------------------------------------------------------------------------
  // Clear DTC
  // -------------------------------------------------------------------------
  async guidedClearDTC(dtcCode: string): Promise<ClearResult> {
    try {
      return await postJSON<ClearResult>('/ai/clear-dtc', {
        dtc_code: dtcCode,
      })
    } catch {
      return {
        cleared: false,
        safeToClear: false,
        warnings: [
          'No se pudo validar la seguridad para borrar este DTC sin conexion.',
        ],
        followUp:
          'Confirma que la causa raiz fue reparada antes de borrar el codigo.',
      }
    }
  }

  // -------------------------------------------------------------------------
  // Web research
  // -------------------------------------------------------------------------
  async researchOnline(
    query: string,
    vehicleContext: Vehicle | null | Record<string, never>
  ): Promise<ResearchResult> {
    try {
      return await postJSON<ResearchResult>('/ai/research', {
        query,
        vehicle: vehicleContext,
      })
    } catch {
      return {
        query,
        sources: [],
        summary: 'Busqueda no disponible sin conexion al backend.',
      }
    }
  }

  // -------------------------------------------------------------------------
  // Chat / Q&A
  // -------------------------------------------------------------------------
  async askQuestion(
    question: string,
    vehicle: Vehicle | null
  ): Promise<string> {
    try {
      const res = await postJSON<{ answer: string }>('/ai/chat', {
        message: question,
        vehicle,
      })
      return res.answer
    } catch {
      return 'No puedo conectar con el motor de IA en este momento. Revisa el backend e intenta de nuevo.'
    }
  }

  // -------------------------------------------------------------------------
  // Learning
  // -------------------------------------------------------------------------
  async learnFromSession(sessionData: SessionData): Promise<void> {
    try {
      await postJSON('/ai/learn', sessionData)
    } catch {
      // Silent fail - learning is best-effort
    }
  }

  async getKnowledgeStats(): Promise<KnowledgeBaseStats> {
    try {
      return await getJSON<KnowledgeBaseStats>('/ai/knowledge-stats')
    } catch {
      return {
        dtcCount: 0,
        pdfCount: 0,
        rulesCount: 0,
        lastUpdated: new Date().toISOString(),
        lessonsLearned: 0,
      }
    }
  }
}
