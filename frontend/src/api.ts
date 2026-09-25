export type Tenant = { id: string; name: string; status: string }
export type Client = { id: string; tenantId: string; name: string; apiKeyPrefix: string; status: string; lastUsedAt?: string; rateLimit?: RateLimit }
export type RateLimit = { bucketCapacity: number; refillRate: number; enabled: boolean }
export type Route = { id: string; tenantId: string; name: string; gatewayPath: string; upstreamUrl: string; allowedMethods: string[]; timeoutMs: number; authenticationRequired: boolean; active: boolean }
export type Log = { id: string; requestId: string; clientId?: string; routeId?: string; method: string; statusCode: number; latencyMilliseconds: number; blocked: boolean; createdAt: string }
export type Summary = { totalRequests: number; successfulRequests: number; blockedRequests: number; averageResponseTime: number; activeClients: number; mostUsedRoute: string }
export type Traffic = { requestsOverTime: { bucket: string; count: number }[]; statusDistribution: { statusCode: number; count: number }[]; requestsByClient: { name: string; count: number }[]; blockedRequestsByRoute: { name: string; count: number }[]; latencyTrend: { bucket: string; count: number }[] }

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
}
