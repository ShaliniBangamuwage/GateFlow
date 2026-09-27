package httpapi

import (
	"context"
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	jwt "github.com/golang-jwt/jwt/v5"

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

func TestAdminJWTValidationAndRoleEnforcement(t *testing.T) {
	store := storage.NewMemoryStore()
	now := time.Now().UTC()
	if err := store.CreateTenant(context.Background(), &domain.Tenant{ID: "tenant-a", Name: "Tenant A", Status: "active", CreatedAt: now, UpdatedAt: now}); err != nil {
		t.Fatal(err)
	}

	privateKey, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	publicDER, err := x509.MarshalPKIXPublicKey(&privateKey.PublicKey)
	if err != nil {
		t.Fatal(err)
	}
	publicPEM := pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: publicDER})
	viewerToken, err := jwt.NewWithClaims(jwt.SigningMethodRS256, jwt.MapClaims{
		"iss":       "https://issuer.example.com",
		"aud":       "gateflow-admin",
		"exp":       time.Now().Add(1 * time.Hour).Unix(),
		"role":      "viewer",
		"tenant_id": "tenant-a",
	}).SignedString(privateKey)
	if err != nil {
		t.Fatal(err)
	}

	server := NewServer(config.Config{
		AdminToken:        "admin",
		FrontendOrigin:    "*",
		AdminJWTIssuer:    "https://issuer.example.com",
		AdminJWTAudience:  "gateflow-admin",
		AdminJWTPublicKey: string(publicPEM),
		AdminRoleClaim:    "role",
		AdminTenantClaim:  "tenant_id",
	}, store, ratelimit.NewLocalLimiter(), slog.Default(), "tenant-a")

	viewerRequest := httptest.NewRequest(http.MethodPost, "/api/clients", strings.NewReader(`{"name":"Blocked"}`))
	viewerRequest.Header.Set("Authorization", "Bearer "+viewerToken)
	viewerRequest.Header.Set("X-Tenant-ID", "tenant-a")
	viewerResponse := httptest.NewRecorder()
	server.Handler().ServeHTTP(viewerResponse, viewerRequest)
	if viewerResponse.Code != http.StatusForbidden {
		t.Fatalf("viewer create client status = %d, want 403: %s", viewerResponse.Code, viewerResponse.Body.String())
	}
	viewerRead := httptest.NewRequest(http.MethodGet, "/api/clients", nil)
	viewerRead.Header.Set("Authorization", "Bearer "+viewerToken)
	viewerRead.Header.Set("X-Tenant-ID", "tenant-a")
	viewerReadResponse := httptest.NewRecorder()
	server.Handler().ServeHTTP(viewerReadResponse, viewerRead)
	if viewerReadResponse.Code != http.StatusOK {
		t.Fatalf("viewer list clients status = %d, want 200: %s", viewerReadResponse.Code, viewerReadResponse.Body.String())
	}
	otherTenantRequest := httptest.NewRequest(http.MethodGet, "/api/clients", nil)
	otherTenantRequest.Header.Set("Authorization", "Bearer "+viewerToken)
	otherTenantRequest.Header.Set("X-Tenant-ID", "tenant-b")
	otherTenantResponse := httptest.NewRecorder()
	server.Handler().ServeHTTP(otherTenantResponse, otherTenantRequest)
	if otherTenantResponse.Code != http.StatusForbidden {
		t.Fatalf("cross-tenant viewer status = %d, want 403", otherTenantResponse.Code)
	}

	adminToken, err := jwt.NewWithClaims(jwt.SigningMethodRS256, jwt.MapClaims{
		"iss":       "https://issuer.example.com",
		"aud":       "gateflow-admin",
		"exp":       time.Now().Add(1 * time.Hour).Unix(),
		"role":      "admin",
		"tenant_id": "tenant-a",
	}).SignedString(privateKey)
	if err != nil {
		t.Fatal(err)
	}

	adminRequest := httptest.NewRequest(http.MethodPost, "/api/clients", strings.NewReader(`{"name":"Allowed"}`))
	adminRequest.Header.Set("Authorization", "Bearer "+adminToken)
	adminRequest.Header.Set("X-Tenant-ID", "tenant-a")
	adminResponse := httptest.NewRecorder()
	server.Handler().ServeHTTP(adminResponse, adminRequest)
	if adminResponse.Code != http.StatusCreated {
		t.Fatalf("admin create client status = %d, want 201: %s", adminResponse.Code, adminResponse.Body.String())
	}

	productionServer := NewServer(config.Config{
		Environment:    "production",
		AdminToken:     "admin",
		FrontendOrigin: "*",
	}, store, ratelimit.NewLocalLimiter(), slog.Default(), "tenant-a")
	localTokenRequest := httptest.NewRequest(http.MethodGet, "/api/clients", nil)
	localTokenRequest.Header.Set("Authorization", "Bearer admin")
	localTokenRequest.Header.Set("X-Tenant-ID", "tenant-a")
	localTokenResponse := httptest.NewRecorder()
	productionServer.Handler().ServeHTTP(localTokenResponse, localTokenRequest)
	if localTokenResponse.Code != http.StatusUnauthorized {
		t.Fatalf("production local-token status = %d, want 401", localTokenResponse.Code)
	}
}

