package router

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

type Backend struct {
	id                      string
	target                  *url.URL
	healthURL               string
	metricsURL              string
	maxInflight             int64
	passiveFailureThreshold int
	passiveEjectDuration    time.Duration
	proxy                   *httputil.ReverseProxy

	inflight int64

	mu                  sync.RWMutex
	capacity            float64
	desiredWeight       float64
	effectiveWeight     float64
	healthy             bool
	remoteUtilization   float64
	queueDepth          float64
	latencyEWMA         float64
	lastError           string
	lastUpdated         time.Time
	lastHealthProbe     time.Time
	lastMetricsProbe    time.Time
	passiveUntil        time.Time
	consecutiveFailures int
}

type BackendState struct {
	ID                  string    `json:"id"`
	URL                 string    `json:"url"`
	Capacity            float64   `json:"capacity"`
	DesiredWeight       float64   `json:"desired_weight"`
	EffectiveWeight     float64   `json:"effective_weight"`
	Healthy             bool      `json:"healthy"`
	PassiveEjected      bool      `json:"passive_ejected"`
	Inflight            int64     `json:"inflight"`
	MaxInflight         int64     `json:"max_inflight"`
	RemoteUtilization   float64   `json:"remote_utilization"`
	QueueDepth          float64   `json:"queue_depth"`
	LatencyEWMAMillis   float64   `json:"latency_ewma_ms"`
	LastError           string    `json:"last_error,omitempty"`
	LastUpdated         time.Time `json:"last_updated"`
	LastHealthProbe     time.Time `json:"last_health_probe,omitempty"`
	LastMetricsProbe    time.Time `json:"last_metrics_probe,omitempty"`
	ConsecutiveFailures int       `json:"consecutive_failures"`
}

type metricsSample struct {
	utilization float64
	queueDepth  float64
}

func newBackend(cfg BackendConfig, routerCfg Config) (*Backend, error) {
	target, err := url.Parse(cfg.URL)
	if err != nil {
		return nil, err
	}

	b := &Backend{
		id:                      cfg.ID,
		target:                  target,
		healthURL:               cfg.HealthURL,
		metricsURL:              cfg.MetricsURL,
		maxInflight:             cfg.MaxInflight,
		passiveFailureThreshold: routerCfg.PassiveFailureThreshold,
		passiveEjectDuration:    routerCfg.PassiveEjectDuration.Duration,
		capacity:                cfg.Capacity,
		desiredWeight:           cfg.Capacity,
		effectiveWeight:         cfg.Capacity,
		healthy:                 true,
		lastUpdated:             time.Now(),
	}
	b.proxy = newReverseProxy(target, cfg.PreserveHost, b)
	return b, nil
}

func newReverseProxy(target *url.URL, preserveHost bool, backend *Backend) *httputil.ReverseProxy {
	proxy := &httputil.ReverseProxy{
		Director: func(req *http.Request) {
			rewriteRequestURL(req, target)
			if !preserveHost {
				req.Host = target.Host
			}
			req.Header.Set("X-Router-Backend", backend.id)
		},
		Transport: &http.Transport{
			Proxy:               http.ProxyFromEnvironment,
			MaxIdleConns:        1024,
			MaxIdleConnsPerHost: 256,
			IdleConnTimeout:     90 * time.Second,
			ForceAttemptHTTP2:   true,
		},
		FlushInterval: -1,
		ErrorHandler: func(w http.ResponseWriter, req *http.Request, err error) {
			backend.markFailure(fmt.Sprintf("proxy error: %v", err))
			http.Error(w, "upstream unavailable", http.StatusBadGateway)
		},
		ModifyResponse: func(resp *http.Response) error {
			if resp.StatusCode >= http.StatusInternalServerError {
				backend.markFailure(fmt.Sprintf("upstream status %d", resp.StatusCode))
			} else {
				backend.markSuccess()
			}
			return nil
		},
	}
	return proxy
}

