# 推送 Zotero

只有用户要求保存到 Zotero 时执行写入。脚本默认优先连接本机 Zotero MCP（默认 `http://127.0.0.1:23120/mcp`，可由 `ZOTERO_MCP_URL` 覆盖），使用 MCP 创建题录、加入目标分类并导入本地 PDF。MCP 在任何写入前不可用时，`--transport auto` 才回退到本机 Zotero Connector；不会在 MCP 写入结果不明后自动切换通道或重发。Zotero 自身的同步设置决定后续是否同步。

## 准备题录和目标

1. 在校园知网页面通过可见原生导出或完整详情页获取题录。复用已核对数据，不固定请求直连 GetExport。脚本接受规范 JSON，也可解析 ELEARNING 字符串；作者完整性仍须人工/代理根据真实内容核对。
2. 使用 `python <skill-dir>/scripts/push_to_zotero.py --list` 优先读取 MCP 可见的文库和分类。若当前 Connector 选择能与 MCP 分类唯一对应，输出会同时给出兼容目标（如 `C1`）和 `mcpTarget`；否则从 `targets` 中选择 `M<libraryID>:<collectionKey>`。未运行时提示启动 Zotero。用户指定分类时请其在 Zotero 选择，核对输出目标；已授权保存不再重复询问。
   MCP 的 `get_libraries` 只返回 `libraryType`，不返回 `editable`/`filesEditable`。脚本把 `user` 库视为可写；`group` 库标记为权限未知，显式 `False` 会拒绝写入。PDF 附件要求 `filesEditable=true`；`user` 库按可写处理，`group` 库在 MCP 未暴露该字段时默认拒绝，此时可改用 Connector 目标（`C<id>`）或先核对目标。
3. 如要求 PDF，先经所选本地校园浏览器下载，打开/解析并核对题名。脚本只接受本地路径，不接收 pdfUrl、Cookie、密码或登录票据。

输入示例（合成数据）：

```json
[{"title":"合成研究题名","authors":["测试作者"],"authors_complete":true,"journal":"合成期刊","year":"2025","database":"SYNTHETIC","record_id":"example-1","keywords":["合成示例"]}]
```

可选字段：doi、公开 url、volume、issue、pages、issn、language、abstract、pdf_path、pdf_identity_verified。后两项在核验本地 PDF 后填入绝对路径和 true。只核对摘要不能视为已核验 PDF。脚本支持本项目默认的期刊论文；其他文献类型不能强制转换为期刊论文。

URL 使用实际导出的公开题录链接；如果只有校园代理地址，暂不填 url，保留核验的 DOI/数据库与记录 ID，不把代理登录地址写入 Zotero。本地研究台账可保留不含认证票据的校园访问定位。

## 执行

```sh
python <skill-dir>/scripts/push_to_zotero.py papers.json --dry-run
python <skill-dir>/scripts/push_to_zotero.py papers.json --state <research-folder>/zotero-receipts.json --expect-target C1
```

需要强制使用某一路线时，可加 `--transport mcp` 或 `--transport connector`；默认 `auto` 优先 MCP，仅在 MCP 初始化/能力发现失败且尚未写入时回退 Connector。`--list --transport connector` 可单独查看 Connector 当前选择。dry-run 完全离线。收据文件选在研究目录，续跑必须复用。MCP 路线以工具成功响应作为阶段确认；Connector 路线只把 HTTP 201 记为相应阶段成功。执行期间保持 Zotero 目标分类不变。

成功结果以 JSON 分别报告题录、附件和整体结果；输入/连接/状态错误以纯文本写入 stderr。退出码 0=全部请求完成，2=部分未完成，1=输入/连接/状态错误。metadata=saved 但附件失败时，应报告“题录已保存，附件未保存”。

## 续跑与结果不明

- 同一收据、同一目标内，按 DOI、数据库记录 ID 或多字段身份复用成功项；同名论文不直接合并。字段冲突停止该条。MCP 路线会把 `C1` 与对应的 `M1:<collectionKey>` 规范为同一收据目标；旧 C 目标收据首次复用时持久保存目标映射并补齐身份别名，之后可使用对应的 M 目标续跑。原收据键保持不变，`--resolve` 继续使用返回的原键；若已有多个匹配收据则停止并要求核对，不覆盖已有收据。若升级前只有 C 目标收据且首次直接使用 M 目标，可能无法自动映射；先用 C 目标续跑一次即可迁移。
- 这是任务收据去重，不能查询全库；已手工导入、其他任务或设备中的条目需在 Zotero 核对。
- 发送前记 sending，成功后记 saved。超时、断线、HTTP 409 或中断可能已经产生条目，不能当成功或自动重发。
- MCP 路线将创建后的 Zotero item key 保存到收据，用于后续附件导入和续跑；附件导入还要求 MCP 返回 `attachmentKey`，缺失时记为 `uncertain`，不冒充已保存。旧 Connector 收据没有 MCP item key 时，若题录已保存但附件未完成，脚本会阻止 MCP 路线继续；核对实际题录后，可显式使用 `--transport connector` 续跑，不会自动创建第二条题录。
- 先在 Zotero 查看实际条目，再执行手工核验登记，随后续跑原输入：

```sh
python <skill-dir>/scripts/push_to_zotero.py --state <research-folder>/zotero-receipts.json --resolve <returned-record-key> --stage metadata --outcome saved --note "已核对目标分类、题名、作者、年份" --item-key <MCP_ITEM_KEY>
```

stage 可为 metadata/pdf，outcome 可为 saved/not-saved。不得为了通过流程而虚构核验。锁文件残留时先确认进程已退出，再移除明确的 .lock；不要删除收据。核对到 MCP item key 时用 `--item-key` 一并写入收据；这样旧 Connector 题录无需重建即可继续 MCP 附件。

旧 Connector 收据的 metadata 已为 saved、但缺少 MCP item key 时，也可使用上面的 `--stage metadata --outcome saved --item-key ... --note ...` 命令补录。必须先核对实际条目的文库、分类和题录身份；补录只更新本地收据并保存核验说明与 key，不重新创建题录或重置附件状态。已有不同 item key 时拒绝覆盖，应先核对冲突。其他 saved 阶段不允许借此重置为未保存。

附件标为 blocked 后，重复执行只报告阻碍，不再次上传。修复明确的拒绝原因并核对附件确实未保存后，才用 `--resolve ... --stage pdf --outcome not-saved --note "核验与修复说明"` 将其恢复为 pending；这条登记本身不会修复失效的 Connector 会话。sending/uncertain 同样先核对实际结果，不能盲目重发。

Zotero 重启后旧 Connector 会话可能失效。题录已保存但 PDF 返回 SESSION_NOT_FOUND 时，通过 Zotero 可用界面/连接器把本地 PDF 附加到已有条目，打开附件并核对题名/页数后，再登记 pdf=saved；保留原 HTTP 错误与核验说明，不要再建题录。收据也不能证明用户后来没有删除条目。

参考：[cookjohn 推送实现](https://github.com/cookjohn/cnki-skills/blob/20d65f660456daf53ad0f7c74494ac3b829b925f/skills/cnki-export/scripts/push_to_zotero.py)、[Zotero Connector 源码](https://github.com/zotero/zotero/blob/main/chrome/content/zotero/xpcom/server/server_connector.js)。本版重新实现了收据和本地 PDF 流程。

补录 DOI 时会匹配 CNKI 身份及旧收据键，避免因身份升级重复建条目；已有条目的题录指纹变化会阻止重推，需在 Zotero 中核对和更新。该阻止结果不等于题录已同步更新，不要删除收据来绕过去重。
