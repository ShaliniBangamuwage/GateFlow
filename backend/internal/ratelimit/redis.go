package ratelimit

import (
	"context"
	"github.com/redis/go-redis/v9"
	"strconv"
	"time"
)

type RedisLimiter struct{ client *redis.Client }

func NewRedisLimiter(redisURL string) (*RedisLimiter, error) {
	options, err := redis.ParseURL(redisURL)
	if err != nil {
		return nil, err
	}
	client := redis.NewClient(options)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := client.Ping(ctx).Err(); err != nil {
		client.Close()
		return nil, err
	}
	return &RedisLimiter{client: client}, nil
}
func (l *RedisLimiter) Close() error                     { return l.client.Close() }
func (l *RedisLimiter) Health(ctx context.Context) error { return l.client.Ping(ctx).Err() }
func (l *RedisLimiter) Allow(ctx context.Context, key string, capacity, refill float64) (Result, error) {
	values, err := l.client.Eval(ctx, redisTokenBucketScript, []string{key}, capacity, refill, float64(time.Now().UnixNano())/float64(time.Second)).Result()
	if err != nil {
		return Result{}, err
	}
	items, ok := values.([]interface{})
	if !ok || len(items) != 3 {
		return Result{}, redis.Nil
	}
	allowed, _ := redisAsFloat(items[0])
	remaining, _ := redisAsFloat(items[1])
	retry, _ := redisAsFloat(items[2])
	return Result{Allowed: allowed >= 1, Remaining: remaining, RetryAfter: time.Duration(retry * float64(time.Second))}, nil
}
func redisAsFloat(value interface{}) (float64, bool) {
	switch number := value.(type) {
	case int64:
		return float64(number), true
	case float64:
		return number, true
	case string:
		parsed, err := strconv.ParseFloat(number, 64)
		return parsed, err == nil
	}
	return 0, false
}
