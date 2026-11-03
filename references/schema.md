# Shared ledger / 输入格式与命令

Python 3.9+; no third-party runtime dependencies. All workflows are included in cnki-htu.
Replace the script path below with the absolute installed `cnki-htu/scripts/workflow.py`.
All JSON is UTF-8. Examples are synthetic and must not be reported as CNKI results.

## Start and import

`config.json`:
```json
{
  "topic": "数字化转型与企业创新",
  "query": "主题=数字化转型 AND 主题=企业创新",
  "criteria": "中国企业；实证研究；直接检验创新产出；不确定项保留待全文确认",
  "stages": ["screening", "extraction"],
  "database": "学术期刊",
  "platform": "国内知网",
  "date_range": "2023-01-01至2026-09-21",
  "sort": "实际观察到的排序",
  "retrieved_at": "2026-09-21T10:00:00+08:00"
}
```
Set `"required_access": "full_text"` when the user requires full-text analysis.
Partial extraction is saved but its stage remains blocked until full text is read;
the default `available` accepts explicitly labeled abstract/preview extraction.

Optional requested stages: `download`, `citation`. Downloads/citations apply to
all imported papers when requested; import only the specifically authorized set
into such a task. Do not add a download stage merely to read existing local PDFs.

```sh
python3 /path/to/workflow.py --task /local/research/task.sqlite init --config config.json
python3 /path/to/workflow.py --task /local/research/task.sqlite import --input records.json
```

`records.json` is an array. Required: title, observed public URL, retrieved_at.
Preferred: DOI, or database + record_id. Import returns stable IDs used below.
`source` is an alias of `journal`; imports retain the observed source and store
the canonical journal. Different non-empty values are rejected, including across
duplicate imports. Legacy source-only records use the same conflict checks;
exports refuse legacy records containing contradictory source/journal values.
Without a strong ID, the observed URL supplies a local locator key; possible
same-title/year records are preserved and flagged. Original metadata is retained.
Conflicting title/year/authors/record identifiers on the same identity abort the
entire import transaction; resolve the source conflict instead of overwriting.
```json
[{
  "title": "数字化转型与企业创新（合成演示）",
  "url": "https://example.org/synthetic-paper-1",
  "database": "SYNTHETIC",
  "record_id": "demo-1",
  "authors": ["测试作者"],
  "authors_complete": true,
  "year": "2025",
  "source": "合成测试期刊",
  "site_rank": 1,
  "abstract": "本合成示例使用中国企业样本研究创新产出。",
  "retrieved_at": "2026-09-21T10:00:00+08:00"
}]
```

## Screening

`screening.json`:
```json
{
  "decision": "include",
  "reason": "研究对象及创新结果符合纳入标准；依据摘要初筛",
  "basis": "abstract",
  "access_level": "abstract_only",
  "evidence": "本合成示例使用中国企业样本研究创新产出。"
}
```
Decisions: `include`, `exclude`, `uncertain`; basis: `title`, `abstract`, `full_text`;
access: `metadata_only`, `abstract_only`, `preview`, `full_text`.
```sh
python3 /path/to/workflow.py --task /local/research/task.sqlite screen --id cnki:SYNTHETIC:demo-1 --input screening.json
```
Screening is complete even if its decision is uncertain; extraction remains blocked.
Exclusion skips extraction; changing an earlier decision invalidates extraction.
Identical repeated decisions are idempotent and preserve completed extraction.

## Evidence extraction

`extraction.json`:
```json
{
  "access_level": "abstract_only",
  "fields": {
    "question": {
      "value": "数字化转型与企业创新产出的关系",
      "quote": "本合成示例使用中国企业样本研究创新产出。",
      "locator": "摘要",
      "source": "https://example.org/synthetic-paper-1"
    },
    "sample": null,
    "method": null
  }
}
```
For full text, use a public source URL or absolute local file path and precise
locator, e.g. `PDF第6页（印刷页42），表3列(2)`; exact short quote required.
The agent verifies evidence truth and support; structural validation cannot do so.
A completed extraction can still have missing fields; these remain explicitly
unknown. A preview/abstract extraction is never counted as full-text reading.

