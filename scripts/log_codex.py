#!/usr/bin/env python3
"""Extract user prompts for this repository from local Codex rollout files."""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

VN_TZ = timezone(timedelta(hours=7))
CODEX_SESSIONS = Path.home() / ".codex" / "sessions"
SECRET_PATTERNS = (
    re.compile(r"\bAIza[\w-]{20,}\b"),
    re.compile(r"\bAQ\.[\w-]{20,}\b"),
    re.compile(r"(?i)\b(bearer\s+)[\w.-]{16,}"),
    re.compile(r"(?i)\b(api[ _-]?key|token|secret|password)\s*([=:])\s*\S+"),
)


def git(command: str) -> str:
    try:
        return subprocess.check_output(
            command.split(), text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return ""


def normalize(path: str) -> str:
    return path.strip().lower().replace("/", "\\").rstrip("\\")


def matches_repo(session_cwd: str, repo_root: str) -> bool:
    session_cwd, repo_root = normalize(session_cwd), normalize(repo_root)
    return bool(session_cwd and repo_root and (
        session_cwd == repo_root
        or session_cwd.startswith(repo_root + "\\")
        or repo_root.startswith(session_cwd + "\\")
    ))


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
    for log_file in files:
        if not log_file.exists():
            continue
        for line in log_file.read_text(encoding="utf-8-sig").splitlines():
            try:
                entry = json.loads(line)
                if entry.get("entry_id"):
                    result.add(entry["entry_id"])
            except json.JSONDecodeError:
                continue
    return result


def parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def user_text(content) -> str:
    if not isinstance(content, list):
        return ""
    return "\n".join(
        item.get("text", "").strip()
        for item in content
        if isinstance(item, dict) and item.get("type") == "input_text"
    ).strip()


def iter_prompts(repo_root: str, cutoff: datetime | None):
    if not CODEX_SESSIONS.exists():
        return
    for rollout in CODEX_SESSIONS.rglob("rollout-*.jsonl"):
        session_cwd = ""
        session_id = rollout.stem
        try:
            lines = rollout.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = record.get("payload") or {}
            if record.get("type") == "session_meta":
                session_cwd = payload.get("cwd", session_cwd)
                session_id = payload.get("session_id", session_id)
        if not matches_repo(session_cwd, repo_root):
            continue
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = record.get("payload") or {}
            if record.get("type") != "response_item" or payload.get("role") != "user":
                continue
            timestamp = record.get("timestamp", "")
            moment = parse_timestamp(timestamp)
            if cutoff and moment and moment < cutoff:
                continue
            text = user_text(payload.get("content"))
            message_id = payload.get("id", "")
            if len(text) < 2 or not message_id:
                continue
            yield session_id, message_id, timestamp, redact(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Codex user prompts")
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
    for session_id, message_id, timestamp, prompt in iter_prompts(repo_root, cutoff):
        entry_id = f"codex-{session_id}-{message_id}"
        if entry_id in seen:
            continue
        moment = parse_timestamp(timestamp)
        entries.append({
            "ts": (moment.astimezone(VN_TZ).isoformat() if moment else datetime.now(VN_TZ).isoformat()),
            "tool": "codex",
            "event": "UserPrompt",
            "entry_id": entry_id,
            "session_id": session_id,
            "model": "codex",
            "repo": repo,
            "branch": branch,
            "commit": commit,
            "student": student,
            "prompt": prompt,
            "response_summary": "",
        })

    if args.dry_run:
        print(f"[codex-log] Would log {len(entries)} prompt(s).", file=sys.stderr)
        return
    if not entries:
        print("[codex-log] No new prompts.", file=sys.stderr)
        return
    with log_file.open("a", encoding="utf-8") as output:
        for entry in entries:
            output.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"[codex-log] Logged {len(entries)} prompt(s).", file=sys.stderr)


if __name__ == "__main__":
    main()
