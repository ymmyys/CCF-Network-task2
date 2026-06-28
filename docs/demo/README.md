# 原型展示材料

本目录用于管理 5 分钟以内的赛题原型展示材料。最终可提交文件已集中放在 `submission/`。

## 文件

| 文件 | 用途 |
|---|---|
| `submission/README.md` | 最终演示材料索引 |
| `submission/suan-router-preliminary-demo-deck.pptx` | 辅助用浅色可编辑 PPT，适合现场答辩补充，不作为视频主体 |
| `submission/slide-speaker-notes.md` | 辅助 PPT 每页讲解思路、项目理解、重制建议和逐页讲稿 |
| `submission/prototype-demo-final.mp4` | 推荐提交的 5 分钟以内证据型原型展示视频 |
| `submission/prototype-evidence-video-guide.md` | 证据型视频镜头说明和数据源索引 |
| `submission/prototype-demo-final.srt` | 字幕文件 |
| `submission/prototype-demo-final-narration.txt` | 最终版旁白文本 |
| `submission/prototype-demo-final-cover.png` | 视频封面 |

## 推荐成片结构

1. 先讲赛题痛点：静态轮询无法感知 NPU 真实负载。
2. 展示系统架构：OpenAI-compatible router 位于客户端和 5 个 vLLM-Ascend 后端之间。
3. 展示算法：`desired_weight = capacity * headroom`，再通过 `smooth_step` 平滑到 `effective_weight`。
4. 展示核心实验：热点避让、动态 capacity、故障恢复、资源池隔离。
5. 用 Qwen2.5-7B 补充跨模型泛化证据。
6. 最后给出复现路径和安全边界。

## 生成材料

```bash
python3 scripts/generate_final_demo_video.py
```

生成过程只读取 `bench/results/formal/analysis/real_npu_summary.csv`，不会连接远程机器，也不会占用 NPU。调试用 HTML 和早期草稿可通过 `scripts/generate_demo_assets.py` 生成到 `docs/demo/work/`，该目录不作为正式提交材料。

## 推荐上传文件

将 `submission/prototype-demo-final.mp4` 上传至项目数据集。该文件为 1920x1080 H.264/AAC，有中文旁白，时长约 3 分 46 秒；画面直接展示真实终端输出、NPU 状态、router `/admin/state`、`/metrics` 和实验对比图。仓库 README 和 `docs/` 中保留设计方案、技术路线图、操作手册和实验数据。

如需重新录制原型视频，优先按 `submission/prototype-evidence-video-guide.md` 的镜头顺序展示真实运行证据：终端文件、NPU 状态、router `/admin/state`、`/metrics` 和实验图表。`submission/suan-router-preliminary-demo-deck.pptx` 只作为现场答辩或重新制图的辅助材料；所有关键数值来自 `bench/results/formal/analysis/real_npu_summary.csv`。
