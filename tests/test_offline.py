"""
Offline tests for tgkit 0.3. No Telegram account or network is needed.
Run from the project folder:  uv run python tests/test_offline.py
"""
import asyncio
import http.server
import json
import tempfile
import threading
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from tgkit import File, Sticker, Text, f
from tgkit.content import as_content
from tgkit.filters import Filter
from tgkit.policy import ReplyPolicy
from tgkit.records import Message
from tgkit.runtime import Runtime
from tgkit.settings import SettingsError, load_settings
from tgkit.sinks import JsonFileSink, TelegramSink, WebhookSink, format_record
from tgkit.store import Store
from tgkit.utils import RateLimiter, is_quiet_hours, normalize_chat, parse_when, to_id

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


def write_config(directory, data):
    path = Path(directory) / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def good_config(directory, **extra):
    base = {"api_id": 12345, "api_hash": "abcdef", "database": str(Path(directory) / "t.db"),
            "error_log": str(Path(directory) / "errors.log"),
            "download_dir": str(Path(directory) / "dl"),
            "log_file": str(Path(directory) / "log.json"), "sinks": ["json"]}
    base.update(extra)
    return write_config(directory, base)


def sample(**overrides):
    values = dict(id=1, chat_id=5, date="2026-01-01 10:00:00", type="text", text="hello",
                  sender_id=7, username="ali", first_name="Ali", is_private=True, mentioned=False)
    values.update(overrides)
    return Message(**values)


class FakeBot:
    def __init__(self):
        self.calls = []

    def send(self, chat, content, **options):
        self.calls.append(("send", chat, content, options))

    def delete(self, chat, messages, **options):
        self.calls.append(("delete", chat, messages))

    def forward(self, from_chat, to_chat, messages):
        self.calls.append(("forward", from_chat, to_chat, messages))

    def pin(self, chat, message, notify=False):
        self.calls.append(("pin", chat, message, notify))

    def unpin(self, chat, message=None):
        self.calls.append(("unpin", chat, message))

    def download(self, chat, message, folder=None):
        self.calls.append(("download", chat, message, folder))
        return "/tmp/x.jpg"


# ============ settings ============

@test
def settings_missing_file_names_the_path():
    try:
        load_settings("/no/such/config.json")
    except SettingsError as e:
        assert "config file not found" in e.problems[0]
        return
    raise AssertionError("no error raised")


@test
def settings_bad_json_reports_line_and_column():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "c.json"
        p.write_text('{\n  "api_id": 1,\n  oops\n}', encoding="utf-8")
        try:
            load_settings(str(p))
        except SettingsError as e:
            assert "line 3" in e.problems[0], e.problems
            return
    raise AssertionError("no error raised")


@test
def settings_reports_all_problems_at_once():
    with tempfile.TemporaryDirectory() as d:
        p = write_config(d, {"api_id": "abc", "api_hash": "your_api_hash", "nonsense": 1,
                             "reply": {"max_per_hour": "5"}})
        try:
            load_settings(p)
        except SettingsError as e:
            text = "\n".join(e.problems)
            # Type and spelling errors are reported together. Value checks run only after these pass.
            assert "api_id must be a number" in text
            assert "nonsense is not a known setting" in text
            assert "reply.max_per_hour must be a number" in text
            assert len(e.problems) == 3, e.problems
            return
    raise AssertionError("no error raised")


@test
def settings_fills_defaults_and_allows_attribute_access():
    with tempfile.TemporaryDirectory() as d:
        cfg = load_settings(good_config(d, reply={"max_per_hour": 9}))
        assert cfg.reply.max_per_hour == 9
        assert cfg.reply.default, "default reply must be filled in"
        assert cfg.features.logging is True


@test
def settings_rejects_bad_clock_and_delays():
    with tempfile.TemporaryDirectory() as d:
        p = good_config(d, reply={"quiet_hours": ["25:00", "07:00"], "delay_seconds": [9, 2]})
        try:
            load_settings(p)
        except SettingsError as e:
            text = "\n".join(e.problems)
            assert "quiet_hours" in text and "delay_seconds" in text
            return
    raise AssertionError("no error raised")


# ============ content ============

@test
def content_plain_string_is_text():
    assert as_content("hi") == Text("hi")


@test
def content_rejects_unknown_types():
    try:
        as_content(12)
    except TypeError:
        return
    raise AssertionError("no error raised")


@test
def content_file_and_sticker_keep_their_options():
    assert File("a.jpg", caption="c", as_document=True).as_document is True
    assert Sticker("me", 742).msg_id == 742


# ============ filters ============

@test
def filters_combine_with_and_or_not():
    private_text = f.private & f.text
    assert private_text(sample()) is True
    assert private_text(sample(is_private=False)) is False
    assert (f.group | f.text)(sample()) is True
    assert (~f.text)(sample()) is False
    assert isinstance(private_text, Filter)


