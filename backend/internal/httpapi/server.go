package httpapi

import (
	"bytes"
	"context"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"errors"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strconv"
	"strings"
	"time"

	jwt "github.com/golang-jwt/jwt/v5"

	"gateflow/internal/apikey"
	"gateflow/internal/config"
	"gateflow/internal/domain"
	"gateflow/internal/ratelimit"
	"gateflow/internal/storage"
)

type Server struct {
	cfg           config.Config
	store         storage.Store
	limiter       ratelimit.Limiter
	logger        *slog.Logger
	defaultTenant string
	aiClient      *http.Client
}

func NewServer(cfg config.Config, store storage.Store, limiter ratelimit.Limiter, logger *slog.Logger, defaultTenant string) *Server {
	if logger == nil {
		logger = slog.New(slog.NewTextHandler(io.Discard, nil))
	}
	timeout := time.Duration(cfg.AIServiceTimeoutMS) * time.Millisecond
	if timeout <= 0 {
		timeout = 8 * time.Second
	}
	return &Server{cfg: cfg, store: store, limiter: limiter, logger: logger, defaultTenant: defaultTenant, aiClient: &http.Client{Timeout: timeout}}
}
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", s.health)
	mux.HandleFunc("/readyz", s.ready)
	mux.HandleFunc("/ready", s.ready)
	mux.Handle("/api/", s.adminAuth(http.HandlerFunc(s.api)))
	mux.Handle("/gateway/", s.requestID(http.HandlerFunc(s.gateway)))
	mux.Handle("/gateway", s.requestID(http.HandlerFunc(s.gateway)))
	return s.cors(s.requestID(mux))
}
func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeJSON(w, 405, map[string]string{"error": "METHOD_NOT_ALLOWED"})
		return
	}
	writeJSON(w, 200, map[string]string{"status": "ok", "service": "gateflow"})
}
func (s *Server) ready(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	if err := s.store.Health(ctx); err != nil {
		writeJSON(w, 503, map[string]string{"status": "not_ready", "error": "DATABASE_UNAVAILABLE"})
		return
	}
	if err := s.limiter.Health(ctx); err != nil {
		writeJSON(w, 503, map[string]string{"status": "not_ready", "error": "REDIS_UNAVAILABLE"})
		return
	}
	writeJSON(w, 200, map[string]string{"status": "ready"})
}
func (s *Server) cors(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", s.cfg.FrontendOrigin)
		w.Header().Set("Access-Control-Allow-Headers", "Authorization,Content-Type,X-API-Key,X-Tenant-ID,X-Request-ID")
		w.Header().Set("Access-Control-Allow-Methods", "GET,POST,PATCH,DELETE,OPTIONS")
		if r.Method == http.MethodOptions {
			w.WriteHeader(204)
			return
		}
		next.ServeHTTP(w, r)
	})
}
func (s *Server) adminAuth(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		principal, ok := s.authenticateAdmin(r)
		if !ok {
			writeJSON(w, 401, map[string]string{"error": "UNAUTHORIZED", "message": "Administrator authentication required."})
			return
		}
		if !principal.hasRequiredRole(r.Method) {
			writeJSON(w, 403, map[string]string{"error": "FORBIDDEN", "message": "Insufficient administrator role."})
			return
		}
		if !principal.local && principal.tenantID != s.tenantID(r) {
			writeJSON(w, 403, map[string]string{"error": "FORBIDDEN", "message": "Token is not authorized for the requested tenant."})
			return
		}
		path := strings.TrimPrefix(r.URL.Path, "/api/")
		if path == "tenants" && r.Method == http.MethodPost {
			next.ServeHTTP(w, r)
			return
		}
		if strings.TrimSpace(s.tenantID(r)) == "" {
			writeJSON(w, 400, map[string]string{"error": "TENANT_REQUIRED", "message": "A tenant identifier is required."})
			return
		}
		if _, err := s.store.GetTenant(r.Context(), s.tenantID(r)); err != nil {
			writeStoreError(w, err)
			return
		}
		next.ServeHTTP(w, r)
	})
}

type adminPrincipal struct {
	role     string
	tenantID string
	local    bool
}

func (p adminPrincipal) hasRequiredRole(method string) bool {
	if p.local || p.role == "admin" {
		return true
	}
	if p.role == "viewer" {
		return method == http.MethodGet
	}
	return false
}

