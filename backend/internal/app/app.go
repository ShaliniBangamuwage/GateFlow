package app

import (
	"context"
	"fmt"
	"gateflow/internal/apikey"
	"gateflow/internal/config"
	"gateflow/internal/domain"
	"gateflow/internal/ratelimit"
	"gateflow/internal/storage"
	"log/slog"
	"os"
	"time"
)

type Runtime struct {
	Store      storage.Store
	Limiter    ratelimit.Limiter
	Close      func() error
	TenantID   string
	DemoAPIKey string
}

func Initialize(ctx context.Context, cfg config.Config, logger *slog.Logger) (*Runtime, error) {
	var store storage.Store
	var closeFns []func() error
	if cfg.DatabaseURL != "" {
		postgres, err := storage.OpenPostgres(cfg.DatabaseURL)
		if err != nil {
			return nil, err
		}
		schema, err := readSchema()
		if err != nil {
			postgres.Close()
			return nil, err
		}
		if err := postgres.Migrate(ctx, string(schema)); err != nil {
			postgres.Close()
			return nil, err
		}
		store = postgres
		closeFns = append(closeFns, postgres.Close)
	} else {
		store = storage.NewMemoryStore()
	}
	var limiter ratelimit.Limiter = ratelimit.NewLocalLimiter()
	if cfg.RedisURL != "" {
		redisLimiter, err := ratelimit.NewRedisLimiter(cfg.RedisURL)
		if err != nil {
			store.Close()
			return nil, err
		}
		limiter = redisLimiter
		closeFns = append(closeFns, redisLimiter.Close)
	}
	if err := seed(ctx, store, cfg, logger); err != nil {
		for _, closeFn := range closeFns {
			_ = closeFn()
		}
		return nil, err
	}
	return &Runtime{Store: store, Limiter: limiter, TenantID: cfg.SeedTenantID, DemoAPIKey: cfg.SeedAPIKey, Close: func() error {
		for i := len(closeFns) - 1; i >= 0; i-- {
			if err := closeFns[i](); err != nil {
				return err
			}
		}
		if len(closeFns) == 0 {
			return store.Close()
		}
		return nil
	}}, nil
}

func readSchema() ([]byte, error) {
	for _, path := range []string{"migrations/001_init.sql", "../migrations/001_init.sql"} {
		if value, err := os.ReadFile(path); err == nil {
			return value, nil
		}
	}
	return nil, fmt.Errorf("migration file not found")
}
func seed(ctx context.Context, store storage.Store, cfg config.Config, logger *slog.Logger) error {
	now := time.Now().UTC()
	tenant := &domain.Tenant{ID: cfg.SeedTenantID, Name: cfg.SeedTenantName, Status: "active", CreatedAt: now, UpdatedAt: now}
	if _, err := store.GetTenant(ctx, tenant.ID); err != nil {
		if err := store.CreateTenant(ctx, tenant); err != nil {
			return err
		}
	}
	key := cfg.SeedAPIKey
	if key == "" {
		key = "gf_local_demo_key"
		logger.Warn("using local demo API key; set SEED_API_KEY outside development")
	}
	existing, err := store.ListClients(ctx, tenant.ID)
	if err != nil {
		return err
	}
	if len(existing) > 0 {
		return nil
	}
	prefix := apikey.Prefix(key)
	client := &domain.APIClient{ID: domain.NewID(), TenantID: tenant.ID, Name: "Local Demo Client", KeyPrefix: prefix, KeyHash: apikey.Hash(key), Status: "active", CreatedAt: now, UpdatedAt: now}
	if err := store.CreateClient(ctx, client); err != nil {
		return err
	}
	policy := &domain.RateLimitPolicy{ID: domain.NewID(), TenantID: tenant.ID, ClientID: client.ID, Capacity: 5, RefillRate: 1, Enabled: true, CreatedAt: now, UpdatedAt: now}
	if err := store.UpsertPolicy(ctx, policy); err != nil {
		return err
	}
	route := &domain.GatewayRoute{ID: domain.NewID(), TenantID: tenant.ID, Name: "Gateway default", GatewayPath: "/gateway", UpstreamURL: cfg.MockUpstreamURL, AllowedMethods: []string{"GET", "POST", "PUT", "PATCH", "DELETE"}, TimeoutMS: 5000, AuthenticationRequired: true, Active: true, CreatedAt: now, UpdatedAt: now}
	if err := store.CreateRoute(ctx, route); err != nil {
		return err
	}
	logger.Info("seeded_local_demo", "tenant_id", tenant.ID, "api_key_prefix", prefix)
	return nil
}
