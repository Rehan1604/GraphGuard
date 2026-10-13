




// Where the backend lives. Override with VITE_API_URL in frontend/.env.local.
export const API_URL = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000').replace(/\/+$/, '') // no trailing slash
export const WS_URL = API_URL.replace(/^http/, 'ws')

export class ApiError extends Error {
  status
  constructor(status, message) {
    super(message)
    this.status = status
  }
}

/** FastAPI errors come back as {detail: "text"} or {detail: [{msg: ...}, ...]}. */
function describe(detail) {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d ).msg) : JSON.stringify(d)))
      .join('; ')
  }
  return 'Request failed'
}

async function request(path, init) {
  let response
  try {
    response = await fetch(`${API_URL}${path}`, init)
  } catch {
    throw new ApiError(0, `Cannot reach the API at ${API_URL}. Is the backend running?`)
  }
  if (!response.ok) {
    let message = `Request failed (HTTP ${response.status})`
    try {
      message = describe(((await response.json()) ).detail)
    } catch {
      /* keep the default message */
    }
    throw new ApiError(response.status, message)
  }
  return (await response.json()) 
}

const post = (body) => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
})







export function fetchAlerts(filters = {}) {
  const params = new URLSearchParams({ limit: '500' })
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value)
  return request(`/api/alerts?${params.toString()}`)
}
export const fetchAlert = (id) => request(`/api/alerts/${id}`)
export const addNote = (id, author, body) =>
  request(`/api/alerts/${id}/notes`, post({ author, body }))
export const changeStatus = (id, status, comment, actor) =>
  request(`/api/alerts/${id}/status`, post({ status, comment: comment || null, actor }))

export const fetchStats = () => request('/api/stats')
export const fetchMetrics = () => request('/api/metrics/alerts')
export const fetchGraph = (limit) => request(`/api/graph?limit=${limit}`)
export const fetchTransactions = (limit = 50) => request(`/api/transactions?limit=${limit}`)

export const fetchSimulation = () => request('/api/simulation')
export const simulationAction = (action, options) =>
  request(`/api/simulation/${action}`, post(options))

export const fetchDetectionConfig = () => request('/api/detection/config')
export const previewDetection = (config) =>
  request('/api/detection/run', post(config))
export const scanAlerts = (config) => request('/api/alerts/scan', post(config))
export const fetchAssistantStatus = () => request('/api/assistant/status')
export const askAssistant = (alertId, question, useAi) =>
  request(`/api/alerts/${alertId}/assistant`, post({ question, use_ai: useAi }))
export const fetchEvaluation = (dataset, seed, nEvents) =>
  request(`/api/evaluation?dataset=${dataset}&seed=${seed}&n_events=${nEvents}`)