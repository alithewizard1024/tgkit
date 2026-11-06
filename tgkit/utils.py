"""Small helpers with no Telegram dependency, so they are easy to test."""
import logging
import time
from datetime import datetime

logger = logging.getLogger("tgkit")


def setup_logging(path):
    """Logs to a file and to the terminal. Calling it again changes nothing."""
    if logger.handlers:
        return
    logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("[tgkit] %(message)s"))
    logger.addHandler(file_handler)
    logger.addHandler(console)


def normalize_chat(chat):
    """'-5590006027' becomes -5590006027. Usernames, 'me' and phone numbers stay as text."""
    if isinstance(chat, int):
        return chat
    text = str(chat).strip()
    if text.lstrip("-").isdigit():
        return int(text)
    return text


def to_id(value):
    """Accepts a message id, a Message, or None. Returns the id (or None)."""
    if value is None or isinstance(value, int):
        return value
    if hasattr(value, "id"):
        return value.id
    raise TypeError(f"expected a message id or a message, got {type(value).__name__}")


def parse_when(value):
    """Accepts None, a datetime, or 'YYYY-MM-DD HH:MM'. Returns None or a datetime in the future."""
    if value is None:
        return None
    dt = value if isinstance(value, datetime) else datetime.strptime(value, "%Y-%m-%d %H:%M")
    if dt <= datetime.now():
        raise ValueError("the scheduled time must be in the future")
    return dt


def local_time(dt):
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def is_quiet_hours(window, now=None):
    """window is ["23:00", "07:00"]. Pass now (a datetime) to test a specific time."""
    if not window:
        return False
    start_text, end_text = window
    start = datetime.strptime(start_text, "%H:%M").time()
    end = datetime.strptime(end_text, "%H:%M").time()
    current = (now or datetime.now()).time()
    if start <= end:
        return start <= current < end
    return current >= start or current < end


def find_keyword(text, keywords):
    """Returns the first keyword that appears in text (case-insensitive), or None."""
    if not text:
        return None
    low = text.lower()
    for word in keywords:
        if word.lower() in low:
            return word
    return None


class RateLimiter:
    """At most max_per_hour allowed actions in any rolling hour."""

    def __init__(self, max_per_hour):
        self.max = max_per_hour
        self.stamps = []

    def allow(self, now=None):
        now = time.time() if now is None else now
        self.stamps = [t for t in self.stamps if now - t < 3600]
        if len(self.stamps) >= self.max:
            return False
        self.stamps.append(now)
        return True
