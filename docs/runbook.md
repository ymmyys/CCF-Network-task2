# Operation Runbook

本文档用于在 Kunlun-02 或其他 Ascend 910B 机器上迁移、启动和复现实验。原则是：

- router 在 CANN 开发容器内运行；
- vLLM Ascend 后端一张 NPU 一个容器；
- 每次启动前先检查 NPU 和端口，不要停止或杀掉他人任务；
- 实验优先使用独立端口，避免影响长期运行服务。

## 1. 登录机器

```bash
ssh kunlun-02-act
```

当前已配置免密 SSH。VS Code Remote-SSH 也可以直接连接 `kunlun-02-act`。

## 2. 检查 NPU 占用

必须先执行：

```bash
docker exec yijq27-cann851 bash -lc "npu-smi info"
```

重点看底部 `Process id` 区域。示例：

```text
NPU 0: yijq27-vllm-qwen-0
NPU 1: yijq27-vllm-qwen-1
NPU 2: other user's process, do not touch
NPU 3-7: available
```

如果某张卡已有非当前实验进程，不要执行 `docker stop`、`kill`、`pkill` 或其他清理命令。换一张空闲 NPU 和一组新端口即可。

## 3. 检查端口占用

长期服务使用：

- router: `8080` / `8081`
- vLLM smoke-test 后端: `9011` / `9012`

实验服务使用：

- experiment router: `8180` / `8181`
- Qwen2.5-1.5B vLLM 后端: `9021` / `9022`

检查端口：

```bash
ss -ltnp 2>/dev/null | grep -E ':(8180|8181|9021|9022)\b' || true
```

如果端口被占用，改配置文件里的端口并同步修改启动命令。

## 4. 同步代码

项目在本机仓库：

```text
/Users/xiantianjian/Track1_fuiglwgfnq_repos
```

远端运行目录：

```text
/home/yijq27/workspace/Track1_fuiglwgfnq_repos
```

从本机同步到远端：

```bash
rsync -az --delete --exclude .git ./ \
  kunlun-02-act:/home/yijq27/workspace/Track1_fuiglwgfnq_repos/
```

## 5. Router 容器

router 使用这个容器：

```text
yijq27-cann851
```

进入容器：

```bash
docker exec -it yijq27-cann851 bash
```

项目路径：

```bash
cd /workspace/Track1_fuiglwgfnq_repos
```

测试和构建：

```bash
go test ./...
go build -o /workspace/bin/suan-router ./cmd/router
```

## 6. 下载实验模型

推荐实验模型：

```text
Qwen/Qwen2.5-1.5B-Instruct
```

原因：

- 比 0.5B 更能体现真实推理延迟和尾延迟；
- 单卡 910B 可直接运行；
- 下载和启动成本仍然可控。

下载到：

```text
/home/yijq27/workspace/models/Qwen2.5-1.5B-Instruct
```

命令：

```bash
docker run --rm --entrypoint bash \
  -e HF_HOME=/models/.cache \
  -e HF_ENDPOINT=https://hf-mirror.com \
  -v /home/yijq27/workspace/models:/models \
  quay.io/ascend/vllm-ascend:v0.18.0rc1 \
  -lc 'hf download Qwen/Qwen2.5-1.5B-Instruct \
    --local-dir /models/Qwen2.5-1.5B-Instruct \
    --max-workers 4'
```

如果迁移机器可以直连 Hugging Face，可去掉 `HF_ENDPOINT`。

## 7. 启动两个 vLLM Ascend 后端

以下示例使用 NPU 3 和 NPU 4。迁移时把 `NPU_A/NPU_B` 和端口改成空闲资源。

```bash
MODEL_DIR=/home/yijq27/workspace/models/Qwen2.5-1.5B-Instruct
IMAGE=quay.io/ascend/vllm-ascend:v0.18.0rc1
```

启动 NPU 3 后端：

