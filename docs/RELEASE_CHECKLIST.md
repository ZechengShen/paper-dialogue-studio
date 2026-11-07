# 发布者检查清单

本次准备的是 Windows 本地运行源码版，保留 Codex 接力与使用者自带 API。没有部署公网服务，没有开通自动扣费，没有分发账号。仓库保持当前可见性，MIT 文件随源码保留。

## 先验收

在仓库根目录执行：

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p "test_*.py"
.\.venv\Scripts\python.exe -B scripts/package_repo.py --check
```

发布测试包含：源码白名单、必要入口、假密钥拦截、私有文件排除、ZIP 哈希核对，以及解压到新目录后的本地网页、空任务列表、Codex 任务创建和领取。它不调用模型或在线语音，不等于在另一台干净电脑完整安装并生成真实论文的验收。发给第一位使用者时，先用非敏感短材料试运行，再生成长节目。

## 生成分享包

```powershell
.\.venv\Scripts\python.exe -B scripts/package_repo.py
```

输出在 `dist/`：源码 ZIP、对应 `.sha256` 校验文件。ZIP 内 `SOURCE-MANIFEST.json` 记录每个文件的 SHA-256。哈希用于核对文件一致性，不是签名或安全认证。

打包不包含 `.git`、`.env`、作者的 Codex 登录缓存、虚拟环境、真实材料、历史节目、日志、音频、截图、迁移备份或模型权重。自动扫描只能发现部分模式；发布者仍须检查 `config/`、示例、文档和 Git 历史，不要把整份本地文件夹拖上 GitHub。

## 你之后上传 GitHub 时

1. 查看 `git status` 和待发布提交，确认只包含本次源码／规范。这里的本地 commit 不会自动出现在远端；需要由你明确执行 push。
2. 上传源码用 Git 推送，源码 ZIP 可作为 Release 附件；不要把 ZIP 放进仓库根目录代替源码。`dist/` 本身被忽略。
3. 保持 Private：给需要的人授权仓库访问，或直接提供净化源码 ZIP。不需要为了分享给少数朋友而公开仓库；MIT 不会自动改变访问权限。
4. 附上 [分享版使用指南](SHARING.md)，明确“Python 安装后运行”“使用自己的 Codex 或 API”“在线生成可能有费用”“尚非多人网站”。
5. 若将来主动改为 Public，先额外审查整个 Git 历史；只清理当前目录不能抹去过去误提交的秘密。凭据泄露先撤销／轮换。

## 可直接复制的发布说明

> 论文开讲 V3：Windows 本地运行源码版。支持导入 PDF、HTML、文章及 Notion 链接，使用自己的 Codex 接力，或自己的 Kimi／兼容 API 生成精读报告、讲解脚本与可选音频、HTML 解释动画。先安装 Python，双击“首次安装.cmd”，再运行“启动论文开讲.cmd”。不附带账号、API 额度、私人文献或历史音频。请先阅读 docs/SHARING.md；在线模型与语音需联网，API 费用由使用者承担，科学结论和听感仍需复核。MIT 仅适用于本项目源码。
