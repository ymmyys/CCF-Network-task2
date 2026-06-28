# 初赛原型展示提交材料

本目录集中保存原型展示相关的最终材料。评审或迁移时优先查看本目录，不需要再到 `docs/demo/` 上层寻找零散文件。

| 文件 | 用途 |
|---|---|
| `suan-router-preliminary-demo-deck.pptx` | 辅助用浅色可编辑 PPT，适合现场答辩补充，不作为视频主体 |
| `slide-speaker-notes.md` | 辅助 PPT 每页讲解思路、项目理解、重制建议和逐页讲稿 |
| `prototype-remote-container-recording-subtitled.mp4` | 推荐提交的远程容器真实运行录屏，含中文字幕 |
| `prototype-remote-container-recording.srt` | 远程容器录屏字幕文件 |
| `prototype-demo-final.mp4` | 备用的 5 分钟以内证据型合成展示视频 |
| `prototype-evidence-video-guide.md` | 证据型视频镜头说明和数据源索引 |
| `prototype-demo-final.srt` | 备用视频字幕 |
| `prototype-demo-final-narration.txt` | 备用视频旁白文本 |
| `prototype-demo-final-cover.png` | 视频封面 |

建议正式提交：

1. 代码仓库提交：保留 README、`docs/`、`bench/results/formal/` 和本目录。
2. 视频上传：优先将 `prototype-remote-container-recording-subtitled.mp4` 上传到项目数据集；该视频直接展示 VS Code 连接远程 Ascend 容器、`npu-smi`、模型目录、代码入口、正式实验结果、脚本检查和 vLLM 指标证据。
3. 现场答辩补充：如需要 PPT，再使用 `suan-router-preliminary-demo-deck.pptx` 和 `slide-speaker-notes.md`；原型视频本身应按 `prototype-evidence-video-guide.md` 展示真实运行证据。

材料安全边界：

- 不包含密码、令牌或远程登录凭据。
- 不展示无关容器或其他用户任务。
- 视频和 PPT 的关键数值来自 `bench/results/formal/analysis/real_npu_summary.csv`。
