"""Persistent message inbox, evidence-backed task extraction and reminder timing."""
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))


def reminder_stage(due_at, now, offsets):
    if due_at is None:
        return None
    reached = [offset for offset in offsets if now >= due_at - offset]
    return min(reached) if reached else None


def format_time(timestamp):
    return datetime.fromtimestamp(timestamp, CST).strftime("%Y-%m-%d %H:%M")


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                group_id TEXT, message_id TEXT, sent_at REAL, text TEXT,
                processed INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(group_id, message_id));
            CREATE INDEX IF NOT EXISTS pending_messages ON messages(group_id, processed);
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, group_id TEXT, title TEXT, source_id TEXT,
                quote TEXT, due_at REAL, updated_at REAL);
            CREATE TABLE IF NOT EXISTS sent (key TEXT PRIMARY KEY);
        """)

    def close(self):
        self.db.close()

    def ingest(self, event, account, groups):
        if not isinstance(event, dict) or event.get("post_type") != "message":
            return False
        group = str(event.get("group_id", ""))
        if (event.get("message_type") != "group" or group not in groups
                or str(event.get("self_id")) != account):
            return False
        segments = event.get("message")
        if not isinstance(segments, list):
            return False  # OneBot must use array format, never interpret CQ strings.
        text = "".join(str(seg.get("data", {}).get("text", ""))
                       for seg in segments if isinstance(seg, dict) and seg.get("type") == "text").strip()
        message_id, sent_at = event.get("message_id"), event.get("time")
        if not text or message_id is None or not isinstance(sent_at, (int, float)):
            return False
        with self.db:
            result = self.db.execute("INSERT OR IGNORE INTO messages(group_id,message_id,sent_at,text) VALUES(?,?,?,?)",
                                     (group, str(message_id), sent_at, text))
        return result.rowcount == 1

    def pending(self, group, limit=80):
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM messages WHERE group_id=? AND processed=0 ORDER BY sent_at,message_id LIMIT ?",
            (group, limit))]

    def tasks(self, group=None):
        if group is not None:
            return [dict(row) for row in self.db.execute("SELECT * FROM tasks WHERE group_id=? ORDER BY updated_at DESC", (group,))]
        return [dict(row) for row in self.db.execute("SELECT * FROM tasks ORDER BY due_at IS NULL,due_at,title")]

    def apply(self, group, batch, response):
        payload = json.loads(response)
        if not isinstance(payload, dict) or not isinstance(payload.get("tasks"), list):
            raise ValueError("Model response must contain a tasks array")
        sources = {row["message_id"]: row for row in batch}
        existing = {row["id"]: row for row in self.tasks(group)}
        updates = []
        for item in payload["tasks"]:
            if not isinstance(item, dict):
                raise ValueError("Invalid task")
            source_id = str(item.get("source_id", ""))
            source = sources.get(source_id)
            title, quote = item.get("title"), item.get("quote")
            if (source is None or not isinstance(title, str) or not title.strip()
                    or not isinstance(quote, str) or not quote.strip() or quote not in source["text"]):
                raise ValueError("Task lacks a valid source quotation")
            title = title.strip()
            task_id = item.get("task_id")
            if task_id:
                if task_id not in existing:
                    raise ValueError("Cannot update unknown task or another group's task")
                if existing[task_id]["updated_at"] > source["sent_at"]:
                    continue  # Delayed delivery cannot undo a newer correction.
            else:
                task_id = hashlib.sha256(f"{group}:{source_id}:{title}".encode()).hexdigest()[:20]
            due_at = None
            evidence = item.get("deadline_text")
            if (item.get("uncertain") is False and isinstance(evidence, str)
                    and evidence.strip() and evidence in quote and isinstance(item.get("due_at"), str)):
                try:
                    parsed = datetime.fromisoformat(item["due_at"])
                    if parsed.tzinfo is not None:
                        due_at = parsed.timestamp()
                except (ValueError, OverflowError):
                    pass
            updates.append((task_id, group, title, source_id, quote, due_at, source["sent_at"]))
        with self.db:
            self.db.executemany("""INSERT INTO tasks VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET title=excluded.title,source_id=excluded.source_id,
                quote=excluded.quote,due_at=excluded.due_at,updated_at=excluded.updated_at""", updates)
            self.db.executemany("UPDATE messages SET processed=1 WHERE group_id=? AND message_id=?",
                                [(group, row["message_id"]) for row in batch])

    def was_sent(self, key):
        return self.db.execute("SELECT 1 FROM sent WHERE key=?", (key,)).fetchone() is not None

    def mark_sent(self, key):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO sent VALUES(?)", (key,))

    def pending_count(self):
        return self.db.execute("SELECT count(*) FROM messages WHERE processed=0").fetchone()[0]

    def prune(self, before):
        # Keep evidence in tasks, and never discard a message awaiting AI processing.
        with self.db:
            self.db.execute("DELETE FROM messages WHERE processed=1 AND sent_at<?", (before,))
