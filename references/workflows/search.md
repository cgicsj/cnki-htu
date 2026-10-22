# CNKI search

1. Record the requested keywords verbatim; default to subject/主题 if that field is offered. State the actual field used. Do not silently add synonyms or restrictive filters.
2. Inspect the homepage search box and database selector. Choose academic journals/学术期刊 when available; otherwise search then filter to journals.
3. Enter keywords through the UI and submit. Wait for a result list, explicit zero-results message, or access blocker.
4. Report actual query, database, retrieval time, total count and current sort. Extract up to the requested count (default 20) through the internal parse-results workflow.
5. Read each distinct result row: title and observed detail URL, displayed authors, source, date, document type, DOI/record identifier if exposed. Mark shortened author lists incomplete. Preserve site rank; never substitute a paraphrased title for a new record.
6. For additional pages use the visible next-page control, verifying the page indicator and changed first record. Stop at the count or end; report shortfalls. Deduplicate on DOI, then observed database+record ID, otherwise flag matching title/year for review.
Example: “使用 search 搜索生成式人工智能”。
