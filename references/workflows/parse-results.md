# CNKI parse-results

1. Verify the current page is a results list; an empty/loading page is not a zero-results finding.
2. Identify the result container and a representative row using current accessibility/DOM observations. Ignore menus, recommendations, advertisements and cited-reference lists.
3. Extract exact title, observed article URL, displayed authors, authors_complete, source, date, date_kind, document_type, DOI or observed record ID, site_rank and page. Never infer open access from a download link.
4. Distinguish “等”/ellipsis from a complete author list. If complete authors are needed, open the detail or native citation export. Do not invent a DOI from an identifier.
5. Deduplicate by normalized DOI; otherwise observed database+record ID. Without strong identifiers flag title/year matches for manual review. Similar titles with different DOIs remain distinct.
6. Preserve the site ordering and record displayed_count, unique_count, total_results, query, filters, sort and retrieved_at. A requested 20 rows must be 20 distinct observed papers, or an explicit shortfall.
7. Render numbered records with links and missing fields disclosed. Do not rename records, fill gaps with recommendations or re-count the same paper under another title.
