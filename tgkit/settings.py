"""Reads config.json, fills in defaults, and reports every problem in one error.

Keys are fixed: a misspelled key is reported as an error."""
import copy
import json
from datetime import datetime
from pathlib import Path

DEFAULTS = {
    "api_id": 0,
    "api_hash": "",
    "session": "session_name",
    "database": "tgkit.db",
    "log_file": "log.json",
    "export_file": "export.json",
    "error_log": "errors.log",
    "download_dir": "downloads",
    "sinks": ["telegram"],
    "log_target": "me",
    "webhook_url": "",
    "features": {"auto_reply": True, "logging": True, "download_media": False},
    "reply": {
        "default": "Thanks for your message, I will reply later.",
        "quiet_reply": "I am resting now, I will reply in the morning.",
        "quiet_hours": [],
        "by_username": {},
        "keyword_replies": {},
        "ignore_bots": True,
        "once_per_user": True,
        "delay_seconds": [3, 8],
        "max_per_hour": 20,
    },
    "report": {"enabled": False, "time": "23:55", "chat": "me"},
}
KNOWN_SINKS = ("telegram", "json", "webhook")


class SettingsError(ValueError):
    """Carries the full list of problems, so every mistake is fixed in one pass."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("config.json has problems:\n  - " + "\n  - ".join(self.problems))


class Settings(dict):
    """A dict that also allows cfg.reply.default style access."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


def _wrap(value):
    if isinstance(value, dict):
        return Settings({k: _wrap(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_wrap(v) for v in value]
    return value


def _type_ok(value, default):
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, int):
        return isinstance(value, int) and not isinstance(value, bool)
    if isinstance(default, str):
        return isinstance(value, str)
    if isinstance(default, list):
        return isinstance(value, list)
    return True


def _type_name(default):
    names = {bool: "true or false", int: "a number", str: "text in quotes", list: "a list [ ... ]"}
    return names.get(type(default), "a value")


def is_clock(text):
    try:
        datetime.strptime(text, "%H:%M")
        return True
    except (TypeError, ValueError):
        return False


def _merge(data, defaults, path, problems):
    out = {}
    for key, default in defaults.items():
        here = f"{path}{key}"
        if key not in data:
            out[key] = copy.deepcopy(default)
        elif isinstance(default, dict):
            if not isinstance(data[key], dict):
                problems.append(here + ' must be an object { ... }')
                out[key] = copy.deepcopy(default)
            elif not default:
                # An empty default means "any keys", e.g. by_username: names are not fixed in advance.
                bad = [k for k, v in data[key].items() if not isinstance(v, str)]
                for k in bad:
                    problems.append(f"{here}.{k} must be text in quotes")
                out[key] = copy.deepcopy(data[key])
            else:
                out[key] = _merge(data[key], default, here + ".", problems)
        else:
            if not _type_ok(data[key], default):
                problems.append(f"{here} must be {_type_name(default)}, not {type(data[key]).__name__}")
            out[key] = data[key]
    for key in data:
        if key not in defaults:
            problems.append(f"{path}{key} is not a known setting (check the spelling)")
    return out


def _check_values(cfg, problems):
    if cfg["api_id"] <= 0:
        problems.append("api_id is missing: put the number from my.telegram.org")
    if cfg["api_hash"] in ("", "your_api_hash"):
        problems.append("api_hash is missing: put the hash from my.telegram.org")
    if not cfg["session"].strip():
        problems.append("session must not be empty")
    for name in cfg["sinks"]:
        if name not in KNOWN_SINKS:
            problems.append(f"sinks: unknown sink '{name}' (use telegram, json or webhook)")
    if "webhook" in cfg["sinks"] and not cfg["webhook_url"]:
        problems.append("sinks includes 'webhook' but webhook_url is empty")
    reply = cfg["reply"]
    quiet = reply["quiet_hours"]
    if quiet and (len(quiet) != 2 or not all(is_clock(t) for t in quiet)):
        problems.append('reply.quiet_hours must be ["HH:MM", "HH:MM"] or []')
    delays = reply["delay_seconds"]
    numbers = all(isinstance(d, (int, float)) and not isinstance(d, bool) for d in delays)
    if len(delays) != 2 or not numbers or delays[0] < 0 or delays[0] > delays[1]:
        problems.append("reply.delay_seconds must be [min, max] with 0 <= min <= max")
    if reply["max_per_hour"] < 0:
        problems.append("reply.max_per_hour must be 0 or more")
    if not is_clock(cfg["report"]["time"]):
        problems.append('report.time must look like "23:55"')


def load_settings(path="config.json"):
    file = Path(path)
    if not file.exists():
        raise SettingsError([f"config file not found: {file.resolve()}"])
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SettingsError([f"{file.name} is not valid JSON at line {e.lineno}, column {e.colno}: {e.msg}"]) from None
    if not isinstance(data, dict):
        raise SettingsError(["the top level of config.json must be an object { ... }"])
    problems = []
    merged = _merge(data, DEFAULTS, "", problems)
    if not problems:
        _check_values(merged, problems)
    if problems:
        raise SettingsError(problems)
    return _wrap(merged)
