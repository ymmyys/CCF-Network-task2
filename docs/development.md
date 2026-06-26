# Development Guide

This project is a Go HTTP router for multiple OpenAI-compatible inference
backends. The target deployment for Kunlun-02 is:

- one router process in the CANN development container;
- two or more vLLM Ascend containers on different NPU devices;
- the router data plane on `:8080` and admin plane on `:8081`.

## Current Remote Target

- SSH host: `kunlun-02-act`
- Router container: `yijq27-cann851`
- Workspace mount: `/home/yijq27/workspace` on the host, `/workspace` in the container
- Smoke-test model: `Qwen/Qwen2.5-0.5B-Instruct`
- Model directory: `/home/yijq27/workspace/models/Qwen2.5-0.5B-Instruct`
- vLLM image: `quay.io/ascend/vllm-ascend:v0.18.0rc1`

The smoke-test model is intentionally small. It is used to validate the
download, vLLM Ascend, router, health-check, metrics, and OpenAI-compatible
request path before switching to a larger model.

## Router Configuration

Use `config/router.vllm-ascend.example.json` for the two-backend local setup:

- `vllm-ascend-0`: `http://127.0.0.1:9011`
- `vllm-ascend-1`: `http://127.0.0.1:9012`

Each backend exposes:

- OpenAI-compatible API on `/v1/chat/completions`
- health probe on `/health`
- Prometheus metrics on `/metrics`

The router forwards incoming requests unchanged and adds `X-Router-Backend` to
show which vLLM backend served the request.

## Start vLLM Ascend Backends

Create one container per backend. Bind each container to a different NPU with
`ASCEND_RT_VISIBLE_DEVICES`, and share the model cache directory read-only.

```bash
MODEL_DIR=/home/yijq27/workspace/models/Qwen2.5-0.5B-Instruct
IMAGE=quay.io/ascend/vllm-ascend:v0.18.0rc1

docker run -itd \
  --name yijq27-vllm-qwen-0 \
  --privileged \
  --net=host \
  --ipc=host \
  --device /dev/davinci0 \
  --device /dev/davinci_manager \
  --device /dev/devmm_svm \
  --device /dev/hisi_hdc \
  -e ASCEND_RT_VISIBLE_DEVICES=0 \
  -v "$MODEL_DIR":"$MODEL_DIR":ro \
  -v /usr/local/dcmi:/usr/local/dcmi \
  -v /usr/local/bin/npu-smi:/usr/local/bin/npu-smi \
  -v /usr/local/Ascend/driver/lib64/:/usr/local/Ascend/driver/lib64/ \
  -v /usr/local/Ascend/driver/version.info:/usr/local/Ascend/driver/version.info \
  -v /etc/ascend_install.info:/etc/ascend_install.info \
  "$IMAGE" \
  bash -lc "vllm serve $MODEL_DIR --host 0.0.0.0 --port 9011 --served-model-name qwen2.5-0.5b-instruct --tensor-parallel-size 1 --max-model-len 2048 --gpu-memory-utilization 0.75"
```

Repeat with container name `yijq27-vllm-qwen-1`, device
`/dev/davinci1`, `ASCEND_RT_VISIBLE_DEVICES=1`, and port `9012`.

## Start Router In Container

```bash
ssh kunlun-02-act
docker exec -it yijq27-cann851 bash

cd /workspace/Track1_fuiglwgfnq_repos
go run ./cmd/router -config config/router.vllm-ascend.example.json
```

For long-running use, build the binary and run it under `nohup` or a process
manager inside the container:

```bash
go build -o /workspace/bin/suan-router ./cmd/router
nohup /workspace/bin/suan-router -config config/router.vllm-ascend.example.json \
  >/workspace/router.log 2>&1 &
```

## Validate

Check router state:

```bash
curl http://127.0.0.1:8081/admin/state
```

Send a chat request through the router:

```bash
curl http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen2.5-0.5b-instruct",
    "messages": [{"role": "user", "content": "Say hello in one short sentence."}],
    "max_tokens": 32,
    "temperature": 0
  }'
```

Watch which backend handled the request:

```bash
curl -i http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen2.5-0.5b-instruct","messages":[{"role":"user","content":"ping"}],"max_tokens":8}'
```

The response headers should include `X-Router-Backend`.

## Operational Notes

- Keep router and vLLM processes inside containers on Kunlun-02.
- Do not expose `:8080` or `:8081` outside the machine until backend health,
  metrics, and request routing are verified locally.
- Prefer one vLLM container per NPU for the first working deployment. Increase
  tensor parallelism only after the single-card path is stable.
- Replace the smoke-test model by editing both the vLLM startup command and the
  request `model` field.
