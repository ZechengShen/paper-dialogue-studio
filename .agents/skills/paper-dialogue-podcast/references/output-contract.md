# 输出契约

V3 新任务还必须遵循 research-v3.md：research.json 为底稿，生成可阅读报告、专业追问、推进计划与学习卡，按需生成动画；release.json 记录绑定底稿的内容复核。下面是保留给旧网页的兼容格式，不替代 V3 底稿。

每个节目目录必须包含 `analysis.json`、`script.json`、`transcript.md`；成功合成后还应包含 `audio/podcast.mp3`、`audio/directed-script.json`、`audio/voice-director-report.json`、`audio/chapters.json` 和 `audio/voice-manifest.json`。

## analysis.json 通用字段

```json
{
  "analysis_mode": "single_paper_close_reading|commentary_plus_original|multi_paper_research|multi_paper_briefing",
  "primary_paper_count": 1,
  "metadata": {
    "title": "单篇论文题名或多篇汇总主题",
    "authors": [],
    "year": null,
    "venue": "",
    "doi": "",
    "arxiv_id": "",
    "source_type": "pdf|html|notion|url",
    "source_label": ""
  },
  "plain_language_overview": "",
  "research_map": {
    "question": "",
    "why_it_matters": "",
    "prior_belief": "",
    "gap": "",
    "core_hypothesis": "",
    "contribution": ""
  },
  "logic_chain": [
    {
      "stage": "",
      "author_claim": "",
      "paper_evidence": "",
      "codex_inference": "",
      "hidden_assumptions": [],
      "why_next": "",
      "source_refs": []
    }
  ],
  "public_versions": [],
  "source_list": [],
  "reading_caveats": [],
  "recommended_minutes": 45,
  "recommended_reason": ""
}
```

单篇模式继续提供 `methods`、`findings` 和 `critique`。此外：

- `single_paper_close_reading` 必须包含 `paragraph_map[]`，每项记录 `location`、`function`、`important_information`、`why_it_matters` 和 `source_refs`。仅收录有实质论证功能的段落，但必须先检查全文。
- `commentary_plus_original` 必须包含 `commentary_crosscheck[]`，每项记录 `commentary_claim`、`original_support`、`relationship`（`confirmed|qualified|contradicted|not_verified`）和 `source_refs`。

## 多篇模式 papers[]

`multi_paper_briefing` 和 `multi_paper_research` 必须包含至少两项：

```json
{
  "papers": [
    {
      "metadata": {
        "title": "",
        "authors": [],
        "year": null,
        "venue": "",
        "doi": "",
        "arxiv_id": ""
      },
      "background": "",
      "question_or_goal": "",
      "prior_context_and_gap": "",
      "logic_chain": [],
      "what_they_did": "",
      "methods_or_materials": "",
      "main_findings": [],
      "conclusions": "",
      "necessary_boundary": "",
      "relationship_to_collection": "",
      "source_refs": []
    }
  ],
  "cross_paper_synthesis": {
    "common_ground": [],
    "differences": [],
    "open_question": ""
  }
}
```

## script.json

新脚本的开场前缀由 research-v3.md 的 `teaching.opening` 派生。顶层新增 `opening: {version: 1, assumes_unread_paper: true, paper_ids: ["P1"], end_turn: <最后开场轮次索引>}`；开场轮次使用 `kind=orientation`，带 `orientation_topic`、`paper_id`、`verification`、`evidence_ids`。元数据或报告里列出题名、作者不等于已向听众介绍，实际口播必须覆盖。下面保留原有正文结构，不能单独作为新节目的完整脚本。

```json
{
  "format": "dialogue|single_narrator",
  "analysis_mode": "single_paper_close_reading|commentary_plus_original|multi_paper_research|multi_paper_briefing",
  "episode_title": "",
  "paper_title": "",
  "target_minutes": 20,
  "opening_disclosure": "本节目由 AI 生成，仅用于教学，不是真人录音或作者访谈。",
  "speakers": {
    "host_name": "知原",
    "learner_name": "小问",
    "narrator_name": "简报"
  },
  "chapters": [
    {"title": "", "objective": "", "start_turn": 0, "paper_index": null}
  ],
  "turns": [
    {
      "chapter": "开场",
      "speaker": "host|learner|narrator",
      "kind": "disclosure|orientation|explain|question|challenge|recap|transition|brief",
      "text": "",
      "delivery": "calm|curious|skeptical|reflective|emphatic|recap|warm",
      "pause_ms": 650,
      "source_refs": [],
      "claim_ids": [],
      "paper_index": null
    }
  ],
  "closing_takeaways": []
}
```

`dialogue` 只能使用 `host` 和 `learner`；`single_narrator` 只能使用 `narrator`。`transcript.md` 按章节呈现角色、正文和必要原文定位，但不把 `delivery` 或 `pause_ms` 写入口播文本。

## 人声导演 V2 输出

`directed-script.json` 保留全部原始脚本字段，并增加：

```json
{
  "voice_direction_version": 2,
  "voice_direction_provider_independent": true,
  "performance_units": [
    {
      "index": 0,
      "source_turn_index": 0,
      "unit_in_turn": 0,
      "chapter": "开场",
      "speaker": "host",
      "display_text": "原轮文本，仅在第一个单元保留",
      "spoken_text": "实际送入语音模型的可朗读文本。",
      "delivery": "calm",
      "rate_delta": -1,
      "pitch_delta_hz": -1,
      "volume_delta": 0,
      "pause_ms": 500,
      "emphasis_terms": [],
      "direction_reasons": ["role:host", "turn_boundary"],
      "source_refs": []
    }
  ]
}
```

`voice-director-report.json` 必须记录替换统计、拆句提示、逐片段时长/字速检查和错误数。`voice-manifest.json` 必须记录实际语音提供者以及每个表演单元最终使用的 voice、rate、pitch、volume、pause 和时间位置。
