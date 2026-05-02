<!--
sb-os managed file — installs to `{vault}/Home.md`.

Content INSIDE `<!-- sb:start v=1 -->` ... `<!-- sb:end -->` is overwritten
on `python install.py --upgrade`. Edit it in the sb-os source repo.

Content OUTSIDE the markers is yours — add a personal welcome message,
custom widgets, links, or any home-page content. It is preserved verbatim
on `--upgrade`.

Plugin requirements (soft, recommended — install via Community Plugins):
  - Dataview — powers the dynamic queries below
  - Tasks    — date parsing for 📅 (due), ✅ (done), 🔁 (recurrence) emoji

If either plugin is missing, the corresponding query block renders as its
literal source text and a static "missing plugin" notice appears beside it.
-->

<!-- sb:start v=1 -->
# Home

Vault dashboard. Inline queries aggregate vault state via Dataview + Tasks. Install both plugins for the full experience; missing-plugin notices replace each query block when its plugin is unavailable.

---

## Periodic Notes

```dataviewjs
// Periodic notes navigation — links to today's daily and this week's weekly note.
// Path convention: `0-periodic-notes/daily/YYYY-MM-DD.md` and
// `0-periodic-notes/weekly/YYYY-Www.md`. Adjust if your convention differs.
const today = dv.date("today");
const yyyy = today.year;
const mm = String(today.month).padStart(2, "0");
const dd = String(today.day).padStart(2, "0");
const ww = String(today.weekNumber).padStart(2, "0");
const dailyPath = `0-periodic-notes/daily/${yyyy}-${mm}-${dd}`;
const weeklyPath = `0-periodic-notes/weekly/${yyyy}-W${ww}`;
dv.paragraph(`**Today:** [[${dailyPath}]]  ·  **This week:** [[${weeklyPath}]]`);
```

> [!info] Missing Dataview?
> Install the **Dataview** plugin (Community Plugins) to render this block. Without it, the code above shows as literal text.

---

## Today

Tasks due today, plus any unchecked recurring tasks.

```tasks
not done
(due today) OR (no due date AND recurring)
sort by priority
sort by due
```

> [!info] Missing Tasks plugin?
> Install the **Tasks** plugin to render this block. Until then, this section will display as literal code.

---

## This Week

Tasks due in the next 7 days.

```tasks
not done
due after yesterday
due before in 8 days
sort by due
sort by priority
group by due
```

---

## Active Projects

Folders under `1-projects/` with one-line descriptions pulled from each project's index file (if present).

```dataview
TABLE WITHOUT ID
  file.link AS "Project",
  description AS "Description"
FROM "1-projects"
WHERE file.name = file.folder
SORT file.name ASC
```

---

## Recent Notes

Files modified in the last 7 days, across the vault.

```dataview
TABLE WITHOUT ID
  file.link AS "Note",
  dateformat(file.mtime, "yyyy-MM-dd HH:mm") AS "Modified"
FROM "" 
WHERE file.mtime >= date(today) - dur(7 days)
  AND !contains(file.path, "4-archives")
SORT file.mtime DESC
LIMIT 20
```

---

## Backlog (No Date)

Open tasks across the vault that have no due date.

```tasks
not done
no due date
sort by priority
group by filename
limit 30
```

<!-- sb:end -->

<!-- =====================================================================
     User content below this line is preserved on `--upgrade`. Add a
     welcome message, custom widgets, dashboards, or any personal links.
     ===================================================================== -->

<!-- Add your own content below — anything outside the sb:start/sb:end markers survives --upgrade. -->
