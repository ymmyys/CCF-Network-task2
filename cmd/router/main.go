package main

import (
	"context"
	"errors"
	"flag"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"mutt/internal/router"
)

func main() {
	configPath := flag.String("config", "config/router.example.json", "router config file")
	flag.Parse()

	cfg, err := router.LoadConfig(*configPath)
	if err != nil {
		log.Fatalf("load config: %v", err)
	}

	rt, err := router.New(cfg)
	if err != nil {
		log.Fatalf("create router: %v", err)
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	rt.Start(ctx)

	proxySrv := &http.Server{
		Addr:              cfg.Listen,
		Handler:           rt.ProxyHandler(),
		ReadHeaderTimeout: 10 * time.Second,
	}
	adminSrv := &http.Server{
		Addr:              cfg.AdminListen,
		Handler:           rt.AdminHandler(),
		ReadHeaderTimeout: 10 * time.Second,
	}

	errCh := make(chan error, 2)
	go func() {
		log.Printf("router data plane listening on %s", cfg.Listen)
		errCh <- proxySrv.ListenAndServe()
	}()
	go func() {
		log.Printf("router admin plane listening on %s", cfg.AdminListen)
		errCh <- adminSrv.ListenAndServe()
	}()

	select {
	case <-ctx.Done():
	case err := <-errCh:
		if err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Printf("server error: %v", err)
		}
		stop()
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = proxySrv.Shutdown(shutdownCtx)
	_ = adminSrv.Shutdown(shutdownCtx)
	log.Printf("router stopped")
}
