package httpapi

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"gateflow/internal/apikey"
	"gateflow/internal/config"
	"gateflow/internal/domain"
	"gateflow/internal/ratelimit"
	"gateflow/internal/storage"
)

func TestGatewayProxiesAuthenticatedRequestAndRejectsOverLimit(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"ok":true,"path":"` + r.URL.Path + `"}`))
	}))
	defer upstream.Close()

	store := storage.NewMemoryStore()
	now := time.Now().UTC()
	tenant := &domain.Tenant{ID: "tenant-a", Name: "Tenant A", Status: "active", CreatedAt: now, UpdatedAt: now}
	if err := store.CreateTenant(context.Background(), tenant); err != nil {
		t.Fatal(err)
	}
	client := &domain.APIClient{ID: "client-a", TenantID: tenant.ID, Name: "Client A", Status: "active", CreatedAt: now, UpdatedAt: now}
	policy := &domain.RateLimitPolicy{ID: "policy-a", TenantID: tenant.ID, ClientID: client.ID, Capacity: 1, RefillRate: 0, Enabled: true, CreatedAt: now, UpdatedAt: now}
	key := "gf_test_key_secret"
	client.KeyPrefix = apikey.Prefix(key)
	client.KeyHash = apikey.Hash(key)
	if err := store.CreateClient(context.Background(), client); err != nil {
		t.Fatal(err)
	}
	if err := store.UpsertPolicy(context.Background(), policy); err != nil {
		t.Fatal(err)
	}
	route := &domain.GatewayRoute{ID: "route-a", TenantID: tenant.ID, Name: "Products", GatewayPath: "/gateway", UpstreamURL: upstream.URL, AllowedMethods: []string{"GET"}, TimeoutMS: 5000, AuthenticationRequired: true, Active: true, CreatedAt: now, UpdatedAt: now}
	if err := store.CreateRoute(context.Background(), route); err != nil {
		t.Fatal(err)
	}

	server := NewServer(config.Config{FrontendOrigin: "http://localhost:5173"}, store, ratelimit.NewLocalLimiter(), slog.Default(), tenant.ID)
	request := httptest.NewRequest(http.MethodGet, "/gateway/products", nil)
	request.Header.Set("X-API-Key", key)
	response := httptest.NewRecorder()
	server.Handler().ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("proxy status = %d, want 200: %s", response.Code, response.Body.String())
	}
	body, _ := io.ReadAll(response.Body)
	if string(body) == "" {
		t.Fatal("expected upstream response")
	}

	secondRequest := httptest.NewRequest(http.MethodGet, "/gateway/products", nil)
	secondRequest.Header.Set("X-API-Key", key)
	second := httptest.NewRecorder()
	server.Handler().ServeHTTP(second, secondRequest)
	if second.Code != http.StatusTooManyRequests {
		t.Fatalf("second status = %d, want 429", second.Code)
	}
}

func TestAdminRequiresTenantAndDoesNotReturnKeyHash(t *testing.T) {
	store := storage.NewMemoryStore()
	now := time.Now().UTC()
	if err := store.CreateTenant(context.Background(), &domain.Tenant{ID: "tenant-a", Name: "Tenant A", Status: "active", CreatedAt: now, UpdatedAt: now}); err != nil {
		t.Fatal(err)
	}
	server := NewServer(config.Config{AdminToken: "admin", FrontendOrigin: "*"}, store, ratelimit.NewLocalLimiter(), slog.Default(), "tenant-a")
	unauthorized := httptest.NewRecorder()
	server.Handler().ServeHTTP(unauthorized, httptest.NewRequest(http.MethodGet, "/api/clients", nil))
	if unauthorized.Code != http.StatusUnauthorized || unauthorized.Header().Get("X-Request-ID") == "" {
		t.Fatalf("unauthorized response = %d, request id = %q", unauthorized.Code, unauthorized.Header().Get("X-Request-ID"))
	}

	request := httptest.NewRequest(http.MethodPost, "/api/clients", strings.NewReader(`{"name":"Test"}`))
	request.Header.Set("Authorization", "Bearer admin")
	request.Header.Set("X-Tenant-ID", "tenant-a")
	response := httptest.NewRecorder()
	server.Handler().ServeHTTP(response, request)
	if response.Code != http.StatusCreated {
		t.Fatalf("create client status = %d: %s", response.Code, response.Body.String())
	}
	var payload map[string]any
	if err := json.NewDecoder(response.Body).Decode(&payload); err != nil {
		t.Fatal(err)
	}
	client := payload["client"].(map[string]any)
	if _, exists := client["keyHash"]; exists {
		t.Fatal("client response exposed key hash")
	}
}
