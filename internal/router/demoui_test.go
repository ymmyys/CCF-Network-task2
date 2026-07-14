package router

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestDemoUIServedFromAdminPlane(t *testing.T) {
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
	rt, err := New(cfg)
	if err != nil {
		t.Fatalf("new router: %v", err)
	}

	srv := httptest.NewServer(rt.AdminHandler())
	t.Cleanup(srv.Close)

	resp, err := http.Get(srv.URL + "/demo/")
	if err != nil {
		t.Fatalf("get demo: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d", resp.StatusCode)
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("read body: %v", err)
	}
	if !strings.Contains(string(body), "MUTT Live Console") {
		t.Fatalf("demo page missing title")
	}

	stateResp, err := http.Get(srv.URL + "/admin/state")
	if err != nil {
		t.Fatalf("get state: %v", err)
	}
	defer stateResp.Body.Close()
	if stateResp.Header.Get("Access-Control-Allow-Origin") != "*" {
		t.Fatalf("expected CORS header on admin state")
	}
}
