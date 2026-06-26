package router

import (
	"encoding/json"
	"fmt"
	"net/url"
	"os"
	"time"
)

type Duration struct {
	time.Duration
}

func (d *Duration) UnmarshalJSON(data []byte) error {
	var s string
	if err := json.Unmarshal(data, &s); err == nil {
		parsed, err := time.ParseDuration(s)
		if err != nil {
			return err
		}
		d.Duration = parsed
		return nil
	}

	var seconds float64
	if err := json.Unmarshal(data, &seconds); err != nil {
		return err
	}
	d.Duration = time.Duration(seconds * float64(time.Second))
	return nil
}

type Config struct {
	Listen                  string       `json:"listen"`
	AdminListen             string       `json:"admin_listen"`
	DefaultPool             string       `json:"default_pool"`
	PoolHeader              string       `json:"pool_header"`
	UpdateInterval          Duration     `json:"update_interval"`
	ProbeTimeout            Duration     `json:"probe_timeout"`
	SmoothStep              float64      `json:"smooth_step"`
	SlowStartDuration       Duration     `json:"slow_start_duration"`
	PassiveFailureThreshold int          `json:"passive_failure_threshold"`
	PassiveEjectDuration    Duration     `json:"passive_eject_duration"`
	FailureCooloffDuration  Duration     `json:"failure_cooloff_duration"`
	Scheduler               Scheduler    `json:"scheduler"`
	Load                    LoadPolicy   `json:"load"`
	Pools                   []PoolConfig `json:"pools"`
}

type Scheduler struct {
	Mode string `json:"mode"`
}

type LoadPolicy struct {
	EWMAAlpha          float64 `json:"ewma_alpha"`
	UtilizationWeight  float64 `json:"utilization_weight"`
	QueueWeight        float64 `json:"queue_weight"`
	InflightWeight     float64 `json:"inflight_weight"`
	KVCacheWeight      float64 `json:"kv_cache_weight"`
	LatencyWeight      float64 `json:"latency_weight"`
	QueueSoftLimit     float64 `json:"queue_soft_limit"`
	KVCacheSoftLimit   float64 `json:"kv_cache_soft_limit"`
	LatencySLOMillis   float64 `json:"latency_slo_ms"`
	MinHealthyFraction float64 `json:"min_healthy_fraction"`
}

type PoolConfig struct {
	Name     string          `json:"name"`
	Backends []BackendConfig `json:"backends"`
}

type BackendConfig struct {
	ID           string  `json:"id"`
	URL          string  `json:"url"`
	Capacity     float64 `json:"capacity"`
	MaxInflight  int64   `json:"max_inflight"`
	HealthURL    string  `json:"health_url"`
	MetricsURL   string  `json:"metrics_url"`
	PreserveHost bool    `json:"preserve_host"`
}

func LoadConfig(path string) (Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return Config{}, err
	}

	var cfg Config
	if err := json.Unmarshal(data, &cfg); err != nil {
		return Config{}, err
	}
	cfg.applyDefaults()
	return cfg, cfg.validate()
}

