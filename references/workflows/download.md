# CNKI download

First read [Chrome permissions and paced downloads](../downloads.md). For this adaptation, sequential downloads are the default; the shared paced-download rules override upstream batch preferences.

1. Verify the requested paper identity and the user's download request. Default to PDF unless the user explicitly requests another format. Carry this preference through retries and batch operations. Before starting any transfer, create the local date folder described below.
2. Inspect the paper's observed native download controls, including any download menu. Prefer a control explicitly labeled PDF or PDF下载. A generic 下载/整本下载 button does not establish the format; inspect its options or the paper detail page before proceeding. Do not reconstruct file endpoints, change URL parameters to force PDF, replay cookies, use another institution's proxy or purchase access without explicit authority.
3. If no authorized PDF option is available after inspecting those controls, mark the item “PDF unavailable” or “PDF access blocked” as appropriate and continue other requested items. Do not silently fall back to CAJ. Download CAJ only if the user explicitly requests or accepts it; prior acceptance within the same task remains valid. Do not rename CAJ to .pdf, install a converter/viewer or print HTML as a substitute PDF unless separately requested.
4. Verify the actual file using the browser's documented download receipt or an authorized local directory: completed transfer, non-empty file and matching paper identity. For PDF, confirm PDF content using file-type inspection or a PDF reader/parser; extension alone is insufficient. CAJ or an HTML login/error page saved as .pdf is failure. Report an unexpected format and retain the PDF preference on retry; do not delete the unexpected file automatically.
5. Batch only specifically requested records; verify selected identities/count and the chosen PDF format, obey the displayed batch limit and collect per-item status. If the batch control only offers CAJ or its format is unclear, use individual verified PDF controls instead. Report remaining unavailable items without substituting CAJ.
6. Return the absolute date-folder link and confirmed local file links, plus blocked/failed items and reasons. Only count a file as saved when it has been verified in that folder. If the runtime cannot inspect the saved file, say “download initiated, file not verified.”
7. Do not upload full texts to GitHub, Zotero or another service unless separately requested. Zotero import is optional and requires available connector support; this package does not transfer authenticated browser cookies.

## Local destination — create first

- Unless the user specifies a destination, use the user's Downloads directory with
  `CNKI/YYYY-MM-DD/` beneath it (for example, `~/Downloads/CNKI/2026-09-11/`).
  Resolve the actual absolute path; do not pass a literal `~` to a browser API.
- Compute the date once at task start in the user's local timezone and create the
  folder before clicking Download. Reuse an existing same-date folder without
  clearing it. If the user supplies a base directory, create the date subfolder
  there; if they supply an exact final folder, respect it without double nesting.
- Use a documented per-download or per-session destination setting when available.
  Do not invent browser APIs or change global browser preferences. Site-specific permission changes follow ../downloads.md. If the browser
  only saves to its default directory, use the exact completed-download receipt
  to identify each task-owned file, then move it into the date folder and verify
  it there. Never sweep the Downloads directory or move unrelated files.
- Keep a useful title/author filename when possible, sanitize filesystem-invalid
  characters, and retain `.pdf` only for confirmed PDFs. Never overwrite an
  existing file: reuse a verified identical paper or append a unique suffix.
- If local filesystem access or download receipts are unavailable, report that
  limitation and the actual known save location; do not claim the requested
  folder was created or populated. Never substitute a cloud upload.

## Efficient execution and bounded waiting

- Reuse the authorized logged-in session, existing result list and already verified
  paper metadata. Do not repeat searches, reload the homepage or reopen a detail
  page for each retry when the current observed PDF control is still valid.
- For multiple requested papers, use sequential individual downloads by default. Only when the user requests native batching, use a verified PDF batch operation
  within the displayed limit. Otherwise use individual PDF controls, keeping a
  per-item receipt/status. Do not launch duplicate transfers while one is active,
  or add unbounded parallel requests that could trigger site throttling.
- Prefer documented completion events/receipts over fixed sleeps. Where polling
  is necessary, check the specific transfer at short bounded intervals (about
  2–5 seconds if supported), stop immediately on completion, and verify once.
  A changing byte count or transfer status is progress; a repeated screenshot is
  not. Do not repeatedly parse a partially downloaded file.
- If there is no observed progress for 60 seconds, inspect the current transfer
  and visible page once for a login, CAPTCHA, access or network error. Do not
  reclick an active download. Retry only a confirmed failed transfer, at most
  once; after a second failure without progress, report it and continue other
  accessible items. An active but stalled transfer should be reported as pending,
  not silently restarted or called complete.
- Continue waiting on a progressing transfer, keeping the user informed at least
  once per minute. Respect user-specified deadlines and runtime wait limits.
  Report site-side blockers honestly; these workflow rules do not guarantee
  faster CNKI network throughput.
