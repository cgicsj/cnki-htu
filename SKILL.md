---
name: cnki-htu
description: 通过河南师范大学 EasyConnect/VPN 和本地 Chrome 使用中国知网，完成检索、期刊浏览、文献筛选、PDF 下载、引用导出、推送 Zotero 及任务续跑。
---

# cnki-htu · 河南师范大学知网

这是唯一技能入口。根据用户请求读取下表中的内部流程，不要求安装其他 cnki-* 技能，也不创建子代理。所有路径相对于本技能目录；调用脚本时解析为实际绝对路径。Python 3.9+，脚本使用标准库。

## 先确定访问状态

需要访问网站时，先读取 [校园访问与认证](references/access.md)。使用用户本地、已登录 VPN 的 Chrome 会话。依次确认 EasyConnect/VPN 连接、校园知网页面、知网机构认证；进程存在或网页能打开不能单独证明认证成功。

- VPN 服务：`https://vpn.htu.edu.cn`
- 校园知网入口：`http://www-cnki-net-s.vpn.htu.edu.cn:8118`
- 未连接时提示：请登录 https://www.htu.edu.cn/info/2011/0116/c18431a250850/page.htm，下载深信服 VPN（EasyConnect），输入 https://vpn.htu.edu.cn，使用学生账号和密码登录。完成后告诉我，我会重新检查连接和知网机构认证。
- 认证失效、验证码或连接中断：保存进度，提示用户在 EasyConnect/Chrome 中手工完成，再重新观察页面并续跑。不要索取聊天中的密码或验证码，不导出 Cookie。
- 仅处理已有本地文件、离线引用转换或读取台账时不强制联网。恢复任务时先读台账，再对需要联网的剩余步骤检查访问状态。

## 按需求调用内部流程

| 用户需求 | 读取文件 |
|---|---|
| 完整文献研究任务 | [研究调度](references/workflows/researcher.md)，再读所需阶段 |
| 关键词检索 | [基础检索](references/workflows/search.md) |
| 作者、机构、期刊、日期、多条件检索 | [高级检索](references/workflows/advanced-search.md) |
| 提取结果、去重 | [结果解析](references/workflows/parse-results.md) |
| 翻页、每页条数、排序 | [翻页](references/workflows/navigate-pages.md) |
| 摘要、完整题录、全文分析 | [论文详情](references/workflows/paper-detail.md) |
| 期刊和卷期目录 | [期刊浏览](references/workflows/journal-browse.md) |
| 下载 PDF | [下载](references/workflows/download.md)及[Chrome 与连续下载](references/downloads.md) |
| BibTeX、RIS/EndNote 转换、原生引用导出 | [引用导出](references/workflows/export.md)及[格式](references/formats.md) |
| 保存到 Zotero，含已下载 PDF | [Zotero 推送](references/zotero.md)；需要下载时先走下载流程 |
| 文献纳入/排除/待判断 | [筛选](references/workflows/screening.md) |
| 变量、样本、方法、机制及原文证据对照 | [实证对照](references/workflows/evidence-table.md) |
| 保存进度、继续任务、Excel/CSV | [续跑](references/workflows/resume.md)及[台账格式](references/schema.md) |

## 共同约束

1. 保留用户给定的检索范围、排序、文献集合和输出目的。默认学术期刊，日期使用用户时区；不要因为请求完整研究就自动下载或推送未请求的文献。
2. 沿校园入口实际提供的链接操作，导航和新标签后重新观察。禁止写死直连知网 API、拼接代理地址、照搬旧选择器或因访问失败自动切换海外站。
3. 每篇记录标题、来源、访问层级与结果状态。未读全文不能称全文分析；缺失字段保持缺失。文件点击成功不等于文件下载完成。
4. 连续 PDF 下载逐篇执行，使用短随机间隔；坐标交互仅限当前已确认按钮内部。验证码立即交给用户，详见下载流程。
5. 需要长期保存来源链接时，优先采用实际导出的公开链接或已核验 DOI。校园代理链接只作本地访问定位，不能含登录票据/会话参数，不从代理编码猜测公开地址。Zotero 不接收 Cookie 或远程 PDF 下载任务。
6. 一个操作连续两次没有进展，记录阻碍并保留已完成成果；认证和验证码出现时立即暂停相关网页操作。不能把失败记录当零结果。
7. 按实际完成情况交付结果、文件绝对路径及未完成项。运行技能不意味着设置定时任务、上传到远程仓库或启用额外付费服务。

## 使用示例

- “用 cnki-htu 检索 2023 年以来数字化转型与企业创新的期刊论文，按时间列出前 20 篇。”
- “下载这 5 篇的 PDF，并将题录和 PDF 保存到 Zotero 当前分类。”
- “继续这个 task.sqlite，生成筛选表和实证研究对照表。”