func TestAIFeatureProxyUsesAuthenticatedTenantAndInternalCredential(t *testing.T) {
	store := storage.NewMemoryStore()
	now := time.Now().UTC()
	if err := store.CreateTenant(context.Background(), &domain.Tenant{ID: "tenant-a", Name: "Tenant A", Status: "active", CreatedAt: now, UpdatedAt: now}); err != nil {
		t.Fatal(err)
	}
	var observedTenant, observedAuthorization, observedPath string
	ai := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		observedTenant = r.URL.Query().Get("tenant_id")
		observedAuthorization = r.Header.Get("Authorization")
		observedPath = r.URL.Path
		if r.URL.Query().Get("ignored") != "" {
			t.Error("unexpected query parameter forwarded")
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"count":0,"results":[],"model_version":"test"}`))
	}))
	defer ai.Close()

	server := NewServer(config.Config{
		AdminToken:         "admin",
		AIServiceURL:       ai.URL,
		AIServiceToken:     "internal-secret",
		AIServiceTimeoutMS: 1000,
		FrontendOrigin:     "*",
	}, store, ratelimit.NewLocalLimiter(), slog.Default(), "tenant-a")
	request := httptest.NewRequest(http.MethodGet, "/api/ai/anomalies?tenant_id=tenant-b&start_time=2026-09-26T00%3A00%3A00Z&end_time=2026-09-26T01%3A00%3A00Z&limit=50&ignored=bad", nil)
	request.Header.Set("Authorization", "Bearer admin")
	request.Header.Set("X-Tenant-ID", "tenant-a")
	response := httptest.NewRecorder()
	server.Handler().ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("AI proxy status = %d: %s", response.Code, response.Body.String())
	}
	if observedTenant != "tenant-a" || observedAuthorization != "Bearer internal-secret" || observedPath != "/api/ai/anomalies" {
		t.Fatalf("AI request tenant=%q auth=%q path=%q", observedTenant, observedAuthorization, observedPath)
	}
	if strings.Contains(response.Body.String(), "internal-secret") {
		t.Fatal("AI service credential leaked in response")
	}
}

func TestAIAssistantProxyForwardsQuestionAndOverridesBodyTenant(t *testing.T) {
	store := storage.NewMemoryStore()
	now := time.Now().UTC()
	if err := store.CreateTenant(context.Background(), &domain.Tenant{ID: "tenant-a", Name: "Tenant A", Status: "active", CreatedAt: now, UpdatedAt: now}); err != nil {
		t.Fatal(err)
	}
	var received struct {
		TenantID string `json:"tenant_id"`
		Question string `json:"question"`
	}
	ai := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if err := json.NewDecoder(r.Body).Decode(&received); err != nil {
			t.Errorf("decode assistant payload: %v", err)
		}
		if r.Header.Get("Authorization") != "Bearer internal-secret" {
			t.Errorf("internal Authorization header = %q", r.Header.Get("Authorization"))
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"answer":"observed response"}`))
	}))
	defer ai.Close()

	server := NewServer(config.Config{
		AdminToken:         "admin",
		AIServiceURL:       ai.URL,
		AIServiceToken:     "internal-secret",
		AIServiceTimeoutMS: 1000,
		FrontendOrigin:     "*",
	}, store, ratelimit.NewLocalLimiter(), slog.Default(), "tenant-a")
	request := httptest.NewRequest(http.MethodPost, "/api/ai/assistant", strings.NewReader(`{"tenant_id":"tenant-b","question":"Summarize observed traffic"}`))
	request.Header.Set("Authorization", "Bearer admin")
	request.Header.Set("X-Tenant-ID", "tenant-a")
	response := httptest.NewRecorder()
	server.Handler().ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("assistant proxy status = %d: %s", response.Code, response.Body.String())
	}
	if received.TenantID != "tenant-a" || received.Question != "Summarize observed traffic" {
		t.Fatalf("assistant payload tenant=%q question=%q", received.TenantID, received.Question)
	}
}

func TestAIFailureDoesNotAffectGatewayReadinessOrProxying(t *testing.T) {
	store := storage.NewMemoryStore()
	now := time.Now().UTC()
	if err := store.CreateTenant(context.Background(), &domain.Tenant{ID: "tenant-a", Name: "Tenant A", Status: "active", CreatedAt: now, UpdatedAt: now}); err != nil {
		t.Fatal(err)
	}
	server := NewServer(config.Config{AdminToken: "admin", FrontendOrigin: "*"}, store, ratelimit.NewLocalLimiter(), slog.Default(), "tenant-a")
	request := httptest.NewRequest(http.MethodGet, "/api/ai/anomalies", nil)
	request.Header.Set("Authorization", "Bearer admin")
	request.Header.Set("X-Tenant-ID", "tenant-a")
	response := httptest.NewRecorder()
	server.Handler().ServeHTTP(response, request)
	if response.Code != http.StatusServiceUnavailable {
		t.Fatalf("AI unavailable status = %d, want 503", response.Code)
	}
	ready := httptest.NewRecorder()
	server.Handler().ServeHTTP(ready, httptest.NewRequest(http.MethodGet, "/readyz", nil))
	if ready.Code != http.StatusOK {
		t.Fatalf("gateway readiness status = %d, want 200", ready.Code)
	}
}
