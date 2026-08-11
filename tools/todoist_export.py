#!/usr/bin/env python3
"""Export everything from a Todoist account to JSON + CSV.

Quick start:

    export TODOIST_TOKEN='your-token-here'
    python3 tools/todoist_export.py

Get the token from Todoist: Settings -> Integrations -> Developer -> API token.
Treat it like a password. It grants full read/write access to the account, so
don't paste it into a chat window, a commit, or a shared document.

The script only reads. It never creates, edits, or deletes anything in Todoist.

Output is a single timestamped directory:

    todoist-export-20260811-142530/
        json/          raw API responses - the authoritative copy
        csv/           flattened, spreadsheet-friendly versions
        attachments/   every file attached to a task or comment
        MANIFEST.json  what was captured, what failed, and why

Requires Python 3.8 or newer. No third-party packages.
"""

from __future__ import annotations

import argparse
import csv
import getpass
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.todoist.com/api/v1"
LEGACY_SYNC = "https://api.todoist.com/sync/v9"
USER_AGENT = "todoist-export/1.0 (personal data export)"

# The completed-by-completion-date endpoint only accepts a three-month window
# per request, so history is walked backwards in chunks this size.
COMPLETED_WINDOW_DAYS = 89

# Oldest date to reach back to if the account's join date can't be determined.
# Todoist launched in 2007, so nothing predates this.
EPOCH_FALLBACK = "2007-01-01"


class ApiError(Exception):
    def __init__(self, status, url, body):
        self.status = status
        self.url = url
        self.body = body
        super().__init__(f"HTTP {status} for {url}: {body[:300]}")


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