func (s *Server) authenticateAdmin(r *http.Request) (adminPrincipal, bool) {
	value := r.Header.Get("Authorization")
	if !strings.HasPrefix(value, "Bearer ") {
		return adminPrincipal{}, false
	}
	tokenValue := strings.TrimPrefix(value, "Bearer ")
	if s.cfg.Environment != "production" && tokenValue == s.cfg.AdminToken {
		return adminPrincipal{local: true}, true
	}
	if s.cfg.AdminJWTIssuer == "" || s.cfg.AdminJWTPublicKey == "" {
		return adminPrincipal{}, false
	}
	publicKey, err := parsePublicKey(s.cfg.AdminJWTPublicKey)
	if err != nil {
		return adminPrincipal{}, false
	}
	parsed, err := jwt.Parse(tokenValue, func(token *jwt.Token) (any, error) {
		if _, ok := token.Method.(*jwt.SigningMethodRSA); !ok {
			return nil, errors.New("unexpected signing method")
		}
		return publicKey, nil
	})
	if err != nil || !parsed.Valid {
		return adminPrincipal{}, false
	}
	claims, ok := parsed.Claims.(jwt.MapClaims)
	if !ok {
		return adminPrincipal{}, false
	}
	issuer, _ := claims.GetIssuer()
	if issuer != s.cfg.AdminJWTIssuer {
		return adminPrincipal{}, false
	}
	audience, err := claims.GetAudience()
	if err != nil || len(audience) == 0 || !containsAudience(audience, s.cfg.AdminJWTAudience) {
		return adminPrincipal{}, false
	}
	exp, err := claims.GetExpirationTime()
	if err != nil || exp == nil || time.Until(exp.Time) <= 0 {
		return adminPrincipal{}, false
	}
	role, _ := claims[s.cfg.AdminRoleClaim].(string)
	tenantID, _ := claims[s.cfg.AdminTenantClaim].(string)
	if strings.TrimSpace(tenantID) == "" {
		return adminPrincipal{}, false
	}
	return adminPrincipal{role: strings.ToLower(role), tenantID: tenantID}, true
}

func containsAudience(values jwt.ClaimStrings, want string) bool {
	for _, value := range values {
		if value == want {
			return true
		}
	}
	return false
}

func parsePublicKey(value string) (any, error) {
	block, _ := pem.Decode([]byte(value))
	if block == nil {
		return nil, errors.New("invalid PEM")
	}
	if block.Type != "PUBLIC KEY" && block.Type != "RSA PUBLIC KEY" {
		return nil, errors.New("unsupported public key format")
	}
	key, err := x509.ParsePKIXPublicKey(block.Bytes)
	if err == nil {
		return key, nil
	}
	return x509.ParsePKCS1PublicKey(block.Bytes)
}
func (s *Server) tenantID(r *http.Request) string {
	if value := r.Header.Get("X-Tenant-ID"); value != "" {
		return value
	}
	return s.defaultTenant
}
func (s *Server) api(w http.ResponseWriter, r *http.Request) {
	path := strings.TrimPrefix(r.URL.Path, "/api/")
	switch {
	case path == "tenants":
		s.tenants(w, r)
	case path == "clients":
		s.clients(w, r)
	case strings.HasPrefix(path, "clients/"):
		s.clientAction(w, r, strings.TrimPrefix(path, "clients/"))
	case path == "routes":
		s.routes(w, r)
	case strings.HasPrefix(path, "routes/"):
		s.routeAction(w, r, strings.TrimPrefix(path, "routes/"))
	case path == "analytics/summary":
		s.summary(w, r)
	case path == "analytics/traffic":
		s.traffic(w, r)
	case path == "analytics/logs":
		s.logs(w, r)
	case path == "ai/anomalies":
		s.aiAnomalies(w, r)
	case path == "ai/overview", path == "ai/recent-anomalies", path == "ai/forecast", path == "ai/assistant", path == "ai/incident-analysis":
		s.aiDashboardProxy(w, r, strings.TrimPrefix(path, "ai/"))
	default:
		writeJSON(w, 404, map[string]string{"error": "NOT_FOUND"})
	}
}