func (cfg *Config) applyDefaults() {
	if cfg.Listen == "" {
		cfg.Listen = ":8080"
	}
	if cfg.AdminListen == "" {
		cfg.AdminListen = ":8081"
	}
	if cfg.DefaultPool == "" {
		cfg.DefaultPool = "default"
	}
	if cfg.PoolHeader == "" {
		cfg.PoolHeader = "X-Resource-Pool"
	}
	if cfg.UpdateInterval.Duration <= 0 {
		cfg.UpdateInterval.Duration = time.Second
	}
	if cfg.ProbeTimeout.Duration <= 0 {
		cfg.ProbeTimeout.Duration = 800 * time.Millisecond
	}
	if cfg.SmoothStep <= 0 || cfg.SmoothStep > 1 {
		cfg.SmoothStep = 0.25
	}
	if cfg.SlowStartDuration.Duration <= 0 {
		cfg.SlowStartDuration.Duration = 15 * time.Second
	}
	if cfg.PassiveFailureThreshold <= 0 {
		cfg.PassiveFailureThreshold = 3
	}
	if cfg.PassiveEjectDuration.Duration <= 0 {
		cfg.PassiveEjectDuration.Duration = 5 * time.Second
	}
	if cfg.FailureCooloffDuration.Duration <= 0 {
		cfg.FailureCooloffDuration.Duration = time.Second
	}
	if cfg.Scheduler.Mode == "" {
		cfg.Scheduler.Mode = "p2c_smooth_wrr"
	}
	if cfg.Load.EWMAAlpha <= 0 || cfg.Load.EWMAAlpha > 1 {
		cfg.Load.EWMAAlpha = 0.35
	}
	if cfg.Load.UtilizationWeight <= 0 &&
		cfg.Load.QueueWeight <= 0 &&
		cfg.Load.InflightWeight <= 0 &&
		cfg.Load.KVCacheWeight <= 0 &&
		cfg.Load.LatencyWeight <= 0 {
		cfg.Load.UtilizationWeight = 0.45
		cfg.Load.QueueWeight = 0.20
		cfg.Load.InflightWeight = 0.15
		cfg.Load.KVCacheWeight = 0.10
		cfg.Load.LatencyWeight = 0.10
	}
	if cfg.Load.QueueSoftLimit <= 0 {
		cfg.Load.QueueSoftLimit = 32
	}
	if cfg.Load.KVCacheSoftLimit <= 0 {
		cfg.Load.KVCacheSoftLimit = 1
	}
	if cfg.Load.LatencySLOMillis <= 0 {
		cfg.Load.LatencySLOMillis = 2000
	}
	if cfg.Load.MinHealthyFraction < 0 || cfg.Load.MinHealthyFraction > 0.5 {
		cfg.Load.MinHealthyFraction = 0.03
	}
}

func (cfg Config) validate() error {
	if len(cfg.Pools) == 0 {
		return fmt.Errorf("at least one pool is required")
	}
	switch cfg.Scheduler.Mode {
	case "swrr", "p2c_smooth_wrr":
	default:
		return fmt.Errorf("unsupported scheduler mode %q", cfg.Scheduler.Mode)
	}

	seenPools := make(map[string]struct{}, len(cfg.Pools))
	defaultFound := false
	for _, pool := range cfg.Pools {
		if pool.Name == "" {
			return fmt.Errorf("pool name is required")
		}
		if _, exists := seenPools[pool.Name]; exists {
			return fmt.Errorf("duplicate pool %q", pool.Name)
		}
		seenPools[pool.Name] = struct{}{}
		if pool.Name == cfg.DefaultPool {
			defaultFound = true
		}
		if len(pool.Backends) == 0 {
			return fmt.Errorf("pool %q must contain at least one backend", pool.Name)
		}

		seenBackends := make(map[string]struct{}, len(pool.Backends))
		for _, backend := range pool.Backends {
			if backend.ID == "" {
				return fmt.Errorf("pool %q has backend without id", pool.Name)
			}
			if _, exists := seenBackends[backend.ID]; exists {
				return fmt.Errorf("pool %q has duplicate backend %q", pool.Name, backend.ID)
			}
			seenBackends[backend.ID] = struct{}{}

			if backend.Capacity <= 0 {
				return fmt.Errorf("backend %q capacity must be > 0 at startup", backend.ID)
			}
			if backend.MaxInflight < 0 {
				return fmt.Errorf("backend %q max_inflight must be >= 0", backend.ID)
			}
			if _, err := url.ParseRequestURI(backend.URL); err != nil {
				return fmt.Errorf("backend %q url: %w", backend.ID, err)
			}
			if backend.HealthURL != "" {
				if _, err := url.ParseRequestURI(backend.HealthURL); err != nil {
					return fmt.Errorf("backend %q health_url: %w", backend.ID, err)
				}
			}
			if backend.MetricsURL != "" {
				if _, err := url.ParseRequestURI(backend.MetricsURL); err != nil {
					return fmt.Errorf("backend %q metrics_url: %w", backend.ID, err)
				}
			}
		}
	}
	if !defaultFound {
		return fmt.Errorf("default_pool %q does not exist", cfg.DefaultPool)
	}
	return nil
}