class Client:
    """Minimal Todoist API client with retry and rate-limit handling."""

    def __init__(self, token, sleep=0.0, verbose=True):
        self.token = token
        self.sleep = sleep
        self.verbose = verbose
        self.requests_made = 0

    def log(self, msg):
        if self.verbose:
            print(msg, flush=True)

    def _raw(self, method, url, form=None, timeout=60, max_retries=5):
        """Return (status, body_bytes). Raises only on network failure."""
        headers = {"Authorization": f"Bearer {self.token}", "User-Agent": USER_AGENT}
        body = None
        if form is not None:
            body = urllib.parse.urlencode(form, doseq=True).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        last_error = None
        for attempt in range(max_retries):
            request = urllib.request.Request(
                url, data=body, headers=headers, method=method
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    self.requests_made += 1
                    if self.sleep:
                        time.sleep(self.sleep)
                    return response.status, response.read()
            except urllib.error.HTTPError as exc:
                payload = exc.read()
                self.requests_made += 1
                if exc.code == 429:
                    retry_after = exc.headers.get("Retry-After")
                    try:
                        wait = float(retry_after)
                    except (TypeError, ValueError):
                        wait = 2 ** attempt
                    wait = max(wait, 1.0)
                    self.log(f"    rate limited, waiting {wait:.0f}s")
                    time.sleep(wait)
                    continue
                if 500 <= exc.code < 600 and attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return exc.code, payload
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise
        if last_error:
            raise last_error
        raise ApiError(429, url, b"gave up after repeated rate limiting")

    def get(self, path, params=None):
        url = f"{API}/{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        status, body = self._raw("GET", url)
        if status != 200:
            raise ApiError(status, url, body.decode("utf-8", "replace"))
        return json.loads(body.decode("utf-8"))

    def post(self, url, form):
        status, body = self._raw("POST", url, form=form)
        if status != 200:
            raise ApiError(status, url, body.decode("utf-8", "replace"))
        return json.loads(body.decode("utf-8"))

    def paginate(self, path, params=None):
        """Follow next_cursor until exhausted, returning every item."""
        params = dict(params or {})
        params.setdefault("limit", 200)
        collected = []
        cursor = None
        while True:
            page_params = dict(params)
            if cursor:
                page_params["cursor"] = cursor
            page = self.get(path, page_params)
            if isinstance(page, list):
                # Some endpoints return a bare list rather than an envelope.
                collected.extend(page)
                break
            # Active resources use "results"; completed tasks use "items".
            items = page.get("results")
            if items is None:
                items = page.get("items")
            if items is None:
                items = []
            collected.extend(items)
            cursor = page.get("next_cursor")
            if not cursor:
                break
        return collected

    def download(self, url, dest, timeout=120):
        headers = {"Authorization": f"Bearer {self.token}", "User-Agent": USER_AGENT}
        request = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            with open(dest, "wb") as handle:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    handle.write(chunk)
        return os.path.getsize(dest)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def flatten(obj, prefix=""):
    """Turn nested JSON into a single-level dict with dotted keys."""
    out = {}
    key = prefix.rstrip(".")
    if isinstance(obj, dict):
        if not obj:
            out[key] = ""
        for name, value in obj.items():
            out.update(flatten(value, f"{prefix}{name}."))
    elif isinstance(obj, list):
        if not obj:
            out[key] = ""
        elif all(not isinstance(item, (dict, list)) for item in obj):
            out[key] = "; ".join("" if i is None else str(i) for i in obj)
        else:
            for index, value in enumerate(obj):
                out.update(flatten(value, f"{prefix}{index}."))
    elif obj is None:
        out[key] = ""
    elif isinstance(obj, bool):
        out[key] = "true" if obj else "false"
    else:
        out[key] = obj
    return out


def write_csv(path, rows, first_columns=()):
    """Write rows (list of dicts) to CSV, using the union of all keys."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    flat = [flatten(row) for row in rows]
    columns = []
    for name in first_columns:
        if any(name in row for row in flat):
            columns.append(name)
    for row in flat:
        for name in row:
            if name not in columns:
                columns.append(name)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in flat:
            writer.writerow(row)
    return path


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False, sort_keys=True)
    return path


def slugify(text, limit=60):
    text = (text or "untitled").strip()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    return (text[:limit] or "untitled").lower()


def parse_date(value):
    """Parse YYYY-MM-DD or a full ISO timestamp into an aware UTC datetime."""
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    for candidate in (text, text[:10]):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


# --------------------------------------------------------------------------
# Fetchers
# --------------------------------------------------------------------------


def fetch_sync(client, errors):
    """One call that returns nearly all active data, including comments.

    The REST endpoints below cover the same ground, but the sync snapshot also
    carries filters, reminders, collaborators, and account settings that have
    no REST equivalent, so it is worth keeping as the belt-and-braces copy.
    """
    client.log("  full sync snapshot")
    try:
        return client.post(
            f"{API}/sync",
            {"sync_token": "*", "resource_types": json.dumps(["all"])},
        )
    except (ApiError, OSError) as exc:
        errors.append({"step": "sync", "error": str(exc)})
        client.log(f"    could not fetch sync snapshot: {exc}")
        return None


def fetch_completed(client, since, until, errors):
    """Walk completed tasks backwards in three-month windows."""
    collected = []
    seen = set()
    # The API has accepted both a bare ISO timestamp and a Z-suffixed one over
    # the years. Try the Z form, and fall back on the first rejection.
    date_formats = ["%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"]
    window_end = until
    while window_end > since:
        window_start = max(since, window_end - timedelta(days=COMPLETED_WINDOW_DAYS))
        page = None
        for index, fmt in enumerate(list(date_formats)):
            params = {
                "since": window_start.strftime(fmt),
                "until": window_end.strftime(fmt),
                "limit": 200,
            }
            try:
                page = client.paginate("tasks/completed/by_completion_date", params)
            except ApiError as exc:
                if exc.status == 400 and index + 1 < len(date_formats):
                    # Wrong date format - promote the other one and retry.
                    date_formats.reverse()
                    continue
                errors.append(
                    {
                        "step": "completed_tasks",
                        "window": f"{window_start.date()}..{window_end.date()}",
                        "error": str(exc),
                    }
                )
                client.log(f"    {window_start.date()}..{window_end.date()}: {exc}")
                page = []
            break

        new = 0
        for task in page or []:
            task_id = task.get("id") or task.get("task_id")
            marker = task_id or json.dumps(task, sort_keys=True)
            if marker in seen:
                continue
            seen.add(marker)
            collected.append(task)
            new += 1
        client.log(f"    {window_start.date()} .. {window_end.date()}: {new} tasks")
        window_end = window_start - timedelta(seconds=1)
    return collected


def fetch_archived_projects(client, active_ids, errors):
    """Archived projects have moved around between API versions.

    Try the known locations and report honestly if none of them answer. Only
    dedicated paths are probed - a filter like ?is_archived=true is no good,
    because an API that ignores the unknown parameter hands back the active
    project list, which would then be filed as archived.
    """
    attempts = [
        ("GET", f"{API}/projects/archived", None),
        ("POST", f"{LEGACY_SYNC}/projects/get_archived", {}),
    ]
    for method, url, form in attempts:
        try:
            status, body = client._raw(method, url, form=form)
        except OSError as exc:
            errors.append({"step": "archived_projects", "url": url, "error": str(exc)})
            continue
        if status != 200:
            continue
        try:
            data = json.loads(body.decode("utf-8"))
        except ValueError:
            continue
        if isinstance(data, dict):
            data = data.get("results") or data.get("projects") or data.get("items") or []
        if not isinstance(data, list):
            continue
        # Belt and braces: never let an active project through as archived.
        archived = [p for p in data if p.get("id") not in active_ids]
        client.log(f"    found {len(archived)} archived project(s) via {url}")
        return archived, url
    client.log("    no archived-project endpoint responded (see MANIFEST.json)")
    return [], None


def fetch_comments_via_rest(client, projects, tasks, errors):
    """Fallback when the sync snapshot is unavailable.

    Comments are only addressable per project or per task, so this is one
    request per object. It is slow but complete.
    """
    comments = []
    seen = set()
    targets = [("project_id", p.get("id")) for p in projects]
    targets += [("task_id", t.get("id")) for t in tasks]
    total = len(targets)
    for index, (key, value) in enumerate(targets, 1):
        if not value:
            continue
        if index % 50 == 0:
            client.log(f"    comments {index}/{total}")
        try:
            for comment in client.paginate("comments", {key: value}):
                marker = comment.get("id") or json.dumps(comment, sort_keys=True)
                if marker not in seen:
                    seen.add(marker)
                    comments.append(comment)
        except ApiError as exc:
            errors.append({"step": "comments", key: value, "error": str(exc)})
    return comments


def collect_attachments(*blobs):
    """Find every file_url anywhere in the captured data."""
    found = {}

    def walk(node):
        if isinstance(node, dict):
            url = node.get("file_url")
            if isinstance(url, str) and url.startswith("http"):
                found.setdefault(
                    url,
                    {
                        "file_url": url,
                        "file_name": node.get("file_name") or "",
                        "file_type": node.get("file_type") or "",
                        "file_size": node.get("file_size") or "",
                    },
                )
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for blob in blobs:
        walk(blob)
    return list(found.values())


def download_attachments(client, attachments, out_dir, errors):
    os.makedirs(out_dir, exist_ok=True)
    index = []
    used = set()
    for number, item in enumerate(attachments, 1):
        name = item.get("file_name") or ""
        stem, ext = os.path.splitext(name)
        if not ext:
            ext = os.path.splitext(urllib.parse.urlparse(item["file_url"]).path)[1]
        filename = f"{number:04d}-{slugify(stem)}{ext}"
        while filename in used:
            number += 1
            filename = f"{number:04d}-{slugify(stem)}{ext}"
        used.add(filename)
        dest = os.path.join(out_dir, filename)
        record = dict(item)
        record["saved_as"] = filename
        try:
            record["bytes_downloaded"] = client.download(item["file_url"], dest)
            record["status"] = "ok"
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
            record["status"] = f"failed: {exc}"
            record["bytes_downloaded"] = 0
            errors.append(
                {"step": "attachment", "file_url": item["file_url"], "error": str(exc)}
            )
            if os.path.exists(dest):
                os.remove(dest)
        index.append(record)
        if number % 10 == 0:
            client.log(f"    {number}/{len(attachments)} attachments")
    return index


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Export everything from a Todoist account to JSON and CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "The token is read from the TODOIST_TOKEN environment variable, or "
            "prompted for if unset. Passing it with --token puts it in your "
            "shell history, so prefer the environment variable."
        ),
    )
    parser.add_argument("--token", help="Todoist API token (prefer TODOIST_TOKEN)")
    parser.add_argument("--out", help="Output directory (default: timestamped)")
    parser.add_argument(
        "--since",
        help=f"Earliest completion date to fetch, YYYY-MM-DD "
        f"(default: account creation date, else {EPOCH_FALLBACK})",
    )
    parser.add_argument(
        "--no-attachments", action="store_true", help="Skip downloading attached files"
    )
    parser.add_argument(
        "--no-completed", action="store_true", help="Skip completed-task history"
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Seconds to pause between requests (default: 0)",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output")
    args = parser.parse_args(argv)

    token = args.token or os.environ.get("TODOIST_TOKEN")
    if not token:
        try:
            token = getpass.getpass("Todoist API token: ")
        except (EOFError, KeyboardInterrupt):
            print("\nNo token supplied.", file=sys.stderr)
            return 2
    token = token.strip()
    if not token:
        print("No token supplied.", file=sys.stderr)
        return 2

    started = datetime.now(timezone.utc)
    out_dir = args.out or started.strftime("todoist-export-%Y%m%d-%H%M%S")
    out_dir = os.path.abspath(out_dir)
    json_dir = os.path.join(out_dir, "json")
    csv_dir = os.path.join(out_dir, "csv")
    os.makedirs(out_dir, exist_ok=True)

    client = Client(token, sleep=args.sleep, verbose=not args.quiet)
    errors = []
    counts = {}

    client.log(f"Exporting to {out_dir}")

    # --- account -----------------------------------------------------------
    client.log("Account")
    sync = fetch_sync(client, errors)
    if sync:
        write_json(os.path.join(json_dir, "sync-full.json"), sync)
    user = (sync or {}).get("user") or {}

    # --- active data -------------------------------------------------------
    client.log("Active data")
    resources = {}
    for name, path in (
        ("projects", "projects"),
        ("sections", "sections"),
        ("tasks", "tasks"),
        ("labels", "labels"),
    ):
        try:
            resources[name] = client.paginate(path)
            client.log(f"  {name}: {len(resources[name])}")
        except (ApiError, OSError) as exc:
            resources[name] = (sync or {}).get(
                {"tasks": "items"}.get(name, name)
            ) or []
            errors.append({"step": name, "error": str(exc)})
            client.log(f"  {name}: failed ({exc}); fell back to sync copy")
        write_json(os.path.join(json_dir, f"{name}.json"), resources[name])

    projects = resources["projects"]
    sections = resources["sections"]
    active_tasks = resources["tasks"]
    labels = resources["labels"]

    # --- archived projects -------------------------------------------------
    client.log("Archived projects")
    active_ids = {p.get("id") for p in projects}
    archived, archived_source = fetch_archived_projects(client, active_ids, errors)
    write_json(os.path.join(json_dir, "projects-archived.json"), archived)

    archived_tasks = []
    for project in archived:
        project_id = project.get("id")
        if not project_id:
            continue
        try:
            archived_tasks.extend(client.paginate("tasks", {"project_id": project_id}))
        except (ApiError, OSError) as exc:
            errors.append(
                {"step": "archived_tasks", "project_id": project_id, "error": str(exc)}
            )
    if archived:
        client.log(f"    {len(archived_tasks)} task(s) readable in archived projects")
    write_json(os.path.join(json_dir, "tasks-archived-projects.json"), archived_tasks)

    # --- comments ----------------------------------------------------------
    client.log("Comments")
    if sync is not None:
        comments = list(sync.get("notes") or [])
        project_comments = list(sync.get("project_notes") or [])
        client.log(
            f"  {len(comments)} task comment(s), "
            f"{len(project_comments)} project comment(s) from sync"
        )
    else:
        client.log("  sync unavailable, falling back to per-object requests")
        comments = fetch_comments_via_rest(client, projects, active_tasks, errors)
        project_comments = []
        client.log(f"  {len(comments)} comment(s)")
    write_json(os.path.join(json_dir, "comments.json"), comments)
    write_json(os.path.join(json_dir, "comments-project.json"), project_comments)

    # --- completed tasks ---------------------------------------------------
    completed = []
    if args.no_completed:
        client.log("Completed tasks: skipped (--no-completed)")
    else:
        client.log("Completed tasks")
        since = parse_date(args.since)
        if since is None:
            since = parse_date(
                user.get("joined_at") or user.get("join_date") or EPOCH_FALLBACK
            )
        if since is None:
            since = parse_date(EPOCH_FALLBACK)
        until = datetime.now(timezone.utc) + timedelta(days=1)
        client.log(f"  walking back to {since.date()}")
        completed = fetch_completed(client, since, until, errors)
        client.log(f"  {len(completed)} completed task(s)")
    write_json(os.path.join(json_dir, "tasks-completed.json"), completed)

    # --- CSV ---------------------------------------------------------------
    client.log("Writing CSV")
    project_names = {p.get("id"): p.get("name", "") for p in projects}
    project_names.update({p.get("id"): p.get("name", "") for p in archived})
    section_names = {s.get("id"): s.get("name", "") for s in sections}

    def decorate(task):
        row = dict(task)
        row["project_name"] = project_names.get(task.get("project_id"), "")
        row["section_name"] = section_names.get(task.get("section_id"), "")
        return row

    task_columns = (
        "project_name",
        "section_name",
        "content",
        "description",
        "priority",
        "due.date",
        "due.string",
        "deadline.date",
        "labels",
        "completed_at",
        "added_at",
        "id",
        "project_id",
        "section_id",
        "parent_id",
        "url",
    )

    active_rows = [decorate(t) for t in active_tasks]
    archived_rows = [decorate(t) for t in archived_tasks]
    completed_rows = [decorate(t) for t in completed]

    write_csv(os.path.join(csv_dir, "tasks-active.csv"), active_rows, task_columns)
    write_csv(
        os.path.join(csv_dir, "tasks-completed.csv"), completed_rows, task_columns
    )
    write_csv(
        os.path.join(csv_dir, "tasks-archived-projects.csv"),
        archived_rows,
        task_columns,
    )
    write_csv(
        os.path.join(csv_dir, "projects.csv"),
        projects + archived,
        ("name", "id", "parent_id", "is_archived", "color", "view_style", "url"),
    )
    write_csv(os.path.join(csv_dir, "sections.csv"), sections, ("name", "project_id", "id"))
    write_csv(os.path.join(csv_dir, "labels.csv"), labels, ("name", "id", "color", "order"))
    write_csv(
        os.path.join(csv_dir, "comments.csv"),
        comments + project_comments,
        ("posted_at", "content", "task_id", "item_id", "project_id", "id"),
    )

    # One file per project, mirroring Todoist's own export layout.
    by_project = {}
    for row in active_rows + completed_rows + archived_rows:
        by_project.setdefault(row.get("project_id"), []).append(row)
    for project_id, rows in by_project.items():
        name = project_names.get(project_id) or "no-project"
        filename = f"{slugify(name)}-{project_id}.csv"
        write_csv(os.path.join(csv_dir, "projects", filename), rows, task_columns)

    # --- attachments -------------------------------------------------------
    attachment_index = []
    attachments = collect_attachments(
        sync, comments, project_comments, active_tasks, completed, archived_tasks
    )
    if args.no_attachments:
        client.log(f"Attachments: {len(attachments)} found, skipped (--no-attachments)")
    elif attachments:
        client.log(f"Attachments: downloading {len(attachments)}")
        attachment_index = download_attachments(
            client, attachments, os.path.join(out_dir, "attachments"), errors
        )
        ok = sum(1 for a in attachment_index if a.get("status") == "ok")
        client.log(f"  {ok}/{len(attachment_index)} downloaded")
    else:
        client.log("Attachments: none found")
    if attachments:
        write_csv(
            os.path.join(csv_dir, "attachments.csv"),
            attachment_index or attachments,
            ("file_name", "saved_as", "status", "file_type", "file_size", "file_url"),
        )

    # --- manifest ----------------------------------------------------------
    counts = {
        "projects_active": len(projects),
        "projects_archived": len(archived),
        "sections": len(sections),
        "labels": len(labels),
        "tasks_active": len(active_tasks),
        "tasks_completed": len(completed),
        "tasks_in_archived_projects": len(archived_tasks),
        "comments_task": len(comments),
        "comments_project": len(project_comments),
        "attachments_found": len(attachments),
        "attachments_downloaded": sum(
            1 for a in attachment_index if a.get("status") == "ok"
        ),
    }
    finished = datetime.now(timezone.utc)
    manifest = {
        "exported_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_seconds": round((finished - started).total_seconds(), 1),
        "api_base": API,
        "api_requests": client.requests_made,
        "account": {
            "email": user.get("email", ""),
            "full_name": user.get("full_name", ""),
            "id": user.get("id", ""),
            "joined_at": user.get("joined_at", ""),
            "premium_status": user.get("premium_status", ""),
        },
        "counts": counts,
        "archived_projects_source": archived_source,
        "sync_snapshot_captured": sync is not None,
        "errors": errors,
        "notes": [
            "json/ is the authoritative copy; csv/ is a flattened convenience view.",
            "These CSVs are readable but are NOT in Todoist's own import format. "
            "To move projects into another Todoist account, use Todoist's built-in "
            "per-project 'Export as CSV' instead.",
            "Tasks inside archived projects are often not readable over the API. "
            "If tasks_in_archived_projects is 0 but you know those projects had "
            "tasks, unarchive them in the app and re-run this script.",
        ],
    }
    write_json(os.path.join(out_dir, "MANIFEST.json"), manifest)

    client.log("")
    client.log(f"Done in {manifest['duration_seconds']}s, "
               f"{client.requests_made} API requests")
    for key, value in counts.items():
        client.log(f"  {key:<30} {value}")
    if errors:
        client.log(f"\n{len(errors)} problem(s) recorded in MANIFEST.json")
    client.log(f"\nExport written to {out_dir}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
