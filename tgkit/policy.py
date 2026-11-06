"""Decides whether to auto-reply and what to say. Pure logic: no Telegram, no network.

Checks run in order and the first one that returns a reason blocks the reply.
To add a rule, append a function: bot.policy.checks.append(my_check)
where my_check(sender_id, is_bot) returns None (allowed) or a reason string (blocked)."""
from .utils import find_keyword, is_quiet_hours


class ReplyPolicy:
    def __init__(self, reply, has_replied, limiter):
        self._cfg = reply
        self._has_replied = has_replied
        self._limiter = limiter
        self.checks = [self._check_bot, self._check_once, self._check_hourly]

    def blocked_reason(self, sender_id, is_bot):
        for check in self.checks:
            reason = check(sender_id, is_bot)
            if reason:
                return reason
        return None

    def text_for(self, username, text=""):
        """Priority: username reply, keyword reply, quiet-hours reply, default reply."""
        name = (username or "").lstrip("@").lower()
        by_user = {k.lstrip("@").lower(): v for k, v in self._cfg.by_username.items()}
        if name and name in by_user:
            return by_user[name]
        keywords = {k.lower(): v for k, v in self._cfg.keyword_replies.items()}
        hit = find_keyword(text, keywords)
        if hit:
            return keywords[hit]
        if is_quiet_hours(self._cfg.quiet_hours):
            return self._cfg.quiet_reply
        return self._cfg.default

    def _check_bot(self, sender_id, is_bot):
        return "sender is a bot" if self._cfg.ignore_bots and is_bot else None

    def _check_once(self, sender_id, is_bot):
        if self._cfg.once_per_user and self._has_replied(sender_id):
            return "already replied to this user"
        return None

    def _check_hourly(self, sender_id, is_bot):
        return None if self._limiter.allow() else "hourly limit reached"
