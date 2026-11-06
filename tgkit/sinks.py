"""Where the log goes. Each sink has one async method: send(row)."""
import asyncio
import json
import urllib.request
from pathlib import Path


def format_record(r):
    user = f"@{r['username']}" if r.get("username") else f"id {r.get('sender_id')}"
    return f"{r['date']} | {user} | {r.get('first_name', '')}"


class Sink:
    async def send(self, row):
        raise NotImplementedError


class TelegramSink(Sink):
    """One line per message in a chat (default: Saved Messages)."""

    def __init__(self, send_text, target):
        self.send_text = send_text
        self.target = target

    async def send(self, row):
        await self.send_text(self.target, format_record(row))


class JsonFileSink(Sink):
    def __init__(self, path):
        self.path = Path(path)

    async def send(self, row):
        rows = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []
        rows.append(row)
        self.path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


class WebhookSink(Sink):
    """POSTs each row as JSON to a URL, for example a local server at http://127.0.0.1:8000/log"""

    def __init__(self, url):
        self.url = url

    async def send(self, row):
        await asyncio.to_thread(self._post, row)

    def _post(self, row):
        body = json.dumps(row, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.url, data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=10).close()