@test
def filters_from_user_ignores_at_sign_and_case():
    assert f.from_user("@ALI")(sample()) is True
    assert f.from_user("bob")(sample()) is False


@test
def filters_contains_is_case_insensitive_and_takes_several_words():
    assert f.contains("PRICE")(sample(text="what is the price?")) is True
    assert f.contains("cost", "price")(sample(text="price?")) is True
    assert f.contains("cost")(sample(text="price?")) is False


@test
def filters_media_and_of_type():
    assert f.media(sample(type="photo")) is True
    assert f.media(sample(type="text")) is False
    assert f.of_type("photo", "video")(sample(type="video")) is True


# ============ records ============

@test
def message_reply_delegates_with_chat_and_id():
    bot = FakeBot()
    msg = sample(_bot=bot)
    msg.reply("hi")
    assert bot.calls == [("send", 5, "hi", {"at": None, "reply_to": 1})] or \
        bot.calls[0][1:3] == (5, "hi")
    assert bot.calls[0][3]["reply_to"] == 1


@test
def message_actions_need_a_bot():
    try:
        sample().delete()
    except RuntimeError:
        return
    raise AssertionError("no error raised")


@test
def message_download_stores_the_path():
    bot = FakeBot()
    msg = sample(_bot=bot)
    assert msg.download() == "/tmp/x.jpg"
    assert msg.file == "/tmp/x.jpg"


# ============ utils ============

@test
def normalize_chat_variants():
    assert normalize_chat("-5590006027") == -5590006027
    assert normalize_chat(" 42 ") == 42
    assert normalize_chat("@lain") == "@lain"
    assert normalize_chat("me") == "me"


@test
def to_id_accepts_id_message_or_none():
    assert to_id(7) == 7
    assert to_id(sample(id=9)) == 9
    assert to_id(None) is None
    try:
        to_id("x")
    except TypeError:
        return
    raise AssertionError("no TypeError")


