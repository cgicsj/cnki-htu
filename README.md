# cnki-htu

`cnki-htu` 是面向河南师范大学校园网访问场景的 Codex 技能。它通过用户本地已登录的 EasyConnect/VPN 使用中国知网，优先通过 Codex Chrome 插件（`@Chrome`）操作本地 Chrome，插件不可用时回退 Chrome DevTools MCP，帮助完成文献检索、筛选、下载与整理。

## 功能

- 知网关键词检索和作者、机构、期刊、日期等高级检索
- 结果解析、去重、翻页、排序和期刊卷期浏览
- 题录与摘要查看、文献纳入/排除筛选、实证证据对照
- 在机构权限允许时下载 PDF，并导出 BibTeX、RIS/EndNote 等引用格式
- 将题录及已下载的 PDF 推送到 Zotero
- 保存任务进度并从台账续跑，支持 Excel/CSV 工作流

具体流程和数据字段说明见 [`references/`](references/) 中的指南。

## 使用前准备

- Windows 本地环境、Google Chrome、可连接本地 Chrome 会话的 Codex Chrome 插件（`@Chrome`）或 Chrome DevTools MCP，以及 Python 3.9 或更高版本。技能脚本使用 Python 标准库。
- 需要访问校园资源时，先登录河南师范大学 EasyConnect/VPN，并在所选浏览器中确认知网机构认证有效。校园访问入口和故障处理见[访问与认证说明](references/access.md)。
- 下载 PDF、Zotero 推送等能力受机构订阅、账号权限、浏览器设置及 Zotero 本地服务状态影响。
- 首次登录、验证码或重新认证由用户在本机浏览器中完成；请勿在聊天中发送密码、验证码或浏览器 Cookie。

## 安装

将本仓库克隆到 Codex 技能目录。当前用户全局安装可使用 PowerShell：

```powershell
git clone https://github.com/cgicsj/cnki-htu.git "$env:USERPROFILE\.codex\skills\cnki-htu"
```

也可以将仓库放入项目级技能目录 `.agents/skills/cnki-htu`。安装或更新后，重新加载 Codex，使其发现技能。

## 使用示例

在 Codex 中直接提出需求，例如：

- “使用 cnki-htu 检索 2023 年以来数字化转型与企业创新的期刊论文，按时间列出前 20 篇。”
- “筛选这组文献，并制作包含样本、方法和原文证据的对照表。”
- “下载这 5 篇文献的 PDF，并将题录和已下载文件保存到 Zotero 当前分类。”
- “继续这个任务台账，完成剩余检索并导出 Excel。”

技能会根据任务读取相应的内部流程。默认不会超出用户指定的文献范围，也不会自动下载或推送未明确要求的文献。

## 使用边界

技能通过校园入口和用户已认证的浏览器会话操作，不调用写死的知网 API、不绕过访问控制，也不导出登录凭据。验证码、登录失效或连续操作无进展时，流程会暂停并请用户在本机处理。每项工作的完成状态以实际观察到的页面、文件和导出结果为准。

## 许可

许可和第三方来源说明见 [`LICENSE`](LICENSE) 与 [`NOTICE.md`](NOTICE.md)。

## 浏览器选择

网页任务先检查当前 agent 提供的浏览器能力：优先用 Codex Chrome 插件（`@Chrome`）连接本地 Chrome；插件不可用或无法接入时，再使用 Chrome DevTools MCP 等可连接同一会话的工具。连接不可用时明确报告实际状态；每个会话需要单独核验校园认证，不能沿用其他会话的登录结论。详见[浏览器选择](references/browser.md)。离线任务不要求 VPN 或浏览器。

## 离线快速示例与测试

在仓库根目录用 PowerShell 运行，`local-data` 已被 Git 忽略：

```powershell
New-Item -ItemType Directory -Path local-data -Force | Out-Null
python scripts/workflow.py --task local-data/task.sqlite init --config examples/config.json
python scripts/workflow.py --task local-data/task.sqlite import --input examples/records.json
python scripts/workflow.py --task local-data/task.sqlite export --output local-data/report-001
python scripts/convert.py examples/records.json --format json --output local-data/citations.bib
python -m unittest discover -s tests -v
```

示例均为合成数据。重复执行时请换用新的台账/输出路径；既有任务直接续跑。测试只用临时目录和模拟 Zotero 客户端，不访问真实知网或文献库。CI 配置覆盖 Windows/Linux、Python 3.9/3.12/3.14；以实际 CI 结果为准。

旧 SQLite 台账保留 schema_version=1 和原文献 ID，首次导入时自动添加身份别名表；升级前备份已关闭的台账。旧 Zotero v1 收据继续可读。补 DOI 等操作导致已保存题录变化时会阻止重推，需核对已有条目；这不会自动更新 Zotero 条目，也不能保证全库去重。

环境检查可运行 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check_environment.ps1`，仅输出技能/CLI、EasyConnect 安装与进程信号。认证仍须观察页面。导出遇到残留 `.publish.lock` 时先确认没有活跃导出进程再移除锁；保留已生成成果。所有私人研究输入和导出建议放在 `local-data/` 或仓库外。
