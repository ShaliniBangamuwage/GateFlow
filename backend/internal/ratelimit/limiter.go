package ratelimit

import (
	"context"
	"fmt"
	"sync"
	"time"
)

type Result struct {
	Allowed    bool
	Remaining  float64
	RetryAfter time.Duration
}
type Limiter interface {
	Allow(context.Context, string, float64, float64) (Result, error)
	Health(context.Context) error
}

type LocalLimiter struct {
	mu      sync.Mutex
	buckets map[string]*TokenBucket
}

func NewLocalLimiter() *LocalLimiter                 { return &LocalLimiter{buckets: map[string]*TokenBucket{}} }
func (l *LocalLimiter) Health(context.Context) error { return nil }
func (l *LocalLimiter) Allow(_ context.Context, key string, capacity, refill float64) (Result, error) {
	l.mu.Lock()
	bucket := l.buckets[key]
	if bucket == nil {
		bucket = NewTokenBucket(capacity, capacity, refill, time.Now)
		l.buckets[key] = bucket
	}
	l.mu.Unlock()
	allowed, remaining, retry := bucket.Allow()
	return Result{Allowed: allowed, Remaining: remaining, RetryAfter: retry}, nil
}

const redisTokenBucketScript = `
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local state = redis.call('HMGET', key, 'tokens', 'timestamp')
local tokens = tonumber(state[1])
local timestamp = tonumber(state[2])
if not tokens then tokens = capacity end
if not timestamp then timestamp = now end
local elapsed = math.max(0, now - timestamp)
tokens = math.min(capacity, tokens + elapsed * refill)
local allowed = 0
local retry = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
elseif refill > 0 then
  retry = math.ceil((1 - tokens) / refill)
else
  retry = 1
end
redis.call('HSET', key, 'tokens', tokens, 'timestamp', now)
redis.call('EXPIRE', key, 86400)
return {allowed, tokens, retry}
`

func RedisKey(tenantID, clientID, routeID string) string {
	return fmt.Sprintf("gateflow:ratelimit:%s:%s:%s", tenantID, clientID, routeID)
}
