export type Tenant = { id: string; name: string; status: string }
export type Client = { id: string; tenantId: string; name: string; apiKeyPrefix: string; status: string; lastUsedAt?: string; rateLimit?: RateLimit }
export type RateLimit = { bucketCapacity: number; refillRate: number; enabled: boolean }
export type Route = { id: string; tenantId: string; name: string; gatewayPath: string; upstreamUrl: string; allowedMethods: string[]; timeoutMs: number; authenticationRequired: boolean; active: boolean }
export type Log = { id: string; requestId: string; clientId?: string; routeId?: string; method: string; statusCode: number; latencyMilliseconds: number; blocked: boolean; createdAt: string }
export type Summary = { totalRequests: number; successfulRequests: number; blockedRequests: number; averageResponseTime: number; activeClients: number; mostUsedRoute: string }
export type Traffic = { requestsOverTime: { bucket: string; count: number }[]; statusDistribution: { statusCode: number; count: number }[]; requestsByClient: { name: string; count: number }[]; blockedRequestsByRoute: { name: string; count: number }[]; latencyTrend: { bucket: string; count: number }[] }
export type AIOverview = { tenant_id: string; summary: string; observed: Record<string, unknown>[]; forecast: { timestamp: string; predicted_requests: number; label?: string }[]; top_client: string; most_used_route: string; blocked_requests: number; anomaly_count: number | null; model_status: string; window: { start_time: string; end_time: string } }
export type AIAnomaly = { tenant_id: string; client_id?: string; route_id?: string; window_start?: string; severity?: string; score?: number; score_semantics?: string; model_version?: string }
export type AIForecast = { tenant_id: string; status: string; model_version: string | null; forecast: { timestamp: string; predicted_requests: number; label?: string }[]; naive_baseline: { timestamp: string; predicted_requests: number; label?: string }[]; evaluation: { status: string; note?: string } }
export type AIIncident = { tenant_id: string; summary: string; observed: string[]; interpretations: string[]; recommended_actions: string[]; evidence_sources: string[] }
export type AIAssistantResponse = { tenant_id: string; question: string; route: string; answer: string; sources: string[]; observed: string[]; interpretation: string[]; recommended_actions: string[] }

const baseUrl = import.meta.env.VITE_API_URL ?? 'http://localhost:8080'
const adminToken = import.meta.env.VITE_ADMIN_TOKEN ?? 'gateflow-local-admin'
const tenantId = import.meta.env.VITE_TENANT_ID ?? 'local-tenant'

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, { ...options, headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${adminToken}`, 'X-Tenant-ID': tenantId, ...(options.headers ?? {}) } })
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`)
  return response.status === 204 ? (undefined as T) : response.json()
}

export const api = {
  summary: () => request<Summary>('/api/analytics/summary'),
  traffic: () => request<Traffic>('/api/analytics/traffic'),
  logs: () => request<{ logs: Log[] }>('/api/analytics/logs'),
  clients: () => request<{ clients: Client[] }>('/api/clients'),
  createClient: (body: { name: string; bucketCapacity: number; refillRate: number }) => request<{ client: Client; apiKey: string; warning: string }>('/api/clients', { method: 'POST', body: JSON.stringify(body) }),
  clientAction: (id: string, action: 'rotate-key' | 'revoke' | 'activate') => request<Client>(`/api/clients/${id}/${action}`, { method: action === 'rotate-key' ? 'POST' : 'PATCH' }),
  updateClientRateLimit: (id: string, body: RateLimit) => request<Client>(`/api/clients/${id}/rate-limit`, { method: 'PATCH', body: JSON.stringify(body) }),
  routes: () => request<{ routes: Route[] }>('/api/routes'),
  createRoute: (body: Omit<Route, 'id' | 'tenantId'>) => request<Route>('/api/routes', { method: 'POST', body: JSON.stringify(body) }),
  updateRoute: (id: string, body: Omit<Route, 'id' | 'tenantId'>) => request<Route>(`/api/routes/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteRoute: (id: string) => request<void>(`/api/routes/${id}`, { method: 'DELETE' }),
  aiOverview: () => request<AIOverview>('/api/ai/overview'),
  aiRecentAnomalies: (limit = 10) => request<{ tenant_id: string; anomalies: AIAnomaly[]; count: number | null; status: string; model_version: string | null; detail: string | null }>(`/api/ai/recent-anomalies?limit=${limit}`),
  aiForecast: () => request<AIForecast>('/api/ai/forecast'),
  aiAssistant: (question: string) => request<AIAssistantResponse>('/api/ai/assistant', { method: 'POST', body: JSON.stringify({ question }) }),
  aiIncidentAnalysis: () => request<AIIncident>('/api/ai/incident-analysis'),
}
