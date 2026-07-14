package router

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

func TestDataPlaneCompletionEndpoint(t *testing.T) {
	tests := map[string]string{
		":8180":        "http://127.0.0.1:8180/v1/chat/completions",
		"0.0.0.0:8180": "http://127.0.0.1:8180/v1/chat/completions",
		"[::]:8180":    "http://127.0.0.1:8180/v1/chat/completions",
	}
	for listen, want := range tests {
		if got := dataPlaneCompletionEndpoint(listen); got != want {
			t.Fatalf("endpoint for %q = %q, want %q", listen, got, want)
		}
	}
}

func TestLoadInjectorSendsBoundedRequests(t *testing.T) {
	var received int64
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		if req.URL.Path != "/v1/chat/completions" {
			t.Errorf("path = %q", req.URL.Path)
		}
		if got := req.Header.Get("X-Resource-Pool"); got != "default" {
			t.Errorf("pool header = %q", got)
		}
		var body map[string]any
		if err := json.NewDecoder(req.Body).Decode(&body); err != nil {
			t.Errorf("decode body: %v", err)
		}
		atomic.AddInt64(&received, 1)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"choices":[{"message":{"content":"OK"}}]}`))
	}))
	defer server.Close()

	injector := newLoadInjector(server.URL+"/v1/chat/completions", "X-Resource-Pool")
	started, err := injector.start(loadInjectionRequest{
		Pool:        "default",
		Model:       "test-model",
		Prompt:      "hello",
		Requests:    12,
		Concurrency: 4,
		MaxTokens:   8,
	})
	if err != nil {
		t.Fatalf("start injector: %v", err)
	}
	if !started.Running {
		t.Fatal("started job is not running")
	}

	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		state := injector.snapshot()
		if !state.Running {
			if state.Completed != 12 || state.Failed != 0 {
				t.Fatalf("completed=%d failed=%d", state.Completed, state.Failed)
			}
			if got := atomic.LoadInt64(&received); got != 12 {
				t.Fatalf("received = %d, want 12", got)
			}
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("load injection did not finish")
}

func TestLoadInjectorRejectsUnsafeBounds(t *testing.T) {
	injector := newLoadInjector("http://127.0.0.1:8180/v1/chat/completions", "X-Resource-Pool")
	_, err := injector.start(loadInjectionRequest{
		Pool:        "default",
		Model:       "test-model",
		Prompt:      "hello",
		Requests:    maxInjectedRequests + 1,
		Concurrency: 1,
		MaxTokens:   8,
	})
	if err == nil {
		t.Fatal("unsafe request count was accepted")
	}
}

func TestLoadInjectorCancellationIsNotFailure(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		time.Sleep(200 * time.Millisecond)
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	injector := newLoadInjector(server.URL, "X-Resource-Pool")
	_, err := injector.start(loadInjectionRequest{
		Pool:        "default",
		Model:       "test-model",
		Prompt:      "hello",
		Requests:    10,
		Concurrency: 2,
		MaxTokens:   8,
	})
	if err != nil {
		t.Fatalf("start injector: %v", err)
	}
	time.Sleep(20 * time.Millisecond)
	injector.stop()

	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		state := injector.snapshot()
		if !state.Running {
			if !state.Canceled {
				t.Fatal("canceled job is not marked canceled")
			}
			if state.Failed != 0 {
				t.Fatalf("canceled requests counted as failures: %d", state.Failed)
			}
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("canceled load injection did not stop")
}
