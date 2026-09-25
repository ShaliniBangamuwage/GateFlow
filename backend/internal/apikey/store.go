package apikey

import (
	"gateflow/internal/domain"
	"gateflow/internal/ratelimit"
	"time"
)

// Store defines the API-key validation contract.
type Store interface {
	Validate(key string) (*domain.Client, bool)
}

// InMemoryStore is a simple in-memory implementation intended for the MVP.
type InMemoryStore struct {
	clients map[string]*domain.Client
}

// NewInMemoryStore creates a demo client with the configured API key and bucket.
func NewInMemoryStore(demoAPIKey string) *InMemoryStore {
	if demoAPIKey == "" {
		demoAPIKey = "gateflow-demo-key"
	}

	bucket := ratelimit.NewTokenBucket(5, 5, 1, time.Now)
	return &InMemoryStore{
		clients: map[string]*domain.Client{
			demoAPIKey: {
				Name:      "Demo Client",
				APIKey:    demoAPIKey,
				RateLimit: bucket,
			},
		},
	}
}

// Validate checks a provided API key and returns its client.
func (s *InMemoryStore) Validate(key string) (*domain.Client, bool) {
	if s == nil {
		return nil, false
	}
	client, ok := s.clients[key]
	return client, ok
}
