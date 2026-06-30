# 原型展示材料

本目录只保留初赛原型展示的最终材料入口。当前推荐提交的是一段真实远程容器录屏，不再使用 PPT 或合成式视频作为主体。

## 最终文件

| 文件 | 用途 |
|---|---|
| `submission/README.md` | 最终演示材料索引 |
| `submission/prototype-architecture-realrun-subtitled.mp4` | 推荐上传的原型展示视频，75 秒，含中文字幕 |
| `submission/prototype-architecture-realrun.srt` | 与视频对应的字幕源文件 |

## 视频内容

`prototype-architecture-realrun-subtitled.mp4` 直接录制远程 VS Code 连接到 Ascend CANN 容器后的真实运行过程：

1. 展示 MUTT 项目架构：OpenAI-compatible client -> router -> NPU 3-7 vLLM-Ascend 后端。
2. 展示关键代码位置：`cmd`、`internal/router`、`config`、负载分数、P2C、smooth effective weight 和 `metrics_url`。
3. 检查真实环境：后端 `/health` 与 `npu-smi info`。
4. 在容器内构建并启动临时 router。
5. 通过 router 发起真实 OpenAI-compatible 推理请求。
6. 展示请求数、错误数、p50/p95/p99、后端分布、`/admin/state` 与 `/metrics`。
7. 安全清理：脚本只停止自己启动的 router，vLLM 后端由外层流程统一停止释放 NPU。

## 重新录制

远程容器中执行：

```bash
bash /workspace/Track1_fuiglwgfnq_repos/scripts/recordrealrun.sh
```

该脚本会启动临时 router 并跑一次真实请求实验。运行前需要确认 NPU 3-7 上的 `yijq27-vllm-qwen15b-3` 到 `yijq27-vllm-qwen15b-7` 已启动且健康；运行后需要停止这些后端容器释放 NPU。
