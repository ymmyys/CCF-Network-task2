# 初赛原型展示提交材料

本目录只保留最终提交所需的真实运行演示材料。

| 文件 | 用途 |
|---|---|
| `prototype-architecture-realrun-subtitled.mp4` | 推荐上传到项目数据集的原型展示视频，75 秒，含中文字幕 |
| `prototype-architecture-realrun.srt` | 字幕源文件，便于重新压制或修改旁白 |

## 视频主线

这版视频不是 PPT，也不是离线合成图表，而是在远程 VS Code 已连接 Ascend CANN 容器的状态下录制真实命令执行过程：

1. 项目架构：客户端请求进入 MUTT，再分发到 5 个真实 vLLM-Ascend 后端。
2. 代码证据：展示 router 入口、调度器、后端状态机、`metrics_url`、负载分数与平滑权重更新的位置。
3. 硬件证据：检查 9021/9022/9026/9027/9028 的 `/health`，并展示 `npu-smi info`。
4. 运行证据：容器内 `go build` 当前 router，启动临时数据面和管理面。
5. 真实请求：`bench/loadgen.py` 通过 router 发起 OpenAI-compatible 推理请求。
6. 指标证据：输出请求数、错误数、延迟分位数、后端分布、`/admin/state` 与 `/metrics`。
7. 清理边界：脚本只停止自己启动的 router；vLLM 后端容器由外层流程停止释放 NPU。

## 安全边界

- 视频不包含密码、令牌或远程登录凭据。
- 视频不展示无关容器和其他用户任务。
- 录制脚本使用临时端口 `18180/18181`，不会占用正式实验端口。
- 录制脚本不使用宽泛 `pkill`，只清理自己写入 PID 文件的 router。
