"""SQLite log of incoming messages. Stores metadata only, never the message text."""
import sqlite3
import threading
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_date TEXT, chat_id INTEGER, msg_id INTEGER, sender_id INTEGER,
    username TEXT, first_name TEXT, msg_type TEXT
);
CREATE TABLE IF NOT EXISTS replied (
    user_id INTEGER PRIMARY KEY,
    replied_at TEXT DEFAULT (datetime('now', 'localtime'))
);
"""


class Store:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def add_event(self, row):
        with self._lock:
            self.conn.execute(
                "INSERT INTO events (msg_date, chat_id, msg_id, sender_id, username, first_name, msg_type) "
                "VALUES (:date, :chat_id, :msg_id, :sender_id, :username, :first_name, :type)",
                row,
            )
            self.conn.commit()

    def has_replied(self, user_id):
        with self._lock:
            return self.conn.execute("SELECT 1 FROM replied WHERE user_id = ?", (user_id,)).fetchone() is not None

    def mark_replied(self, user_id):
        with self._lock:
            self.conn.execute("INSERT OR IGNORE INTO replied (user_id) VALUES (?)", (user_id,))
            self.conn.commit()

    def export_rows(self):
        with self._lock:
            return [dict(r) for r in self.conn.execute("SELECT * FROM events ORDER BY id")]

    def report(self, day):
        sql = """
            SELECT COALESCE(NULLIF(username, ''), 'id ' || sender_id) AS who, msg_type, COUNT(*) AS n
            FROM events WHERE substr(msg_date, 1, 10) = ?
            GROUP BY who, msg_type ORDER BY n DESC
        """
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, (day,))]

    def report_text(self, day=None):
        day = day or datetime.now().strftime("%Y-%m-%d")
        rows = self.report(day)
        if not rows:
            return f"Report {day}: no messages logged"
        total = sum(r["n"] for r in rows)
        lines = [f"Report {day}: {total} messages"]
        lines += [f"{r['who']} | {r['msg_type']} | {r['n']}" for r in rows]
        return "\n".join(lines)

    def close(self):
        with self._lock:
            self.conn.close()
