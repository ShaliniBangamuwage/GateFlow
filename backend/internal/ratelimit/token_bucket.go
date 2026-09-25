package ratelimit

import (
	"math"
	"sync"
	"time"
)

// TokenBucket models a thread-safe token bucket with a simple refill rate.
type TokenBucket struct {
	Capacity   float64
	Tokens     float64
	RefillRate float64
	LastRefill time.Time
	Mutex      sync.Mutex
	now        func() time.Time
}

// NewTokenBucket creates a new bucket and clamps the initial tokens to capacity.
func NewTokenBucket(capacity, initialTokens, refillRate float64, now func() time.Time) *TokenBucket {
	if capacity <= 0 {
		capacity = 1
	}
	if refillRate < 0 {
		refillRate = 0
	}
	if initialTokens < 0 {
		initialTokens = 0
	}
	if initialTokens > capacity {
		initialTokens = capacity
	}
	if now == nil {
		now = time.Now
	}

	return &TokenBucket{
		Capacity:   capacity,
		Tokens:     initialTokens,
		RefillRate: refillRate,
		LastRefill: now(),
		now:        now,
	}
}

// Allow checks whether the bucket has enough tokens for a request.
// It updates the current token count based on elapsed time and returns a retryAfter
// value when the bucket is empty.
func (b *TokenBucket) Allow() (allowed bool, remaining float64, retryAfter time.Duration) {
	b.Mutex.Lock()
	defer b.Mutex.Unlock()

	now := b.now()
	if b.LastRefill.IsZero() {
		b.LastRefill = now
	}

	elapsed := now.Sub(b.LastRefill)
	if elapsed > 0 {
		b.Tokens += elapsed.Seconds() * b.RefillRate
		if b.Tokens > b.Capacity {
			b.Tokens = b.Capacity
		}
		b.LastRefill = now
	}

	if b.Tokens >= 1 {
		b.Tokens -= 1
		return true, b.Tokens, 0
	}

	remaining = 0
	if b.RefillRate > 0 {
		secondsUntilToken := (1 - b.Tokens) / b.RefillRate
		retryAfter = time.Duration(math.Ceil(secondsUntilToken*float64(time.Second))) * time.Nanosecond
		if retryAfter <= 0 {
			retryAfter = time.Second
		}
	} else {
		retryAfter = time.Second
	}

	return false, remaining, retryAfter
}
