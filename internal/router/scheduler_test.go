package router

import (
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
