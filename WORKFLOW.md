# 研究制作流程 V3

入口是一篇或多篇文章，核心产物是一份能回到原文的研究底稿。精读报告、教学对话、播客和小动画共享这份底稿。工具负责结构检查、排版和媒体制作；论文阅读、证据判断与跨论文综合仍由研究过程完成，不由格式转换程序代替。

## 先把研究做专业

必须执行 [专业精读协议](.agents/skills/paper-dialogue-podcast/references/expert-reading.md)：三遍阅读＋八类追问＋按学科审查＋建构式理解。每篇保留真实回答、证据和未知项；没有证据就不强行形成清晰故事。

建构式理解是新增重点：目标与约束 → 朴素方案 → 失败瓶颈 → 最小改动 → 可检验预测 → 新代价与边界。像“从记忆问题理解 Transformer”这类范例启发我们解释技术为什么需要这些设计，但不宣称教学推导等于真实发明史。新技术允许只推到目前有把握的一步。

流程借鉴及核验范围见专业协议的原始链接清单；不假称已看完无法访问的视频，不将二手解读当作原文，不用名人风格替代证据。脚本以清楚解释为目标，公式与术语按受众和时长递进。

[跨学科教学范例与讲解档位](.agents/skills/paper-dialogue-podcast/references/teaching-exemplars.md) 已纳入物理、凝聚态和量子计算。可选直觉导览、层层深入、建构式理解、研讨审查；自动选择先看受众与目标，再看话题和时长。费曼式“清楚解释”在这里意味着可预测、可举例、知道类比边界，不是模仿名人说话或删去必要数学。

## 每次固定执行

| 阶段 | 研究动作 | 保存的结果 | 进入下一阶段的条件 |
|---|---|---|---|
| 1. 立题与收件 | 明确研究问题、读者基础、深度、输入清单；领取指定网页任务 | `research.json` 的 project / sources | 论文与评论材料身份分开，版本与缺失全文可见 |
| 2. 全文与证据 | 阅读正文、图表、公式、方法和关键附录，建立逐篇阅读地图 | papers / evidence | 每条关键证据有来源 ID、页码或章节定位；访问不到的内容不能标为已核验 |
| 3. 形成分析 | 重建研究逻辑，区分作者主张、观测与补充推断 | claims / logic / synthesis | 论断能回到证据；跨论文差异检查模型、样本、指标、精度与假设是否可比 |
| 4. 精读与推进 | 形成可阅读报告、限制、问题清单和下一步实验／检索计划 | `report.html`、`reading-report.md`、`followup-plan.md` | 每项后续任务写明要回答什么、需什么输入、如何算完成；计划不自动授权外部实验 |
| 5. 教学设计 | 先定学习目标和先修知识，再写课程大纲、双人脚本、自测卡 | `script.json`、`transcript.md`、`learning-cards.json` | 每章推进一个问题；证据 ID 可追踪；避免多次“最终总结”和为时长堆重复内容 |
| 6. 按需媒体 | 逻辑链难以用短段文字表达时生成动画；先测人声小样，再做全量音频 | `visuals/logic-chain.html`、audio 目录 | 动画与音频复用相同论断；图像中的因果箭头不能凭空加强论文结论 |
| 7. 验收与交付 | 科学内容复核、结构验证、音频解码与时长检查、动画可访问性检查 | `validation.json`、`release.json` | 工具检查与科学／听感检查分开记录；只有请求的产物真实存在且通过验收才完成任务 |

网站已支持七个可见 stage，兼容 phase 为 claimed/extract、research、analysis、report、script、voice/mix、review/complete；状态记录中保留阶段历史。没有音频需求时可跳过语音阶段，不能伪报生成过音频。

## 两种执行方式

默认 Codex 接力：网站只收件与展示，用户将指令交给本项目中的 Codex。可选 API 自动制作：用户明确选择、填写密钥并确认发送与计费后，由兼容 Chat Completions 的模型分阶段生成；当前默认 Kimi。两种方式共用构建与发布校验，不相互自动切换。API 的文本读取、arXiv 检索、模型内容复核及暂停续做的边界见 [docs/API.md](docs/API.md)。API 文本复核必须标明非人工、非独立专家，没有图像阅读能力就不能宣称核验过图表。

