# 文献筛选表

Use for requests such as “按中国企业实证研究筛选这50篇文献，给我Excel和排除理由”。
Reuse search/advanced-search, parse-results and paper-detail for website access;
this skill does not operate a new crawler. Existing authorized scope carries through.

1. Freeze the observed result set and record query, date range, source platform,
   sorting, retrieval time and original rank. Define inclusion/exclusion criteria
   from the user's research question. If useful, propose a narrow criterion;
   do not silently restrict the population, date range or method.
2. Read [the shared ledger schema](../schema.md). Use
   `../../scripts/workflow.py` to init/import the task, or use the supplied
   existing task file. All resources are included in this single skill.
3. Read each paper's actual title/abstract/full text as available. Store `include`,
   `exclude` or `uncertain`, a specific reason tied to criteria, a short exact
   evidence excerpt, the basis and access level using `screen`. Avoid numeric
   relevance scores that imply unsupported precision. Do not treat unavailable
   full text as irrelevant. A title-only exclusion needs an unambiguous criterion
   violation; otherwise mark uncertain. Uncertain records require follow-up.
4. Persist each decision immediately. Never replace the result set with more
   convenient papers. Retain exclusions and original ranks. Similar title/year
   matches flagged by import are review candidates, not automatic duplicates.
5. Export with `export --output <new-folder>`. Deliver `研究工作表.xlsx` with the
   文献筛选表 sheet and UTF-8 CSV fallback. Report counts of included/excluded/
   uncertain/unprocessed records and the evidence-access limit.

Changing a decision invalidates that paper's extraction and records the old/new
values in the event history. Screening criteria are frozen per task: create a new
task for changed criteria, so earlier decisions are never silently reused.
