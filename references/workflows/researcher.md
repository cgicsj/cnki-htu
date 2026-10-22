# CNKI research workflow

Read the internal workflow reference before its stage. These are parts of the single cnki-htu skill, not separately installed skills or subagents.

1. State the database, query/fields, period, sort, requested count and citation scope.
   Default to Chinese journal articles. For “since 2023” use 2023-01-01 through today.
2. Use search or advanced-search, navigate-pages and parse-results.
   Freeze a unique, source-linked result list before screening; retain site rank.
3. Select the requested subset based on title/abstract relevance to the question.
   Explain selection and retain original list numbers. Do not substitute newer or
   better-known papers outside the list without clearly reporting the change.
4. Use paper-detail. Full-text analysis requires retrieved readable full text;
   otherwise label abstract/preview analysis and identify missing evidence.
   When downloads are requested, use download with PDF as the default.
   Create the local Downloads/CNKI/YYYY-MM-DD folder first (user's local date;
   respect a supplied destination), then save and verify files there. Reuse the
   current session and follow download's bounded progress-based waiting.
   Preserve an explicit user format choice; otherwise do not substitute CAJ
   when PDF is unavailable. Continue accessible items and report the shortfall.
5. Use export for the requested citation set. If “export the citations” is
   unspecified, export the listed set and a separate selected-subset file.
6. Before delivery compare all titles/identifiers against extracted records,
   ensure no duplicate filler entries, and verify exported counts and file paths.
7. Return the search manifest, result list, reading analysis, .bib artifact and
   any limitations. Never claim a blocked stage completed.

## Durable screening, comparison and resume

When the user requests screening tables, empirical comparisons, or resumable work,
use resume from task start and save each verified result immediately. Use
screening for criterion-linked include/exclude/uncertain decisions, and
evidence-table for per-field evidence with page/section locators. Follow their
shared schema; use one task file through these stages. Existing local readable
papers can be analyzed without downloading again. All workflow references are bundled inside cnki-htu.

On continuation, read the existing queue before any web action. Reuse completed
records and verified files; inspect running transfers before retry. Preserve the
original query/criteria and selection scope. Export the workbook even if access
blocks some records, while explicitly reporting unfinished work and abstract-only
analysis. Do not claim structural evidence validation proves scholarly accuracy.

When Zotero is requested, route to [Zotero push](../zotero.md). Preserve metadata and attachment completion separately. Only include artifacts the user requested in the final delivery.
