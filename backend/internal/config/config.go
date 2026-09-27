package config

import (
	"os"
	"strconv"
)

// Config holds runtime settings used by the gateway backend.
type Config struct {
	Port               int
	AdminToken         string
	AdminJWTIssuer     string
	AdminJWTAudience   string
	AdminJWTPublicKey  string
	AdminRoleClaim     string
	AdminTenantClaim   string
	AIServiceURL       string
	AIServiceToken     string
	AIServiceTimeoutMS int
	DatabaseURL        string
	RedisURL           string
	FrontendOrigin     string
	SeedTenantName     string
	SeedTenantID       string
	SeedAPIKey         string
	UpstreamURL        string
	MockUpstreamURL    string
	Environment        string
}

// Load reads configuration from environment variables.
func Load() Config {
	return Config{
		Port:               envInt("PORT", 8080),
		AdminToken:         envString("ADMIN_TOKEN", "gateflow-local-admin"),
		AdminJWTIssuer:     envString("ADMIN_JWT_ISSUER", ""),
		AdminJWTAudience:   envString("ADMIN_JWT_AUDIENCE", "gateflow-admin"),
		AdminJWTPublicKey:  os.Getenv("ADMIN_JWT_PUBLIC_KEY"),
		AdminRoleClaim:     envString("ADMIN_ROLE_CLAIM", "role"),
		AdminTenantClaim:   envString("ADMIN_TENANT_CLAIM", "tenant_id"),
		AIServiceURL:       os.Getenv("AI_SERVICE_URL"),
		AIServiceToken:     os.Getenv("AI_SERVICE_TOKEN"),
		AIServiceTimeoutMS: envInt("AI_SERVICE_TIMEOUT_MS", 8000),
		DatabaseURL:        os.Getenv("DATABASE_URL"),
		RedisURL:           os.Getenv("REDIS_URL"),
		FrontendOrigin:     envString("FRONTEND_ORIGIN", "http://localhost:5173"),
		SeedTenantName:     envString("SEED_TENANT_NAME", "Local Demo Tenant"),
		SeedTenantID:       envString("SEED_TENANT_ID", "local-tenant"),
		SeedAPIKey:         os.Getenv("SEED_API_KEY"),
		UpstreamURL:        envString("UPSTREAM_URL", "http://localhost:9090"),
		MockUpstreamURL:    envString("MOCK_UPSTREAM_URL", "http://localhost:9090"),
		Environment:        envString("APP_ENV", "development"),
	}
}

func envString(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}

func envInt(name string, fallback int) int {
	value, err := strconv.Atoi(os.Getenv(name))
	if err != nil || value <= 0 {
		return fallback
	}
	return value
}