```bash
docker run -itd \
  --name yijq27-vllm-qwen15b-3 \
  --restart unless-stopped \
  --privileged \
  --net=host \
  --ipc=host \
  --device /dev/davinci3 \
  --device /dev/davinci_manager \
  --device /dev/devmm_svm \
  --device /dev/hisi_hdc \
  -e ASCEND_RT_VISIBLE_DEVICES=3 \
  -e HF_ENDPOINT=https://hf-mirror.com \
  -v "$MODEL_DIR":"$MODEL_DIR":ro \
  -v /usr/local/dcmi:/usr/local/dcmi \
  -v /usr/local/bin/npu-smi:/usr/local/bin/npu-smi \
  -v /usr/local/Ascend/driver/lib64/:/usr/local/Ascend/driver/lib64/ \
  -v /usr/local/Ascend/driver/version.info:/usr/local/Ascend/driver/version.info \
  -v /etc/ascend_install.info:/etc/ascend_install.info \
  "$IMAGE" \
  bash -lc "vllm serve $MODEL_DIR \
    --host 0.0.0.0 \
    --port 9021 \
    --served-model-name qwen2.5-1.5b-instruct \
    --tensor-parallel-size 1 \
    --max-model-len 2048 \
    --gpu-memory-utilization 0.75"
```

启动 NPU 4 后端：

```bash
docker run -itd \
  --name yijq27-vllm-qwen15b-4 \
  --restart unless-stopped \
  --privileged \
  --net=host \
  --ipc=host \
  --device /dev/davinci4 \
  --device /dev/davinci_manager \
  --device /dev/devmm_svm \
  --device /dev/hisi_hdc \
  -e ASCEND_RT_VISIBLE_DEVICES=4 \
  -e HF_ENDPOINT=https://hf-mirror.com \
  -v "$MODEL_DIR":"$MODEL_DIR":ro \
  -v /usr/local/dcmi:/usr/local/dcmi \
  -v /usr/local/bin/npu-smi:/usr/local/bin/npu-smi \
  -v /usr/local/Ascend/driver/lib64/:/usr/local/Ascend/driver/lib64/ \
  -v /usr/local/Ascend/driver/version.info:/usr/local/Ascend/driver/version.info \
  -v /etc/ascend_install.info:/etc/ascend_install.info \
  "$IMAGE" \
  bash -lc "vllm serve $MODEL_DIR \
    --host 0.0.0.0 \
    --port 9022 \
    --served-model-name qwen2.5-1.5b-instruct \
    --tensor-parallel-size 1 \
    --max-model-len 2048 \
    --gpu-memory-utilization 0.75"
```

等待健康检查：

```bash
curl http://127.0.0.1:9021/health
curl http://127.0.0.1:9022/health
```

查看日志：

```bash
docker logs -f yijq27-vllm-qwen15b-3
docker logs -f yijq27-vllm-qwen15b-4
```

## 8. 启动实验 Router

动态负载感知版本：

```bash
docker exec -d yijq27-cann851 bash -lc '
  cd /workspace/Track1_fuiglwgfnq_repos &&
  exec /workspace/bin/suan-router \
    -config config/router.qwen15b-p2c.example.json \
    >>/workspace/logs/suan-router-qwen15b-p2c.log 2>&1
'
```

静态基线版本：

```bash
docker exec -d yijq27-cann851 bash -lc '
  cd /workspace/Track1_fuiglwgfnq_repos &&
  exec /workspace/bin/suan-router \
    -config config/router.qwen15b-static-swrr.example.json \
    >>/workspace/logs/suan-router-qwen15b-swrr.log 2>&1
'
```

两个版本都默认监听：

```text
data plane:  http://127.0.0.1:8180
admin plane: http://127.0.0.1:8181
```

同一时间只能启动一个实验 router，因为端口相同。切换算法前先停止当前 qwen15b 实验 router：

```bash
docker exec yijq27-cann851 bash -lc \
  "ps -eo pid=,args= | awk '/\\/workspace\\/bin\\/suan-router -config config\\/router\\.qwen15b/ && !/awk/ {print \$1}' | xargs -r kill"
```

注意：不要用无条件 `pkill -x suan-router`，否则会同时停止长期运行的 `8080/8081`
router。上面的命令只匹配 `config/router.qwen15b-*` 实验配置，不会停止 vLLM 容器，
也不会杀 NPU 上他人任务。

当前配置建议保留：

```json
"failure_cooloff_duration": "1s"
```

该参数用于代理错误或 5xx 响应后的短暂避让。在尚未达到被动熔断阈值前，router 会先把该后端从调度候选中移出约 1 秒，减少故障检测窗口内继续打到坏节点的概率。

如果要验证 aggressive P2C 的 QPS 折中，可单独启动 balanced 配置：

```bash
docker exec -d yijq27-cann851 bash -lc '
  cd /workspace/Track1_fuiglwgfnq_repos &&
  exec /workspace/bin/suan-router \
    -config config/router.qwen15b-heterogeneous-balanced.json \
    >>/workspace/logs/suan-router-qwen15b-balanced.log 2>&1
'
```

