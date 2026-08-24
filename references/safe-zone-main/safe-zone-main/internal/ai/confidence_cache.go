package ai

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"strconv"
	"time"

	"thyris-sz/internal/cache"
)

// cache key: ai_conf:{label}:{sha256(text)}
func aiConfidenceCacheKey(label, text string) string {
	h := sha256.Sum256([]byte(text))
	return "ai_conf:" + label + ":" + hex.EncodeToString(h[:])
}

func GetCachedConfidence(label, text string) (float64, bool) {
	key := aiConfidenceCacheKey(label, text)
	val, err := cache.RDB.Get(context.Background(), key).Result()
	if err != nil {
		return 0, false
	}

	f, err := strconv.ParseFloat(val, 64)
	if err != nil {
		return 0, false
	}
	return f, true
}

func SetCachedConfidence(label, text string, score float64, ttl time.Duration) {
	key := aiConfidenceCacheKey(label, text)
	_ = cache.RDB.Set(context.Background(), key, strconv.FormatFloat(score, 'f', 4, 64), ttl).Err()
}