// aiAnomalies forwards only an allowlisted set of filters and the tenant
// resolved by Go's authenticated admin boundary. Browser-supplied tenant IDs
// never reach the AI service as trusted identity.
func (s *Server) aiAnomalies(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "METHOD_NOT_ALLOWED"})
		return
	}
	if strings.TrimSpace(s.cfg.AIServiceURL) == "" || strings.TrimSpace(s.cfg.AIServiceToken) == "" {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "AI_SERVICE_UNAVAILABLE"})
		return
	}
	base, err := url.Parse(strings.TrimRight(s.cfg.AIServiceURL, "/"))
	if err != nil || (base.Scheme != "http" && base.Scheme != "https") || base.Host == "" {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "AI_SERVICE_UNAVAILABLE"})
		return
	}
	target := base.ResolveReference(&url.URL{Path: "/api/ai/anomalies"})
	query := url.Values{}
	query.Set("tenant_id", s.tenantID(r))
	for _, key := range []string{"start_time", "end_time", "client_id", "route_id", "limit"} {
		if value := r.URL.Query().Get(key); value != "" {
			query.Set(key, value)
		}
	}
	target.RawQuery = query.Encode()
	request, err := http.NewRequestWithContext(r.Context(), http.MethodGet, target.String(), nil)
	if err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "AI_SERVICE_UNAVAILABLE"})
		return
	}
	request.Header.Set("Authorization", "Bearer "+s.cfg.AIServiceToken)
	request.Header.Set("Accept", "application/json")
	response, err := s.aiClient.Do(request)
	if err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "AI_SERVICE_UNAVAILABLE"})
		return
	}
	defer response.Body.Close()
	if response.StatusCode == http.StatusBadRequest || response.StatusCode == http.StatusUnprocessableEntity {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "INVALID_AI_REQUEST"})
		return
	}
	if response.StatusCode != http.StatusOK {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "AI_SERVICE_UNAVAILABLE"})
		return
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, (2<<20)+1))
	if err != nil || len(body) > 2<<20 {
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": "INVALID_AI_RESPONSE"})
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(body)
}

