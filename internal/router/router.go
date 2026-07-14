package router

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"sort"
	"sync"
	"time"
)

type Router struct {
	cfg          Config
	pools        map[string]*Pool
	client       *http.Client
	loadInjector *loadInjector
}

type State struct {
	Time  time.Time   `json:"time"`
	Pools []PoolState `json:"pools"`
}

type capacityUpdateRequest struct {
	Pool     string  `json:"pool"`
	Backend  string  `json:"backend"`
	Capacity float64 `json:"capacity"`
}

type healthUpdateRequest struct {
	Pool    string `json:"pool"`
	Backend string `json:"backend"`
	Healthy bool   `json:"healthy"`
}

func New(cfg Config) (*Router, error) {
	cfg.applyDefaults()
	if err := cfg.validate(); err != nil {
		return nil, err
	}

	rt := &Router{
		cfg:          cfg,
		pools:        make(map[string]*Pool, len(cfg.Pools)),
		loadInjector: newLoadInjector(dataPlaneCompletionEndpoint(cfg.Listen), cfg.PoolHeader),
		client: &http.Client{
			Timeout: cfg.ProbeTimeout.Duration,
		},
	}

	for _, poolCfg := range cfg.Pools {
		pool, err := newPool(poolCfg, cfg)
		if err != nil {
			return nil, fmt.Errorf("pool %q: %w", poolCfg.Name, err)
		}
		rt.pools[poolCfg.Name] = pool
	}
	return rt, nil
}

func (rt *Router) Start(ctx context.Context) {
	rt.refreshOnce(ctx)
	go func() {
		ticker := time.NewTicker(rt.cfg.UpdateInterval.Duration)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				rt.refreshOnce(ctx)
			}
		}
	}()
}

func (rt *Router) ProxyHandler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		poolName := req.Header.Get(rt.cfg.PoolHeader)
		if poolName == "" {
			poolName = rt.cfg.DefaultPool
		}

		pool, ok := rt.pools[poolName]
		if !ok {
			http.Error(w, "unknown resource pool", http.StatusNotFound)
			return
		}

		backend, err := rt.pick(pool)
		if err != nil {
			if errors.Is(err, ErrNoBackendAvailable) {
				http.Error(w, "no backend available", http.StatusServiceUnavailable)
				return
			}
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}

		start := time.Now()
		w.Header().Set("X-Router-Backend", backend.ID())
		defer func() {
			backend.release(time.Since(start))
		}()
		backend.Proxy().ServeHTTP(w, req)
	})
}

func (rt *Router) AdminHandler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, req *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok\n"))
	})
	mux.HandleFunc("/admin/state", rt.handleState)
	mux.HandleFunc("/admin/capacity", rt.handleCapacityUpdate)
	mux.HandleFunc("/admin/health", rt.handleHealthUpdate)
	mux.HandleFunc("/admin/load", rt.handleLoadInjection)
	mux.HandleFunc("/metrics", rt.handleMetrics)
	mux.HandleFunc("/demo", rt.handleDemo)
	mux.HandleFunc("/demo/", rt.handleDemo)
	mux.HandleFunc("/", rt.handleDemoRedirect)
	return withCORS(mux)
}

func (rt *Router) pick(pool *Pool) (*Backend, error) {
	return pool.pick()
}

func (rt *Router) refreshOnce(ctx context.Context) {
	type item struct {
		name string
		pool *Pool
	}
	pools := make([]item, 0, len(rt.pools))
	for name, pool := range rt.pools {
		pools = append(pools, item{name: name, pool: pool})
	}
	sort.Slice(pools, func(i, j int) bool { return pools[i].name < pools[j].name })

	var wg sync.WaitGroup
	for _, item := range pools {
		pool := item.pool
		pool.refreshAll(ctx.Done(), func(backend *Backend) {
			wg.Add(1)
			go func() {
				defer wg.Done()
				probeCtx, cancel := context.WithTimeout(ctx, rt.cfg.ProbeTimeout.Duration)
				defer cancel()
				backend.refresh(probeCtx, rt.client, rt.cfg.Load, rt.cfg.SmoothStep)
			}()
		})
	}
	wg.Wait()
}

func (rt *Router) State() State {
	now := time.Now()
	state := State{
		Time:  now,
		Pools: make([]PoolState, 0, len(rt.pools)),
	}
	names := make([]string, 0, len(rt.pools))
	for name := range rt.pools {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		state.Pools = append(state.Pools, rt.pools[name].state(now))
	}
	return state
}

func (rt *Router) handleState(w http.ResponseWriter, req *http.Request) {
	if req.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	writeJSON(w, rt.State())
}

func (rt *Router) handleCapacityUpdate(w http.ResponseWriter, req *http.Request) {
	if req.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var body capacityUpdateRequest
	if err := json.NewDecoder(req.Body).Decode(&body); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	if body.Pool == "" {
		body.Pool = rt.cfg.DefaultPool
	}

	backend, ok := rt.findBackend(body.Pool, body.Backend)
	if !ok {
		http.Error(w, "backend not found", http.StatusNotFound)
		return
	}
	if err := backend.setCapacity(body.Capacity); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	backend.recomputeWeight(rt.cfg.Load, rt.cfg.SmoothStep)
	writeJSON(w, backend.state(time.Now()))
}

