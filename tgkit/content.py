"""What you can send. Each kind is a plain value that carries its own options."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Text:
    value: str


@dataclass(frozen=True)
class File:
    """Any file: a picture, a video, an mp3, a document. as_document=True sends it without compression."""
    path: str
    caption: str = ""
    as_document: bool = False


@dataclass(frozen=True)
class Sticker:
    """A sticker copied from an existing message. chat is where that message lives, msg_id is its id."""
    chat: object
    msg_id: int


def as_content(value):
    """A plain string means text. Anything else must be Text, File or Sticker."""
    if isinstance(value, (Text, File, Sticker)):
        return value
    if isinstance(value, str):
        return Text(value)
    raise TypeError(f"cannot send {type(value).__name__}: use a string, File(...) or Sticker(...)")