Supported fields:
`question`, `theory`, `data_source`, `sample`, `period`, `outcome`, `exposure`,
`controls`, `method`, `endogeneity`, `robustness`, `mechanism`, `heterogeneity`,
`findings`, `limitations`. Unknown fields are rejected; omitted/null fields export
as “未提取/证据不足”. A value claiming “未报告” still needs a checked source location.
```sh
python3 /path/to/workflow.py --task /local/research/task.sqlite extract --id cnki:SYNTHETIC:demo-1 --input extraction.json
```

## Progress and files

```sh
python3 /path/to/workflow.py --task /local/research/task.sqlite queue
python3 /path/to/workflow.py --task /local/research/task.sqlite status
python3 /path/to/workflow.py --task /local/research/task.sqlite mark --id cnki:SYNTHETIC:demo-1 --stage download --status running
python3 /path/to/workflow.py --task /local/research/task.sqlite mark --id cnki:SYNTHETIC:demo-1 --stage download --status blocked --reason '需要恢复机构登录'
python3 /path/to/workflow.py --task /local/research/task.sqlite mark --id cnki:SYNTHETIC:demo-1 --stage download --status pending --reason '机构登录已恢复；已确认没有活跃下载'
python3 /path/to/workflow.py --task /local/research/task.sqlite mark --id cnki:SYNTHETIC:demo-1 --stage download --status done --artifact /local/research/paper.pdf --identity-verified
python3 /path/to/workflow.py --task /local/research/task.sqlite reset --id cnki:SYNTHETIC:demo-1 --stage download --reason '下载到错误论文；已核对并删除旧文件'
```
Only pending eligible stages can be claimed. After an interruption, a running
stage is deliberately not reset automatically. Recover a completed transfer from
its receipt and verify its file before marking done. `queue`/`export` revalidate
artifact hashes and download PDF framing; missing/changed/invalid files become pending.
Download completion requires a non-temporary filename, `%PDF-` header and `%%EOF`
within the final 4096 bytes. This lightweight check does not validate PDF structure
or the paper's identity; open/read the document before `--identity-verified`.
Old completed receipts with invalid PDF framing also return to pending on the next
`queue`/`export`; this does not delete files or launch a new transfer.
The ledger stores no browser
session and does not keep a download alive after the browser exits.

## Export

```sh
python3 /path/to/workflow.py --task /local/research/task.sqlite export --output /local/research/report-001
```
Creates `研究工作表.xlsx` with five sheets: 文献筛选表、实证研究对照表、原文证据、
任务进度、检索与筛选规则; five UTF-8 BOM CSVs and `task-snapshot.json` audit history.
Header rows are frozen, filters enabled, text wrapped. Formula-like text remains
literal in XLSX and is prefixed with an apostrophe in CSV. Existing output folders
are refused. Exports may be partial: consult progress and access levels.
Keep the `.sqlite` file to resume; snapshot JSON is not an editable import format.
Do not manually edit SQLite while a task is running or copy an active transaction.

## Identity upgrades and compatibility

Import builds batch indexes for normalized DOI, CNKI database/record ID, observed URLs and title/year warnings. Stable paper IDs never change after enrichment. Existing schema-v1 ledgers gain a `paper_aliases` table transactionally on first import; close the task and back it up before upgrading. New observed URL aliases persist across restarts. Conflicting strong IDs or multiple existing matches stop the transaction; existing duplicate rows are not silently merged.

An explicitly incomplete author list can be upgraded to a verified complete list when the old list is a prefix in the same order. Other author changes remain conflicts requiring source review. Enrichment records before/after metadata in the event history. Session-bearing URLs, including encoded parameters, are rejected; extraction sources must be safe source URLs or absolute local paths.

CLI queue/export hash artifacts before obtaining the write lock and compare the original receipt before invalidating it. Strict hashing remains enabled. Exports are staged and published as a complete directory under a per-destination lock, never overwritten. A stale publish lock requires checking the active process before removing it.
