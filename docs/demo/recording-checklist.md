# 原型视频录制检查清单

## 录制前

- 打开本地演示页：`docs/demo/prototype-demo.html`。
- 浏览器缩放设为 100%，窗口比例建议 16:9。
- 关闭会弹通知的软件。
- 准备讲稿：`docs/demo/video-script.md`。
- 确认远程没有占用演示用端口和临时 7B 容器：

```bash
ssh kunlun-02-act 'docker ps -a --filter name=yijq27-vllm-qwen7b --format "{{.Names}} {{.Status}}"; ss -ltnp 2>/dev/null | grep -E ":(9121|9122|9126|9127|9128|8180|8181)\b" || true'
```

## 推荐录屏路线

1. 展示第 1 页：赛题目标和痛点。
2. 按右方向键切到架构页。
3. 切到算法页，讲 `desired_weight` 和 `effective_weight`。
4. 切到 exp2 页，重点讲热点 NPU3 流量从 19.96% 到 0%。
5. 切到 exp3 页，讲 capacity 10->1 后 2.37% 接近理论 2.44%。
6. 切到 exp4/exp5 页，讲故障摘除和资源池隔离。
7. 切到 exp8 页，讲 7B 泛化验证。
8. 切到最后一页，展示仓库文件、runbook 和安全边界。

## 可选终端镜头

只展示安全、短命令：

```bash
python3 bench/generate_summary.py \
  --results-dir bench/results/formal \
  --output-dir /tmp/demo-summary

grep 'exp8' /tmp/demo-summary/real_npu_summary.md
```

远程环境可展示：

```bash
curl http://127.0.0.1:8181/admin/state
curl http://127.0.0.1:8181/metrics
```

## 导出要求

- 时长不超过 5 分钟。
- 分辨率建议 1920x1080 或 1280x720。
- 文件名建议：`动态负载感知调度-suan-router-赛题2.mp4`。
- 视频里不要出现密码、令牌、个人隐私或无关容器操作。
