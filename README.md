# tgkit 0.3

A small, consistent layer over Telethon for a personal Telegram account.
You write plain functions. You never write async code.

Read DESIGN.md for why the library is shaped this way.

## Install into a uv project

```bash
cd ~/myproject
uv add --editable /path/to/tgkit
```

Copy config.json next to your script and fill in api_id and api_hash.
Settings are checked when the bot starts, and every problem is listed in one error.

## The whole API in one screen

```python
from tgkit import File, Sticker, Userbot, f

bot = Userbot("config.json")

bot.send(chat, "text")                              # text
bot.send(chat, File("p.jpg", caption="c"))           # photo, video, mp3, any file
bot.send(chat, Sticker("me", 742))                   # copy a sticker from a message
bot.send(chat, "text", reply_to=742)                 # reply (id or Message)
bot.send(chat, "text", at="2026-11-06 09:00")        # schedule

bot.get(chat, 742)                                   # one message, or None
bot.messages(chat, limit=50, before=None,            # newest first
             search=None, types=None)
bot.chats(limit=50)

bot.delete(chat, [742, 743], for_everyone=True)
bot.forward(from_chat, to_chat, [742])
bot.pin(chat, 742, notify=False)
bot.unpin(chat, 742)                                 # unpin(chat) unpins all
bot.download(chat, 742, folder=None)                 # returns the path
bot.download_all(chat, types=None, limit=50)

bot.mute(chat, hours=8)                              # hours=None: forever
bot.unmute(chat)                                     # same as mute(chat, hours=0)
bot.delete_chat(chat)
bot.scheduled(chat)
bot.cancel_scheduled(chat, [55])

bot.report(day=None, send_to="me")                   # text summary
bot.export(send_to="me")                             # database as JSON

@bot.on(f.private & f.text)                          # filtered hook
def handle(msg): ...

@bot.on                                              # hook for every message
def log_all(msg): ...

bot.run()                                            # listen until Ctrl+C
```

## A message is an object

Every message you receive, or read, is a `Message` with actions on it:

```python
msg.reply("text")
msg.reply(File("photo.jpg"))
msg.reply(Sticker("me", 742))
msg.delete()
msg.forward("me")
msg.pin()
msg.unpin()
msg.download()          # sets msg.file
```

## Filters

Combine with `&` (and), `|` (or) and `~` (not):

| Filter | Matches |
|---|---|
| `f.text`, `f.media` | text messages, or messages with a file |
| `f.private`, `f.group` | private chats, or groups and channels |
| `f.mentioned` | messages where you were tagged |
| `f.of_type("photo", "video")` | by kind |
| `f.from_user("@name")` | by username, case-insensitive |
| `f.from_id(123)` | by numeric id |
| `f.contains("price", "cost")` | any of the words, case-insensitive |

## Settings

Every key is checked: a misspelled key is reported as an error.
Important keys: `features` (auto_reply, logging, download_media), `reply` (the reply rules),
`report` (daily summary), `sinks` (telegram, json or webhook).

## Warning

Do not share config.json or the .session file. They give full access to your account.
Automatic replies and mass sending can get an account restricted.
