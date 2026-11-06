"""Message and Chat objects. A Message knows how to act on itself, so you write msg.reply(...)."""
from dataclasses import dataclass, field

_NO_BOT = "this message is not attached to a Userbot"


@dataclass
class Message:
    id: int
    chat_id: object
    date: str
    type: str
    text: str = ""
    sender_id: object = None
    username: str = ""
    first_name: str = ""
    is_private: bool = False
    mentioned: bool = False
    file: object = None          # set after download
    _bot: object = field(default=None, repr=False, compare=False)

    def _attached(self):
        if self._bot is None:
            raise RuntimeError(_NO_BOT)
        return self._bot

    def reply(self, content, *, at=None):
        return self._attached().send(self.chat_id, content, reply_to=self.id, at=at)

    def delete(self):
        return self._attached().delete(self.chat_id, [self.id])

    def forward(self, to_chat):
        return self._attached().forward(self.chat_id, to_chat, [self.id])

    def pin(self, notify=False):
        return self._attached().pin(self.chat_id, self.id, notify=notify)

    def unpin(self):
        return self._attached().unpin(self.chat_id, self.id)

    def download(self, folder=None):
        path = self._attached().download(self.chat_id, self.id, folder)
        self.file = path
        return path


@dataclass
class Chat:
    id: object
    name: str
