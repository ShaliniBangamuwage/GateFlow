package apikey

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"fmt"
	"strings"
)

func Generate() (string, string, string, error) {
	bytes := make([]byte, 32)
	if _, err := rand.Read(bytes); err != nil {
		return "", "", "", err
	}
	key := "gf_live_" + base64.RawURLEncoding.EncodeToString(bytes)
	return key, Prefix(key), Hash(key), nil
}

func Prefix(key string) string {
	if len(key) > 16 {
		return key[:16]
	}
	return key
}

func Hash(key string) string {
	digest := sha256.Sum256([]byte(key))
	return fmt.Sprintf("%x", digest[:])
}

func Verify(key, encodedHash string) bool {
	provided := Hash(key)
	return subtle.ConstantTimeCompare([]byte(provided), []byte(encodedHash)) == 1
}

func ExtractPrefix(key string) string {
	parts := strings.SplitN(key, ".", 2)
	if len(parts) == 2 {
		return parts[0]
	}
	return Prefix(key)
}
