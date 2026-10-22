# 推送 Zotero

只有用户要求保存到 Zotero 时执行写入。目标为本机 Zotero 桌面端 Connector 服务，无需 API Key。Zotero 自身的同步设置决定后续是否同步。

## 准备题录和目标

1. 在校园知网页面通过可见原生导出或完整详情页获取题录。复用已核对数据，不固定请求直连 GetExport。脚本接受规范 JSON，也可解析 ELEARNING 字符串；作者完整性仍须人工/代理根据真实内容核对。
2. 使用 `python <skill-dir>/scripts/push_to_zotero.py --list` 读取当前分类与可用目标。未运行时提示启动 Zotero。用户指定分类时请其在 Zotero 选择，记录返回的 target（如 C123 或 L1）；未指定时使用当前分类并告知名称，已授权保存不再重复询问。
3. 如要求 PDF，先经校园 Chrome 下载，打开/解析并核对题名。脚本只接受本地路径，不接收 pdfUrl、Cookie、密码或登录票据。

输入示例（合成数据）：

```json
[{"title":"合成研究题名","authors":["测试作者"],"authors_complete":true,"journal":"合成期刊","year":"2025","database":"SYNTHETIC","record_id":"example-1","keywords":["合成示例"]}]
```

可选字段：doi、公开 url、volume、issue、pages、issn、language、abstract、pdf_path、pdf_identity_verified。后两项在核验本地 PDF 后填入绝对路径和 true。只核对摘要不能视为已核验 PDF。脚本支持本项目默认的期刊论文；其他文献类型不能强制转换为期刊论文。

URL 使用实际导出的公开题录链接；如果只有校园代理地址，暂不填 url，保留核验的 DOI/数据库与记录 ID，不把代理登录地址写入 Zotero。本地研究台账可保留不含认证票据的校园访问定位。

## 执行

```sh
python <skill-dir>/scripts/push_to_zotero.py papers.json --dry-run
python <skill-dir>/scripts/push_to_zotero.py papers.json --state <research-folder>/zotero-receipts.json --expect-target C123
```

dry-run 完全离线。收据文件选在研究目录，续跑必须复用。脚本对 localhost 禁用系统 HTTP 代理及重定向，逐篇保存题录再附加本地 PDF，只把 HTTP 201 记为相应阶段成功。执行期间保持 Zotero 目标分类不变。

返回 JSON 分别报告题录、附件和整体结果。退出码 0=全部请求完成，2=部分未完成，1=输入/连接/状态错误。metadata=saved 但附件失败时，应报告“题录已保存，附件未保存”。

## 续跑与结果不明

- 同一收据、同一目标内，按 DOI、数据库记录 ID 或多字段身份复用成功项；同名论文不直接合并。字段冲突停止该条。
- 这是任务收据去重，不能查询全库；已手工导入、其他任务或设备中的条目需在 Zotero 核对。
- 发送前记 sending，成功后记 saved。超时、断线、HTTP 409 或中断可能已经产生条目，不能当成功或自动重发。
- 先在 Zotero 查看实际条目，再执行手工核验登记，随后续跑原输入：

```sh
python <skill-dir>/scripts/push_to_zotero.py --state <research-folder>/zotero-receipts.json --resolve <returned-record-key> --stage metadata --outcome saved --note "已核对目标分类、题名、作者、年份"
```

stage 可为 metadata/pdf，outcome 可为 saved/not-saved。不得为了通过流程而虚构核验。锁文件残留时先确认进程已退出，再移除明确的 .lock；不要删除收据。

Zotero 重启后旧 Connector 会话可能失效。题录已保存但 PDF 返回 SESSION_NOT_FOUND 时，通过 Zotero 可用界面/连接器把本地 PDF 附加到已有条目，再登记附件结果；不要再建题录。收据也不能证明用户后来没有删除条目。

参考：[cookjohn 推送实现](https://github.com/cookjohn/cnki-skills/blob/20d65f660456daf53ad0f7c74494ac3b829b925f/skills/cnki-export/scripts/push_to_zotero.py)、[Zotero Connector 源码](https://github.com/zotero/zotero/blob/main/chrome/content/zotero/xpcom/server/server_connector.js)。本版重新实现了收据和本地 PDF 流程。
