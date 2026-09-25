package storage

import (
	"context"
	"gateflow/internal/domain"
	"time"
)

type Store interface {
	Close() error
	Health(context.Context) error
	CreateTenant(context.Context, *domain.Tenant) error
	GetTenant(context.Context, string) (*domain.Tenant, error)
	ListClients(context.Context, string) ([]*domain.APIClient, error)
	CreateClient(context.Context, *domain.APIClient) error
	GetClientByID(context.Context, string, string) (*domain.APIClient, error)
	FindClientByPrefix(context.Context, string) (*domain.APIClient, error)
	UpdateClient(context.Context, *domain.APIClient) error
	TouchClient(context.Context, string, string, time.Time) error
	ListRoutes(context.Context, string) ([]*domain.GatewayRoute, error)
	CreateRoute(context.Context, *domain.GatewayRoute) error
	GetRoute(context.Context, string, string) (*domain.GatewayRoute, error)
	UpdateRoute(context.Context, *domain.GatewayRoute) error
	DeleteRoute(context.Context, string, string) error
	FindRoute(context.Context, string, string) (*domain.GatewayRoute, error)
	GetPolicy(context.Context, string, string, string) (*domain.RateLimitPolicy, error)
	UpsertPolicy(context.Context, *domain.RateLimitPolicy) error
	InsertLog(context.Context, *domain.RequestLog) error
	Summary(context.Context, string) (*domain.AnalyticsSummary, error)
	Traffic(context.Context, string) (*domain.TrafficAnalytics, error)
	ListLogs(context.Context, string) ([]*domain.RequestLog, error)
}
