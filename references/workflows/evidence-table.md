# 实证研究对照表

Use for “比较这几篇论文的数据、变量、内生性处理和机制检验，附原文页码”。
Use paper-detail for source reading and download only when downloads
are authorized. Reading supplied local PDFs does not require another download.

1. Read [the shared ledger schema](../schema.md), then use
   `../../scripts/workflow.py`. Reuse the current task. For a user-selected
   set without earlier screening, initialize a task with selection criteria
   “用户指定文献”; import and mark each paper included with its observed title as
   evidence. Do not invent a separate exclusion exercise.
   When the user requires full-text reading, initialize with
   `required_access: full_text`; partial evidence stays blocked until fulfilled.
2. Confirm title/author identity against each source. Read accessible material;
   record `full_text`, `preview` or `abstract_only`. Scanned/unreadable PDFs are a
   blocker until readable content is available, not completed full-text reading.
   If one parser rejects a PDF which a reader can open, use another available
   reader/parser or an in-memory repaired copy for extraction; retain the source
   file and disclose the recovery. Do not silently overwrite the original or
   treat malformed text extraction as missing research evidence.
3. Extract supported fields from the schema. Every non-empty field requires
   `value`, a short exact `quote`, `locator`, and `source`. Prefer PDF page number
   (1-based), printed page if different, table number and section. For abstracts
   use locator `摘要` and only facts explicitly stated there. Do not infer sample
   size, coefficients, causal identification or mechanisms from a title.
4. Missing fields stay null. Distinguish “未报告” (checked the relevant full-text
   sections) from “未提取/证据不足” (not known). Record author's claims separately
   from your evaluation; field `limitations` contains author-stated limitations.
   Preserve model/column, units and sample context when recording an effect size.
   The program validates evidence structure, not whether a quote supports a claim;
   the agent must check every value against the source before saving `extract`.
   Two-column text and spanning tables need reading-order/page-render checks.
   For tables split across columns or pages, anchor each fragment to its model
   headers, preserve empty cells in their original columns, and pair coefficients
   with their parenthetical test statistics before merging. Compare populated and
   blank cells against the page render; a one-column shift can leave values
   plausible while changing their model assignments.
   Preserve regression column, raw sample versus analysis sample and exclusion
   notes. Separate data-collection waves from a strict longitudinal/causal design;
   do not turn reported associations into causal identification. Review relevant
   limitation sections rather than deriving limitations solely from the abstract.
5. Save each paper immediately and export `研究工作表.xlsx`. The 实证研究对照表
   sheet holds comparisons; 原文证据 holds per-field source excerpts and locators.
   All included papers remain visible, even if not yet read. Report the number
   with completed extraction, the number read in full, and missing evidence.
   `full_text` describes the available evidence level, not proof every page or
   field has been reviewed. If only selected sections/fields were read, say so;
   an empty queue means configured stages are complete, not a complete literature
   review. Export validation should count actual rows when a read-only workbook
   reader has no worksheet dimensions; native Excel visual QA is a separate check.

Do not claim causal effects merely because the authors report correlations.
Do not upload PDFs or the private ledger to the repository or third-party services.
