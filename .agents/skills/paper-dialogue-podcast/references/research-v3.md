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
