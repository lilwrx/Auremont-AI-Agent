#!/usr/bin/env python3
"""Extract user prompts for this repository from local Claude Code transcripts.

Claude Code writes a transcript for each session to
    ~/.claude/projects/<path-slug>/<session-id>.jsonl
where every line is a JSON record. The prompt the user actually typed lives in
the `type == "user"` record, under `message.content[*].type == "text"`.

Why is this script needed when there's already a `log_hook.py` hook?
  - The hook only fires at the moment of typing, and only when Claude Code is opened
    in a directory that has `.claude/settings.json`. Opening a parent directory by
    mistake loses the whole session.
  - This script scans transcripts on disk instead, so it can recover sessions the
    hook missed — the same way `log_codex.py` and `log_antigravity.py` do for
    Codex and Antigravity.
Both write paths de-duplicate against each other via `entry_id`, so running both is safe.

Usage:
  python scripts/log_claude.py --auto            # default: last 24h
  python scripts/log_claude.py --hours 72
  python scripts/log_claude.py --all             # every session, no time limit
  python scripts/log_claude.py --dry-run         # preview only, no write

Env overrides:
  CLAUDE_PROJECTS_DIR   point to a different projects/ directory
  AI_LOG_DIR            where session.jsonl is written (default: .ai-log)
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

VN_TZ = timezone(timedelta(hours=7))
CLAUDE_PROJECTS = Path(
    os.environ.get("CLAUDE_PROJECTS_DIR", Path.home() / ".claude" / "projects")
)

SECRET_PATTERNS = (
    re.compile(r"\bAIza[\w-]{20,}\b"),
    re.compile(r"\bAQ\.[\w-]{20,}\b"),
    re.compile(r"(?i)\b(bearer\s+)[\w.-]{16,}"),
    re.compile(r"(?i)\b(api[ _-]?key|token|secret|password)\s*([=:])\s*\S+"),
)

_INJECTED_BLOCKS = re.compile(
    r"<(ide_opened_file|ide_selection|system-reminder|command-name|command-message|"
    r"command-args|local-command-stdout)>.*?</\1>",
    re.DOTALL,
)


def git(command: str) -> str:
    try:
        return subprocess.check_output(command.split(), text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def normalize(path: str) -> str:
    return path.strip().lower().replace("/", "\\").rstrip("\\")


def matches_repo(session_cwd: str, repo_root: str) -> bool:
    """A session belongs to this repo when its cwd matches, is nested inside, or is a parent of the repo.

    The "parent directory" branch matters: opening Claude Code in an enclosing directory
    and then working inside a sub-repo is a common scenario, and it's exactly when the
    hook doesn't fire — which is why this script needs to recover it.
    """
    session_cwd, repo_root = normalize(session_cwd), normalize(repo_root)
    return bool(
        session_cwd
        and repo_root
        and (
            session_cwd == repo_root
            or session_cwd.startswith(repo_root + "\\")
            or repo_root.startswith(session_cwd + "\\")
        )
    )


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def logged_ids(log_dir: Path) -> set[str]:
    result: set[str] = set()
    files = [log_dir / "session.jsonl"]
    archive_dir = log_dir / "archive"
    if archive_dir.is_dir():
        files.extend(archive_dir.glob("*.jsonl"))
    files.extend(log_dir.glob("session.pending.*.jsonl"))
    for log_file in files:
        if not log_file.exists():
            continue
        for line in log_file.read_text(encoding="utf-8-sig").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("entry_id"):
                result.add(entry["entry_id"])
    return result


def parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def user_text(content) -> str:
    """Join the text fragments of a user turn, dropping tool_result and IDE-injected blocks."""
    if not isinstance(content, list):
        return ""
    parts = []
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        cleaned = _INJECTED_BLOCKS.sub("", item.get("text", "")).strip()
        if cleaned:
            parts.append(cleaned)
    return "\n".join(parts).strip()


def iter_prompts(repo_root: str, cutoff: datetime | None):
    if not CLAUDE_PROJECTS.exists():
        return
    for transcript in CLAUDE_PROJECTS.rglob("*.jsonl"):
        try:
            lines = transcript.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue

        records = []
        session_cwd = ""
        session_id = transcript.stem
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            records.append(record)
            if not session_cwd and record.get("cwd"):
                session_cwd = record["cwd"]
            if record.get("sessionId"):
                session_id = record["sessionId"]

        if not matches_repo(session_cwd, repo_root):
            continue

        for record in records:
            if record.get("type") != "user":
                continue
            message = record.get("message") or {}
            timestamp = record.get("timestamp", "")
            moment = parse_timestamp(timestamp)
            if cutoff and moment and moment < cutoff:
                continue
            text = user_text(message.get("content"))
            uuid = record.get("uuid", "")
            if len(text) < 2 or not uuid:
                continue
            yield session_id, uuid, timestamp, redact(text)


def main() -> None:
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Collect Claude Code user prompts")
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    log_dir = Path(os.environ.get("AI_LOG_DIR", ".ai-log"))
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "session.jsonl"
    seen = logged_ids(log_dir)
    cutoff = None if args.all else datetime.now(timezone.utc) - timedelta(hours=args.hours)
    repo_root = str(Path.cwd())
    repo = git("git remote get-url origin").split("/")[-1].removesuffix(".git") or Path.cwd().name
    branch = git("git rev-parse --abbrev-ref HEAD")
    commit = git("git rev-parse --short HEAD")
    student = git("git config user.email") or os.environ.get("USERNAME", "unknown")

    entries = []
    for session_id, uuid, timestamp, prompt in iter_prompts(repo_root, cutoff):
        entry_id = f"claude-{session_id}-{uuid}"
        if entry_id in seen:
            continue
        seen.add(entry_id)
        moment = parse_timestamp(timestamp)
        entries.append(
            {
                "ts": (moment.astimezone(VN_TZ).isoformat() if moment else datetime.now(VN_TZ).isoformat()),
                "tool": "claude-code",
                "event": "UserPrompt",
                "entry_id": entry_id,
                "session_id": session_id,
                "model": "claude-code",
                "repo": repo,
                "branch": branch,
                "commit": commit,
                "student": student,
                "prompt": prompt[:1000],
                "response_summary": "",
            }
        )

    entries.sort(key=lambda entry: entry["ts"])

    if args.dry_run:
        print(f"[claude-log] Would log {len(entries)} prompt(s).", file=sys.stderr)
        for entry in entries:
            preview = entry["prompt"].replace("\n", " ")[:100]
            print(f"  {entry['ts']}  {preview}", file=sys.stderr)
        return
    if not entries:
        print("[claude-log] No new prompts.", file=sys.stderr)
        return
    with log_file.open("a", encoding="utf-8") as output:
        for entry in entries:
            output.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"[claude-log] Logged {len(entries)} prompt(s).", file=sys.stderr)


if __name__ == "__main__":
    main()
