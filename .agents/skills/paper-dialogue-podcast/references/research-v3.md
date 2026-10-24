# V3 研究底稿与发布契约

项目根目录的 scripts/research_pipeline.py 是结构验证／渲染入口，示例在 examples/research-v3/research.json。它不自动阅读论文，不自动判定科学内容正确。

## research.json

- schema_version: 3；project 包含 title、question、audience、depth、status。
- sources：id、title、location、kind、access_status；核验身份后 identity_checked=true，并填 authors、year、version、verified_at。只有实际看到全文才能填 full_text。
- papers：id、source_id、study_type、question、method、limitations、claim_ids、reading_map。阅读地图每项包含 location、role、summary、evidence_ids。
- evidence：id、source_id、location、observation、verification（verified/partial/unverified）。verified 指材料确实这样写，不意味着实验证实了世界的真相。
- claims：id、text、type（author_claim/observation/inference）、boundary、evidence_ids。推断的 evidence_ids 是其前提，不能称为直接证明。
- logic：nodes 各含 id、label、explanation、claim_ids；edges 含 from、to、relation、reason、evidence_ids。relation 为 motivates/requires/supports/contrasts/limits/enables/causes；causes 另需 causal_justification。
- synthesis：summary、agreements、conflicts、comparability、open_questions。conflicts 每项含 claim_ids、explanation、reconciliation；comparability 含 dimension、paper_ids、assessment，多篇必需。
- followups：id、question、action、done_when、expected_artifact、status、priority、input_ids。仅生成计划，不自动运行实验、发送消息、监控或购买资源。
- teaching：mode、selection_reason、objectives、prerequisites、glossary、cards、visual。mode 由 auto 决策为 intuitive/progressive/reconstruction/seminar，并说明取舍；cards 含 question、answer、claim_ids；visual 含 mode（auto/on/off）、reason、scene_node_ids。场景节点上限及步进时间来自 config/research.yaml。
- reading_caveats：限制列表。

V3 网站新增的可执行字段：

- `public_version_search[]`：每篇一个 paper_id、status（verified/not_found/unavailable）、queries（实际检索词／标识符数组）、identity_notes。找不到全文如实说明；状态不是假装已读的许可。匹配到的合法版本列入 `public_versions[]`，含 label、url、version_type、relationship、verification_note。
- `teaching.beats[]`：每个实质章节一个 chapter、question、example、prediction、check_question、check_answer、claim_ids。chapter 与脚本完全同名，必须互相覆盖。第一轮披露、纯过渡不单独要求教学设计。
- `teaching.visual.scenes[]` 可选：node_id、question、before、after、takeaway、claim_ids。节点与论断必须对应。用于先预测再揭示的对照，不把两个条件画成已经证明的因果。
- HTML 精读稿与原文对照保存在顶层 `commentary_crosscheck[]`，字段依 output-contract.md；原文未取得时标 not_verified。`project.analysis_mode` 可明确记录分类，不由文件扩展名推断。

## 新节目的工作全景开场

新任务 `project.opening_contract_version=1`。先在 `teaching.opening` 写面向未读原文听众的口播，再写正文教学 beats：

```json
{
  "version": 1,
  "assumes_unread_paper": true,
  "segments": [
    {"paper_id":"P1","topic":"identity","text":"这里是实际可口播的题名、译意、年份与发表状态。","verification":"verified","evidence_ids":["E1"],"claim_ids":[]}
  ]
}
```

上面只演示一项，不是完整模板。每篇必须覆盖 `identity`、`first_authors`（含共同一作）、`corresponding_authors`、`affiliations`、`goal`、`approach`、`findings`、`boundary`，每个主题一段，首次出现该论文时先 identity。整段开场先从第一篇的身份说起。另有 `paper_id=null` 的全片 `prerequisites`（最少背景和术语白话说明）与 `roadmap`（精讲路线）。可选 `author_context` 只讲有来源且相关的代表贡献，不能强行罗列名人。

