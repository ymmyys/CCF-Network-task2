package router

import (
	"errors"
	"sync"
	"time"
)

var ErrNoBackendAvailable = errors.New("no backend available")

type backendSlot struct {
	backend *Backend
	current float64
}

type Pool struct {
	name     string
	backends []*backendSlot
	mu       sync.Mutex
}

type PoolState struct {
	Name     string         `json:"name"`
	Backends []BackendState `json:"backends"`
}

func newPool(cfg PoolConfig, routerCfg Config) (*Pool, error) {
	pool := &Pool{name: cfg.Name}
	for _, backendCfg := range cfg.Backends {
		backend, err := newBackend(backendCfg, routerCfg)
		if err != nil {
			return nil, err
		}
		pool.backends = append(pool.backends, &backendSlot{backend: backend})
	}
	return pool, nil
}

func (p *Pool) pick() (*Backend, error) {
	p.mu.Lock()
	defer p.mu.Unlock()

	now := time.Now()
	var best *backendSlot
	total := 0.0

	for _, slot := range p.backends {
		weight, ok := slot.backend.schedulingState(now)
		if !ok {
			continue
		}
		slot.current += weight
		total += weight
		if best == nil || slot.current > best.current {
			best = slot
		}
	}

	if best == nil || total <= 0 {
		return nil, ErrNoBackendAvailable
	}

	best.current -= total
	best.backend.acquire()
	return best.backend, nil
}

func (p *Pool) state(now time.Time) PoolState {
	state := PoolState{
		Name:     p.name,
		Backends: make([]BackendState, 0, len(p.backends)),
	}
	for _, slot := range p.backends {
		state.Backends = append(state.Backends, slot.backend.state(now))
	}
	return state
}

func (p *Pool) backend(id string) *Backend {
	for _, slot := range p.backends {
		if slot.backend.ID() == id {
			return slot.backend
		}
	}
	return nil
}

func (p *Pool) refreshAll(ctxDone <-chan struct{}, refresh func(*Backend)) {
	for _, slot := range p.backends {
		select {
		case <-ctxDone:
			return
		default:
			refresh(slot.backend)
		}
	}
}