该配置启用：

```json
"balanced_p2c": true,
"slow_backend_min_share": 0.10
```

它只给 healthy slow backend 少量受控流量；unhealthy、passive ejected、failure cooling off、drained、capacity=0 的后端仍然不会被调度。

## 9. 直接测试后端

```bash
curl http://127.0.0.1:9021/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Reply with pong only."}],"max_tokens":16,"temperature":0}'
```

```bash
curl http://127.0.0.1:9022/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Reply with pong only."}],"max_tokens":16,"temperature":0}'
```

## 10. 测试 Router

```bash
curl -i http://127.0.0.1:8180/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Reply with pong only."}],"max_tokens":16,"temperature":0}'
```

看响应头：

```text
X-Router-Backend: qwen15b-npu3
```

或：

```text
X-Router-Backend: qwen15b-npu4
```

查看 router 状态：

```bash
curl http://127.0.0.1:8181/admin/state
```

重点观察字段：

```text
phase
effective_weight
healthy
passive_ejected
failure_cooling_off
latency_ewma_ms
```

查看 Prometheus 指标：

```bash
curl http://127.0.0.1:8181/metrics | grep -E 'router_backend_(healthy|failure_cooling_off|effective_weight|latency_ewma_ms)'
```

## 11. 运行实验

创建结果目录：

```bash
mkdir -p /home/yijq27/workspace/Track1_fuiglwgfnq_repos/bench/results
```

平衡负载实验：

```bash
cd /home/yijq27/workspace/Track1_fuiglwgfnq_repos
python3 bench/loadgen.py \
  --url http://127.0.0.1:8180/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --body '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Reply with pong only."}],"max_tokens":16,"temperature":0}' \
  --duration 60 \
  --concurrency 16 \
  --timeout 90 \
  --output bench/results/qwen15b-balanced-p2c.csv
```

动态降容实验：

```bash
python3 bench/loadgen.py \
  --url http://127.0.0.1:8180/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --body '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Reply with pong only."}],"max_tokens":16,"temperature":0}' \
  --duration 80 \
  --concurrency 16 \
  --timeout 90 \
  --output bench/results/qwen15b-capacity-drop-p2c.csv
```

另开一个终端注入 capacity 变化：

```bash
python3 bench/inject_capacity.py \
  --admin http://127.0.0.1:8181 \
  --event 20,default,qwen15b-npu3,1 \
  --event 50,default,qwen15b-npu3,10
```

生成汇总：

```bash
python3 bench/plot_results.py \
  --input bench/results/qwen15b-capacity-drop-p2c.csv \
  --output bench/results/qwen15b-capacity-drop-p2c.png
```

如果没有 matplotlib，脚本会至少输出 `.summary.csv`。

调度微基准不占用 NPU，只启动 fake backend 和临时 router：

```bash
BEFORE_BIN=/tmp/suan-router-before AFTER_BIN=/workspace/bin/suan-router \
  ./scripts/run_router_microbench.sh
```

脚本只清理自己启动的 PID。如果端口已被占用，会直接退出，不会 kill 未知进程。

## 12. 停止当前实验服务

停止实验 router：

```bash
docker exec yijq27-cann851 bash -lc \
  "ps -eo pid=,args= | awk '/\\/workspace\\/bin\\/suan-router -config config\\/router\\.qwen15b/ && !/awk/ {print \$1}' | xargs -r kill"
```

停止本次创建的 vLLM 后端：

```bash
docker rm -f yijq27-vllm-qwen15b-3 yijq27-vllm-qwen15b-4
```

不要停止不认识的容器，不要杀不属于本实验的 NPU 进程。

确认实验 router 已释放：

```bash
ss -ltnp 2>/dev/null | grep -E ':(8180|8181)\b' || true
```

没有输出表示 8180/8181 已释放。

## 13. 迁移到其他机器时需要修改的项

- SSH host
- router 容器名
- workspace 挂载目录
- 可用 NPU ID
- vLLM 端口
- router `listen` / `admin_listen` 端口
- 模型路径
- 镜像名和 CANN/vLLM 版本

迁移后先跑：

```bash
go test ./...
curl http://127.0.0.1:<backend-port>/health
curl http://127.0.0.1:<admin-port>/admin/state
```

确认通过后再跑正式压测。