func rewriteRequestURL(req *http.Request, target *url.URL) {
	targetQuery := target.RawQuery
	req.URL.Scheme = target.Scheme
	req.URL.Host = target.Host
	req.URL.Path, req.URL.RawPath = joinURLPath(target, req.URL)
	if targetQuery == "" || req.URL.RawQuery == "" {
		req.URL.RawQuery = targetQuery + req.URL.RawQuery
	} else {
		req.URL.RawQuery = targetQuery + "&" + req.URL.RawQuery
	}
}

func joinURLPath(a, b *url.URL) (path, rawpath string) {
	if a.RawPath == "" && b.RawPath == "" {
		return singleJoiningSlash(a.Path, b.Path), ""
	}
	apath := a.EscapedPath()
	bpath := b.EscapedPath()
	aslash := strings.HasSuffix(apath, "/")
	bslash := strings.HasPrefix(bpath, "/")
	switch {
	case aslash && bslash:
		return a.Path + b.Path[1:], apath + bpath[1:]
	case !aslash && !bslash:
		return a.Path + "/" + b.Path, apath + "/" + bpath
	}
	return a.Path + b.Path, apath + bpath
}

func singleJoiningSlash(a, b string) string {
	aslash := strings.HasSuffix(a, "/")
	bslash := strings.HasPrefix(b, "/")
	switch {
	case aslash && bslash:
		return a + b[1:]
	case !aslash && !bslash:
		return a + "/" + b
	}
	return a + b
}

func (b *Backend) ID() string {
	return b.id
}

func (b *Backend) Proxy() *httputil.ReverseProxy {
	return b.proxy
}

func (b *Backend) acquire() {
	atomic.AddInt64(&b.inflight, 1)
}

func (b *Backend) release(latency time.Duration) {
	atomic.AddInt64(&b.inflight, -1)
	if latency <= 0 {
		return
	}

	b.mu.Lock()
	alpha := 0.25
	ms := float64(latency.Microseconds()) / 1000
	if b.latencyEWMA == 0 {
		b.latencyEWMA = ms
	} else {
		b.latencyEWMA = alpha*ms + (1-alpha)*b.latencyEWMA
	}
	b.mu.Unlock()
}

func (b *Backend) schedulingState(now time.Time) (float64, bool) {
	b.mu.RLock()
	weight := b.effectiveWeight
	healthy := b.healthy && now.After(b.passiveUntil)
	maxInflight := b.maxInflight
	b.mu.RUnlock()

	inflight := atomic.LoadInt64(&b.inflight)
	if maxInflight > 0 && inflight >= maxInflight {
		return 0, false
	}
	return weight, healthy && weight > 0
}

func (b *Backend) state(now time.Time) BackendState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return BackendState{
		ID:                  b.id,
		URL:                 b.target.String(),
		Capacity:            b.capacity,
		DesiredWeight:       b.desiredWeight,
		EffectiveWeight:     b.effectiveWeight,
		Healthy:             b.healthy,
		PassiveEjected:      now.Before(b.passiveUntil),
		Inflight:            atomic.LoadInt64(&b.inflight),
		MaxInflight:         b.maxInflight,
		RemoteUtilization:   b.remoteUtilization,
		QueueDepth:          b.queueDepth,
		LatencyEWMAMillis:   b.latencyEWMA,
		LastError:           b.lastError,
		LastUpdated:         b.lastUpdated,
		LastHealthProbe:     b.lastHealthProbe,
		LastMetricsProbe:    b.lastMetricsProbe,
		ConsecutiveFailures: b.consecutiveFailures,
	}
}

func (b *Backend) setCapacity(capacity float64) error {
	if capacity <= 0 {
		return errors.New("capacity must be > 0")
	}

	b.mu.Lock()
	b.capacity = capacity
	b.lastUpdated = time.Now()
	b.mu.Unlock()
	return nil
}

func (b *Backend) setHealth(healthy bool) {
	b.mu.Lock()
	b.healthy = healthy
	if healthy {
		b.passiveUntil = time.Time{}
		b.consecutiveFailures = 0
		b.lastError = ""
	}
	b.lastHealthProbe = time.Now()
	b.lastUpdated = time.Now()
	b.mu.Unlock()
}