func (s *Server) aiDashboardProxy(w http.ResponseWriter, r *http.Request, route string) {
	if route == "assistant" {
		if r.Method != http.MethodPost {
			writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "METHOD_NOT_ALLOWED"})
			return
		}
	} else if r.Method != http.MethodGet {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "METHOD_NOT_ALLOWED"})
		return
	}
	if strings.TrimSpace(s.cfg.AIServiceURL) == "" || strings.TrimSpace(s.cfg.AIServiceToken) == "" {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "AI_SERVICE_UNAVAILABLE"})
		return
	}
	base, err := url.Parse(strings.TrimRight(s.cfg.AIServiceURL, "/"))
	if err != nil || (base.Scheme != "http" && base.Scheme != "https") || base.Host == "" {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "AI_SERVICE_UNAVAILABLE"})
		return
	}
	target := base.ResolveReference(&url.URL{Path: "/api/ai/" + route})
	if route == "assistant" {
		var payload struct {
			Question string `json:"question"`
		}
		decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 16<<10))
		if err := decoder.Decode(&payload); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "INVALID_AI_REQUEST"})
			return
		}
		var trailing any
		if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "INVALID_AI_REQUEST"})
			return
		}
		question := strings.TrimSpace(payload.Question)
		if question == "" {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "INVALID_AI_REQUEST"})
			return
		}
		forwardPayload := map[string]string{"tenant_id": s.tenantID(r), "question": question}
		body, err := json.Marshal(forwardPayload)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "INVALID_AI_REQUEST"})
			return
		}
		request, err := http.NewRequestWithContext(r.Context(), http.MethodPost, target.String(), bytes.NewReader(body))
		if err != nil {
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "AI_SERVICE_UNAVAILABLE"})
			return
		}
		request.Header.Set("Authorization", "Bearer "+s.cfg.AIServiceToken)
		request.Header.Set("Content-Type", "application/json")
		request.Header.Set("Accept", "application/json")
		response, err := s.aiClient.Do(request)
		if err != nil {
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "AI_SERVICE_UNAVAILABLE"})
			return
		}
		defer response.Body.Close()
		if response.StatusCode >= 400 {
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "AI_SERVICE_UNAVAILABLE"})
			return
		}
		bodyResp, err := io.ReadAll(io.LimitReader(response.Body, (2<<20)+1))
		if err != nil || len(bodyResp) > 2<<20 {
			writeJSON(w, http.StatusBadGateway, map[string]string{"error": "INVALID_AI_RESPONSE"})
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(bodyResp)
		return
	}
	query := url.Values{}
	query.Set("tenant_id", s.tenantID(r))
	for _, key := range []string{"start_time", "end_time", "client_id", "route_id", "limit"} {
		if value := r.URL.Query().Get(key); value != "" {
			query.Set(key, value)
		}
	}
	target.RawQuery = query.Encode()
	request, err := http.NewRequestWithContext(r.Context(), http.MethodGet, target.String(), nil)
	if err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "AI_SERVICE_UNAVAILABLE"})
		return
	}
	request.Header.Set("Authorization", "Bearer "+s.cfg.AIServiceToken)
	request.Header.Set("Accept", "application/json")
	response, err := s.aiClient.Do(request)
	if err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "AI_SERVICE_UNAVAILABLE"})
		return
	}
	defer response.Body.Close()
	if response.StatusCode >= 400 {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "AI_SERVICE_UNAVAILABLE"})
		return
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, (2<<20)+1))
	if err != nil || len(body) > 2<<20 {
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": "INVALID_AI_RESPONSE"})
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(body)
}
func (s *Server) tenants(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]string{"error": "METHOD_NOT_ALLOWED"})
		return
	}
	var input struct {
		Name string `json:"name"`
	}
	if !decode(w, r, &input) || strings.TrimSpace(input.Name) == "" {
		return
	}
	now := time.Now().UTC()
	tenant := &domain.Tenant{ID: domain.NewID(), Name: strings.TrimSpace(input.Name), Status: "active", CreatedAt: now, UpdatedAt: now}
	if err := s.store.CreateTenant(r.Context(), tenant); err != nil {
		writeStoreError(w, err)
		return
	}
	writeJSON(w, 201, tenant)
}
func (s *Server) clients(w http.ResponseWriter, r *http.Request) {
	tenantID := s.tenantID(r)
	switch r.Method {
	case http.MethodGet:
		values, err := s.store.ListClients(r.Context(), tenantID)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		for _, value := range values {
			value.KeyHash = ""
			if policy, policyErr := s.store.GetPolicy(r.Context(), tenantID, value.ID, ""); policyErr == nil {
				value.RateLimit = policy
			}
		}
		writeJSON(w, 200, map[string]any{"clients": values})
	case http.MethodPost:
		var input struct {
			Name       string  `json:"name"`
			Capacity   float64 `json:"bucketCapacity"`
			RefillRate float64 `json:"refillRate"`
		}
		if !decode(w, r, &input) {
			return
		}
		if input.Capacity <= 0 {
			input.Capacity = 5
		}
		if input.RefillRate < 0 {
			writeJSON(w, 400, map[string]string{"error": "INVALID_RATE_LIMIT"})
			return
		}
		key, prefix, hash, err := apikey.Generate()
		if err != nil {
			writeJSON(w, 500, map[string]string{"error": "KEY_GENERATION_FAILED"})
			return
		}
		now := time.Now().UTC()
		client := &domain.APIClient{ID: domain.NewID(), TenantID: tenantID, Name: strings.TrimSpace(input.Name), KeyPrefix: prefix, KeyHash: hash, Status: "active", CreatedAt: now, UpdatedAt: now, RateLimit: &domain.RateLimitPolicy{ID: domain.NewID(), TenantID: tenantID, Capacity: input.Capacity, RefillRate: input.RefillRate, Enabled: true, CreatedAt: now, UpdatedAt: now}}
		if client.Name == "" {
			client.Name = "Unnamed client"
		}
		if err := s.store.CreateClient(r.Context(), client); err != nil {
			writeStoreError(w, err)
			return
		}
		if err := s.store.UpsertPolicy(r.Context(), client.RateLimit); err != nil {
			writeStoreError(w, err)
			return
		}
		client.KeyHash = ""
		writeJSON(w, 201, map[string]any{"client": client, "apiKey": key, "warning": "Store this API key now. It will not be shown again."})
	default:
		writeJSON(w, 405, map[string]string{"error": "METHOD_NOT_ALLOWED"})
	}
}
func (s *Server) clientAction(w http.ResponseWriter, r *http.Request, id string) {
	parts := strings.Split(strings.Trim(id, "/"), "/")
	if len(parts) < 2 {
		writeJSON(w, 404, map[string]string{"error": "NOT_FOUND"})
		return
	}
	client, err := s.store.GetClientByID(r.Context(), s.tenantID(r), parts[0])
	if err != nil {
		writeStoreError(w, err)
		return
	}
	switch parts[1] {
	case "rate-limit":
		if r.Method != http.MethodPatch {
			writeJSON(w, 405, map[string]string{"error": "METHOD_NOT_ALLOWED"})
			return
		}
		var input struct {
			Capacity   float64 `json:"bucketCapacity"`
			RefillRate float64 `json:"refillRate"`
			Enabled    bool    `json:"enabled"`
		}
		if !decode(w, r, &input) {
			return
		}
		if input.Capacity <= 0 || input.RefillRate < 0 {
			writeJSON(w, 400, map[string]string{"error": "INVALID_RATE_LIMIT", "message": "Capacity must be positive and refill rate cannot be negative."})
			return
		}
		now := time.Now().UTC()
		policy := &domain.RateLimitPolicy{ID: domain.NewID(), TenantID: client.TenantID, ClientID: client.ID, Capacity: input.Capacity, RefillRate: input.RefillRate, Enabled: input.Enabled, CreatedAt: now, UpdatedAt: now}
		if existing, policyErr := s.store.GetPolicy(r.Context(), client.TenantID, client.ID, ""); policyErr == nil {
			policy.ID, policy.CreatedAt = existing.ID, existing.CreatedAt
		}
		if err := s.store.UpsertPolicy(r.Context(), policy); err != nil {
			writeStoreError(w, err)
			return
		}
		client.KeyHash = ""
		client.RateLimit = policy
		writeJSON(w, 200, client)
	case "rotate-key":
		if r.Method != http.MethodPost {
			writeJSON(w, 405, map[string]string{"error": "METHOD_NOT_ALLOWED"})
			return
		}
		key, prefix, hash, err := apikey.Generate()
		if err != nil {
			writeJSON(w, 500, map[string]string{"error": "KEY_GENERATION_FAILED"})
			return
		}
		client.KeyPrefix, client.KeyHash, client.UpdatedAt = prefix, hash, time.Now().UTC()
		if err := s.store.UpdateClient(r.Context(), client); err != nil {
			writeStoreError(w, err)
			return
		}
		client.KeyHash = ""
		writeJSON(w, 200, map[string]any{"client": client, "apiKey": key, "warning": "Store this API key now. It will not be shown again."})
	case "revoke":
		if r.Method != http.MethodPatch {
			writeJSON(w, 405, map[string]string{"error": "METHOD_NOT_ALLOWED"})
			return
		}
		client.Status = "revoked"
		client.UpdatedAt = time.Now().UTC()
		if err := s.store.UpdateClient(r.Context(), client); err != nil {
			writeStoreError(w, err)
			return
		}
		client.KeyHash = ""
		writeJSON(w, 200, client)
	case "activate":
		if r.Method != http.MethodPatch {
			writeJSON(w, 405, map[string]string{"error": "METHOD_NOT_ALLOWED"})
			return
		}
		client.Status = "active"
		client.UpdatedAt = time.Now().UTC()
		if err := s.store.UpdateClient(r.Context(), client); err != nil {
			writeStoreError(w, err)
			return
		}
		client.KeyHash = ""
		writeJSON(w, 200, client)
	default:
		writeJSON(w, 404, map[string]string{"error": "NOT_FOUND"})
	}
}
func (s *Server) routes(w http.ResponseWriter, r *http.Request) {
	tenantID := s.tenantID(r)
	switch r.Method {
	case http.MethodGet:
		values, err := s.store.ListRoutes(r.Context(), tenantID)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		writeJSON(w, 200, map[string]any{"routes": values})
	case http.MethodPost:
		route, ok := s.parseRoute(w, r, tenantID, nil)
		if !ok {
			return
		}
		if err := s.store.CreateRoute(r.Context(), route); err != nil {
			writeStoreError(w, err)
			return
		}
		writeJSON(w, 201, route)
	default:
		writeJSON(w, 405, map[string]string{"error": "METHOD_NOT_ALLOWED"})
	}
}
func (s *Server) routeAction(w http.ResponseWriter, r *http.Request, id string) {
	routeID := strings.Trim(id, "/")
	route, err := s.store.GetRoute(r.Context(), s.tenantID(r), routeID)
	if err != nil {
		writeStoreError(w, err)
		return
	}
	switch r.Method {
	case http.MethodPatch:
		updated, ok := s.parseRoute(w, r, route.TenantID, route)
		if !ok {
			return
		}
		updated.ID = route.ID
		updated.CreatedAt = route.CreatedAt
		if err := s.store.UpdateRoute(r.Context(), updated); err != nil {
			writeStoreError(w, err)
			return
		}
		writeJSON(w, 200, updated)
	case http.MethodDelete:
		if err := s.store.DeleteRoute(r.Context(), route.TenantID, route.ID); err != nil {
			writeStoreError(w, err)
			return
		}
		w.WriteHeader(204)
	default:
		writeJSON(w, 405, map[string]string{"error": "METHOD_NOT_ALLOWED"})
	}
}
func (s *Server) parseRoute(w http.ResponseWriter, r *http.Request, tenantID string, current *domain.GatewayRoute) (*domain.GatewayRoute, bool) {
	value := struct {
		Name, GatewayPath, UpstreamURL string
		AllowedMethods                 []string
		TimeoutMS                      int
		AuthenticationRequired, Active *bool
	}{}
	if !decode(w, r, &value) {
		return nil, false
	}
	route := &domain.GatewayRoute{ID: domain.NewID(), TenantID: tenantID, Name: strings.TrimSpace(value.Name), GatewayPath: value.GatewayPath, UpstreamURL: value.UpstreamURL, AllowedMethods: value.AllowedMethods, TimeoutMS: value.TimeoutMS, AuthenticationRequired: true, Active: true, CreatedAt: time.Now().UTC(), UpdatedAt: time.Now().UTC()}
	if current != nil {
		*route = *current
		route.UpdatedAt = time.Now().UTC()
	}
	if value.AuthenticationRequired != nil {
		route.AuthenticationRequired = *value.AuthenticationRequired
	}
	if value.Active != nil {
		route.Active = *value.Active
	}
	if route.Name == "" || !validPath(route.GatewayPath) {
		writeJSON(w, 400, map[string]string{"error": "INVALID_ROUTE_PATH"})
		return nil, false
	}
	parsed, err := url.Parse(route.UpstreamURL)
	if err != nil || parsed.Scheme != "http" && parsed.Scheme != "https" || parsed.Host == "" || strings.Contains(parsed.Host, "@") || strings.Contains(route.GatewayPath, "..") || !s.safeUpstream(parsed) {
		writeJSON(w, 400, map[string]string{"error": "INVALID_UPSTREAM_URL"})
		return nil, false
	}
	if route.TimeoutMS == 0 {
		route.TimeoutMS = 5000
	}
	if route.TimeoutMS < 100 || route.TimeoutMS > 120000 {
		writeJSON(w, 400, map[string]string{"error": "INVALID_TIMEOUT"})
		return nil, false
	}
	if len(route.AllowedMethods) == 0 {
		route.AllowedMethods = []string{"GET", "POST", "PUT", "PATCH", "DELETE"}
	}
	for i, method := range route.AllowedMethods {
		route.AllowedMethods[i] = strings.ToUpper(method)
		if !validMethod(route.AllowedMethods[i]) {
			writeJSON(w, 400, map[string]string{"error": "INVALID_METHOD"})
			return nil, false
		}
	}
	return route, true
}

