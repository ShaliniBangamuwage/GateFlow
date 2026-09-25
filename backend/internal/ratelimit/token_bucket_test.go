package ratelimit

import (
	"sync"
	"testing"
	"time"
)

func TestTokenBucketStartsWithConfiguredTokenCount(t *testing.T) {
	clock := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
	bucket := NewTokenBucket(5, 1, 5, func() time.Time { return clock })

	if bucket.Capacity != 5 {
		t.Fatalf("capacity = %v, want 5", bucket.Capacity)
	}
	if bucket.Tokens != 1 {
		t.Fatalf("tokens = %v, want 1", bucket.Tokens)
	}
}

func TestTokenBucketAllowsAndConsumesOneToken(t *testing.T) {
	clock := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
	bucket := NewTokenBucket(5, 2, 2, func() time.Time { return clock })

	allowed, remaining, retryAfter := bucket.Allow()
	if !allowed {
		t.Fatal("expected first request to be allowed")
	}
	if remaining != 1 {
		t.Fatalf("remaining = %v, want 1", remaining)
	}
	if retryAfter != 0 {
		t.Fatalf("retryAfter = %v, want 0", retryAfter)
	}
}

func TestTokenBucketRejectsWhenEmpty(t *testing.T) {
	clock := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
	bucket := NewTokenBucket(1, 0, 0, func() time.Time { return clock })

	allowed, remaining, retryAfter := bucket.Allow()
	if allowed {
		t.Fatal("expected request to be rejected when bucket is empty")
	}
	if remaining != 0 {
		t.Fatalf("remaining = %v, want 0", remaining)
	}
	if retryAfter <= 0 {
		t.Fatalf("retryAfter = %v, want a positive duration", retryAfter)
	}
}

func TestTokenBucketRefillsAfterTimePasses(t *testing.T) {
	clock := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
	bucket := NewTokenBucket(5, 0, 1, func() time.Time { return clock })

	allowed, _, _ := bucket.Allow()
	if allowed {
		t.Fatal("expected bucket to reject when empty")
	}

	clock = clock.Add(1500 * time.Millisecond)
	allowed, remaining, retryAfter := bucket.Allow()
	if !allowed {
		t.Fatal("expected token to refill after time passed")
	}
	if remaining != 0.5 {
		t.Fatalf("remaining = %v, want 0.5", remaining)
	}
	if retryAfter != 0 {
		t.Fatalf("retryAfter = %v, want 0", retryAfter)
	}
}

func TestTokenBucketNeverExceedsMaximumCapacity(t *testing.T) {
	clock := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
	bucket := NewTokenBucket(5, 10, 4, func() time.Time { return clock })

	clock = clock.Add(10 * time.Second)
	allowed, remaining, _ := bucket.Allow()
	if !allowed {
		t.Fatal("expected request to be allowed")
	}
	if remaining != 4 {
		t.Fatalf("remaining = %v, want 4", remaining)
	}
	if bucket.Tokens > bucket.Capacity {
		t.Fatalf("tokens = %v exceed capacity %v", bucket.Tokens, bucket.Capacity)
	}
}

func TestTokenBucketConcurrentRequestsStayValid(t *testing.T) {
	clock := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
	bucket := NewTokenBucket(5, 1, 5, func() time.Time { return clock })

	var wg sync.WaitGroup
	allowedCount := 0
	var mu sync.Mutex

	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			allowed, _, _ := bucket.Allow()
			if allowed {
				mu.Lock()
				allowedCount++
				mu.Unlock()
			}
		}()
	}
	wg.Wait()

	if allowedCount > 5 {
		t.Fatalf("allowedCount = %d, want <= 5", allowedCount)
	}
	if bucket.Tokens < 0 || bucket.Tokens > bucket.Capacity {
		t.Fatalf("bucket.Tokens = %v is invalid for capacity %v", bucket.Tokens, bucket.Capacity)
	}
}

func TestTokenBucketReturnsRetryAfterWhenEmpty(t *testing.T) {
	clock := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
	bucket := NewTokenBucket(1, 0, 0, func() time.Time { return clock })

	allowed, remaining, retryAfter := bucket.Allow()
	if allowed {
		t.Fatal("expected request to be rejected")
	}
	if remaining != 0 {
		t.Fatalf("remaining = %v, want 0", remaining)
	}
	if retryAfter < time.Second {
		t.Fatalf("retryAfter = %v, want at least 1s", retryAfter)
	}
}
