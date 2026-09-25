package httpapi

import (
	"encoding/json"
	"fmt"
	"gateflow/internal/apikey"
	"gateflow/internal/config"
	"gateflow/internal/middleware"
	"gateflow/internal/proxy"
	"io"
	"log/slog"
	"net/http"
	"time"
)

// NewRouter builds the gateway HTTP routes for health, auth, rate-limit, and proxying.
func NewRouter(cfg config.Config, store apikey.Store, logger *slog.Logger) http.Handler {
	if logger == nil {
		logger = slog.New(slog.NewTextHandler(io.Discard, nil))
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		legacyWriteJSON(w, http.StatusOK, map[string]string{
			"status":  "ok",
			"service": "gateflow",
		})
	})

	gatewayHandler := proxy.Handler(cfg)
	gatewayHandler = middleware.RequireAPIKey(store)(middleware.RateLimit()(gatewayHandler))
	gatewayHandler = loggingMiddleware(logger)(gatewayHandler)
	mux.Handle("/gateway/", gatewayHandler)
	mux.Handle("/gateway", gatewayHandler)

	return mux
}

type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (r *statusRecorder) WriteHeader(status int) {
	r.status = status
	r.ResponseWriter.WriteHeader(status)
}

func (r *statusRecorder) Write(b []byte) (int, error) {
	if r.status == 0 {
		r.status = http.StatusOK
	}
	return r.ResponseWriter.Write(b)
}

func loggingMiddleware(logger *slog.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			recorder := &statusRecorder{ResponseWriter: w}
			start := time.Now()
			next.ServeHTTP(recorder, r)

			if recorder.status == 0 {
				recorder.status = http.StatusOK
			}

			clientName := "unknown"
			if client := middleware.ClientFromContext(r.Context()); client != nil {
				clientName = client.Name
			}

			logger.Info("gateway_request",
				"timestamp", time.Now().UTC().Format(time.RFC3339Nano),
				"client_name", clientName,
				"gateway_route", fmt.Sprintf("%s %s", r.Method, r.URL.Path),
				"method", r.Method,
				"response_status", recorder.status,
				"latency_ms", time.Since(start).Milliseconds(),
				"rate_limited", recorder.status == http.StatusTooManyRequests,
			)
		})
	}
}

func legacyWriteJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}
