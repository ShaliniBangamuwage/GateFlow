package domain

import "gateflow/internal/ratelimit"

// Client represents a single API client with an in-memory rate-limit bucket.
type Client struct {
	Name      string
	APIKey    string
	RateLimit *ratelimit.TokenBucket
}
