"""The Userbot class: the only module that talks to Telethon.

Public methods are plain functions. Each one hands an async implementation (the _name
methods) to the runtime loop and waits for the result. Inside the loop, code must use
'await' on the _name methods, never the public ones, to avoid waiting on itself."""
import asyncio
import inspect
import json
import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.tl.functions.account import UpdateNotifySettingsRequest
from telethon.tl.functions.messages import DeleteScheduledMessagesRequest, GetScheduledHistoryRequest
from telethon.tl.types import InputPeerNotifySettings

from .content import File, Sticker, Text, as_content
from .filters import Filter
from .policy import ReplyPolicy
from .records import Chat, Message
from .runtime import Runtime
from .settings import load_settings
from .sinks import JsonFileSink, TelegramSink, WebhookSink
from .store import Store
from .utils import RateLimiter, local_time, normalize_chat, parse_when, setup_logging, to_id

logger = logging.getLogger("tgkit")
FOREVER = 2**31 - 1
NON_MEDIA = ("text", "other")


def message_type(raw):
    if raw.sticker:
        return "sticker"
    if raw.gif:
        return "gif"
    if raw.voice:
        return "voice"
    if raw.audio:
        return "audio"
    if raw.video:
        return "video"
    if raw.photo:
        return "photo"
    if raw.document:
        return "file"
    if raw.media:
        return "media"
    if raw.text:
        return "text"
    return "other"


def _wrap(raw, bot, sender=None):
    sender = sender if sender is not None else getattr(raw, "sender", None)
    return Message(
        id=raw.id,
        chat_id=raw.chat_id,
        date=local_time(raw.date),
        type=message_type(raw),
        text=raw.text or "",
        sender_id=raw.sender_id,
        username=getattr(sender, "username", "") or "",
        first_name=getattr(sender, "first_name", "") or "",
        is_private=bool(raw.is_private),
        mentioned=bool(raw.mentioned),
        _bot=bot,
    )


def _listify(value):
    return list(value) if isinstance(value, (list, tuple, set)) else [value]


async def _retry(make_call, tries=3):
    """Telegram sometimes asks us to wait (FloodWait). Wait the requested time, then retry."""
    for attempt in range(tries):
        try:
            return await make_call()
        except FloodWaitError as e:
            if attempt == tries - 1:
                raise
            logger.warning("Telegram asked to wait %s seconds", e.seconds)
            await asyncio.sleep(e.seconds + 1)