func (s *Server) safeUpstream(target *url.URL) bool {
	if s.cfg.Environment != "production" {
		return true
	}
	host := target.Hostname()
	if host == "localhost" || host == "metadata.google.internal" || host == "169.254.169.254" {
		return false
	}
	if ip := net.ParseIP(host); ip != nil {
		return !ip.IsLoopback() && !ip.IsPrivate() && !ip.IsLinkLocalUnicast()
	}
	addresses, err := net.LookupIP(host)
	if err != nil || len(addresses) == 0 {
		return false
	}
	for _, ip := range addresses {
		if ip.IsLoopback() || ip.IsPrivate() || ip.IsLinkLocalUnicast() {
			return false
		}
	}
	return true
}
func validPath(value string) bool {
	return strings.HasPrefix(value, "/") && !strings.ContainsAny(value, "?#")
}
func validMethod(value string) bool {
	switch value {
	case "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS":
		return true
	}
	return false
}
func (s *Server) summary(w http.ResponseWriter, r *http.Request) {
	value, err := s.store.Summary(r.Context(), s.tenantID(r))
	if err != nil {
		writeStoreError(w, err)
		return
	}
	writeJSON(w, 200, value)
}
func (s *Server) traffic(w http.ResponseWriter, r *http.Request) {
	value, err := s.store.Traffic(r.Context(), s.tenantID(r))
	if err != nil {
		writeStoreError(w, err)
		return
	}
	writeJSON(w, 200, value)
}
func (s *Server) logs(w http.ResponseWriter, r *http.Request) {
	value, err := s.store.ListLogs(r.Context(), s.tenantID(r))
	if err != nil {
		writeStoreError(w, err)
		return
	}
	writeJSON(w, 200, map[string]any{"logs": value})
}
func (s *Server) requestID(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := r.Header.Get("X-Request-ID")
		if id == "" {
			id = domain.NewID()
		}
		w.Header().Set("X-Request-ID", id)
		next.ServeHTTP(&requestIDWriter{ResponseWriter: w, id: id}, r.WithContext(context.WithValue(r.Context(), requestIDKey{}, id)))
	})
}

