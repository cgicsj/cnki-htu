# 任务续跑与本地台账

Use for interrupted CNKI research, avoiding repeated downloads, and durable
screening/extraction output. The helper is offline Python 3.9+ standard library;
it does not access CNKI, purchase papers, handle logins or schedule background work.

Read [schema and command examples](../schema.md) before initializing or
updating a ledger. Resolve `scripts/workflow.py` relative to this installed skill.
Store research data in the user's chosen local task folder, outside a source repo.

- Initialize once with immutable query/criteria and requested stages. Import
  verified records; save every completed operation immediately. Existing task
  files are never overwritten. DOI/record ID duplicates are reused; title matches
  require review. Review any conflict before changing evidence.
- At resume, run `queue`: it verifies saved artifact paths and SHA-256 hashes,
  reports pending work and blockers, and excludes completed/skipped stages.
  `status` is only a summary; it does not verify files. Never call a task complete
  with unresolved required stages. Explain excluded/uncertain extraction status.
- Before an operation, claim an eligible pending stage with `mark --status running`.
  The atomic transaction rejects a second claim. Running entries remain running
  after a crash: inspect the browser/transfer/files before deciding whether to
  record a verified completion or explicitly reset to pending with a reason.
- A completed `download` or `citation` receipt can be explicitly reset with
  `reset --stage <stage> --reason <why>` when the artifact is valid but wrong
  (for example, a different paper was downloaded). This clears the old artifact
  receipt and records both stages in the event history. Evidence stages are
  updated with `screen`/`extract`, not `reset`.
- Failed/blocked entries do not auto-retry. After resolving the cause, reset that
  specific stage using `mark --status pending --reason ...`, then resume. Preserve
  bounded retry limits in download. Do not restart an active transfer.
- Complete screening/extraction only with their evidence-validating commands.
  Download/citation completion requires an existing nonempty artifact and explicit
  `--identity-verified`, only after the agent has checked file identity and content.
  The PDF header check is not a substitute for opening/parsing the PDF. This helper
  tracks PDF downloads; explicitly requested CAJ work remains with download
  and must not be labeled PDF-complete here.
- Export to a new directory: Excel, CSVs and a JSON audit snapshot. Export is a
  report, not evidence that all requested work succeeded. Preserve the SQLite
  task for actual resume; the JSON snapshot is for inspection, not re-import.

Do not store credentials/cookies. Never commit research ledgers, PDFs, task inputs,
or exported reports to the skills repository. No autonomous recurring runs are
created by this skill. A changed query or criteria requires a new task.
