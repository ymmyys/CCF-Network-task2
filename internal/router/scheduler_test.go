package router

import (
	"math"
	"math/rand"
	"sync/atomic"
	"testing"
	"time"
)

func TestSmoothCapacityDropDoesNotInstantlyZeroEffectiveWeight(t *testing.T) {
	cfg := Config{
		DefaultPool: "default",
		Pools: []PoolConfig{{
			Name: "default",
			Backends: []BackendConfig{{
				ID:       "npu-a",
				URL:      "http://127.0.0.1:9001",
				Capacity: 10,
			}},
		}},
	}
	cfg.applyDefaults()

	rt, err := New(cfg)
	if err != nil {
		t.Fatalf("new router: %v", err)
	}
	backend, ok := rt.findBackend("default", "npu-a")
	if !ok {
		t.Fatal("backend not found")
	}

	if err := backend.setCapacity(1); err != nil {
		t.Fatalf("set capacity: %v", err)
	}
	backend.recomputeWeight(rt.cfg.Load, 0.25)
	state := backend.state(time.Now())

	if state.DesiredWeight != 1 {
		t.Fatalf("desired weight = %v, want 1", state.DesiredWeight)
	}
	if state.EffectiveWeight <= 1 || state.EffectiveWeight >= 10 {
		t.Fatalf("effective weight = %v, want smooth value between 1 and 10", state.EffectiveWeight)
	}
}

func TestWeightedRoundRobinPrefersHigherWeight(t *testing.T) {
	cfg := Config{
		DefaultPool: "default",
		Scheduler: Scheduler{
			Mode: "swrr",
		},
		Pools: []PoolConfig{{
			Name: "default",
			Backends: []BackendConfig{
				{ID: "a", URL: "http://127.0.0.1:9001", Capacity: 3},
				{ID: "b", URL: "http://127.0.0.1:9002", Capacity: 1},
			},
		}},
	}
	cfg.applyDefaults()

	rt, err := New(cfg)
	if err != nil {
		t.Fatalf("new router: %v", err)
	}
	pool := rt.pools["default"]
	counts := map[string]int{}
	for i := 0; i < 40; i++ {
		backend, err := pool.pick()
		if err != nil {
			t.Fatalf("pick: %v", err)
		}
		counts[backend.ID()]++
		backend.release(time.Millisecond)
	}

	if counts["a"] <= counts["b"] {
		t.Fatalf("backend a picks = %d, backend b picks = %d, want a > b", counts["a"], counts["b"])
	}
}

func TestP2CPrefersLowerInflightCandidate(t *testing.T) {
	cfg := Config{
		DefaultPool: "default",
		Scheduler: Scheduler{
			Mode: "p2c_smooth_wrr",
		},
		Pools: []PoolConfig{{
			Name: "default",
			Backends: []BackendConfig{
				{ID: "hot", URL: "http://127.0.0.1:9001", Capacity: 1, MaxInflight: 10},
				{ID: "cool", URL: "http://127.0.0.1:9002", Capacity: 1, MaxInflight: 10},
			},
		}},
	}
	cfg.applyDefaults()

	rt, err := New(cfg)
	if err != nil {
		t.Fatalf("new router: %v", err)
	}
	hot, ok := rt.findBackend("default", "hot")
	if !ok {
		t.Fatal("hot backend not found")
	}
	atomic.StoreInt64(&hot.inflight, 9)

	pool := rt.pools["default"]
	// 高权重 + 高负载使得 weighted sample 不以 hot 为主，但 loadScore 会偏好 cool
	coolWins := 0
	for i := 0; i < 40; i++ {
		backend, err := pool.pick()
		if err != nil {
			t.Fatalf("pick: %v", err)
		}
		if backend.ID() == "cool" {
			coolWins++
		}
		backend.release(time.Millisecond)
	}
	if coolWins <= 20 {
		t.Fatalf("cool wins = %d, want > 20 (p2c should prefer lower inflight)", coolWins)
	}
}

