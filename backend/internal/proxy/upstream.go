package proxy

import (
	"encoding/json"
	"fmt"
	"gateflow/internal/config"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
	"time"
)

// Handler builds a reverse proxy to the configured upstream.
func Handler(cfg config.Config) http.Handler {
	upstreamURL, err := url.Parse(cfg.UpstreamURL)
	if err != nil || upstreamURL.Scheme == "" || upstreamURL.Host == "" {
		upstreamURL = mustParseURL("https://httpbin.org/anything")
	}

	reverseProxy := httputil.NewSingleHostReverseProxy(upstreamURL)
	reverseProxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		if isTimeoutError(err) {
			writeJSON(w, http.StatusGatewayTimeout, map[string]any{
				"error":   "GATEWAY_TIMEOUT",
				"message": "The upstream service did not respond in time.",
			})
			return
		}
		writeJSON(w, http.StatusBadGateway, map[string]any{
			"error":   "BAD_GATEWAY",
			"message": "The upstream service is currently unavailable.",
		})
	}
	reverseProxy.Transport = &http.Transport{
		Proxy: http.ProxyFromEnvironment,
		DialContext: (&net.Dialer{
			Timeout:   5 * time.Second,
			KeepAlive: 30 * time.Second,
		}).DialContext,
		TLSHandshakeTimeout:   5 * time.Second,
		ResponseHeaderTimeout: 5 * time.Second,
		ExpectContinueTimeout: 1 * time.Second,
	}

	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		r.Header.Del("X-API-Key")
		r.Header.Del("Authorization")

		incomingPath := r.URL.Path
		upstreamPath := strings.TrimSuffix(upstreamURL.Path, "/") + incomingPath
		if upstreamURL.Path == "" || upstreamURL.Path == "/" {
			upstreamPath = incomingPath
		}

		clone := *r
		clone.URL = &url.URL{
			Scheme:   upstreamURL.Scheme,
			Host:     upstreamURL.Host,
			Path:     upstreamPath,
			RawQuery: r.URL.RawQuery,
		}
		clone.Host = upstreamURL.Host
		reverseProxy.ServeHTTP(w, &clone)
	})
}

func mustParseURL(rawURL string) *url.URL {
	parsed, err := url.Parse(rawURL)
	if err != nil {
		panic(fmt.Sprintf("invalid upstream URL: %v", err))
	}
	return parsed
}

func isTimeoutError(err error) bool {
	if err == nil {
		return false
	}
	if netErr, ok := err.(net.Error); ok && netErr.Timeout() {
		return true
	}
	return strings.Contains(err.Error(), "Client.Timeout exceeded") || strings.Contains(err.Error(), "i/o timeout")
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}
