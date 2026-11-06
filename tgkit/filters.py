"""Conditions for incoming messages. Combine them with & (and), | (or) and ~ (not)."""


class Filter:
    def __init__(self, test, label):
        self._test = test
        self.label = label

    def __call__(self, msg):
        return bool(self._test(msg))

    def __and__(self, other):
        return Filter(lambda m: self(m) and other(m), f"({self.label} & {other.label})")

    def __or__(self, other):
        return Filter(lambda m: self(m) or other(m), f"({self.label} | {other.label})")

    def __invert__(self):
        return Filter(lambda m: not self(m), f"~{self.label}")

    def __repr__(self):
        return f"Filter({self.label})"


class _Filters:
    @property
    def text(self):
        return Filter(lambda m: m.type == "text", "text")

    @property
    def media(self):
        return Filter(lambda m: m.type not in ("text", "other"), "media")

    @property
    def private(self):
        return Filter(lambda m: m.is_private, "private")

    @property
    def group(self):
        return Filter(lambda m: not m.is_private, "group")

    @property
    def mentioned(self):
        return Filter(lambda m: m.mentioned, "mentioned")

    def of_type(self, *kinds):
        return Filter(lambda m: m.type in kinds, f"of_type{kinds}")

    def from_user(self, username):
        name = username.lstrip("@").lower()
        return Filter(lambda m: (m.username or "").lower() == name, f"from_user({name})")

    def from_id(self, user_id):
        return Filter(lambda m: m.sender_id == user_id, f"from_id({user_id})")

    def contains(self, *words):
        needles = [w.lower() for w in words]
        return Filter(lambda m: any(n in (m.text or "").lower() for n in needles), f"contains{words}")


f = _Filters()