type requestIDWriter struct {
	http.ResponseWriter
	id string
}

func (w *requestIDWriter) RequestID() string { return w.id }

type requestIDKey struct{}

func requestID(ctx context.Context) string {
	value, _ := ctx.Value(requestIDKey{}).(string)
	return value
}
func (s *Server) gateway(w http.ResponseWriter, r *http.Request) {
	start := time.Now()
	tenantID := s.tenantID(r)
	var client *domain.APIClient
	var route *domain.GatewayRoute
	status := http.StatusOK
	blocked := false
	defer func() {
		latency := time.Since(start).Milliseconds()
		if client != nil {
			_ = s.store.TouchClient(context.Background(), tenantID, client.ID, time.Now().UTC())
		}
		_ = s.store.InsertLog(context.Background(), &domain.RequestLog{ID: domain.NewID(), RequestID: requestID(r.Context()), TenantID: tenantID, ClientID: clientID(client), RouteID: routeID(route), Method: r.Method, StatusCode: status, LatencyMS: latency, Blocked: blocked, CreatedAt: time.Now().UTC()})
		s.logger.Info("gateway_request", "request_id", requestID(r.Context()), "tenant_id", tenantID, "client_id", clientID(client), "route", r.URL.Path, "method", r.Method, "response_status", status, "latency_ms", latency, "rate_limited", blocked)
	}()
	key := r.Header.Get("X-API-Key")
	if key != "" {
		candidate, err := s.store.FindClientByPrefix(r.Context(), apikey.Prefix(key))
		if err == nil && candidate.Status == "active" && apikey.Verify(key, candidate.KeyHash) {
			client = candidate
			tenantID = client.TenantID
		}
	}
	route, _ = s.store.FindRoute(r.Context(), tenantID, r.URL.Path)
	if route == nil {
		status = 404
		writeJSON(w, 404, map[string]string{"error": "ROUTE_NOT_FOUND"})
		return
	}
	if route.AuthenticationRequired && client == nil {
		status = 401
		writeJSON(w, 401, map[string]string{"error": "UNAUTHORIZED", "message": "Invalid or missing API key."})
		return
	}
	for _, method := range route.AllowedMethods {
		if method == r.Method {
			goto methodOK
		}
	}
	status = 405
	writeJSON(w, 405, map[string]string{"error": "METHOD_NOT_ALLOWED"})
	return
methodOK:
	;
	if client != nil {
		policy, err := s.store.GetPolicy(r.Context(), tenantID, client.ID, route.ID)
		if err != nil && !errors.Is(err, storage.ErrNotFound) {
			status = 503
			writeJSON(w, 503, map[string]string{"error": "RATE_LIMIT_POLICY_UNAVAILABLE"})
			return
		}
		if err == nil && policy.Enabled {
			result, err := s.limiter.Allow(r.Context(), ratelimit.RedisKey(tenantID, client.ID, route.ID), policy.Capacity, policy.RefillRate)
			limit := strconv.FormatFloat(policy.Capacity, 'f', -1, 64)
			w.Header().Set("X-RateLimit-Limit", limit)
			w.Header().Set("X-RateLimit-Remaining", strconv.FormatFloat(result.Remaining, 'f', -1, 64))
			if err != nil {
				status = 503
				writeJSON(w, 503, map[string]string{"error": "RATE_LIMITER_UNAVAILABLE"})
				return
			}
			if !result.Allowed {
				blocked = true
				status = 429
				seconds := int(result.RetryAfter.Seconds())
				if seconds < 1 {
					seconds = 1
				}
				w.Header().Set("X-RateLimit-Reset", strconv.Itoa(seconds))
				w.Header().Set("Retry-After", strconv.Itoa(seconds))
				writeJSON(w, 429, map[string]any{"error": "RATE_LIMIT_EXCEEDED", "message": "Too many requests. Please try again later.", "retryAfterSeconds": seconds})
				return
			}
			w.Header().Set("X-RateLimit-Reset", "0")
		}
	}
	s.proxyRoute(w, r, route, &status)
}

