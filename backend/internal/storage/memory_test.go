package storage

import (
	"context"
	"gateflow/internal/domain"
	"testing"
	"time"
)

func TestMemoryStoreScopesClientsAndRoutesByTenant(t *testing.T) {
	store := NewMemoryStore()
	now := time.Now()
	for _, tenant := range []*domain.Tenant{{ID: "a", Name: "A", Status: "active", CreatedAt: now, UpdatedAt: now}, {ID: "b", Name: "B", Status: "active", CreatedAt: now, UpdatedAt: now}} {
		if err := store.CreateTenant(context.Background(), tenant); err != nil {
			t.Fatal(err)
		}
	}
	client := &domain.APIClient{ID: "client-b", TenantID: "b", Name: "B client", KeyPrefix: "b-prefix", KeyHash: "hash", Status: "active", CreatedAt: now, UpdatedAt: now}
	if err := store.CreateClient(context.Background(), client); err != nil {
		t.Fatal(err)
	}
	route := &domain.GatewayRoute{ID: "route-b", TenantID: "b", Name: "B route", GatewayPath: "/b", UpstreamURL: "http://example.com", AllowedMethods: []string{"GET"}, Active: true, CreatedAt: now, UpdatedAt: now}
	if err := store.CreateRoute(context.Background(), route); err != nil {
		t.Fatal(err)
	}
	clients, err := store.ListClients(context.Background(), "a")
	if err != nil || len(clients) != 0 {
		t.Fatalf("tenant A saw tenant B clients: %v", clients)
	}
	if _, err := store.GetRoute(context.Background(), "a", route.ID); err != ErrNotFound {
		t.Fatalf("cross-tenant route lookup error = %v", err)
	}
	if _, err := store.GetClientByID(context.Background(), "a", client.ID); err != ErrNotFound {
		t.Fatalf("cross-tenant client lookup error = %v", err)
	}
}
