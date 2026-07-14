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

type BackendPhase string
type TransitionReason string

const (
	PhaseActive     BackendPhase = "active"
	PhaseDraining   BackendPhase = "draining"
	PhaseDrained    BackendPhase = "drained"
	PhaseRecovering BackendPhase = "recovering"
)

const (
	ReasonNone              TransitionReason = ""
	ReasonCapacityDownscale TransitionReason = "capacity_downscale"
	ReasonCapacityZero      TransitionReason = "capacity_zero"
	ReasonCapacityUpscale   TransitionReason = "capacity_upscale"
	ReasonAdminDisabled     TransitionReason = "admin_disabled"
	ReasonAdminEnabled      TransitionReason = "admin_enabled"
	ReasonHealthFailed      TransitionReason = "health_probe_failed"
	ReasonHealthRecovered   TransitionReason = "health_recovered"
	ReasonPassiveFailure    TransitionReason = "passive_failure"
	ReasonPassiveRecovered  TransitionReason = "passive_recovered"
)

const weightEpsilon = 0.0001

type Backend struct {
	id                      string
	target                  *url.URL
	healthURL               string
	metricsURL              string
	maxInflight             int64
	passiveFailureThreshold int
	passiveEjectDuration    time.Duration
	failureCooloffDuration  time.Duration
	slowStartDuration       time.Duration
	proxy                   *httputil.ReverseProxy

	inflight int64
	selected uint64

	mu                  sync.RWMutex
	capacity            float64
	desiredWeight       float64
	effectiveWeight     float64
	healthy             bool
	adminDisabled       bool
	phase               BackendPhase
	transitionReason    TransitionReason
	phaseSince          time.Time
	remoteUtilization   float64
	queueDepth          float64
	kvCacheUsage        float64
	latencyEWMA         float64
	lastError           string
	lastUpdated         time.Time
	lastHealthProbe     time.Time
	lastMetricsProbe    time.Time
	passiveUntil        time.Time
	failureCooloffUntil time.Time
	consecutiveFailures int
}