func TestP2CResamplesDuplicateHighLoadCandidate(t *testing.T) {
	cfg := Config{
		DefaultPool: "default",
		Scheduler: Scheduler{
			Mode: "p2c_smooth_wrr",
		},
		Pools: []PoolConfig{{
			Name: "default",
			Backends: []BackendConfig{
				{ID: "hot", URL: "http://127.0.0.1:9001", Capacity: 100, MaxInflight: 10},
				{ID: "cool", URL: "http://127.0.0.1:9002", Capacity: 1, MaxInflight: 10},
			},
		}},
	}
	cfg.applyDefaults()

	rt, err := New(cfg)
	if err != nil {
		t.Fatalf("new router: %v", err)
	}
	hot, ok := rt.findBackend("default", "hot")
	if !ok {
		t.Fatal("hot backend not found")
	}
	hot.mu.Lock()
	hot.remoteUtilization = 0.95
	hot.queueDepth = rt.cfg.Load.QueueSoftLimit
	hot.latencyEWMA = rt.cfg.Load.LatencySLOMillis
	hot.mu.Unlock()

	pool := rt.pools["default"]
	coolWins := 0
	for i := 0; i < 40; i++ {
		backend, err := pool.pick()
		if err != nil {
			t.Fatalf("pick: %v", err)
		}
		if backend.ID() == "cool" {
			coolWins++
		}
		backend.release(time.Millisecond)
	}
	if coolWins < 35 {
		t.Fatalf("cool wins = %d, want >= 35 (duplicate high-load samples should be challenged)", coolWins)
	}
}

func TestBalancedP2CKeepsControlledSlowShare(t *testing.T) {
	cfg := Config{
		DefaultPool: "default",
		Scheduler: Scheduler{
			Mode:                "p2c_smooth_wrr",
			BalancedP2C:         true,
			SlowBackendMinShare: 0.10,
		},
		Pools: []PoolConfig{{
			Name: "default",
			Backends: []BackendConfig{
				{ID: "slow", URL: "http://127.0.0.1:9001", Capacity: 1, MaxInflight: 100},
				{ID: "fast", URL: "http://127.0.0.1:9002", Capacity: 1, MaxInflight: 100},
			},
		}},
	}
	cfg.applyDefaults()

	rt, err := New(cfg)
	if err != nil {
		t.Fatalf("new router: %v", err)
	}
	slow, ok := rt.findBackend("default", "slow")
	if !ok {
		t.Fatal("slow backend not found")
	}
	slow.mu.Lock()
	slow.remoteUtilization = 0.95
	slow.queueDepth = rt.cfg.Load.QueueSoftLimit
	slow.latencyEWMA = rt.cfg.Load.LatencySLOMillis
	slow.mu.Unlock()

	pool := rt.pools["default"]
	pool.rng = rand.New(rand.NewSource(11))
	counts := map[string]int{}
	for i := 0; i < 500; i++ {
		backend, err := pool.pick()
		if err != nil {
			t.Fatalf("pick: %v", err)
		}
		counts[backend.ID()]++
		backend.release(time.Millisecond)
	}

	if counts["slow"] < 20 || counts["slow"] > 90 {
		t.Fatalf("slow picks = %d, want controlled low share in [20,90]", counts["slow"])
	}
	if counts["fast"] <= counts["slow"] {
		t.Fatalf("fast picks = %d, slow picks = %d, want fast dominant", counts["fast"], counts["slow"])
	}
}

