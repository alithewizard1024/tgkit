"""tgkit 0.3: a small, consistent layer over Telethon for personal accounts."""
from .content import File, Sticker, Text
from .filters import f
from .records import Chat, Message
from .settings import Settings, SettingsError, load_settings

__version__ = "0.3.0"
__all__ = ["Userbot", "File", "Sticker", "Text", "f", "Message", "Chat",
           "Settings", "SettingsError", "load_settings"]


def __getattr__(name):
    # Telethon is imported only when Userbot is first used, so the pure modules work without it.
    if name == "Userbot":
        from .core import Userbot
        return Userbot
    raise AttributeError(f"module 'tgkit' has no attribute {name!r}")