type BackendState struct {
	ID                  string    `json:"id"`
	URL                 string    `json:"url"`
	Phase               string    `json:"phase"`
	TransitionReason    string    `json:"transition_reason,omitempty"`
	PhaseSince          time.Time `json:"phase_since"`
	SlowStartProgress   float64   `json:"slow_start_progress"`
	Capacity            float64   `json:"capacity"`
	DesiredWeight       float64   `json:"desired_weight"`
	EffectiveWeight     float64   `json:"effective_weight"`
	Healthy             bool      `json:"healthy"`
	ObservedHealthy     bool      `json:"observed_healthy"`
	AdminDisabled       bool      `json:"admin_disabled"`
	PassiveEjected      bool      `json:"passive_ejected"`
	FailureCoolingOff   bool      `json:"failure_cooling_off"`
	Inflight            int64     `json:"inflight"`
	SelectedTotal       uint64    `json:"selected_total"`
	MaxInflight         int64     `json:"max_inflight"`
	RemoteUtilization   float64   `json:"remote_utilization"`
	QueueDepth          float64   `json:"queue_depth"`
	KVCacheUsage        float64   `json:"kv_cache_usage"`
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
	kvCache     float64
	latencyMS   float64
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
		failureCooloffDuration:  routerCfg.FailureCooloffDuration.Duration,
		slowStartDuration:       routerCfg.SlowStartDuration.Duration,
		capacity:                cfg.Capacity,
		desiredWeight:           cfg.Capacity,
		effectiveWeight:         cfg.Capacity,
		healthy:                 true,
		phase:                   PhaseActive,
		phaseSince:              time.Now(),
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
			if shouldMarkProxyFailure(req, err) {
				backend.markFailure(fmt.Sprintf("proxy error: %v", err))
			}
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

func shouldMarkProxyFailure(req *http.Request, err error) bool {
	return req.Context().Err() == nil && !errors.Is(err, context.Canceled)
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
	atomic.AddUint64(&b.selected, 1)
	atomic.AddInt64(&b.inflight, 1)
}

func (b *Backend) release(latency time.Duration) {
	atomic.AddInt64(&b.inflight, -1)
	if latency <= 0 {
		return
	}

	b.mu.Lock()
	b.updateLatencyEWMALocked(float64(latency.Microseconds())/1000, 0.25)
	b.mu.Unlock()
}

func (b *Backend) schedulingState(now time.Time) (float64, bool) {
	b.mu.RLock()
	weight := b.effectiveWeight
	healthy := b.healthy
	adminDisabled := b.adminDisabled
	passiveUntil := b.passiveUntil
	failureCooloffUntil := b.failureCooloffUntil
	maxInflight := b.maxInflight
	capacity := b.capacity
	phase := b.phase
	b.mu.RUnlock()

	inflight := atomic.LoadInt64(&b.inflight)

	if maxInflight > 0 && inflight >= maxInflight {
		return 0, false
	}
	// 完全不可用: capacity=0 / Drained / unhealthy 且不在 recovering
	if capacity <= 0 || phase == PhaseDrained {
		return 0, false
	}
	// 健康检查失败或被动熔断中: 不可调度
	if !healthy || adminDisabled || now.Before(passiveUntil) {
		return 0, false
	}
	if now.Before(failureCooloffUntil) {
		return 0, false
	}
	// weight <= 0 or non-finite: not schedulable
	if !isFinite(weight) || weight <= 0 {
		return 0, false
	}
	return weight, true
}

func (b *Backend) state(now time.Time) BackendState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return BackendState{
		ID:                  b.id,
		URL:                 b.target.String(),
		Phase:               string(b.phase),
		TransitionReason:    string(b.transitionReason),
		PhaseSince:          b.phaseSince,
		SlowStartProgress:   b.slowStartProgressLocked(now),
		Capacity:            b.capacity,
		DesiredWeight:       b.desiredWeight,
		EffectiveWeight:     b.effectiveWeight,
		Healthy:             b.healthy && !b.adminDisabled,
		ObservedHealthy:     b.healthy,
		AdminDisabled:       b.adminDisabled,
		PassiveEjected:      now.Before(b.passiveUntil),
		FailureCoolingOff:   now.Before(b.failureCooloffUntil),
		Inflight:            atomic.LoadInt64(&b.inflight),
		SelectedTotal:       atomic.LoadUint64(&b.selected),
		MaxInflight:         b.maxInflight,
		RemoteUtilization:   b.remoteUtilization,
		QueueDepth:          b.queueDepth,
		KVCacheUsage:        b.kvCacheUsage,
		LatencyEWMAMillis:   b.latencyEWMA,
		LastError:           b.lastError,
		LastUpdated:         b.lastUpdated,
		LastHealthProbe:     b.lastHealthProbe,
		LastMetricsProbe:    b.lastMetricsProbe,
		ConsecutiveFailures: b.consecutiveFailures,
	}
}

func (b *Backend) setCapacity(capacity float64) error {
	if capacity < 0 {
		return errors.New("capacity must be >= 0")
	}

	b.mu.Lock()
	oldCapacity := b.capacity
	b.capacity = capacity
	now := time.Now()
	switch {
	case capacity <= 0:
		b.enterTransitionLocked(PhaseDraining, ReasonCapacityZero, now)
	case capacity < oldCapacity:
		b.enterTransitionLocked(PhaseDraining, ReasonCapacityDownscale, now)
	case capacity > oldCapacity && b.healthy && !b.adminDisabled && now.After(b.passiveUntil):
		b.enterTransitionLocked(PhaseRecovering, ReasonCapacityUpscale, now)
	}
	b.lastUpdated = now
	b.mu.Unlock()
	return nil
}

