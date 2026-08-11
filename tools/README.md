# tools

Small standalone scripts. Not part of the website.

## `todoist_export.py`

Pulls everything out of a Todoist account into a folder of JSON and CSV files,
including the things Todoist's own export leaves behind: completed-task
history, comments, filters, reminders, and file attachments.

```sh
export TODOIST_TOKEN='your-token-here'
python3 tools/todoist_export.py
```

The token comes from Todoist: **Settings → Integrations → Developer → API
token**. It grants full access to the account, so keep it out of chat windows,
commits, and shared documents. Prefer the environment variable over `--token`,
which leaves the token in your shell history.

The script only reads. It never creates, edits, or deletes anything in Todoist.

Needs Python 3.8+ and nothing else — no `pip install` step.

### Output

```
todoist-export-20260811-142530/
    json/          raw API responses — the authoritative copy
    csv/           flattened, spreadsheet-friendly versions
      tasks-active.csv, tasks-completed.csv, projects.csv,
      sections.csv, labels.csv, comments.csv, attachments.csv
      projects/    one file per project
    attachments/   every file attached to a task or comment
    MANIFEST.json  counts, account details, and anything that failed
```

### Options

| Flag | Effect |
| --- | --- |
| `--out DIR` | Write somewhere specific instead of a timestamped folder |
| `--since YYYY-MM-DD` | Earliest completion date to fetch (default: account creation) |
| `--no-completed` | Skip completed-task history (much faster) |
| `--no-attachments` | Record attachments in the index but don't download them |
| `--sleep N` | Pause N seconds between requests if you hit rate limits |
| `--quiet` | Suppress progress output |

Completed tasks are fetched in three-month windows walking backwards, because
that is the largest range the API accepts per request. A decade of history is
roughly 40 requests, so it takes a minute or two.

### Known limits

- **These CSVs are not in Todoist's import format.** They are for reading and
  searching. To move a project into another Todoist account, use Todoist's own
  per-project *Export as CSV* instead.
- **Tasks inside archived projects usually aren't readable over the API.** If
  `tasks_in_archived_projects` is 0 in the manifest but you know those projects
  had tasks, unarchive them in the app and re-run.
- Nothing failed silently: every error is recorded in `MANIFEST.json` with the
  step that produced it.