func (b *Backend) markSuccess() {
	b.mu.Lock()
	b.consecutiveFailures = 0
	b.lastError = ""
	b.mu.Unlock()
}

func (b *Backend) markFailure(message string) {
	b.mu.Lock()
	b.consecutiveFailures++
	b.lastError = message
	if b.consecutiveFailures >= b.passiveFailureThreshold {
		b.passiveUntil = time.Now().Add(b.passiveEjectDuration)
	}
	b.lastUpdated = time.Now()
	b.mu.Unlock()
}

func (b *Backend) refresh(ctx context.Context, client *http.Client, policy LoadPolicy, smoothStep float64) {
	if b.healthURL != "" {
		b.probeHealth(ctx, client)
	}
	if b.metricsURL != "" {
		b.scrapeMetrics(ctx, client, policy.EWMAAlpha)
	}
	b.recomputeWeight(policy, smoothStep)
}

func (b *Backend) probeHealth(ctx context.Context, client *http.Client) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, b.healthURL, nil)
	if err != nil {
		b.setProbeHealth(false, fmt.Sprintf("health request: %v", err))
		return
	}

	resp, err := client.Do(req)
	if err != nil {
		b.setProbeHealth(false, fmt.Sprintf("health probe: %v", err))
		return
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))

	if resp.StatusCode >= 200 && resp.StatusCode < 400 {
		b.setProbeHealth(true, "")
		return
	}
	b.setProbeHealth(false, fmt.Sprintf("health status %d", resp.StatusCode))
}

func (b *Backend) setProbeHealth(healthy bool, message string) {
	b.mu.Lock()
	b.healthy = healthy
	if healthy {
		b.consecutiveFailures = 0
		b.passiveUntil = time.Time{}
		b.lastError = ""
	} else {
		b.lastError = message
	}
	b.lastHealthProbe = time.Now()
	b.lastUpdated = time.Now()
	b.mu.Unlock()
}

func (b *Backend) scrapeMetrics(ctx context.Context, client *http.Client, alpha float64) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, b.metricsURL, nil)
	if err != nil {
		b.markTelemetryError(fmt.Sprintf("metrics request: %v", err))
		return
	}

	resp, err := client.Do(req)
	if err != nil {
		b.markTelemetryError(fmt.Sprintf("metrics scrape: %v", err))
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 400 {
		_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
		b.markTelemetryError(fmt.Sprintf("metrics status %d", resp.StatusCode))
		return
	}

	data, err := io.ReadAll(io.LimitReader(resp.Body, 2<<20))
	if err != nil {
		b.markTelemetryError(fmt.Sprintf("metrics read: %v", err))
		return
	}

	sample := parseMetricsSample(data)
	b.mu.Lock()
	if alpha <= 0 || alpha > 1 {
		alpha = 0.35
	}
	if b.remoteUtilization == 0 {
		b.remoteUtilization = sample.utilization
	} else {
		b.remoteUtilization = alpha*sample.utilization + (1-alpha)*b.remoteUtilization
	}
	if b.queueDepth == 0 {
		b.queueDepth = sample.queueDepth
	} else {
		b.queueDepth = alpha*sample.queueDepth + (1-alpha)*b.queueDepth
	}
	b.lastMetricsProbe = time.Now()
	b.lastUpdated = time.Now()
	b.mu.Unlock()
}

func (b *Backend) markTelemetryError(message string) {
	b.mu.Lock()
	b.lastError = message
	b.lastMetricsProbe = time.Now()
	b.lastUpdated = time.Now()
	b.mu.Unlock()
}

func parseMetricsSample(data []byte) metricsSample {
	trimmed := strings.TrimSpace(string(data))
	if strings.HasPrefix(trimmed, "{") {
		return parseJSONMetrics([]byte(trimmed))
	}
	return parsePrometheusMetrics(trimmed)
}

