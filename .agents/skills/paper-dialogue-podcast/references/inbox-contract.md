# 网页任务协议

网站把每个任务保存为 `inbox/<任务ID>/`，其中包含：

- `request.json`：不可变的用户请求与输入位置。
- `status.json`：Codex 可更新的任务状态，网站会轮询它。
- PDF/HTML 原文件：仅在上传或粘贴输入时存在。

## 领取规则

- 消息中带任务 ID 时，只领取这个 ID，避免多个等待任务互相串线。
- 只有 `waiting_codex` 或 `queued` 状态可以领取。
- `next --claim` 会原子更新状态并分配唯一的 `outputs/...` 结果目录。
- V3 以 `sources[]` 为完整材料清单；兼容旧任务才看 `source_path`、`url` 或 `notion_url`。不让用户重复提交。
- 领取后不要移动、删除或改写 `request.json` 和原始输入。

## 状态规则

使用这些固定 phase，便于网页显示：

`claimed → extract → research → analysis → report → script → voice → mix → review → complete`

不需要音频可跳过 voice/mix。状态保留七个 stage 和最多 80 条 history。`workflow.py prepare --job-id <ID>` 可领取并提取，重复调用不会覆盖已有底稿。任务选项必须保留，不能把用户选择的单人、关闭动画或目标时长静默换成默认值。

失败后 `inbox_job.py retry <ID>`（网页按钮调用同一操作）只将 error 任务重新排队，保留 result_dir、输入和部分产物；领取后继续原目录。正在运行或已完成的任务不重复领取。不要删除 claim 锁来强行并发处理，除非已确认没有领取进程。

进度应单调增加，处理中保持在 10–99；只有验证完成后才能写 100。状态消息写成用户能理解的当前动作，不写内部推理或敏感信息。

## 完成规则

`complete` 前，结果目录必须至少有：

- `analysis.json`
- `script.json`
- `transcript.md`

V3 新领取任务另需 research.json、report.html、reading-report.md、followup-plan.md、learning-cards.json、research-build.json 与有效 release.json。完成工具检查专业底稿结构、脚本、内容复核与文件哈希。动画是否必需由本轮 research-build.json 决定。

勾选人声时 V3 必须有 audio/podcast.mp3 和完整 audio-release.json，脚本哈希、文件哈希、解码和时长必须通过。如果语音服务不可用，保留已完成的研究与脚本，用 error 回写具体阻塞原因，不将缺音频的任务标为 complete。旧版无 V3 标记任务保留既有兼容规则。

网站只读取项目 `outputs/` 下的结果，绝不把任意外部路径暴露为下载项。失败时用 `error` 命令回写具体阻塞原因，不能让任务永久停留在 `running`。
