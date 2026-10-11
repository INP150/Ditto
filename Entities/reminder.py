from dataclasses import dataclass, field
import itertools
from typing import ClassVar, Iterator, TypedDict

from datetime import datetime, timedelta, timezone

class ReminderJson(TypedDict):
    id: int
    guild_id: int | None
    channel_id: str
    creator_id: int
    next_reminder_at: str
    repeat_every_seconds: int
    is_active: bool
    message: str
    as_embed: bool
    embed_title: str | None
    embed_color: int | None
    embed_footer: str | None
    embed_json: str | None
    vote_emojis: str | None
    created_at: str
    last_updated_at: str

@dataclass(slots=True, init=True)
class Reminder:
    channel_id: str
    next_reminder_at: datetime
    repeat_every_seconds: int
    message: str

    # Only a fallback for reminders built without a store. Reminders created
    # through ReminderService take their ID from the storage, so restarting the
    # bot cannot hand out an ID that is already saved.
    _id_counter: ClassVar[Iterator[int]] = itertools.count(1)
    id: int = field(default_factory=lambda: next(Reminder._id_counter))
    creator_id: int | None = None
    # None for reminders in DMs, which belong to no server.
    guild_id: int | None = None
    created_at: datetime = field(default_factory=datetime.now)
    last_updated_at: datetime = field(default_factory=datetime.now)
    is_active: bool = True

    # How the reminder is presented. Plain reminders send `message` as content so
    # mentions ping; embed reminders send it as the embed description instead.
    as_embed: bool = False
    embed_title: str | None = None
    embed_color: int | None = None
    embed_footer: str | None = None
    # The full embed as Discord JSON, set for embeds made with the embed builder.
    # When present it is sent as is, with `message` posted above it as content.
    embed_json: str | None = None
    # Space separated emojis shown as vote buttons under every message sent.
    vote_emojis: str | None = None

    def reschedule_after(self, now: datetime) -> None:
        """Move to the next occurrence after `now`, or stop firing once it is done.

        A one-off reminder (repeat_every_seconds <= 0) is deactivated so it never
        fires again. Recurring reminders skip whole intervals, so a bot that was
        offline does not send every missed occurrence back to back on restart.
        """
        if self.repeat_every_seconds <= 0:
            self.is_active = False
            return

        if self.next_reminder_at > now:
            return

        # Skip whole intervals so a bot that was offline sends one reminder on
        # restart instead of every occurrence it missed.
        elapsed = int((now - self.next_reminder_at).total_seconds())
        skipped = elapsed // self.repeat_every_seconds + 1
        self.next_reminder_at += timedelta(seconds=self.repeat_every_seconds * skipped)


class TimestampCodec:
    @staticmethod
    def to_json(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def from_json(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

class ReminderCodec:
    @staticmethod
    def to_dict(r: Reminder) -> ReminderJson:
        return {
            "id": r.id,
            "guild_id": r.guild_id,
            "channel_id": r.channel_id,
            "creator_id": r.creator_id if r.creator_id is not None else 0,
            "message": r.message,
            "next_reminder_at": TimestampCodec.to_json(r.next_reminder_at),
            "repeat_every_seconds": r.repeat_every_seconds,
            "created_at": TimestampCodec.to_json(r.created_at),
            "last_updated_at": TimestampCodec.to_json(r.last_updated_at),
            "is_active": r.is_active,
            "as_embed": r.as_embed,
            "embed_title": r.embed_title,
            "embed_color": r.embed_color,
            "embed_footer": r.embed_footer,
            "embed_json": r.embed_json,
            "vote_emojis": r.vote_emojis,
        }

    @staticmethod
    def from_dict(d: ReminderJson) -> Reminder:
        return Reminder(
            id=d["id"],
            guild_id=d.get("guild_id"),
            channel_id=d["channel_id"],
            message=d["message"],
            next_reminder_at=TimestampCodec.from_json(d["next_reminder_at"]),
            repeat_every_seconds=d["repeat_every_seconds"],
            created_at=TimestampCodec.from_json(d["created_at"]),
            last_updated_at=TimestampCodec.from_json(d["last_updated_at"]),
            is_active=d["is_active"],
            creator_id=d.get("creator_id"),
            as_embed=d.get("as_embed", False),
            embed_title=d.get("embed_title"),
            embed_color=d.get("embed_color"),
            embed_footer=d.get("embed_footer"),
            embed_json=d.get("embed_json"),
            vote_emojis=d.get("vote_emojis"),
        )
