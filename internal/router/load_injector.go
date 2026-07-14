package router

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"sync"
	"time"
)

const (
	maxInjectedRequests    = 500
	maxInjectedConcurrency = 32
	maxInjectedTokens      = 128
)

type loadInjectionRequest struct {
	Pool        string `json:"pool"`
	Model       string `json:"model"`
	Prompt      string `json:"prompt"`
	Requests    int    `json:"requests"`
	Concurrency int    `json:"concurrency"`
	MaxTokens   int    `json:"max_tokens"`
}

type loadInjectionState struct {
	ID          uint64    `json:"id"`
	Running     bool      `json:"running"`
	Canceled    bool      `json:"canceled"`
	Pool        string    `json:"pool,omitempty"`
	Model       string    `json:"model,omitempty"`
	Total       int       `json:"total"`
	Completed   int       `json:"completed"`
	Failed      int       `json:"failed"`
	Concurrency int       `json:"concurrency"`
	MaxTokens   int       `json:"max_tokens"`
	StartedAt   time.Time `json:"started_at,omitempty"`
	FinishedAt  time.Time `json:"finished_at,omitempty"`
	LastError   string    `json:"last_error,omitempty"`
}

type loadInjector struct {
	mu         sync.RWMutex
	nextID     uint64
	state      loadInjectionState
	cancel     context.CancelFunc
	endpoint   string
	poolHeader string
	client     *http.Client
}

func newLoadInjector(endpoint, poolHeader string) *loadInjector {
	return &loadInjector{
		endpoint:   endpoint,
		poolHeader: poolHeader,
		client: &http.Client{
			Timeout: 2 * time.Minute,
		},
	}
}

func dataPlaneCompletionEndpoint(listen string) string {
	port := "8080"
	if strings.HasPrefix(listen, ":") {
		port = strings.TrimPrefix(listen, ":")
	} else if _, parsedPort, err := net.SplitHostPort(listen); err == nil {
		port = parsedPort
	}
	return "http://127.0.0.1:" + port + "/v1/chat/completions"
}

func (li *loadInjector) start(request loadInjectionRequest) (loadInjectionState, error) {
	if request.Model == "" {
		return loadInjectionState{}, fmt.Errorf("model is required")
	}
	if request.Prompt == "" {
		return loadInjectionState{}, fmt.Errorf("prompt is required")
	}
	if len(request.Model) > 200 {
		return loadInjectionState{}, fmt.Errorf("model is too long")
	}
	if len(request.Prompt) > 4000 {
		return loadInjectionState{}, fmt.Errorf("prompt must not exceed 4000 bytes")
	}
	if request.Requests < 1 || request.Requests > maxInjectedRequests {
		return loadInjectionState{}, fmt.Errorf("requests must be between 1 and %d", maxInjectedRequests)
	}
	if request.Concurrency < 1 || request.Concurrency > maxInjectedConcurrency {
		return loadInjectionState{}, fmt.Errorf("concurrency must be between 1 and %d", maxInjectedConcurrency)
	}
	if request.MaxTokens < 1 || request.MaxTokens > maxInjectedTokens {
		return loadInjectionState{}, fmt.Errorf("max_tokens must be between 1 and %d", maxInjectedTokens)
	}

	li.mu.Lock()
	defer li.mu.Unlock()
	if li.state.Running {
		return loadInjectionState{}, fmt.Errorf("a load injection job is already running")
	}

	li.nextID++
	ctx, cancel := context.WithCancel(context.Background())
	li.cancel = cancel
	li.state = loadInjectionState{
		ID:          li.nextID,
		Running:     true,
		Pool:        request.Pool,
		Model:       request.Model,
		Total:       request.Requests,
		Concurrency: request.Concurrency,
		MaxTokens:   request.MaxTokens,
		StartedAt:   time.Now(),
	}
	state := li.state
	go li.run(ctx, state.ID, request)
	return state, nil
}

func (li *loadInjector) run(ctx context.Context, jobID uint64, request loadInjectionRequest) {
	payload, err := json.Marshal(map[string]any{
		"model": request.Model,
		"messages": []map[string]string{{
			"role":    "user",
			"content": request.Prompt,
		}},
		"max_tokens":  request.MaxTokens,
		"temperature": 0,
	})
	if err != nil {
		li.finish(jobID, err)
		return
	}

	jobs := make(chan struct{})
	var workers sync.WaitGroup
	for worker := 0; worker < request.Concurrency; worker++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for range jobs {
				if ctx.Err() != nil {
					return
				}
				li.send(ctx, jobID, request.Pool, payload)
			}
		}()
	}

sendLoop:
	for requestIndex := 0; requestIndex < request.Requests; requestIndex++ {
		select {
		case jobs <- struct{}{}:
		case <-ctx.Done():
			break sendLoop
		}
	}
	close(jobs)
	workers.Wait()
	li.finish(jobID, nil)
}

func (li *loadInjector) send(ctx context.Context, jobID uint64, pool string, payload []byte) {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, li.endpoint, bytes.NewReader(payload))
	if err == nil {
		req.Header.Set("Content-Type", "application/json")
		if pool != "" {
			req.Header.Set(li.poolHeader, pool)
		}
		var response *http.Response
		response, err = li.client.Do(req)
		if err == nil {
			_, _ = io.Copy(io.Discard, response.Body)
			_ = response.Body.Close()
			if response.StatusCode >= http.StatusBadRequest {
				err = fmt.Errorf("router returned HTTP %d", response.StatusCode)
			}
		}
	}

	li.mu.Lock()
	defer li.mu.Unlock()
	if li.state.ID != jobID {
		return
	}
	if err != nil {
		if errors.Is(err, context.Canceled) {
			return
		}
		li.state.Failed++
		li.state.LastError = err.Error()
		return
	}
	li.state.Completed++
}

func (li *loadInjector) finish(jobID uint64, err error) {
	li.mu.Lock()
	defer li.mu.Unlock()
	if li.state.ID != jobID {
		return
	}
	li.state.Running = false
	li.state.FinishedAt = time.Now()
	li.cancel = nil
	if err != nil {
		li.state.LastError = err.Error()
	}
}

func (li *loadInjector) stop() loadInjectionState {
	li.mu.Lock()
	if li.cancel != nil {
		li.state.Canceled = true
		li.cancel()
	}
	state := li.state
	li.mu.Unlock()
	return state
}

func (li *loadInjector) snapshot() loadInjectionState {
	li.mu.RLock()
	defer li.mu.RUnlock()
	return li.state
}