- `text` 是最终口播，不是写作指令或字段标签；适当短段，不写引用编号或网址。单篇通常合计约 2–4 分钟；多篇紧凑介绍并保留每篇 ID，不占满正文预算。
- `verification=verified` 表示这段有可定位的已核实证据，`evidence_ids` 必须非空；不表示论文科学结论已经被独立证实。goal/approach/findings/boundary 还须关联该论文 `claim_ids`，明确结论边界。
- 作者角色、单位、作者背景可用 `unknown` 或 `not_applicable`，允许空 evidence_ids，但口播必须明确“未确认／未标注／不适用”等，而不是凭模型记忆补齐。已确认的一作和无法确认的通讯作者分别记录，不能一概省略。不要依据末位署名猜通讯身份。共同一作需原文注明；单位按原文作者编号映射。
- 只把实际核查过的作者背景放入 evidence；未核查到可省略 author_context。API 文本模式无法外查时不假装查了机构主页。
- `scripts/podcast_opening.py --research <目录>/research.json --format dialogue` 输出开场 `opening`、`chapters`、`turns`，不调用模型或语音、不修改文件。把它们作为新脚本前缀，再追加正文并计算 start_turn。API 模式自动执行同一派生逻辑；正文 beats 不重复包含这个开场。
- `opening.end_turn` 为开场最后一轮的零基索引；开场均由主讲／播报者说明。`orientation` 轮次保留原 text、topic、paper_id、verification、evidence_ids、claim_ids 和派生 source_refs，不能只在字段上打勾却把口播改成其他内容。
- 历史已完成节目保持原样；新制作／重新构建时遵守新门禁，改稿需另存版本并重新复核和合成。

## 每篇 papers[].review

对应 expert-reading.md，禁止只放空白提纲：

- orientation：problem、baseline、claimed_novelty、relevance、reading_decision。
- passes：三项，pass=1/2/3；各含 status（complete/partial/skipped）、coverage、unresolved；未完成需 reason。
- questions：覆盖配置的八类 family；各含 prompt、answer、status（answered/open/not_applicable）、evidence_ids；未回答／不适用需 reason。回答中“尚未找到证据”允许保留，不能虚构答案。
- technical_audit：aspect、verdict（supported/unclear/concern/not_applicable）、rationale、evidence_ids。按论文类型选择实际相关的检查，不机械套 AI 指标。
- reconstruction：inputs、steps、outputs、assumptions、missing_details、execution_status（not_run/partial/reproduced）。实际运行过必须有 execution_artifacts。脑内重建填 not_run。
- design_reconstruction：status（grounded/hypothesis/not_applicable）；不适用需 reason。适用时含 target、constraints、baseline、competing_routes、unresolved、steps。每步含 bottleneck、change、prediction、cost、test、epistemic_status（source_supported/derived/hypothesis）、evidence_ids；derived 另有 derivation。
- explanation_check：plain_language、misconception、correction、transfer_question、answer。

## 派生与一致性

先 validate 再 render；脚本写好后使用 `scripts/workflow.py build --job-id <ID>` 或 `--episode <目录>` 统一派生 analysis.json、报告、文字稿、学习卡、动画与音频预估。analysis.json 保留 research_sha256，不再手工维护第二份结论。修改底稿或脚本后重新 build 并复核，再更新受影响音频；多篇深读使用 multi_paper_research。

## 内容复核与发布

完成实质核查后才调用：

    .\.venv\Scripts\python.exe .\scripts\research_pipeline.py record-review --episode <目录> --note "具体复核的论断、原文位置及一致性检查" --limitations "尚存的限制"

该命令仅记录执行者已完成的复核，不代替复核本身，不冒充独立专家审稿。它验证结构与报告版本并封存文件哈希。release.json 记录 scientific_review、review_note、limitations、reviewed_at、research_sha256、script_sha256 以及必需产物的哈希；文件变动后需重新复核封存。音频由合成器单独形成 audio/audio-release.json。

网页 complete 还会检查当前脚本长度、角色、章节、AI 披露、请求的音频是否存在及实际时长。只交报告的任务不要求音频；科学审阅仍必须。浏览器／播放体验验证与人工听感不能靠 JSON 字段自动证明。