读者基础分零基础、跨专业、本专业本科、研究生／研究人员、领域专家以及自定义。选项写入任务与研究底稿，用于选择先修概念、例子与数学解释的起点；不是降低科学证据要求的开关。研究深度和节目时长继续独立控制。

## 一篇和多篇如何分流

- 单篇：问题背景 → 旧认识 → 缺口 → 方法选择 → 图表／公式证据 → 结论边界 → 可以继续做什么。
- 多篇深读（默认）：每篇先独立建立 dossier，再围绕同一研究问题比较；输出共识、实质冲突、不可比之处与可组合的方法。保留论文 ID，不把各篇结果揉成一个无来源结论。
- 多篇简报：用户要求“简报／快速综述”时启用；每篇短章，最后综合。单人或双人由任务指定，默认双人教学。
- 多篇很长时可以形成分集大纲；如用户没有要求全部音频，先完成综合报告与分集计划，不自动启动无限合成。

## 固定交付包

`research.json` 保存来源、证据、论断、逻辑链、逐篇阅读地图、跨篇比较和后续任务。原有 `analysis.json` 继续保留以兼容网页，其关键结论与 research.json 保持一致。

报告至少回答：研究问题是什么；每篇做了什么；哪条证据支持哪项结论；哪些结论只是推断；有什么限制与替代解释；下一步怎样推进。报告必须可独立阅读，不能只交机器用 JSON。

`script.json` 的实质轮次增加 `claim_ids`，使用 research.json 的稳定 ID。`source_refs` 继续保存具体原文位置。`transcript.md` 由脚本机械生成。学习卡包含问题、答案、所依赖的 claim_ids；不把教材类比当作实验事实。

新增可运行命令（Windows PowerShell）：

```powershell
.\.venv\Scripts\python.exe -B .\scripts\workflow.py prepare --job-id <网页任务ID>
.\.venv\Scripts\python.exe -B .\scripts\workflow.py build --job-id <网页任务ID>
.\.venv\Scripts\python.exe .\scripts\research_pipeline.py init --out .\outputs\<新目录> --title "主题" --question "想解决的问题"
.\.venv\Scripts\python.exe .\scripts\research_pipeline.py validate --episode .\outputs\<目录>
.\.venv\Scripts\python.exe .\scripts\research_pipeline.py render --episode .\outputs\<目录>
.\.venv\Scripts\python.exe .\scripts\research_pipeline.py transcript --episode .\outputs\<目录>
.\.venv\Scripts\python.exe .\scripts\audio_preflight.py --script .\outputs\<目录>\script.json --history .\outputs
powershell -ExecutionPolicy Bypass -File .\run.ps1 -Script .\outputs\<目录>\script.json -OutDir .\outputs\<目录>\audio
.\.venv\Scripts\python.exe -B .\scripts\workflow.py publish --job-id <网页任务ID>
```

init 只建待填写底稿，不生成伪研究。填写并验证 research.json 后 render 才会生成报告、推进计划和按需动画。旧节目无需迁移或重做。

prepare 会保留 PDF 页码、HTML 标题／段落／引用／图片索引，提示低文本页与未访问链接；不会把提取成功标成精读完成。网站 schema_version=3 的请求必须逐章提供 teaching.beats 和逐篇公开版本检索记录。build 从统一底稿派生 analysis.json 并检查网页选项，不再手工维护矛盾的两份分析。科学内容复核后执行 record-review，再 publish。

## 小动画的决策规则

默认按需：三步以上依赖关系、状态变化、方法前后比较或一个假设影响多个结论时值得做。单个事实和已经清晰的短列表不做。动画每段讲一个问题，通常 30–90 秒。

