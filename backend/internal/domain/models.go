package domain

import "time"

type Tenant struct {
	ID        string    `json:"id"`
	Name      string    `json:"name"`
	Status    string    `json:"status"`
	CreatedAt time.Time `json:"createdAt"`
	UpdatedAt time.Time `json:"updatedAt"`
}

type APIClient struct {
	ID         string           `json:"id"`
	TenantID   string           `json:"tenantId"`
	Name       string           `json:"name"`
	KeyPrefix  string           `json:"apiKeyPrefix"`
	KeyHash    string           `json:"-"`
	Status     string           `json:"status"`
	CreatedAt  time.Time        `json:"createdAt"`
	UpdatedAt  time.Time        `json:"updatedAt"`
	LastUsedAt *time.Time       `json:"lastUsedAt,omitempty"`
	RateLimit  *RateLimitPolicy `json:"rateLimit,omitempty"`
}

type GatewayRoute struct {
	ID                     string    `json:"id"`
	TenantID               string    `json:"tenantId"`
	Name                   string    `json:"name"`
	GatewayPath            string    `json:"gatewayPath"`
	UpstreamURL            string    `json:"upstreamUrl"`
	AllowedMethods         []string  `json:"allowedMethods"`
	TimeoutMS              int       `json:"timeoutMs"`
	AuthenticationRequired bool      `json:"authenticationRequired"`
	Active                 bool      `json:"active"`
	CreatedAt              time.Time `json:"createdAt"`
	UpdatedAt              time.Time `json:"updatedAt"`
}

type RateLimitPolicy struct {
	ID         string    `json:"id"`
	TenantID   string    `json:"tenantId"`
	ClientID   string    `json:"apiClientId,omitempty"`
	RouteID    string    `json:"routeId,omitempty"`
	Capacity   float64   `json:"bucketCapacity"`
	RefillRate float64   `json:"refillRate"`
	Enabled    bool      `json:"enabled"`
	CreatedAt  time.Time `json:"createdAt"`
	UpdatedAt  time.Time `json:"updatedAt"`
}

type RequestLog struct {
	ID         string    `json:"id"`
	RequestID  string    `json:"requestId"`
	TenantID   string    `json:"tenantId"`
	ClientID   string    `json:"clientId,omitempty"`
	RouteID    string    `json:"routeId,omitempty"`
	Method     string    `json:"method"`
	StatusCode int       `json:"statusCode"`
	LatencyMS  int64     `json:"latencyMilliseconds"`
	Blocked    bool      `json:"blocked"`
	CreatedAt  time.Time `json:"createdAt"`
}

type AnalyticsSummary struct {
	TotalRequests      int64   `json:"totalRequests"`
	SuccessfulRequests int64   `json:"successfulRequests"`
	BlockedRequests    int64   `json:"blockedRequests"`
	AverageResponseMS  float64 `json:"averageResponseTime"`
	ActiveClients      int64   `json:"activeClients"`
	MostUsedRoute      string  `json:"mostUsedRoute"`
}

type TrafficPoint struct {
	Bucket string `json:"bucket"`
	Count  int64  `json:"count"`
}

type StatusCount struct {
	StatusCode int   `json:"statusCode"`
	Count      int64 `json:"count"`
}

type NamedCount struct {
	Name  string `json:"name"`
	Count int64  `json:"count"`
}

type TrafficAnalytics struct {
	RequestsOverTime   []TrafficPoint `json:"requestsOverTime"`
	StatusDistribution []StatusCount  `json:"statusDistribution"`
	ByClient           []NamedCount   `json:"requestsByClient"`
	BlockedByRoute     []NamedCount   `json:"blockedRequestsByRoute"`
	LatencyTrend       []TrafficPoint `json:"latencyTrend"`
}
