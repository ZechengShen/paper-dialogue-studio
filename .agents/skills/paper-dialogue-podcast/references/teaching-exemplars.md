# 教学视角与跨学科范例库

目的：学习怎样提出问题、建立直觉、检查证据和承认未知，不复制任何人的语言、声音或权威姿态。以下是 2026-10-24 实际核验的入口与片段，不把旧范例中的科学判断当作今天的领域共识。

## 可直接借鉴的样例卡

### 3Blue1Brown：直觉、计算和画面共用同一个问题

[Attention in transformers, step-by-step](https://www.3blue1brown.com/lessons/attention/)（2024）。已读官方网页 Motivating Examples 及后续查询、键、值的解释；没有声称看完视频或取得整段视频字幕。文章用同一个词在不同语境下的含义作为入口，再解释向量为什么需要吸收上下文。借鉴：先展示期望行为，继而分解计算；每屏聚焦一个变化；教学假想与真实学得的机制要区分。应用到 chapter beats 的具体例子、预测，以及动画 before/after 场景；不照搬配色或复制动画资产。

### Keshav：按理解层级阅读，不一次钻入全部细节

[How to Read a Paper](https://systems.cs.columbia.edu/ds2-class/papers/keshav-paper.pdf)，2016 版本，已读两页原文，重点 2.1–2.3。先把握全貌，再检查图表与论证，最后尝试重建；读不下去可有意识地补先修、延期或停止。应用到三遍阅读记录和明确的 partial/skipped 理由。它提供阅读策略，不替代本项目的学科审查，也不承诺三遍后必然读懂任何文章。

### 物理：让听众看到直觉何时失效

[Feynman Lectures I.37：Quantum Behavior](https://www.feynmanlectures.caltech.edu/I_37.html)，重点 37–2 至 37–5。已读官方文本。课程依次比较子弹、水波和电子，先建立预测再展示不一致。可借鉴“同一问题、不同对象、预测对照”的组织方法。类比的失败本身也是知识点，不能把电子真的画成小水波。此页注明该讲录音缺失，本次未声称听过录音。

### 凝聚态：一篇短评如何组织多篇论文

[Laura Classen：Geometry Rescues Superconductivity in Twisted Graphene](https://physics.aps.org/articles/v13/23)，2020。已读正文。可借鉴其组织：提出平带背景下的疑问，再比较三组工作的共同设定与不同贡献，最后保留适用区间和开放问题。用于学习多篇综合结构；尚未据此重新核验全部底层论文。

### 凝聚态：从测量追问到机制

[Natalia B. Perkins：Resolving the Achilles’ Heel of Thermal Hall Conductivity Measurements](https://physics.aps.org/articles/v15/198)，2022。已读正文。可借鉴“测到什么→通常如何解释→哪项假设值得重查→什么机制可能产生信号”的追问顺序。强调观测与机制归因分离，而不是见到一个信号就宣布一个新相。

### 量子计算：用最小例子说明经典直觉为何不足

[Joschka Roffe：Towards practical quantum LDPC codes](https://quantum-journal.org/views/qv-2021-11-30-63/)，2021。已读正文的解码、有限尺寸和 Outlook。文章以小例子解释简并，并明确理想噪声模型与电路级检验的差别。可借鉴“最小例子→算法困难→修补方案→测试缺口”；不把当时的模拟比较直接当作现今硬件性能结论。

### 量子计算：讲完后检验是否真的理解

[Andy Matuschak / Michael Nielsen：Quantum computing for the very curious](https://quantum.country/qcvc)。已检查章节结构、量子比特入门和内嵌问题说明，未声称做完课程。可借鉴把检索练习嵌入讲解，暴露读懂但记不住的缺口。本项目另加反事实和迁移题，记住术语不等于理解机制。

### 凝聚态研讨入口：待补全文样例

[Journal Club for Condensed Matter Physics](https://www.condmatjclub.org/archives/) 是值得保留的专家评论入口。已核验两条具体目录与作者信息：Andrey Chubukov 的 [2D Hubbard 模型讨论](https://www.condmatjclub.org/superconductivity-in-the-2d-hubbard-model-yes-no-or-maybe/)，以及 Patrick Lee 的 [α-RuCl3 多篇热输运讨论](https://www.condmatjclub.org/quantized-or-not-quantized-thermal-hall-effect-and-oscillations-in-the-thermal-conductivity-in-the-kitaev-spin-liquid-candidate-%CE%B1-rucl3/)。评论 PDF 本次返回访问错误，因此仅列候选，不据此虚构其论证过程；取得全文后再补正式样例卡。

AI 的李沐、Alex Wang、Keshav 等参考及访问边界见 expert-reading.md，不重复维护。

## 讲解模式：按需求选择，不由时长机械决定

优先顺序：用户明确要求 → 受众基础与学习目标 → 话题难点 → 时长。research.json 的 teaching.mode 必须选具体值，并用 selection_reason 记录取舍。

| 模式 | 适用目的 | 典型组织 | 通常长度提示 |
|---|---|---|---|
| intuitive／直觉导览 | 先知道问题与核心机制 | 具体困惑→一个例子→关键差别→边界 | 15–20 分钟 |
| progressive／层层深入 | 建立可持续的理解 | 现象→模型→必要概念→公式意义→证据→迁移 | 30–45 分钟 |
| reconstruction／建构式理解 | 理解技术为何这样设计 | 朴素方案→失败→最小改动→预测→代价→对照 | 45–60 分钟；可做单机制短篇 |
| seminar／研讨审查 | 已有基础，研究判断优先 | 核心主张→证据强弱→替代机制→可区分实验 | 30–60 分钟，依基础调整 |

短而深入可以只聚焦一个机制；长而易懂也可以补足先修背景。两者都不能放松证据纪律。研究底稿保持完整，媒体仅选择恰当讲述范围。没有足够材料不硬拉长。

## 清晰表达的可检查标准

1. 先按 script-standard.md 介绍工作身份、作者单位和目标／方法／结果全景，默认听众没读原文；在此基础上再给可理解的问题。新概念先交代它解决什么问题，再给名称，不用“问题先行”跳过知识起点。
2. 一个关键概念至少有具体例子、反例或对照中的一种。使用类比时明确对应关系与失效边界；不是所有抽象对象都必须找生活类比。
3. 公式先解释变量是什么、比较什么、能预测什么，再展开必要推导。术语少不等于不严谨；必须的专业概念应保留并教会。
4. 每章结束应能做一个判断或预测，不只是复述定义。把“我懂了”换成对新场景的解释。
5. 避免“本质上就是”“显然”“可以证明”等掩盖跳步的说法；保留尚未理解／尚无定论之处。
6. 两位角色共同推理，不假装一位是某位著名科学家，不用名人录音或声音仿制。AI 生成披露照常保留。

## 学科特有的失真防护

凝聚态：区分模型与材料、配对与相干、有限尺寸与热力学极限；检查维度、温度、能量尺度、对称性、边界条件、测量可观测量与拟合。顺滑的机制故事不能替代相的证据。

量子计算：区分振幅与概率、相位与经典随机性、物理与逻辑错误率、理想噪声与电路级噪声、算法复杂度与端到端资源。不要用“同时算完所有答案”解释量子加速，也不把纠错等同于复制未知量子态。

这些是本项目审查问题，不是对具体论文预设缺陷。只采用与该研究相关的检查并写明影响。

## 小动画怎样服务教学

只有时间演化、干预前后、状态切换或多步依赖确实难以口头跟随时启用。候选包括：一项控制变量怎样改变预测、两种机制产生相似信号却在某条件下分叉、纠错信息怎样流动。

目前实现是离线逻辑链步进播放器，适合问题→机制→证据→边界；真实干涉图样、量子态演化、相图动画需另做有方程与参数的模型。本轮不宣称这些仿真已实现。动画内标出观测／推断，不画未知电子轨迹，不把示意时间当真实时间。