func (b *Backend) setAdminHealth(healthy bool) {
	b.mu.Lock()
	now := time.Now()
	wasUnavailable := b.adminDisabled || !b.healthy || now.Before(b.passiveUntil) || b.phase == PhaseDrained || b.phase == PhaseDraining
	if healthy {
		b.adminDisabled = false
		b.passiveUntil = time.Time{}
		b.failureCooloffUntil = time.Time{}
		b.consecutiveFailures = 0
		b.lastError = ""
		if b.capacity > 0 && b.healthy && wasUnavailable {
			b.enterTransitionLocked(PhaseRecovering, ReasonAdminEnabled, now)
		}
	} else {
		b.adminDisabled = true
		if b.phase != PhaseDrained {
			b.enterTransitionLocked(PhaseDraining, ReasonAdminDisabled, now)
		}
	}
	b.lastUpdated = now
	b.mu.Unlock()
}

func (b *Backend) markSuccess() {
	b.mu.Lock()
	b.consecutiveFailures = 0
	b.failureCooloffUntil = time.Time{}
	b.lastError = ""
	b.mu.Unlock()
}

func (b *Backend) markFailure(message string) {
	b.mu.Lock()
	now := time.Now()
	b.consecutiveFailures++
	b.lastError = message
	if b.failureCooloffDuration > 0 {
		b.failureCooloffUntil = now.Add(b.failureCooloffDuration)
	}
	if b.phase != PhaseDrained {
		b.enterTransitionLocked(PhaseDraining, ReasonPassiveFailure, now)
	}
	if b.consecutiveFailures >= b.passiveFailureThreshold {
		b.passiveUntil = now.Add(b.passiveEjectDuration)
	}
	b.lastUpdated = now
	b.mu.Unlock()
}