已实现可离线播放的逻辑链动画：播放／暂停、上一步／下一步、进度、节点解释、证据定位、移动端与减少动态效果支持。可选 before/after 场景先显示问题与条件 A，等待预测后揭示条件 B，再解释结论边界；新增大字演示视图与键盘切换。不会默认自动播放。全部内容来自结构化底稿，便于改稿和复核。

后续扩展按需求选择：状态变化可用 SVG／Canvas；有明确方程的定量模型可用 Python 生成科学动画；需要投放时再导出 MP4。当前 HTML 动画不等于物理仿真，不冒充已经生成 MP4、同步配音或公式仿真。

图中标注“观测／作者主张／推断”，箭头注明“支持／前提／启发／限制”等实际关系。示意曲线必须写明示意，无数据时不能画出假装真实的数值。

## 音频生产升级

- 时长从同音色、同参数历史记录或短样本实测推算。原始字符数只作粗筛；中英混排不能把每个英文字符等同于一个汉字。`run.ps1 -Pilot` 生成独立小样，用返回的 manifest 为 audio_preflight.py 的 --pilot-manifest 参数，不发布成片。
- 按“实际口播文本＋提供者＋音色＋语速＋音高＋音量＋提供者版本”缓存片段；改一轮只重做受影响的片段。缓存损坏则重新生成。
- 正式合成写入独立 run 目录，成功后更新音频与元数据，最后写发布标记。合成失败不动旧成片；若发布过程中中断，哈希门禁拒绝混合版本，重新运行恢复发布。失败保留诊断与已完成缓存，不把旧音频与新脚本混在一起当作成片。
- 硬检查覆盖解码、空段、元数据、角色、时长；不宣称这些自动检查等于逐字听写或主观听感通过。
- 需要听感抽检时检查开头、术语、公式、换人和结尾。无法听取时明确标记未做听感审听；可选 ASR 是后续扩展。
- 不通过减速拉长或重复审计凑时长。内容足够则报告实际时长；必须匹配明确时长时，补充有来源的新内容，缓存保留已完成片段。

## 本次升级范围与后续

已落实：固定研究契约、读取准备器、统一构建命令、验证与报告生成器、推进计划／学习卡、章节教学设计、按需逻辑动画、离线示例、音频小样与预估、分段缓存与完成校验。网站源码现位于 `web/`，含多文件／补充链接、深度与讲解方式、七阶段进度、失败恢复、历史任务、报告与动画浏览。原网站入口保留为兼容启动器，并备份旧实现；历史原始输入和节目未迁移。

尚需按实际使用扩展：跨任务长期研究资料库、可靠数学公式渲染、自动 OCR、ASR、专门的人工听感审听界面、MP4 渲染与播客同步。新增服务、收费模型与长期监控应在用户实际要求时接入。当前语音提供者仍为 Edge；软件工程验收不能替代真人感试听。

视觉与教学的长期约定见 [DESIGN.md](DESIGN.md)：瑞士网格、轻编辑式页面、内容不套大框、控件使用温和底色；费曼式解释／预测／检查／再教与 3Blue1Brown 的具体现象到可视机制。参考作者的可观察教学方法，不仿声、不冒充作者、不复制长段脚本。

## 示例与验证

[打开流程报告示例](examples/research-v3/report.html) · [播放六步逻辑链](examples/research-v3/visuals/logic-chain.html)。它们演示本流程，不冒充真实论文研究成果，也不附带人声音频。

本地回归测试：`.\.venv\Scripts\python.exe -B tests/test_workflow.py`。语音接口使用测试替身，FFmpeg 对真实测试音执行编码／解码；不会调用在线语音服务。浏览器检查脚本为 tests/check_visual.cjs，依赖运行环境提供的 Playwright 和浏览器，不自动下载依赖。研究推理、真实声音自然度和学习效果仍需实际论文试运行验证。

实现参考：[MDN：减少动态效果](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/%40media/prefers-reduced-motion)、[FFmpeg：loudnorm](https://ffmpeg.org/ffmpeg-filters.html#loudnorm)。响度配置采用 LUFS，不能将其误称为 dBFS。