func (rt *Router) handleHealthUpdate(w http.ResponseWriter, req *http.Request) {
	if req.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var body healthUpdateRequest
	if err := json.NewDecoder(req.Body).Decode(&body); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	if body.Pool == "" {
		body.Pool = rt.cfg.DefaultPool
	}

	backend, ok := rt.findBackend(body.Pool, body.Backend)
	if !ok {
		http.Error(w, "backend not found", http.StatusNotFound)
		return
	}
	backend.setAdminHealth(body.Healthy)
	backend.recomputeWeight(rt.cfg.Load, rt.cfg.SmoothStep)
	writeJSON(w, backend.state(time.Now()))
}

func (rt *Router) handleLoadInjection(w http.ResponseWriter, req *http.Request) {
	switch req.Method {
	case http.MethodGet:
		writeJSON(w, rt.loadInjector.snapshot())
	case http.MethodDelete:
		writeJSON(w, rt.loadInjector.stop())
	case http.MethodPost:
		var body loadInjectionRequest
		if err := json.NewDecoder(req.Body).Decode(&body); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		if body.Pool == "" {
			body.Pool = rt.cfg.DefaultPool
		}
		if _, ok := rt.pools[body.Pool]; !ok {
			http.Error(w, "pool not found", http.StatusNotFound)
			return
		}
		state, err := rt.loadInjector.start(body)
		if err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		writeJSON(w, state)
	default:
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

func (rt *Router) handleMetrics(w http.ResponseWriter, req *http.Request) {
	if req.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	w.Header().Set("Content-Type", "text/plain; version=0.0.4")
	state := rt.State()
	for _, pool := range state.Pools {
		for _, backend := range pool.Backends {
			fmt.Fprintf(w, "router_backend_capacity{pool=%q,backend=%q} %.6f\n", pool.Name, backend.ID, backend.Capacity)
			fmt.Fprintf(w, "router_backend_phase{pool=%q,backend=%q,phase=%q} 1\n", pool.Name, backend.ID, backend.Phase)
			if backend.TransitionReason != "" {
				fmt.Fprintf(w, "router_backend_transition{pool=%q,backend=%q,reason=%q} 1\n", pool.Name, backend.ID, backend.TransitionReason)
			}
			fmt.Fprintf(w, "router_backend_slow_start_progress{pool=%q,backend=%q} %.6f\n", pool.Name, backend.ID, backend.SlowStartProgress)
			fmt.Fprintf(w, "router_backend_desired_weight{pool=%q,backend=%q} %.6f\n", pool.Name, backend.ID, backend.DesiredWeight)
			fmt.Fprintf(w, "router_backend_effective_weight{pool=%q,backend=%q} %.6f\n", pool.Name, backend.ID, backend.EffectiveWeight)
			fmt.Fprintf(w, "router_backend_inflight{pool=%q,backend=%q} %d\n", pool.Name, backend.ID, backend.Inflight)
			fmt.Fprintf(w, "router_backend_selected_total{pool=%q,backend=%q} %d\n", pool.Name, backend.ID, backend.SelectedTotal)
			fmt.Fprintf(w, "router_backend_healthy{pool=%q,backend=%q} %d\n", pool.Name, backend.ID, bool01(backend.Healthy && !backend.PassiveEjected))
			fmt.Fprintf(w, "router_backend_observed_healthy{pool=%q,backend=%q} %d\n", pool.Name, backend.ID, bool01(backend.ObservedHealthy))
			fmt.Fprintf(w, "router_backend_admin_disabled{pool=%q,backend=%q} %d\n", pool.Name, backend.ID, bool01(backend.AdminDisabled))
			fmt.Fprintf(w, "router_backend_failure_cooling_off{pool=%q,backend=%q} %d\n", pool.Name, backend.ID, bool01(backend.FailureCoolingOff))
			fmt.Fprintf(w, "router_backend_remote_utilization{pool=%q,backend=%q} %.6f\n", pool.Name, backend.ID, backend.RemoteUtilization)
			fmt.Fprintf(w, "router_backend_queue_depth{pool=%q,backend=%q} %.6f\n", pool.Name, backend.ID, backend.QueueDepth)
			fmt.Fprintf(w, "router_backend_kv_cache_usage{pool=%q,backend=%q} %.6f\n", pool.Name, backend.ID, backend.KVCacheUsage)
			fmt.Fprintf(w, "router_backend_latency_ewma_ms{pool=%q,backend=%q} %.6f\n", pool.Name, backend.ID, backend.LatencyEWMAMillis)
		}
	}
}

func (rt *Router) findBackend(poolName, backendID string) (*Backend, bool) {
	pool, ok := rt.pools[poolName]
	if !ok {
		return nil, false
	}
	backend := pool.backend(backendID)
	return backend, backend != nil
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	if err := enc.Encode(v); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
	}
}

func bool01(v bool) int {
	if v {
		return 1
	}
	return 0
}
