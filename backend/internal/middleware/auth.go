package middleware

import (
	"context"
	"encoding/json"
	"gateflow/internal/apikey"
	"gateflow/internal/domain"
	"net/http"
)

type clientContextKey struct{}

// WithClient attaches a validated client to the request context.
func WithClient(ctx context.Context, client *domain.Client) context.Context {
	return context.WithValue(ctx, clientContextKey{}, client)
}

// ClientFromContext extracts the validated client from the request context.
func ClientFromContext(ctx context.Context) *domain.Client {
	client, _ := ctx.Value(clientContextKey{}).(*domain.Client)
	return client
}

// RequireAPIKey validates the X-API-Key header before allowing the request through.
func RequireAPIKey(store apikey.Store) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			key := r.Header.Get("X-API-Key")
			client, ok := store.Validate(key)
			if !ok || client == nil {
				writeJSON(w, http.StatusUnauthorized, map[string]any{
					"error":   "UNAUTHORIZED",
					"message": "Invalid or missing API key.",
				})
				return
			}

			r = r.WithContext(WithClient(r.Context(), client))
			next.ServeHTTP(w, r)
		})
	}
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}
