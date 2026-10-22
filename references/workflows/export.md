# CNKI export

1. Resolve the requested set (single, selected list or all listed papers). Preserve exact titles and identities. Verify selected checkboxes before opening the visible 导出/参考文献 control; do not assume selection survives paging.
2. Prefer an offered native BibTeX option. Otherwise export the actual offered EndNote tagged or RIS format, or build verified structured JSON from detail metadata. Do not call a constructed conversion a native CNKI export.
   - Detail-page 引用 dialog natively offers GB/T 7714-2025, 知网研学 (E-Study) and EndNote.
   - 更多引用格式 opens the 文献管理中心 export page, which natively offers MLA, APA, Refworks, EndNote, NoteExpress, NoteFirst, **BibTex** and 自定义. Select the format in the left list (the clickable row is the `ul.formatlist li`, not only the inner link) and copy the rendered output. Observed 2026-10-21: BibTex rendered `@article{ZZJJ202630009, ...}` with author/title/journal/number/pages/year/issn/doi.
   - The export page may show a 拼图/安全验证 slider. It did not block reading the rendered output in testing, but if it blocks the format switch, hand it to the user rather than solving it.
3. For format details and schema read [../formats.md](../formats.md). Convert with [convert.py](../../scripts/convert.py):
   `python3 <skill-dir>/scripts/convert.py input.json --format json --output citations.bib`
   Formats: json, ris, endnote. Input encoding defaults to UTF-8; explicitly use --encoding gb18030 if confirmed.
4. The converter is offline and refuses incomplete author lists, conflicting duplicate metadata and unsupported record types. Resolve those from the source; do not weaken validation to force an export.
5. Validate the resulting file with an independent BibTeX parser when available, count unique entries, compare titles/DOIs/authors to the source and test Chinese names/special characters. The converter's successful exit alone is not an import test.
6. Deliver the .bib file and conversion provenance/warnings. Missing year/volume/pages remain omitted. If only a formatted GB/T reference is available, verify individual fields against the detail page before forming JSON; do not regex-guess all metadata from prose.
7. When Zotero is requested, read [Zotero push](../zotero.md) and use the bundled local receipt client with verified metadata and optional local PDFs. Do not transfer cookies or request direct remote PDF downloads.
