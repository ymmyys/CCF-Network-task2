package router

import (
	"errors"
	"math"
	"math/rand"
	"sync"
	"time"
)

var ErrNoBackendAvailable = errors.New("no backend available")

type backendSlot struct {
	backend *Backend
	current float64
}

type Pool struct {
	name      string
	backends  []*backendSlot
	scheduler Scheduler
	load      LoadPolicy
	rng       *rand.Rand
	mu        sync.Mutex
}

type PoolState struct {
	Name     string         `json:"name"`
	Backends []BackendState `json:"backends"`
}

func newPool(cfg PoolConfig, routerCfg Config) (*Pool, error) {
	pool := &Pool{
		name:      cfg.Name,
		scheduler: routerCfg.Scheduler,
		load:      routerCfg.Load,
		rng:       rand.New(rand.NewSource(time.Now().UnixNano())),
	}
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

	switch p.scheduler.Mode {
	case "swrr":
		return p.pickSWRRLocked()
	default:
		return p.pickP2CLocked()
	}
}

func (p *Pool) pickSWRRLocked() (*Backend, error) {
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

type candidateSlot struct {
	slot   *backendSlot
	weight float64
}

func (p *Pool) pickP2CLocked() (*Backend, error) {
	now := time.Now()
	candidates, total := p.collectCandidatesLocked(now)
	if len(candidates) == 0 || total <= 0 {
		return nil, ErrNoBackendAvailable
	}
	if len(candidates) == 1 {
		return p.commitPick(candidates[0].slot, total), nil
	}

	first := p.weightedCandidate(candidates, total, nil)
	second := p.weightedCandidate(candidates, total-first.weight, first.slot)
	if second.slot == nil {
		second = p.bestCurrentCandidate(candidates, first.slot)
	}

	winner := p.betterP2CCandidate(first, second)
	return p.commitPick(winner.slot, total), nil
}

func (p *Pool) collectCandidatesLocked(now time.Time) ([]candidateSlot, float64) {
	candidates := make([]candidateSlot, 0, len(p.backends))
	total := 0.0
	for _, slot := range p.backends {
		weight, ok := slot.backend.schedulingState(now)
		if !ok {
			continue
		}
		slot.current += weight
		total += weight
		candidates = append(candidates, candidateSlot{slot: slot, weight: weight})
	}
	return candidates, total
}

func (p *Pool) weightedCandidate(candidates []candidateSlot, total float64, exclude *backendSlot) candidateSlot {
	if total <= 0 {
		return candidateSlot{}
	}
	pick := p.rng.Float64() * total
	for _, candidate := range candidates {
		if candidate.slot == exclude {
			continue
		}
		pick -= candidate.weight
		if pick <= 0 {
			return candidate
		}
	}
	for _, candidate := range candidates {
		if candidate.slot != exclude {
			return candidate
		}
	}
	return candidateSlot{}
}

func (p *Pool) bestCurrentCandidate(candidates []candidateSlot, exclude *backendSlot) candidateSlot {
	var best candidateSlot
	for _, candidate := range candidates {
		if candidate.slot == exclude {
			continue
		}
		if best.slot == nil || candidate.slot.current > best.slot.current {
			best = candidate
		}
	}
	return best
}

func (p *Pool) betterP2CCandidate(a, b candidateSlot) candidateSlot {
	if b.slot == nil {
		return a
	}

	aLoad := a.slot.backend.p2cLoadScore(p.load)
	bLoad := b.slot.backend.p2cLoadScore(p.load)
	if math.Abs(aLoad-bLoad) > 0.05 {
		if aLoad < bLoad {
			return a
		}
		return b
	}
	if a.slot.current != b.slot.current {
		if a.slot.current > b.slot.current {
			return a
		}
		return b
	}
	if a.weight >= b.weight {
		return a
	}
	return b
}

func (p *Pool) commitPick(slot *backendSlot, total float64) *Backend {
	slot.current -= total
	slot.backend.acquire()
	return slot.backend
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
