# 网页与讲解演示：设计参考库

核验日期：2026-10-24。数字取自 GitHub 仓库 API，精确提交记录见 [design-reference-lock.json](design-reference-lock.json)。本库保存来源与本项目的应用决策，不是第三方技能的全局安装，也不把远程说明直接当作本项目指令。

## 筛选结果

| 原始项目 | Stars / Forks（核验时） | 类型与许可 | 适合本项目的部分 |
|---|---:|---|---|
| [UI/UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | 139,536 / 14,780 | 设计技能，MIT | 表单渐进展开、字号与触达尺寸、焦点、对比度和响应式验收 |
| [Anthropic Skills](https://github.com/anthropics/skills) | 183,355 / 21,714 | 技能集合；frontend-design 为 Apache-2.0 | 先明确内容与视觉方向，再制定字体、颜色、布局规则，实施后截图复查 |
| [Reveal.js](https://github.com/hakimel/reveal.js) | 72,465 / 17,020 | HTML 演示框架，MIT | 阅读与演示分开；导航和进度明确；手机优先可滚动，不把长内容裁进固定幻灯片 |
| [Slidev](https://github.com/slidevjs/slidev) | 49,185 / 2,244 | 技术演示框架，MIT | 内容与展示层分离，可交互的条件对照，统一主题支持阅读和讲解 |

四个仓库均超过一万星，核验时未归档且仍有近期提交。Stars/Forks 是采用与关注度信号，不等于好评率、安全审计或实际设计效果保证。没有对用户评论做统计性调查；例如 UI/UX Pro Max 的 [Copilot 兼容性讨论](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/issues/454) 同时包含认可和具体兼容性问题，因此选用规则后仍需本地测试。

## 核验与摘读的原始材料

- [UI/UX Pro Max：快速检查表](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/main/src/ui-ux-pro-max/templates/base/quick-reference.md)：使用可见标签、足够大的控件、清晰焦点和可重排布局，不全盘采用它的配色与字体推荐。
- [Frontend Design 原文](https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md) 与 [该技能许可](https://github.com/anthropics/skills/blob/main/skills/frontend-design/LICENSE.txt)：本项目采用有意图的字体层级、内容驱动结构和两轮视觉复查。瑞士风格是用户明确偏好，不为了“独特”而换成另一种视觉语言。
- [Reveal.js Scroll View](https://revealjs.com/scroll-view/)：吸收阅读与演示为不同使用场景的思想。报告仍为长文；逻辑链仍为逐步演示，不把整份报告硬塞成幻灯片。
- [Why Slidev](https://sli.dev/guide/why)：采用同一内容驱动不同视图的原则。保留已有 research.json，不引入第二份结论。

## 已应用到哪里

| 页面 | 具体决策 | 文件 |
|---|---|---|
| 收件工作台 | 缩短开场标题区；制作偏好默认收起且显示当前选项摘要；顶部可直达材料与研究记录；结果导航吸顶，选中预览立即加载 | web/static/index.html、editorial.css、app.js |
| 精读 HTML | 有编号的章节目录、当前章节标记、可折叠移动目录、专注模式、大字模式；真实记录计数不冒充质量分数 | assets/report.html、scripts/research_pipeline.py |
| 逻辑演示 | 原问题与当前步骤主导画面；放大演示中的问题和对照；手机纵向排列；演示仍可查看证据和边界 | assets/logic-chain.html |
| 维护与验收 | 断网可读、无外部字体、键盘可用、减少动态效果、打印保留完整正文和证据 | DESIGN.md、tests/check_web.cjs、tests/check_visual.cjs |

## 不采用的部分与许可边界

- 不直接复制这些仓库的代码或完整技能，不运行它们的安装脚本；只保存链接、核验信息及自行整理的项目规则。现有 Flask + 原生 HTML/CSS/JS 足以实现本轮改造，无需引入 React、Vue 或新的构建工具。
- Anthropic 仓库采用分目录许可；其 pptx/docx/pdf/xlsx 是 source-available，不应被笼统标成 MIT 或直接并入本仓库。这里仅参考 frontend-design 的通用设计方法，没有安装其 PPTX 技能。
- 不引入在线字体、跟踪脚本、遥测、外部 CDN 或远程图片。第三方更新不会自动下载或覆盖本地规范。
- Reveal.js / Slidev 是演示框架参考，不代表本软件已经具备 PPTX 导出、MP4 渲染或音画同步。
- 真实研究内容不发送到这些项目；历史报告、发布哈希和音频保持不动。只有新的构建使用新模板。

## 以后怎样更新

### 2026-11-07 使用动线迭代

本轮追加参考设计规范的原始网页，而不是再引入 UI 库：

- [IBM Carbon Forms](https://www.carbondesignsystem.com/building-blocks/core/patterns/forms)：按关联任务分组，并在错误发生处提供反馈。应用为上传、链接、基础和授权的就近错误提示与焦点定位。
- [GOV.UK Check answers](https://design-system.service.gov.uk/patterns/check-answers/)：提交前可以检查自己的选择。应用为制作区域的材料数量／体积摘要，继续保留可修改的制作偏好和明确的 API 同意；没有照搬额外确认页增加每次提交步骤。
- [NN/g Progressive Disclosure](https://www.nngroup.com/articles/progressive-disclosure/)：低频选项放到二级区域。保留设置面板，压缩顶部说明，不把流程介绍、历史和配置同时展开。

三轮本地迭代记录：

1. 反馈：上传区明确支持点击选择；加入材料摘要与就近错误反馈。运行浏览器回归并检查桌面截图。
2. 效率：加入历史搜索、状态筛选、无结果提示；缩短顶部和组间重复空隙。手机试验悬浮入口，截图发现会覆盖输入区标签，未保留该方案。
3. 动线修正：改成每阶段末尾的顺序定位按钮，材料 → 阅读起点 → 制作设置；不代替最终提交，也不绕过 API 同意。移动设置面板关闭入口保持可到达。再次验证 320/390/768/1024/1440px 布局、键盘操作与任务切换。

验收是合成任务的功能测试与设计复查，不是真实用户可用性实验，不能宣称节省了具体百分比时间。后续观察首次导入、找到旧报告、输入纠错三项真实任务的完成情况，再决定是否调整流程。没有引入外部字体、遥测或持久化私人草稿。

先读 DESIGN.md，按任务选此表的一到两个相关方法；保留用户的瑞士风格和证据要求。需要采用第三方源码时另行核对固定提交、子目录许可及依赖，保留必要署名。更新参考库后同步核验日期与 lock 文件，不凭旧星数宣称当前热度。最终必须对实际页面截图检查，而不是仅把引用清单变长。
