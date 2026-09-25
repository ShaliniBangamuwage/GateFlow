package main

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"
)

func main() {
	port := os.Getenv("MOCK_UPSTREAM_PORT")
	if port == "" {
		port = "9090"
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/products", resource("products"))
	mux.HandleFunc("/users", resource("users"))
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"status":"ok","service":"mock-upstream"}`))
	})
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	logger.Info("mock_upstream_started", "port", port)
	if err := http.ListenAndServe(":"+port, mux); err != nil {
		logger.Error("mock_upstream_failed", "error", err)
		os.Exit(1)
	}
}
func resource(name string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if delay, _ := strconv.Atoi(r.URL.Query().Get("delay_ms")); delay > 0 && delay < 10000 {
			time.Sleep(time.Duration(delay) * time.Millisecond)
		}
		payload := map[string]any{"service": "mock-upstream", "resource": name, "method": r.Method, "path": r.URL.Path, "message": fmt.Sprintf("GateFlow reached the %s upstream", name)}
		if strings.HasPrefix(r.URL.Path, "/fail") {
			http.Error(w, "upstream failure", 502)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(payload)
	}
}