@test
def parse_when_rules():
    future = datetime.now() + timedelta(days=1)
    assert parse_when(None) is None
    assert parse_when(future) == future
    try:
        parse_when((datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M"))
    except ValueError:
        return
    raise AssertionError("past time accepted")


@test
def quiet_hours_with_an_explicit_clock():
    night = datetime(2026, 1, 1, 23, 30)
    noon = datetime(2026, 1, 1, 12, 0)
    assert is_quiet_hours(["23:00", "07:00"], now=night) is True
    assert is_quiet_hours(["23:00", "07:00"], now=noon) is False
    assert is_quiet_hours(["09:00", "17:00"], now=noon) is True


@test
def rate_limiter_with_explicit_time():
    rl = RateLimiter(2)
    assert rl.allow(now=0) and rl.allow(now=10)
    assert rl.allow(now=20) is False
    assert rl.allow(now=3601) is True  # the first two stamps are older than an hour now


# ============ policy ============

class FakeStore:
    def __init__(self, replied=()):
        self.replied = set(replied)

    def has_replied(self, uid):
        return uid in self.replied


def policy_with(directory, store=None, **reply):
    cfg = load_settings(good_config(directory, reply=reply))
    return ReplyPolicy(cfg.reply, (store or FakeStore()).has_replied, RateLimiter(100))


@test
def policy_text_priority_username_then_keyword_then_default():
    with tempfile.TemporaryDirectory() as d:
        p = policy_with(d, by_username={"@Lain": "for lain"}, keyword_replies={"price": "for price"})
        assert p.text_for("lain", "price?") == "for lain"
        assert p.text_for("ali", "what is the PRICE") == "for price"
        assert p.text_for("ali", "hello") == load_settings(good_config(d)).reply.default


@test
def policy_block_reasons_in_order():
    with tempfile.TemporaryDirectory() as d:
        p = policy_with(d, store=FakeStore(replied={2}))
        assert p.blocked_reason(1, True) == "sender is a bot"
        assert p.blocked_reason(2, False) == "already replied to this user"
        assert p.blocked_reason(3, False) is None


@test
def policy_accepts_a_new_rule_without_editing_the_library():
    with tempfile.TemporaryDirectory() as d:
        p = policy_with(d)
        p.checks.append(lambda sender_id, is_bot: "vip only" if sender_id != 99 else None)
        assert p.blocked_reason(5, False) == "vip only"
        assert p.blocked_reason(99, False) is None


# ============ store ============

@test
def store_roundtrip_replied_and_export():
    with tempfile.TemporaryDirectory() as d:
        s = Store(str(Path(d) / "x.db"))
        s.add_event({"date": "2026-01-01 10:00:00", "chat_id": 1, "msg_id": 2, "sender_id": 3,
                     "username": "ali", "first_name": "A", "type": "photo"})
        rows = s.export_rows()
        assert rows[0]["msg_type"] == "photo" and rows[0]["msg_id"] == 2
        assert s.has_replied(3) is False
        s.mark_replied(3)
        s.mark_replied(3)
        assert s.has_replied(3) is True
        s.close()


@test
def store_report_counts_by_person_and_type():
    with tempfile.TemporaryDirectory() as d:
        s = Store(str(Path(d) / "x.db"))
        for kind in ["text", "text", "photo"]:
            s.add_event({"date": "2026-01-01 10:00:00", "chat_id": 1, "msg_id": 1, "sender_id": 7,
                         "username": "ali", "first_name": "", "type": kind})
        text = s.report_text("2026-01-01")
        assert text.startswith("Report 2026-01-01: 3 messages"), text
        assert "ali | text | 2" in text and "ali | photo | 1" in text
        assert "no messages logged" in s.report_text("2030-01-01")
        s.close()


# ============ sinks ============

@test
def json_sink_appends_in_order():
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "log.json")

        async def go():
            s = JsonFileSink(path)
            await s.send({"a": 1})
            await s.send({"a": 2})

        asyncio.run(go())
        assert json.loads(Path(path).read_text(encoding="utf-8")) == [{"a": 1}, {"a": 2}]


@test
def webhook_sink_posts_json():
    received = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            size = int(self.headers["Content-Length"])
            received.append(json.loads(self.rfile.read(size)))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        asyncio.run(WebhookSink(f"http://127.0.0.1:{server.server_port}/log").send({"n": 3}))
    finally:
        server.shutdown()
        server.server_close()
    assert received == [{"n": 3}]


@test
def telegram_sink_sends_formatted_line():
    sent = []

    async def fake_send(chat, text):
        sent.append((chat, text))

    asyncio.run(TelegramSink(fake_send, "me").send({"date": "d", "username": "ali", "first_name": "A"}))
    assert sent == [("me", "d | @ali | A")]
    assert format_record({"date": "d", "sender_id": 4}) == "d | id 4 | "


# ============ runtime ============

@test
def runtime_returns_results_from_other_threads():
    rt = Runtime()
    rt.start()
    try:
        async def add(a, b):
            await asyncio.sleep(0)
            return a + b

        results = []
        threads = [threading.Thread(target=lambda i=i: results.append(rt.call(add(i, 1))))
                   for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(results) == list(range(1, 9))
    finally:
        rt.stop()


@test
def runtime_propagates_exceptions():
    rt = Runtime()
    rt.start()
    try:
        async def boom():
            raise KeyError("inside")

        try:
            rt.call(boom())
        except KeyError:
            return
        raise AssertionError("exception was swallowed")
    finally:
        rt.stop()


@test
def runtime_refuses_to_deadlock_itself():
    rt = Runtime()
    rt.start()
    try:
        async def nested():
            inner = (async_value())
            return rt.call(inner)

        async def async_value():
            return 1

        try:
            rt.call(nested())
        except RuntimeError as e:
            assert "deadlock" in str(e)
            return
        raise AssertionError("no error raised")
    finally:
        rt.stop()


@test
def runtime_accepts_awaitables_that_are_not_coroutines():
    rt = Runtime()
    rt.start()
    try:
        class Awaitable:
            """Not a coroutine, but awaitable: the kind of object some Telethon calls return."""
            def __await__(self):
                yield from asyncio.sleep(0).__await__()
                return 42

        assert rt.call(Awaitable()) == 42
    finally:
        rt.stop()


@test
def runtime_requires_start_and_stops_cleanly():
    rt = Runtime()

    async def value():
        return 1

    coro = value()
    try:
        rt.call(coro)
    except RuntimeError:
        pass
    else:
        raise AssertionError("call before start did not fail")
    rt.start()
    assert rt.running()
    assert rt.call(value()) == 1
    rt.stop()
    assert not rt.running()


# ============ core (needs Telethon; skipped if it is missing) ============

@test
def core_userbot_registers_hooks_both_styles():
    try:
        from tgkit import Userbot
    except ImportError:
        print("        (skipped: Telethon is not installed in this environment)")
        return
    with tempfile.TemporaryDirectory() as d:
        bot = Userbot(good_config(d))

        @bot.on(f.private & f.text)
        def first(msg):
            return None

        @bot.on
        def second(msg):
            return None

        assert len(bot.hooks) == 2
        assert first is not None and second is not None
        bot.close()


@test
def core_userbot_rejects_bad_config_before_connecting():
    try:
        from tgkit import Userbot
    except ImportError:
        return
    with tempfile.TemporaryDirectory() as d:
        try:
            Userbot(write_config(d, {"api_hash": "your_api_hash"}))
        except SettingsError:
            return
        raise AssertionError("bad config accepted")


# ============ runner ============

def main():
    passed = failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
            passed += 1
        except Exception:
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
