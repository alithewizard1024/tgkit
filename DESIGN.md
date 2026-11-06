# Design notes

## Principles

1. **One verb per action.** Variants are parameters, not new functions.
   Sending text, a file, a sticker, a reply or a scheduled message all use `send`.
2. **Content is a value.** `Text`, `File` and `Sticker` are plain objects that carry their options.
   A new kind of content is a new class plus one branch in `core._send`.
3. **Things you act on are objects.** A `Message` knows how to reply, delete, pin and download.
4. **Conditions are values.** Filters combine with `&`, `|` and `~` instead of nested `if` blocks.
5. **Threads live in one place.** `runtime.py` owns the only event loop. Telethon runs there.
   User code is ordinary synchronous Python and never sees a loop.
6. **Logic is separate from I/O.** `policy`, `store`, `filters`, `content`, `settings` and `utils`
   do not import Telethon, so they are tested without an account.
7. **Configuration fails loudly and completely.** Every problem in config.json is listed in one error.

## Layers

```
your script
    │  bot.send(...), msg.reply(...), @bot.on(f.private)
    ▼
core.py        Userbot: the only module that imports Telethon
    │  submits async work to
    ▼
runtime.py     one event loop in one background thread
    │
    ├── policy.py    reply rules (pure)
    ├── store.py     SQLite log (pure)
    ├── sinks.py     log destinations
    ├── filters.py   conditions (pure)
    ├── content.py   Text, File, Sticker (pure)
    ├── records.py   Message, Chat (pure)
    └── settings.py  config.json (pure)
```

## Why hooks run in worker threads

A hook is user code. If it ran on the event loop and called `bot.send(...)`, the call would wait for
the loop, which is busy running the hook. That is a deadlock. Running hooks in a thread pool means the
loop is always free to deliver the reply. `runtime.call` also refuses to run from the loop thread,
so this mistake raises a clear error instead of hanging.

## How to extend

| You want | Change |
|---|---|
| A new kind of content (a poll, a location) | a class in `content.py`, one branch in `core._send` |
| A new condition for hooks | a `Filter` in `filters.py` (or build one with `Filter(test, label)`) |
| A new reply rule | append a function to `bot.policy.checks`, no library change needed |
| A new log destination | a class in `sinks.py` with `async send(row)`, add its name to `core._build_sinks` and `settings.KNOWN_SINKS` |
| A new action on messages | a public method in `core.py` plus a `_name` async method, and an action on `Message` |
| A new setting | add the default to `settings.DEFAULTS`, and a check to `_check_values` if it has rules |

## Testing

- `tests/test_offline.py` runs without an account. It covers every pure module and the runtime.
- Live tests (Saved Messages only) and destructive tests (a chat named "tgkit test") are the next layer.