func TestBackendFailureCooloffTemporarilyUnschedulable(t *testing.T) {
	cfg := Config{
		DefaultPool: "default",
		FailureCooloffDuration: Duration{
			Duration: 500 * time.Millisecond,
		},
		PassiveFailureThreshold: 3,
		Pools: []PoolConfig{{
			Name: "default",
			Backends: []BackendConfig{{
				ID:       "npu-a",
				URL:      "http://127.0.0.1:9001",
				Capacity: 10,
			}},
		}},
	}
	cfg.applyDefaults()

	rt, err := New(cfg)
	if err != nil {
		t.Fatalf("new router: %v", err)
	}
	backend, ok := rt.findBackend("default", "npu-a")
	if !ok {
		t.Fatal("backend not found")
	}

	backend.markFailure("upstream status 500")
	if _, ok := backend.schedulingState(time.Now()); ok {
		t.Fatal("backend is schedulable during failure cooloff")
	}

	backend.mu.Lock()
	backend.failureCooloffUntil = time.Now().Add(-time.Millisecond)
	backend.mu.Unlock()
	if _, ok := backend.schedulingState(time.Now()); !ok {
		t.Fatal("backend should be schedulable after failure cooloff expires")
	}
}

func TestBackendPhaseTransitionsForDrainAndRecover(t *testing.T) {
	cfg := Config{
		DefaultPool: "default",
		SlowStartDuration: Duration{
			Duration: 10 * time.Second,
		},
		Pools: []PoolConfig{{
			Name: "default",
			Backends: []BackendConfig{{
				ID:       "npu-a",
				URL:      "http://127.0.0.1:9001",
				Capacity: 10,
			}},
		}},
	}
	cfg.applyDefaults()

	rt, err := New(cfg)
	if err != nil {
		t.Fatalf("new router: %v", err)
	}
	backend, ok := rt.findBackend("default", "npu-a")
	if !ok {
		t.Fatal("backend not found")
	}

	if err := backend.setCapacity(1); err != nil {
		t.Fatalf("set capacity: %v", err)
	}
	backend.recomputeWeight(rt.cfg.Load, rt.cfg.SmoothStep)
	if got := backend.state(time.Now()).Phase; got != string(PhaseDraining) {
		t.Fatalf("phase after downscale = %q, want draining", got)
	}

	if err := backend.setCapacity(0); err != nil {
		t.Fatalf("set capacity zero: %v", err)
	}
	backend.mu.Lock()
	backend.effectiveWeight = 0
	backend.mu.Unlock()
	backend.recomputeWeight(rt.cfg.Load, rt.cfg.SmoothStep)
	if got := backend.state(time.Now()).Phase; got != string(PhaseDrained) {
		t.Fatalf("phase after zero capacity = %q, want drained", got)
	}

	if err := backend.setCapacity(5); err != nil {
		t.Fatalf("restore capacity: %v", err)
	}
	backend.recomputeWeight(rt.cfg.Load, rt.cfg.SmoothStep)
	if got := backend.state(time.Now()).Phase; got != string(PhaseRecovering) {
		t.Fatalf("phase after restore = %q, want recovering", got)
	}

	backend.mu.Lock()
	backend.phaseSince = time.Now().Add(-11 * time.Second)
	backend.mu.Unlock()
	backend.recomputeWeight(rt.cfg.Load, rt.cfg.SmoothStep)
	if got := backend.state(time.Now()).Phase; got != string(PhaseActive) {
		t.Fatalf("phase after slow start = %q, want active", got)
	}
}

func TestMetricsSampleParsesKVCacheAndLatency(t *testing.T) {
	policy := LoadPolicy{
		KVCacheSoftLimit: 1000,
	}
	sample := parseMetricsSample([]byte(`
npu_utilization_rate 80
request_queue_depth 16
kv_cache_used_bytes 500
decode_latency_ms 1200
`), policy)

	if sample.utilization != 0.8 {
		t.Fatalf("utilization = %v, want 0.8", sample.utilization)
	}
	if sample.queueDepth != 16 {
		t.Fatalf("queue depth = %v, want 16", sample.queueDepth)
	}
	if sample.kvCache != 0.5 {
		t.Fatalf("kv cache = %v, want 0.5", sample.kvCache)
	}
	if sample.latencyMS != 1200 {
		t.Fatalf("latency = %v, want 1200", sample.latencyMS)
	}
}

