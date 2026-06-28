# 原型展示材料

本目录用于准备 5 分钟以内的赛题原型展示视频及配套讲解 PPT。

## 文件

| 文件 | 用途 |
|---|---|
| `video-script.md` | 中文讲稿、分镜和时间轴 |
| `recording-checklist.md` | 录屏前检查项、推荐窗口和导出要求 |
| `prototype-demo.html` | 可直接打开录屏的本地演示页 |
| `prototype-demo-final.mp4` | 推荐提交的 5 分钟以内有声原型展示视频 |
| `prototype-demo-final-silent.mp4` | 无声版本，便于自行配音 |
| `prototype-demo-final.srt` | 字幕文件 |
| `prototype-demo-final-narration.txt` | 最终版旁白文本 |
| `prototype-demo-final-cover.png` | 视频封面 |
| `prototype-demo-draft.mp4` | 早期无声字幕草稿，仅作备份 |
| `suan-router-preliminary-demo-deck.pptx` | 推荐用于初赛讲解和重新录屏的浅色可编辑 PPT |

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
python3 scripts/generate_final_demo_video.py
```

生成过程只读取 `bench/results/formal/analysis/real_npu_summary.csv`，不会连接远程机器，也不会占用 NPU。

## 推荐上传文件

将 `prototype-demo-final.mp4` 上传至项目数据集。该文件为 1920x1080 H.264/AAC，有中文旁白，时长约 3 分 56 秒。仓库 README 和 `docs/` 中保留设计方案、技术路线图、操作手册和实验数据。

如需重新录制更正式的原型展示，建议优先使用 `suan-router-preliminary-demo-deck.pptx` 作为画面来源。该 PPT 采用浅色技术汇报风格，包含赛题对齐、系统架构、算法、技术路线图、真实热点避让、平滑降容、故障恢复、资源池隔离和 7B 泛化实验；所有关键数值来自 `bench/results/formal/analysis/real_npu_summary.csv`。
