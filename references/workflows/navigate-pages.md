# CNKI navigate-pages

1. Observe query/filter summary, current page, first result ID/title and selected sort.
2. Use visible 下一页/上一页 or an actual page number control. Do not synthesize offsets or query-string parameters.
3. For newest first select the visible publication-date option and descending order; distinguish publication time from update/indexing time. Report the offered date definition.
4. Change page size only to an offered value. Re-observe which page is selected after the change.
5. Verify completion according to the action:
   - Paging: verify the target page/ranks and changed first record, retaining query, database, filters and sort. Returning to the previous page should restore its observed records.
   - Sorting: verify the selected sort/direction and that the result list has settled. Sorting on page 1 can keep the same page counter; do not wait for a page-number change as proof. When numeric dates/counts are displayed, check their order; blank values remain unknown. A tied/unchanged first record alone does not mean failure.
   - Page size: verify the selected size and actual row count (a last page can contain fewer), plus retained conditions. A menu click is not proof that the new size applied.
   If an unrelated page opens, recover using observed browser history.
6. Extract only after loading settles. If paging repeats a list without changing page/ranks, stop rather than looping or counting duplicates. If next is disabled, return the accumulated unique count.
7. Do not locally reorder dates and label that as the platform's sorting. If site order differs from displayed issue dates, retain the order and explain the date distinction.