func parseJSONMetrics(data []byte) metricsSample {
	var raw map[string]float64
	if err := json.Unmarshal(data, &raw); err != nil {
		return metricsSample{}
	}

	var sample metricsSample
	for key, value := range raw {
		key = strings.ToLower(key)
		switch {
		case strings.Contains(key, "util"):
			sample.utilization = math.Max(sample.utilization, normalizeRatio(value))
		case strings.Contains(key, "queue") || strings.Contains(key, "waiting"):
			sample.queueDepth = math.Max(sample.queueDepth, value)
		}
	}
	return sample
}

func parsePrometheusMetrics(text string) metricsSample {
	scanner := bufio.NewScanner(strings.NewReader(text))
	sample := metricsSample{}
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}

		fields := strings.Fields(line)
		if len(fields) < 2 {
			continue
		}
		name := metricName(fields[0])
		value, err := strconv.ParseFloat(fields[len(fields)-1], 64)
		if err != nil {
			continue
		}

		switch {
		case looksLikeUtilizationMetric(name):
			sample.utilization = math.Max(sample.utilization, normalizeRatio(value))
		case looksLikeQueueMetric(name):
			sample.queueDepth = math.Max(sample.queueDepth, value)
		}
	}
	return sample
}

func metricName(token string) string {
	if idx := strings.IndexByte(token, '{'); idx >= 0 {
		token = token[:idx]
	}
	return strings.ToLower(token)
}

func looksLikeUtilizationMetric(name string) bool {
	if strings.Contains(name, "memory") || strings.Contains(name, "hbm") {
		return false
	}
	return strings.Contains(name, "npu_util") ||
		strings.Contains(name, "ai_core_util") ||
		strings.Contains(name, "aicore_util") ||
		strings.Contains(name, "gpu_util") ||
		strings.Contains(name, "device_util") ||
		strings.Contains(name, "utilization_rate")
}

func looksLikeQueueMetric(name string) bool {
	return strings.Contains(name, "queue_depth") ||
		strings.Contains(name, "request_queue") ||
		strings.Contains(name, "waiting_requests") ||
		strings.Contains(name, "pending_requests")
}

func normalizeRatio(value float64) float64 {
	if value > 1 {
		value = value / 100
	}
	return clamp(value, 0, 1)
}

func (b *Backend) recomputeWeight(policy LoadPolicy, smoothStep float64) {
	b.mu.Lock()
	defer b.mu.Unlock()

	now := time.Now()
	eligible := b.healthy && now.After(b.passiveUntil)
	desired := 0.0
	if eligible {
		inflightRatio := 0.0
		if b.maxInflight > 0 {
			inflightRatio = clamp(float64(atomic.LoadInt64(&b.inflight))/float64(b.maxInflight), 0, 1)
		}
		queueRatio := clamp(b.queueDepth/policy.QueueSoftLimit, 0, 1)
		loadScore := weightedLoadScore(policy, b.remoteUtilization, queueRatio, inflightRatio)
		headroom := 1 - clamp(loadScore, 0, 1)
		if headroom < policy.MinHealthyFraction {
			headroom = policy.MinHealthyFraction
		}
		if b.maxInflight > 0 && atomic.LoadInt64(&b.inflight) >= b.maxInflight {
			headroom = 0
		}
		desired = b.capacity * headroom
	}

	b.desiredWeight = desired
	b.effectiveWeight += (desired - b.effectiveWeight) * smoothStep
	if b.effectiveWeight < 0.0001 {
		b.effectiveWeight = 0
	}
	b.lastUpdated = now
}

func weightedLoadScore(policy LoadPolicy, utilRatio, queueRatio, inflightRatio float64) float64 {
	total := policy.UtilizationWeight + policy.QueueWeight + policy.InflightWeight
	if total <= 0 {
		return 0
	}
	return (policy.UtilizationWeight*utilRatio +
		policy.QueueWeight*queueRatio +
		policy.InflightWeight*inflightRatio) / total
}

func clamp(value, low, high float64) float64 {
	if value < low {
		return low
	}
	if value > high {
		return high
	}
	return value
}
