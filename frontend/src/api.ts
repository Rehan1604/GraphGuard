import type {
  AlertDetail, AlertMetrics, AlertSummary, DetectionConfig, DetectionResult, GraphData,
  Note, Priority, Rule, ScanSummary, SimulationState, StartOptions, Stats, Status, Transaction, AssistantAnswer, AssistantStatus,EvaluationReport,
} from './types'

// Where the backend lives. Override with VITE_API_URL in frontend/.env.local.
export const API_URL: string = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000').replace(/\/+$/, '') // no trailing slash
export const WS_URL: string = API_URL.replace(/^http/, 'ws')

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** FastAPI errors come back as {detail: "text"} or {detail: [{msg: ...}, ...]}. */
function describe(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : JSON.stringify(d)))
      .join('; ')
  }
  return 'Request failed'
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_URL}${path}`, init)
  } catch {
    throw new ApiError(0, `Cannot reach the API at ${API_URL}. Is the backend running?`)
  }
  if (!response.ok) {
    let message = `Request failed (HTTP ${response.status})`
    try {
      message = describe(((await response.json()) as { detail?: unknown }).detail)
    } catch {
      /* keep the default message */
    }
    throw new ApiError(response.status, message)
  }
  return (await response.json()) as T
}

const post = (body?: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
})

export interface AlertFilters {
  status?: Status | ''
  priority?: Priority | ''
  rule?: Rule | ''
}

export function fetchAlerts(filters: AlertFilters = {}): Promise<AlertSummary[]> {
  const params = new URLSearchParams({ limit: '500' })
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value)
  return request(`/api/alerts?${params.toString()}`)
}
export const fetchAlert = (id: number) => request<AlertDetail>(`/api/alerts/${id}`)
export const addNote = (id: number, author: string, body: string) =>
  request<Note>(`/api/alerts/${id}/notes`, post({ author, body }))
export const changeStatus = (id: number, status: Status, comment: string, actor: string) =>
  request<AlertDetail>(`/api/alerts/${id}/status`, post({ status, comment: comment || null, actor }))

export const fetchStats = () => request<Stats>('/api/stats')
export const fetchMetrics = () => request<AlertMetrics>('/api/metrics/alerts')
export const fetchGraph = (limit: number) => request<GraphData>(`/api/graph?limit=${limit}`)
export const fetchTransactions = (limit = 50) => request<Transaction[]>(`/api/transactions?limit=${limit}`)

export const fetchSimulation = () => request<SimulationState>('/api/simulation')
export const simulationAction = (action: 'start' | 'pause' | 'resume' | 'reset', options?: StartOptions) =>
  request<SimulationState>(`/api/simulation/${action}`, post(options))

export const fetchDetectionConfig = () => request<DetectionConfig>('/api/detection/config')
export const previewDetection = (config: DetectionConfig) =>
  request<DetectionResult>('/api/detection/run', post(config))
export const scanAlerts = (config: DetectionConfig) => request<ScanSummary>('/api/alerts/scan', post(config))
export const fetchAssistantStatus = () => request<AssistantStatus>('/api/assistant/status')
export const askAssistant = (alertId: number, question: string, useAi: boolean) =>
  request<AssistantAnswer>(`/api/alerts/${alertId}/assistant`, post({ question, use_ai: useAi }))
export const fetchEvaluation = (dataset: 'benchmark' | 'simulator', seed: number, nEvents: number) =>
  request<EvaluationReport>(`/api/evaluation?dataset=${dataset}&seed=${seed}&n_events=${nEvents}`)