func (b *Backend) refresh(ctx context.Context, client *http.Client, policy LoadPolicy, smoothStep float64) {
	if b.healthURL != "" {
		b.probeHealth(ctx, client)
	}
	if b.metricsURL != "" {
		b.scrapeMetrics(ctx, client, policy)
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
	now := time.Now()
	b.healthy = healthy
	if healthy {
		b.consecutiveFailures = 0
		b.passiveUntil = time.Time{}
		b.failureCooloffUntil = time.Time{}
		b.lastError = ""
		canRecover := b.transitionReason == ReasonHealthFailed || b.transitionReason == ReasonPassiveFailure
		if !b.adminDisabled && b.capacity > 0 && canRecover && (b.phase == PhaseDrained || b.phase == PhaseDraining) {
			b.enterTransitionLocked(PhaseRecovering, ReasonHealthRecovered, now)
		}
	} else {
		b.lastError = message
		if b.phase != PhaseDrained {
			b.enterTransitionLocked(PhaseDraining, ReasonHealthFailed, now)
		}
	}
	b.lastHealthProbe = now
	b.lastUpdated = now
	b.mu.Unlock()
}

func (b *Backend) scrapeMetrics(ctx context.Context, client *http.Client, policy LoadPolicy) {
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

	sample := parseMetricsSample(data, policy)
	b.mu.Lock()
	alpha := policy.EWMAAlpha
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
	if b.kvCacheUsage == 0 {
		b.kvCacheUsage = sample.kvCache
	} else {
		b.kvCacheUsage = alpha*sample.kvCache + (1-alpha)*b.kvCacheUsage
	}
	if sample.latencyMS > 0 {
		b.updateLatencyEWMALocked(sample.latencyMS, alpha)
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

func parseMetricsSample(data []byte, policy LoadPolicy) metricsSample {
	trimmed := strings.TrimSpace(string(data))
	if strings.HasPrefix(trimmed, "{") {
		return parseJSONMetrics([]byte(trimmed), policy)
	}
	return parsePrometheusMetrics(trimmed, policy)
}

func parseJSONMetrics(data []byte, policy LoadPolicy) metricsSample {
	var raw map[string]float64
	if err := json.Unmarshal(data, &raw); err != nil {
		return metricsSample{}
	}

	var sample metricsSample
	for key, value := range raw {
		key = strings.ToLower(key)
		switch {
		case looksLikeKVCacheMetric(key):
			sample.kvCache = math.Max(sample.kvCache, normalizeKVCacheMetric(key, value, policy.KVCacheSoftLimit))
		case looksLikeLatencyMetric(key):
			sample.latencyMS = math.Max(sample.latencyMS, normalizeLatencyMillis(key, value))
		case strings.Contains(key, "queue") || strings.Contains(key, "waiting"):
			sample.queueDepth = math.Max(sample.queueDepth, value)
		case strings.Contains(key, "util"):
			sample.utilization = math.Max(sample.utilization, normalizeRatio(value))
		}
	}
	return sample
}

func parsePrometheusMetrics(text string, policy LoadPolicy) metricsSample {
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
		if isPrometheusCreatedMetric(name) {
			continue
		}
		value, err := strconv.ParseFloat(fields[len(fields)-1], 64)
		if err != nil {
			continue
		}
		if !isFinite(value) {
			continue
		}

		switch {
		case looksLikeKVCacheMetric(name):
			sample.kvCache = math.Max(sample.kvCache, normalizeKVCacheMetric(name, value, policy.KVCacheSoftLimit))
		case looksLikeLatencyMetric(name):
			sample.latencyMS = math.Max(sample.latencyMS, normalizeLatencyMillis(name, value))
		case looksLikeActiveRequestMetric(name):
			sample.utilization = math.Max(sample.utilization, normalizeActiveRequestMetric(value, policy.QueueSoftLimit))
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

func isPrometheusCreatedMetric(name string) bool {
	return strings.HasSuffix(name, "_created")
}

func looksLikeUtilizationMetric(name string) bool {
	if strings.Contains(name, "memory") || strings.Contains(name, "hbm") {
		return false
	}
	if looksLikeKVCacheMetric(name) || looksLikeLatencyMetric(name) || looksLikeQueueMetric(name) || looksLikeActiveRequestMetric(name) {
		return false
	}
	return strings.Contains(name, "npu_util") ||
		strings.Contains(name, "ai_core_util") ||
		strings.Contains(name, "aicore_util") ||
		strings.Contains(name, "gpu_util") ||
		strings.Contains(name, "device_util") ||
		strings.Contains(name, "utilization_rate")
}

func looksLikeActiveRequestMetric(name string) bool {
	if isPrometheusHistogramPart(name) {
		return false
	}
	return strings.Contains(name, "num_requests_running") ||
		strings.Contains(name, "requests_running") ||
		strings.Contains(name, "running_requests") ||
		strings.Contains(name, "running_request")
}

func looksLikeQueueMetric(name string) bool {
	if isPrometheusHistogramPart(name) || strings.Contains(name, "queue_time") {
		return false
	}
	return strings.Contains(name, "queue_depth") ||
		strings.Contains(name, "request_queue") ||
		strings.Contains(name, "requests_waiting") ||
		strings.Contains(name, "num_requests_waiting") ||
		strings.Contains(name, "waiting_requests") ||
		strings.Contains(name, "pending_requests")
}

func looksLikeKVCacheMetric(name string) bool {
	return strings.Contains(name, "kv_cache") ||
		strings.Contains(name, "kvcache") ||
		strings.Contains(name, "gpu_cache") ||
		strings.Contains(name, "cpu_cache") ||
		strings.Contains(name, "cache_usage") ||
		strings.Contains(name, "cache_block")
}

func looksLikeLatencyMetric(name string) bool {
	if isPrometheusHistogramPart(name) {
		return false
	}
	return strings.Contains(name, "latency") ||
		strings.Contains(name, "duration") ||
		strings.Contains(name, "ttft") ||
		strings.Contains(name, "time_to_first_token") ||
		strings.Contains(name, "decode_time") ||
		strings.Contains(name, "prefill_time")
}

func isPrometheusHistogramPart(name string) bool {
	return strings.HasSuffix(name, "_bucket") ||
		strings.HasSuffix(name, "_count") ||
		strings.HasSuffix(name, "_sum") ||
		strings.HasSuffix(name, "_created")
}

func normalizeRatio(value float64) float64 {
	if !isFinite(value) {
		return 0
	}
	if value > 1 {
		value = value / 100
	}
	return clamp(value, 0, 1)
}

func normalizeKVCacheMetric(name string, value, softLimit float64) float64 {
	if !isFinite(value) {
		return 0
	}
	if strings.Contains(name, "ratio") ||
		strings.Contains(name, "rate") ||
		strings.Contains(name, "perc") ||
		strings.Contains(name, "percent") ||
		strings.Contains(name, "util") {
		return normalizeRatio(value)
	}
	if softLimit > 1 {
		return clamp(value/softLimit, 0, 1)
	}
	return normalizeRatio(value)
}

func normalizeActiveRequestMetric(value, softLimit float64) float64 {
	if !isFinite(value) || value <= 0 {
		return 0
	}
	if !isFinite(softLimit) || softLimit <= 0 {
		softLimit = 16
	}
	return clamp(value/softLimit, 0, 1)
}

func normalizeLatencyMillis(name string, value float64) float64 {
	if !isFinite(value) {
		return 0
	}
	if strings.Contains(name, "seconds") || strings.HasSuffix(name, "_s") {
		return value * 1000
	}
	return value
}

func (b *Backend) recomputeWeight(policy LoadPolicy, smoothStep float64) {
	b.mu.Lock()
	defer b.mu.Unlock()

	now := time.Now()
	inflight := atomic.LoadInt64(&b.inflight)
	eligible := b.healthy && !b.adminDisabled && now.After(b.passiveUntil) && b.capacity > 0
	desired := b.desiredWeightLocked(policy, eligible, inflight)

	if !eligible {
		desired = 0
		if b.effectiveWeight <= weightEpsilon && inflight == 0 {
			b.enterPhaseLocked(PhaseDrained, now)
		} else if b.phase != PhaseDrained {
			b.enterPhaseLocked(PhaseDraining, now)
		}
	} else {
		switch b.phase {
		case PhaseDrained:
			b.enterTransitionLocked(PhaseRecovering, ReasonPassiveRecovered, now)
			desired *= b.slowStartProgressLocked(now)
		case PhaseRecovering:
			progress := b.slowStartProgressLocked(now)
			desired *= progress
			if progress >= 1 && weightsClose(b.effectiveWeight, desired) {
				b.enterPhaseLocked(PhaseActive, now)
			}
		case PhaseDraining:
			if weightsClose(b.effectiveWeight, desired) {
				b.enterPhaseLocked(PhaseActive, now)
			}
		case "":
			b.enterPhaseLocked(PhaseActive, now)
		}
	}

	if !isFinite(desired) {
		desired = 0
	}
	if !isFinite(smoothStep) || smoothStep <= 0 || smoothStep > 1 {
		smoothStep = 0.25
	}
	b.desiredWeight = desired
	b.effectiveWeight += (desired - b.effectiveWeight) * smoothStep
	if !isFinite(b.effectiveWeight) || b.effectiveWeight < weightEpsilon {
		b.effectiveWeight = 0
	}
	if !eligible && b.effectiveWeight == 0 && inflight == 0 {
		b.enterPhaseLocked(PhaseDrained, now)
	}
	if eligible && b.phase == PhaseDraining && weightsClose(b.effectiveWeight, desired) {
		b.enterPhaseLocked(PhaseActive, now)
	}
	b.lastUpdated = now
}

func (b *Backend) desiredWeightLocked(policy LoadPolicy, eligible bool, inflight int64) float64 {
	if !eligible {
		return 0
	}
	inflightRatio := 0.0
	if b.maxInflight > 0 {
		inflightRatio = clamp(float64(inflight)/float64(b.maxInflight), 0, 1)
	}
	queueRatio := safeRatio(b.queueDepth, policy.QueueSoftLimit)
	latencyRatio := safeRatio(b.latencyEWMA, policy.LatencySLOMillis)
	loadScore := weightedLoadScore(policy, b.remoteUtilization, queueRatio, inflightRatio, b.kvCacheUsage, latencyRatio)
	headroom := 1 - clamp(loadScore, 0, 1)
	if headroom < policy.MinHealthyFraction {
		headroom = policy.MinHealthyFraction
	}
	if b.maxInflight > 0 && inflight >= b.maxInflight {
		headroom = 0
	}
	return b.capacity * headroom
}

func (b *Backend) p2cLoadScore(policy LoadPolicy) float64 {
	b.mu.RLock()
	defer b.mu.RUnlock()

	inflightRatio := 0.0
	if b.maxInflight > 0 {
		inflightRatio = clamp(float64(atomic.LoadInt64(&b.inflight))/float64(b.maxInflight), 0, 1)
	}
	queueRatio := safeRatio(b.queueDepth, policy.QueueSoftLimit)
	latencyRatio := safeRatio(b.latencyEWMA, policy.LatencySLOMillis)
	return weightedLoadScore(policy, b.remoteUtilization, queueRatio, inflightRatio, b.kvCacheUsage, latencyRatio)
}

func (b *Backend) updateLatencyEWMALocked(latencyMillis, alpha float64) {
	if latencyMillis <= 0 {
		return
	}
	if alpha <= 0 || alpha > 1 {
		alpha = 0.25
	}
	if b.latencyEWMA == 0 {
		b.latencyEWMA = latencyMillis
	} else {
		b.latencyEWMA = alpha*latencyMillis + (1-alpha)*b.latencyEWMA
	}
}

func (b *Backend) enterPhaseLocked(phase BackendPhase, now time.Time) {
	if phase == PhaseActive {
		b.transitionReason = ReasonNone
	}
	if b.phase == phase {
		return
	}
	b.phase = phase
	b.phaseSince = now
}

func (b *Backend) enterTransitionLocked(phase BackendPhase, reason TransitionReason, now time.Time) {
	b.transitionReason = reason
	b.enterPhaseLocked(phase, now)
}

func (b *Backend) slowStartProgressLocked(now time.Time) float64 {
	if b.phase != PhaseRecovering {
		if b.phase == PhaseActive {
			return 1
		}
		return 0
	}
	if b.slowStartDuration <= 0 {
		return 1
	}
	return clamp(float64(now.Sub(b.phaseSince))/float64(b.slowStartDuration), 0, 1)
}

func weightsClose(a, b float64) bool {
	diff := math.Abs(a - b)
	return diff <= math.Max(0.05, math.Max(a, b)*0.05)
}

func weightedLoadScore(policy LoadPolicy, utilRatio, queueRatio, inflightRatio, kvCacheRatio, latencyRatio float64) float64 {
	total := policy.UtilizationWeight +
		policy.QueueWeight +
		policy.InflightWeight +
		policy.KVCacheWeight +
		policy.LatencyWeight
	if total <= 0 {
		return 0
	}
	score := (policy.UtilizationWeight*clampFinite(utilRatio, 0, 1) +
		policy.QueueWeight*clampFinite(queueRatio, 0, 1) +
		policy.InflightWeight*clampFinite(inflightRatio, 0, 1) +
		policy.KVCacheWeight*clampFinite(kvCacheRatio, 0, 1) +
		policy.LatencyWeight*clampFinite(latencyRatio, 0, 1)) / total
	if !isFinite(score) {
		return 0
	}
	return score
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

func safeRatio(value, limit float64) float64 {
	if !isFinite(value) || !isFinite(limit) || limit <= 0 {
		return 0
	}
	return clamp(value/limit, 0, 1)
}

func clampFinite(value, low, high float64) float64 {
	if !isFinite(value) {
		return 0
	}
	return clamp(value, low, high)
}

func isFinite(value float64) bool {
	return !math.IsNaN(value) && !math.IsInf(value, 0)
}
