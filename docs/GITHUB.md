# GitHub 仓库交付

## 目录

```text
web/                 本地网页与 HTTP 接口
scripts/             收件、研究构建、API、语音、仓库打包
config/              节目、研究与发音的固定规范
.agents/skills/      Codex 项目执行技能
examples/research-v3/明确标为合成工作流示例的报告与动画
tests/               离线单元、集成与浏览器回归
.github/workflows/   Windows / Linux 自动测试
docs/                API、语音候选、仓库说明
inbox/               私人输入与任务（只发布 .gitkeep）
outputs/             私人报告与音频（只发布 .gitkeep）
```

运行入口保留 `启动论文开讲.cmd`、`start-web.ps1`；安装为 `setup.ps1`。源码、真实材料、历史节目和本地运行环境统一放在 GitHub 本地仓库 `paper-dialogue-studio`。旧目录仅保留启动转接和目录兼容链接，历史文件中的旧路径仍可访问同一份材料；不要删除这些兼容链接后继续使用旧任务路径。迁移前源码及校验清单保存在本地 `_local_archive/`，不进入发布包。

## 先检查，再打包

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p "test_*.py"
.\.venv\Scripts\python.exe -B scripts/package_repo.py --check
.\.venv\Scripts\python.exe -B scripts/package_repo.py
```

最后一条在 `dist/` 创建不覆盖旧包的源码 ZIP，内含 `SOURCE-MANIFEST.json` 文件哈希。采用源码白名单，不收集 `.git`、虚拟环境、真实输入、节目、音频、日志、运行缓存或模型权重。自动检查只报告命中的文件名，不输出疑似密钥。

白名单和正则扫描都不是安全保证。公开前仍要逐个检查示例、测试、配置和文档：无 API Key、Notion Token、私人链接、论文原文、个人目录、未授权声音。`.env.example` 只能放空密钥及设置示例；真实 `.env` 只保留本机。

## 日常维护：本地 commit，不自动 push

已有仓库直接在本地工作，不需要再次 `git init`、新建仓库或导入源码 ZIP。每次更新先查看工作区，完成相关测试与隐私检查，然后只暂存本次修改的源码、配置和规范：

```powershell
git status --short
git diff
# 将下面的占位符换成本次实际修改的文件；不要暂存私人材料。
git add -- <本次修改的文件>
git diff --cached --stat
git diff --cached
git commit -m "说明本次更新内容"
git status --short --branch
```

默认到此为止，不执行 push，也不通过 GitHub 连接器写入远程。只有用户后续明确要求上传时才推送。已有用户未提交改动应保留，不与本次改动混合提交；纯问答或只新增被忽略的节目文件不需要空提交。

不要上传 ZIP 到代码根目录代替源码，也不要把整个工作目录拖到 GitHub。忽略规则不会移除已追踪的敏感文件，因此仍需检查暂存区和历史；若密钥曾公开，先撤销／轮换，再处理历史。

本项目源码采用 [MIT License](../LICENSE)，版权署名为 ZechengShen。仓库可见性保持 Private；MIT 是源码的许可条款，不会自动将私密仓库设为公开。第三方依赖、模型权重、音色和导入文献仍适用各自的许可。仓库中不打包模型或真人参考录音。

CI 使用模拟 API 和测试音，不调用付费模型或在线 TTS。它验证软件链路，不证明真实论文推理和人声自然度。
