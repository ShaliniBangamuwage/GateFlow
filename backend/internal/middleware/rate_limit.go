package middleware

import (
	"context"
	"encoding/json"
	"math"
	"net/http"
	"strconv"
)

type rateLimitBlockedKey struct{}

// WithRateLimitBlocked marks whether the request was blocked by the rate limiter.
func WithRateLimitBlocked(ctx context.Context, blocked bool) context.Context {
	return context.WithValue(ctx, rateLimitBlockedKey{}, blocked)
}

// RateLimit runs a token-bucket check after authentication.
func RateLimit() func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			client := ClientFromContext(r.Context())
			if client == nil || client.RateLimit == nil {
				next.ServeHTTP(w, r)
				return
			}

			allowed, remaining, retryAfter := client.RateLimit.Allow()
			limitValue := strconv.FormatFloat(client.RateLimit.Capacity, 'f', -1, 64)
			w.Header().Set("X-RateLimit-Limit", limitValue)
			w.Header().Set("X-RateLimit-Remaining", strconv.FormatFloat(math.Max(0, remaining), 'f', -1, 64))

			if !allowed {
				resetSeconds := int(math.Ceil(retryAfter.Seconds()))
				if resetSeconds <= 0 {
					resetSeconds = 1
				}
				w.Header().Set("X-RateLimit-Reset", strconv.Itoa(resetSeconds))
				w.Header().Set("Retry-After", strconv.Itoa(resetSeconds))
				w.WriteHeader(http.StatusTooManyRequests)
				_ = json.NewEncoder(w).Encode(map[string]any{
					"error":             "RATE_LIMIT_EXCEEDED",
					"message":           "Too many requests. Please try again later.",
					"retryAfterSeconds": resetSeconds,
				})
				return
			}

			w.Header().Set("X-RateLimit-Reset", "0")
			next.ServeHTTP(w, r.WithContext(WithRateLimitBlocked(r.Context(), false)))
		})
	}
}

// IsRateLimitBlocked reports whether the request was rejected by the token bucket.
func IsRateLimitBlocked(ctx context.Context) bool {
	blocked, _ := ctx.Value(rateLimitBlockedKey{}).(bool)
	return blocked
}
