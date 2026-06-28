# 原型展示视频材料

本目录用于准备 5 分钟以内的赛题原型展示视频。

## 文件

| 文件 | 用途 |
|---|---|
| `video-script.md` | 中文讲稿、分镜和时间轴 |
| `recording-checklist.md` | 录屏前检查项、推荐窗口和导出要求 |
| `prototype-demo.html` | 可直接打开录屏的本地演示页 |
| `prototype-demo-draft.mp4` | 自动生成的无声字幕版草稿视频 |

## 推荐成片结构

1. 先讲赛题痛点：静态轮询无法感知 NPU 真实负载。
2. 展示系统架构：OpenAI-compatible router 位于客户端和 5 个 vLLM-Ascend 后端之间。
3. 展示算法：`desired_weight = capacity * headroom`，再通过 `smooth_step` 平滑到 `effective_weight`。
4. 展示核心实验：热点避让、动态 capacity、故障恢复、资源池隔离。
5. 用 Qwen2.5-7B 补充跨模型泛化证据。
6. 最后给出复现路径和安全边界。

## 生成材料

```bash
python3 scripts/generate_demo_assets.py
```

生成过程只读取 `bench/results/formal/analysis/real_npu_summary.csv`，不会连接远程机器，也不会占用 NPU。
