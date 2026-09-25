package main

import (
	"context"
	"errors"
	"fmt"
	"gateflow/internal/app"
	"gateflow/internal/config"
	"gateflow/internal/httpapi"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

func main() {
	cfg := config.Load()
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	runtime, err := app.Initialize(ctx, cfg, logger)
	if err != nil {
		logger.Error("startup_failed", "error", err)
		os.Exit(1)
	}
	defer runtime.Close()
	server := &http.Server{Addr: fmt.Sprintf(":%d", cfg.Port), Handler: httpapi.NewServer(cfg, runtime.Store, runtime.Limiter, logger, runtime.TenantID).Handler(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 30 * time.Second, WriteTimeout: 30 * time.Second, IdleTimeout: 60 * time.Second}
	errorsChannel := make(chan error, 1)
	go func() {
		logger.Info("gateway_started", "addr", server.Addr, "tenant_id", runtime.TenantID)
		errorsChannel <- server.ListenAndServe()
	}()
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	select {
	case err := <-errorsChannel:
		if !errors.Is(err, http.ErrServerClosed) {
			logger.Error("server_failed", "error", err)
			os.Exit(1)
		}
	case <-stop:
		shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer shutdownCancel()
		_ = server.Shutdown(shutdownCtx)
	}
}