type responseRecorder struct {
	http.ResponseWriter
	status int
}

func (r *responseRecorder) WriteHeader(status int) {
	r.status = status
	r.ResponseWriter.WriteHeader(status)
}
func (r *responseRecorder) Write(body []byte) (int, error) {
	if r.status == 0 {
		r.status = http.StatusOK
	}
	return r.ResponseWriter.Write(body)
}

func (s *Server) proxyRoute(w http.ResponseWriter, r *http.Request, route *domain.GatewayRoute, status *int) {
	target, err := url.Parse(route.UpstreamURL)
	if err != nil {
		*status = 502
		writeJSON(w, 502, map[string]string{"error": "BAD_GATEWAY"})
		return
	}
	proxy := httputil.NewSingleHostReverseProxy(target)
	proxy.Transport = &http.Transport{Proxy: http.ProxyFromEnvironment, DialContext: (&net.Dialer{Timeout: 5 * time.Second}).DialContext, TLSHandshakeTimeout: 5 * time.Second, ResponseHeaderTimeout: time.Duration(route.TimeoutMS) * time.Millisecond, ExpectContinueTimeout: 1 * time.Second}
	proxy.ErrorHandler = func(writer http.ResponseWriter, _ *http.Request, err error) {
		if isTimeout(err) {
			*status = 504
			writeJSON(writer, 504, map[string]string{"error": "GATEWAY_TIMEOUT"})
		} else {
			*status = 502
			writeJSON(writer, 502, map[string]string{"error": "BAD_GATEWAY"})
		}
	}
	clone := r.Clone(r.Context())
	clone.Header.Del("X-API-Key")
	clone.Header.Del("Authorization")
	suffix := strings.TrimPrefix(r.URL.Path, route.GatewayPath)
	clone.URL.Path = strings.TrimSuffix(target.Path, "/") + "/" + strings.TrimPrefix(suffix, "/")
	if suffix == "" {
		clone.URL.Path = target.Path
	}
	clone.URL.RawQuery = r.URL.RawQuery
	clone.Host = target.Host
	recorder := &responseRecorder{ResponseWriter: w}
	proxy.ServeHTTP(recorder, clone)
	if recorder.status != 0 {
		*status = recorder.status
	}
}
func isTimeout(err error) bool {
	if err == nil {
		return false
	}
	if netErr, ok := err.(net.Error); ok && netErr.Timeout() {
		return true
	}
	return strings.Contains(err.Error(), "timeout")
}
func clientID(value *domain.APIClient) string {
	if value == nil {
		return ""
	}
	return value.ID
}
func routeID(value *domain.GatewayRoute) string {
	if value == nil {
		return ""
	}
	return value.ID
}
func decode(w http.ResponseWriter, r *http.Request, value any) bool {
	defer r.Body.Close()
	decoder := json.NewDecoder(io.LimitReader(r.Body, 1<<20))
	if err := decoder.Decode(value); err != nil {
		writeJSON(w, 400, map[string]string{"error": "INVALID_JSON"})
		return false
	}
	return true
}
func writeJSON(w http.ResponseWriter, status int, value any) {
	if requestID, ok := w.(interface{ RequestID() string }); ok && requestID.RequestID() != "" {
		w.Header().Set("X-Request-ID", requestID.RequestID())
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
func writeStoreError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, storage.ErrNotFound):
		writeJSON(w, 404, map[string]string{"error": "NOT_FOUND"})
	case errors.Is(err, storage.ErrConflict):
		writeJSON(w, 409, map[string]string{"error": "CONFLICT"})
	default:
		writeJSON(w, 500, map[string]string{"error": "INTERNAL_ERROR"})
	}
}