func TestMetricsSampleIgnoresPrometheusCreatedTimestamps(t *testing.T) {
	sample := parseMetricsSample([]byte(`
vllm:num_requests_waiting{engine="0",model_name="qwen2.5-0.5b-instruct"} 0.0
vllm:kv_cache_usage_perc{engine="0",model_name="qwen2.5-0.5b-instruct"} 0.25
vllm:request_queue_time_seconds_count{engine="0",model_name="qwen2.5-0.5b-instruct"} 1.0
vllm:request_queue_time_seconds_sum{engine="0",model_name="qwen2.5-0.5b-instruct"} 14.0
vllm:request_queue_time_seconds_created{engine="0",model_name="qwen2.5-0.5b-instruct"} 1.7824789093587415e+09
vllm:time_to_first_token_seconds_created{engine="0",model_name="qwen2.5-0.5b-instruct"} 1.7824789093587415e+09
`), LoadPolicy{})

	if sample.queueDepth != 0 {
		t.Fatalf("queue depth = %v, want 0", sample.queueDepth)
	}
	if sample.kvCache != 0.25 {
		t.Fatalf("kv cache = %v, want 0.25", sample.kvCache)
	}
	if sample.latencyMS != 0 {
		t.Fatalf("latency = %v, want 0", sample.latencyMS)
	}
}

func TestMetricsSampleIgnoresNonFiniteValues(t *testing.T) {
	sample := parseMetricsSample([]byte(`
npu_utilization_rate NaN
request_queue_depth +Inf
kv_cache_usage_ratio -Inf
decode_latency_ms NaN
`), LoadPolicy{KVCacheSoftLimit: 1})

	if sample.utilization != 0 {
		t.Fatalf("utilization = %v, want 0", sample.utilization)
	}
	if sample.queueDepth != 0 {
		t.Fatalf("queue depth = %v, want 0", sample.queueDepth)
	}
	if sample.kvCache != 0 {
		t.Fatalf("kv cache = %v, want 0", sample.kvCache)
	}
	if sample.latencyMS != 0 {
		t.Fatalf("latency = %v, want 0", sample.latencyMS)
	}
}

func TestSchedulingStateRejectsNonFiniteWeight(t *testing.T) {
	cfg := Config{
		DefaultPool: "default",
		Pools: []PoolConfig{{
			Name: "default",
			Backends: []BackendConfig{{
				ID:       "npu-a",
				URL:      "http://127.0.0.1:9001",
				Capacity: 1,
			}},
		}},
	}
	cfg.applyDefaults()

	rt, err := New(cfg)
	if err != nil {
		t.Fatalf("new router: %v", err)
	}
	backend, ok := rt.findBackend("default", "npu-a")
	if !ok {
		t.Fatal("backend not found")
	}

	backend.mu.Lock()
	backend.effectiveWeight = math.NaN()
	backend.mu.Unlock()

	if _, ok := backend.schedulingState(time.Now()); ok {
		t.Fatal("backend with non-finite weight should not be schedulable")
	}
}

func TestResourcePoolIsolation(t *testing.T) {
	cfg := Config{
		DefaultPool: "default",
		Pools: []PoolConfig{
			{
				Name: "default",
				Backends: []BackendConfig{
					{ID: "a", URL: "http://127.0.0.1:9001", Capacity: 1},
				},
			},
			{
				Name: "isolated",
				Backends: []BackendConfig{
					{ID: "c", URL: "http://127.0.0.1:9011", Capacity: 1},
				},
			},
		},
	}
	cfg.applyDefaults()

	rt, err := New(cfg)
	if err != nil {
		t.Fatalf("new router: %v", err)
	}
	backend, err := rt.pools["isolated"].pick()
	if err != nil {
		t.Fatalf("pick isolated: %v", err)
	}
	defer backend.release(time.Millisecond)
	if backend.ID() != "c" {
		t.Fatalf("isolated pool selected %q, want c", backend.ID())
	}
}
