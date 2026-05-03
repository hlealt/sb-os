Ask the user which review they want to run:

| Option | Description |
|--------|-------------|
| **Week** | Weekly review |
| **Month** | Monthly review |
| **Quarter** | Quarterly review |

If context YAML provides `option.week.description`, `option.month.description`, or `option.quarter.description`, use those values instead of the English defaults above for the corresponding rows.

Present the options and wait for the user's choice. Then load and execute the corresponding workflow:

| Choice | File to read and execute |
|--------|--------------------------|
| Week | `weekly-review/weekly-review.md` (sibling of this file) |
| Month | `monthly-review.md` (sibling of this file) |
| Quarter | `quarterly-review.md` (sibling of this file) |

Resolve sibling paths relative to this orchestrator file's location inside the sb-os workflows directory.