class Userbot:
    """Create one per script: bot = Userbot("config.json")."""

    def __init__(self, config_path="config.json"):
        self.cfg = load_settings(config_path)
        setup_logging(self.cfg.error_log)
        Path(self.cfg.download_dir).mkdir(parents=True, exist_ok=True)
        self.store = Store(self.cfg.database)
        self.policy = ReplyPolicy(self.cfg.reply, self.store.has_replied,
                                  RateLimiter(self.cfg.reply.max_per_hour))
        self._sinks = self._build_sinks()
        self._runtime = Runtime()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tgkit-hook")
        self._connect_lock = threading.Lock()
        self._client = None
        self._attached = False
        self._handlers = []  # (condition or None, function)

    # ================= connection plumbing =================

    def _build_sinks(self):
        sinks = []
        for name in self.cfg.sinks:
            if name == "telegram":
                sinks.append(TelegramSink(self._sink_send, self.cfg.log_target))
            elif name == "json":
                sinks.append(JsonFileSink(self.cfg.log_file))
            elif name == "webhook":
                sinks.append(WebhookSink(self.cfg.webhook_url))
        return sinks

    def _ensure_connected(self):
        with self._connect_lock:
            if self._client is None:
                self._runtime.start()
                self._client = self._runtime.call(self._connect())

    async def _connect(self):
        client = TelegramClient(self.cfg.session, self.cfg.api_id, self.cfg.api_hash)
        await client.start()
        return client

    def _run(self, coro_fn, *args):
        self._ensure_connected()
        return self._runtime.call(coro_fn(*args))

    @property
    def client(self):
        """The raw Telethon client, for advanced use."""
        self._ensure_connected()
        return self._client

    # ================= sending =================

    def send(self, chat, content, *, reply_to=None, at=None):
        """Sends content to a chat.

        content: a string (text), File(path, caption=..., as_document=...), or Sticker(chat, msg_id).
        reply_to: a message id or a Message, to reply to it.
        at: a datetime or 'YYYY-MM-DD HH:MM', to schedule the message."""
        return self._run(self._send, normalize_chat(chat), as_content(content),
                         to_id(reply_to), parse_when(at))

    async def _send(self, chat, content, reply_to, when):
        extra = {"reply_to": reply_to, "schedule": when}
        if isinstance(content, Text):
            return await _retry(lambda: self._client.send_message(chat, content.value, **extra))
        if isinstance(content, File):
            path = Path(content.path)
            if not path.is_file():
                raise FileNotFoundError(f"no such file: {path}")
            return await _retry(lambda: self._client.send_file(
                chat, str(path), caption=content.caption, force_document=content.as_document, **extra))
        source = await self._client.get_messages(normalize_chat(content.chat), ids=content.msg_id)
        if source is None or not source.sticker:
            raise ValueError(f"message {content.msg_id} in {content.chat} is not a sticker")
        return await _retry(lambda: self._client.send_file(chat, source.document, **extra))

    async def _sink_send(self, chat, text):
        await self._send(normalize_chat(chat), Text(text), None, None)

    # ================= reading =================

    def get(self, chat, message):
        """One message by id. Returns a Message, or None."""
        return self._run(self._get, normalize_chat(chat), to_id(message))

    async def _get(self, chat, msg_id):
        raw = await self._client.get_messages(chat, ids=msg_id)
        return _wrap(raw, self) if raw else None

    def messages(self, chat, limit=100, *, before=None, search=None, types=None):
        """Newest first. limit counts scanned messages. types filters by kind, e.g. ["photo", "video"].
        before: only messages older than this datetime. search: only messages containing this text."""
        kinds = tuple(types) if types else None
        return self._run(self._messages, normalize_chat(chat), limit, before, search, kinds)

    async def _messages(self, chat, limit, before, search, kinds):
        out = []
        async for raw in self._client.iter_messages(chat, limit=limit, offset_date=before, search=search):
            if kinds and message_type(raw) not in kinds:
                continue
            out.append(_wrap(raw, self))
        return out

    def chats(self, limit=50):
        return self._run(self._chats, limit)

    async def _chats(self, limit):
        return [Chat(id=d.id, name=d.name) async for d in self._client.iter_dialogs(limit=limit)]

    # ================= changing messages =================

    def delete(self, chat, messages, *, for_everyone=True):
        ids = [to_id(m) for m in _listify(messages)]
        return self._run(self._delete, normalize_chat(chat), ids, for_everyone)

    async def _delete(self, chat, ids, for_everyone):
        return await self._client.delete_messages(chat, ids, revoke=for_everyone)

    def forward(self, from_chat, to_chat, messages):
        ids = [to_id(m) for m in _listify(messages)]
        return self._run(self._forward, normalize_chat(from_chat), normalize_chat(to_chat), ids)

    async def _forward(self, from_chat, to_chat, ids):
        return await self._client.forward_messages(to_chat, ids, from_chat)

    def pin(self, chat, message, *, notify=False):
        return self._run(self._pin, normalize_chat(chat), to_id(message), notify)

    async def _pin(self, chat, msg_id, notify):
        return await self._client.pin_message(chat, msg_id, notify=notify)

    def unpin(self, chat, message=None):
        """Unpins one message, or every pinned message when message is None."""
        return self._run(self._unpin, normalize_chat(chat), to_id(message))

    async def _unpin(self, chat, msg_id):
        return await self._client.unpin_message(chat, msg_id)

    # ================= media =================

    def download(self, chat, message, folder=None):
        """Saves the media of one message. Returns the file path, or None if it has no media."""
        return self._run(self._download, normalize_chat(chat), to_id(message), folder)

    async def _download(self, chat, msg_id, folder):
        raw = await self._client.get_messages(chat, ids=msg_id)
        if raw is None or not raw.media:
            return None
        target = folder or self.cfg.download_dir
        Path(target).mkdir(parents=True, exist_ok=True)
        path = await self._client.download_media(raw, file=target)
        return str(path) if path else None

    def download_all(self, chat, *, types=None, limit=50, folder=None):
        """Downloads media from the newest `limit` messages. Returns those Messages, with .file set."""
        saved = []
        for msg in self.messages(chat, limit, types=types):
            if msg.type in NON_MEDIA:
                continue
            path = self.download(chat, msg.id, folder)
            if path:
                msg.file = path
                saved.append(msg)
        return saved

    # ================= chat management =================

    def mute(self, chat, hours=None):
        """hours=None mutes forever. hours=0 unmutes. Any other number mutes for that many hours."""
        if hours is None:
            until = FOREVER
        elif hours == 0:
            until = 0
        else:
            until = int(time.time() + hours * 3600)
        return self._run(self._set_mute, normalize_chat(chat), until)

    def unmute(self, chat):
        return self.mute(chat, hours=0)

    async def _set_mute(self, chat, until):
        peer = await self._client.get_input_entity(chat)
        await self._client(UpdateNotifySettingsRequest(
            peer=peer, settings=InputPeerNotifySettings(mute_until=until)))

    def delete_chat(self, chat):
        """Removes the chat from your list. Cannot be undone. In groups you own it may delete it for everyone."""
        return self._run(self._delete_chat, normalize_chat(chat))

    async def _delete_chat(self, chat):
        await self._client.delete_dialog(chat)

    # ================= scheduled messages =================

    def scheduled(self, chat):
        return self._run(self._scheduled, normalize_chat(chat))

    async def _scheduled(self, chat):
        peer = await self._client.get_input_entity(chat)
        result = await self._client(GetScheduledHistoryRequest(peer=peer, hash=0))
        return [Message(id=m.id, chat_id=chat, date=local_time(m.date), type="text",
                        text=m.message or "", _bot=self) for m in result.messages]

    def cancel_scheduled(self, chat, messages):
        ids = [to_id(m) for m in _listify(messages)]
        return self._run(self._cancel_scheduled, normalize_chat(chat), ids)

    async def _cancel_scheduled(self, chat, ids):
        peer = await self._client.get_input_entity(chat)
        return await self._client(DeleteScheduledMessagesRequest(peer=peer, id=ids))

    # ================= listening and hooks =================

    def on(self, condition=None):
        """Registers a function that runs for each incoming message.

            @bot.on(f.private & f.text)
            def handle(msg): ...

        With no condition the function runs for every message. Bare @bot.on also works.
        The function runs in a worker thread, so it may call any bot method."""
        if callable(condition) and not isinstance(condition, Filter):
            self._handlers.append((None, condition))
            return condition

        def register(fn):
            self._handlers.append((condition, fn))
            return fn

        return register

    @property
    def hooks(self):
        return [fn for _, fn in self._handlers]

    def run(self):
        """Listens until Ctrl+C. Also runs the daily report if it is enabled."""
        self._ensure_connected()
        self._runtime.call(self._attach())
        logger.info("listening. Press Ctrl+C to stop.")
        try:
            self._runtime.call(self._wait_until_disconnected())
        except KeyboardInterrupt:
            logger.info("stopped")
        finally:
            self.close()

    async def _wait_until_disconnected(self):
        # Telethon's run_until_disconnected() starts its own loop, which cannot run inside ours.
        # Awaiting the client's 'disconnected' future does the same job on the loop we already run.
        await self._client.disconnected

    async def _attach(self):
        if self._attached:
            return
        self._attached = True
        self._client.add_event_handler(self._on_event, events.NewMessage(incoming=True))
        if self.cfg.report.enabled:
            asyncio.ensure_future(self._report_loop())

    async def _on_event(self, event):
        try:
            await self._handle(event)
        except Exception:
            logger.exception("error while handling a message")

    async def _handle(self, event):
        raw = event.message
        if not event.is_private and not raw.mentioned:
            return  # groups: only messages where you were mentioned
        sender = await event.get_sender()
        if sender is None:
            return
        msg = _wrap(raw, self, sender=sender)

        if self.cfg.features.download_media and msg.type not in NON_MEDIA:
            try:
                path = await self._client.download_media(raw, file=self.cfg.download_dir)
                if path:
                    msg.file = str(path)
            except Exception:
                logger.exception("could not download media from message %s", msg.id)

        if self.cfg.features.logging:
            self.store.add_event({
                "date": msg.date, "chat_id": msg.chat_id, "msg_id": msg.id,
                "sender_id": msg.sender_id, "username": msg.username,
                "first_name": msg.first_name, "type": msg.type,
            })
            for sink in self._sinks:
                try:
                    await sink.send(self._log_row(msg))
                except Exception:
                    logger.exception("sink %s failed", type(sink).__name__)

        await self._dispatch(msg)

        if self.cfg.features.auto_reply:
            await self._auto_reply(msg, sender)

    @staticmethod
    def _log_row(msg):
        return {"date": msg.date, "chat_id": msg.chat_id, "msg_id": msg.id,
                "sender_id": msg.sender_id, "username": msg.username,
                "first_name": msg.first_name, "type": msg.type}

    async def _dispatch(self, msg):
        loop = asyncio.get_running_loop()
        for condition, fn in self._handlers:
            if condition is not None and not condition(msg):
                continue
            try:
                result = await loop.run_in_executor(self._pool, fn, msg)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("hook %s failed", getattr(fn, "__name__", fn))

    async def _auto_reply(self, msg, sender):
        reason = self.policy.blocked_reason(msg.sender_id, bool(getattr(sender, "bot", False)))
        if reason:
            logger.info("no reply to %s: %s", msg.username or msg.sender_id, reason)
            return
        self.store.mark_replied(msg.sender_id)
        await asyncio.sleep(random.uniform(*self.cfg.reply.delay_seconds))
        await self._send(msg.chat_id, Text(self.policy.text_for(msg.username, msg.text)), msg.id, None)

    async def _report_loop(self):
        hour, minute = map(int, self.cfg.report.time.split(":"))
        while True:
            now = datetime.now()
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            await asyncio.sleep((target - now).total_seconds())
            try:
                await self._sink_send(self.cfg.report.chat, self.store.report_text())
                logger.info("daily report sent")
            except Exception:
                logger.exception("daily report failed")

    def close(self):
        if self._client is not None:
            try:
                pending = self._client.disconnect()  # None when already disconnected
                if pending is not None:
                    self._runtime.call(pending)
            except Exception:
                logger.exception("disconnect failed")
            self._client = None
        self._runtime.stop()
        self._pool.shutdown(wait=False, cancel_futures=True)
        self.store.close()

    # ================= reports and export =================

    def report(self, day=None, *, send_to=None):
        text = self.store.report_text(day)
        if send_to is not None:
            self.send(send_to, text)
        return text

    def export(self, path=None, *, send_to=None):
        path = path or self.cfg.export_file
        Path(path).write_text(json.dumps(self.store.export_rows(), ensure_ascii=False, indent=2), encoding="utf-8")
        if send_to is not None:
            self.send(send_to, File(path, caption="database export"))
        return path
