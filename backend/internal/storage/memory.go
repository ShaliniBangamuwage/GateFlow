package storage

import (
	"context"
	"errors"
	"gateflow/internal/domain"
	"sort"
	"strings"
	"sync"
	"time"
)

var ErrNotFound = errors.New("not found")
var ErrConflict = errors.New("conflict")

type MemoryStore struct {
	mu       sync.RWMutex
	tenants  map[string]*domain.Tenant
	clients  map[string]*domain.APIClient
	routes   map[string]*domain.GatewayRoute
	policies map[string]*domain.RateLimitPolicy
	logs     []*domain.RequestLog
}

func NewMemoryStore() *MemoryStore {
	return &MemoryStore{tenants: map[string]*domain.Tenant{}, clients: map[string]*domain.APIClient{}, routes: map[string]*domain.GatewayRoute{}, policies: map[string]*domain.RateLimitPolicy{}}
}
func (s *MemoryStore) Close() error                 { return nil }
func (s *MemoryStore) Health(context.Context) error { return nil }
func clone[T any](value *T) *T                      { copy := *value; return &copy }
func (s *MemoryStore) CreateTenant(_ context.Context, tenant *domain.Tenant) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.tenants[tenant.ID]; ok {
		return ErrConflict
	}
	s.tenants[tenant.ID] = clone(tenant)
	return nil
}
func (s *MemoryStore) GetTenant(_ context.Context, id string) (*domain.Tenant, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	value, ok := s.tenants[id]
	if !ok {
		return nil, ErrNotFound
	}
	return clone(value), nil
}
func (s *MemoryStore) ListClients(_ context.Context, tenantID string) ([]*domain.APIClient, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	result := []*domain.APIClient{}
	for _, value := range s.clients {
		if value.TenantID == tenantID {
			result = append(result, clone(value))
		}
	}
	sort.Slice(result, func(i, j int) bool { return result[i].CreatedAt.Before(result[j].CreatedAt) })
	return result, nil
}
func (s *MemoryStore) CreateClient(_ context.Context, client *domain.APIClient) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, value := range s.clients {
		if value.KeyPrefix == client.KeyPrefix {
			return ErrConflict
		}
	}
	s.clients[client.ID] = clone(client)
	return nil
}
func (s *MemoryStore) GetClientByID(_ context.Context, tenantID, id string) (*domain.APIClient, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	value, ok := s.clients[id]
	if !ok || value.TenantID != tenantID {
		return nil, ErrNotFound
	}
	return clone(value), nil
}
func (s *MemoryStore) FindClientByPrefix(_ context.Context, prefix string) (*domain.APIClient, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, value := range s.clients {
		if value.KeyPrefix == prefix {
			return clone(value), nil
		}
	}
	return nil, ErrNotFound
}
func (s *MemoryStore) UpdateClient(_ context.Context, client *domain.APIClient) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	current, ok := s.clients[client.ID]
	if !ok || current.TenantID != client.TenantID {
		return ErrNotFound
	}
	s.clients[client.ID] = clone(client)
	return nil
}
func (s *MemoryStore) TouchClient(_ context.Context, tenantID, id string, at time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	value, ok := s.clients[id]
	if !ok || value.TenantID != tenantID {
		return ErrNotFound
	}
	value.LastUsedAt = &at
	value.UpdatedAt = at
	return nil
}
func (s *MemoryStore) ListRoutes(_ context.Context, tenantID string) ([]*domain.GatewayRoute, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	result := []*domain.GatewayRoute{}
	for _, value := range s.routes {
		if value.TenantID == tenantID {
			copied := clone(value)
			copied.AllowedMethods = append([]string{}, value.AllowedMethods...)
			result = append(result, copied)
		}
	}
	sort.Slice(result, func(i, j int) bool { return result[i].CreatedAt.Before(result[j].CreatedAt) })
	return result, nil
}
func (s *MemoryStore) CreateRoute(_ context.Context, route *domain.GatewayRoute) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, value := range s.routes {
		if value.TenantID == route.TenantID && value.GatewayPath == route.GatewayPath {
			return ErrConflict
		}
	}
	s.routes[route.ID] = clone(route)
	return nil
}
func (s *MemoryStore) GetRoute(_ context.Context, tenantID, id string) (*domain.GatewayRoute, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	value, ok := s.routes[id]
	if !ok || value.TenantID != tenantID {
		return nil, ErrNotFound
	}
	return clone(value), nil
}
func (s *MemoryStore) UpdateRoute(_ context.Context, route *domain.GatewayRoute) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.routes[route.ID]; !ok {
		return ErrNotFound
	}
	for _, value := range s.routes {
		if value.ID != route.ID && value.TenantID == route.TenantID && value.GatewayPath == route.GatewayPath {
			return ErrConflict
		}
	}
	s.routes[route.ID] = clone(route)
	return nil
}
func (s *MemoryStore) DeleteRoute(_ context.Context, tenantID, id string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	value, ok := s.routes[id]
	if !ok || value.TenantID != tenantID {
		return ErrNotFound
	}
	delete(s.routes, id)
	return nil
}
func (s *MemoryStore) FindRoute(_ context.Context, tenantID, path string) (*domain.GatewayRoute, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, value := range s.routes {
		if value.TenantID == tenantID && value.Active && (path == value.GatewayPath || strings.HasPrefix(path, strings.TrimSuffix(value.GatewayPath, "/")+"/")) {
			return clone(value), nil
		}
	}
	return nil, ErrNotFound
}
func (s *MemoryStore) GetPolicy(_ context.Context, tenantID, clientID, routeID string) (*domain.RateLimitPolicy, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, value := range s.policies {
		if value.TenantID == tenantID && (value.ClientID == clientID || value.ClientID == "") && (value.RouteID == routeID || value.RouteID == "") && value.Enabled {
			return clone(value), nil
		}
	}
	return nil, ErrNotFound
}
func (s *MemoryStore) UpsertPolicy(_ context.Context, policy *domain.RateLimitPolicy) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for id, value := range s.policies {
		if value.TenantID == policy.TenantID && value.ClientID == policy.ClientID && value.RouteID == policy.RouteID {
			s.policies[id] = clone(policy)
			return nil
		}
	}
	s.policies[policy.ID] = clone(policy)
	return nil
}
func (s *MemoryStore) InsertLog(_ context.Context, log *domain.RequestLog) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.logs = append(s.logs, clone(log))
	if len(s.logs) > 10000 {
		s.logs = s.logs[len(s.logs)-10000:]
	}
	return nil
}
func (s *MemoryStore) tenantLogs(tenantID string) []*domain.RequestLog {
	result := []*domain.RequestLog{}
	for _, value := range s.logs {
		if value.TenantID == tenantID {
			result = append(result, value)
		}
	}
	return result
}
func (s *MemoryStore) Summary(_ context.Context, tenantID string) (*domain.AnalyticsSummary, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	logs := s.tenantLogs(tenantID)
	summary := &domain.AnalyticsSummary{}
	routes := map[string]int{}
	clients := map[string]bool{}
	for _, log := range logs {
		summary.TotalRequests++
		if log.StatusCode >= 200 && log.StatusCode < 400 && !log.Blocked {
			summary.SuccessfulRequests++
		}
		if log.Blocked {
			summary.BlockedRequests++
		}
		summary.AverageResponseMS += float64(log.LatencyMS)
		routes[log.RouteID]++
		if log.ClientID != "" {
			clients[log.ClientID] = true
		}
	}
	if summary.TotalRequests > 0 {
		summary.AverageResponseMS /= float64(summary.TotalRequests)
	}
	summary.ActiveClients = int64(len(clients))
	mostCount := 0
	for routeID, count := range routes {
		if count > mostCount {
			mostCount = count
			if route, ok := s.routes[routeID]; ok {
				summary.MostUsedRoute = route.Name
			} else {
				summary.MostUsedRoute = routeID
			}
		}
	}
	return summary, nil
}
func (s *MemoryStore) Traffic(_ context.Context, tenantID string) (*domain.TrafficAnalytics, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	logs := s.tenantLogs(tenantID)
	traffic := &domain.TrafficAnalytics{RequestsOverTime: []domain.TrafficPoint{}, StatusDistribution: []domain.StatusCount{}, ByClient: []domain.NamedCount{}, BlockedByRoute: []domain.NamedCount{}, LatencyTrend: []domain.TrafficPoint{}}
	byHour := map[string]int64{}
	statuses := map[int]int64{}
	clients := map[string]int64{}
	blocked := map[string]int64{}
	latency := map[string]int64{}
	for _, log := range logs {
		hour := log.CreatedAt.UTC().Format("2006-01-02T15:00:00Z")
		byHour[hour]++
		statuses[log.StatusCode]++
		clients[log.ClientID]++
		latency[hour] += log.LatencyMS
		if log.Blocked {
			blocked[log.RouteID]++
		}
	}
	for key, count := range byHour {
		traffic.RequestsOverTime = append(traffic.RequestsOverTime, domain.TrafficPoint{Bucket: key, Count: count})
		traffic.LatencyTrend = append(traffic.LatencyTrend, domain.TrafficPoint{Bucket: key, Count: latency[key] / count})
	}
	for key, count := range statuses {
		traffic.StatusDistribution = append(traffic.StatusDistribution, domain.StatusCount{StatusCode: key, Count: count})
	}
	for key, count := range clients {
		name := key
		if client, ok := s.clients[key]; ok {
			name = client.Name
		}
		traffic.ByClient = append(traffic.ByClient, domain.NamedCount{Name: name, Count: count})
	}
	for key, count := range blocked {
		name := key
		if route, ok := s.routes[key]; ok {
			name = route.Name
		}
		traffic.BlockedByRoute = append(traffic.BlockedByRoute, domain.NamedCount{Name: name, Count: count})
	}
	return traffic, nil
}
func (s *MemoryStore) ListLogs(_ context.Context, tenantID string) ([]*domain.RequestLog, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	logs := s.tenantLogs(tenantID)
	result := make([]*domain.RequestLog, 0, len(logs))
	for i := len(logs) - 1; i >= 0; i-- {
		result = append(result, clone(logs[i]))
	}
	return result, nil
}
