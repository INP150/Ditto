"""Mapped row for a reminder."""

from datetime import datetime

from sqlalchemy import BigInteger, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from Entities.reminder import Reminder
from Services.database import Base, UTCDateTime


class ReminderRow(Base):
    """A single reminder as stored in the database."""
    __tablename__ = "reminders"

    # Discord snowflakes exceed the 32-bit range of SQLite's INTEGER, so every
    # ID column is explicitly a BIGINT.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, index=True)
    creator_id: Mapped[int] = mapped_column(BigInteger, index=True, default=0)
    message: Mapped[str] = mapped_column(Text)
    next_reminder_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    repeat_every_seconds: Mapped[int] = mapped_column(Integer, default=-1)
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    as_embed: Mapped[bool] = mapped_column(default=False)
    embed_title: Mapped[str | None] = mapped_column(String, nullable=True)
    embed_color: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embed_footer: Mapped[str | None] = mapped_column(String, nullable=True)
    embed_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_updated_at: Mapped[datetime] = mapped_column(UTCDateTime)

    @staticmethod
    def from_entity(reminder: Reminder) -> "ReminderRow":
        """Build a row from a Reminder entity."""
        return ReminderRow(
            id=reminder.id,
            guild_id=reminder.guild_id,
            channel_id=int(reminder.channel_id),
            creator_id=int(reminder.creator_id or 0),
            message=reminder.message,
            next_reminder_at=reminder.next_reminder_at,
            repeat_every_seconds=reminder.repeat_every_seconds,
            is_active=reminder.is_active,
            as_embed=reminder.as_embed,
            embed_title=reminder.embed_title,
            embed_color=reminder.embed_color,
            embed_footer=reminder.embed_footer,
            embed_json=reminder.embed_json,
            created_at=reminder.created_at,
            last_updated_at=reminder.last_updated_at,
        )

    def to_entity(self) -> Reminder:
        """Build a Reminder entity from this row."""
        return Reminder(
            id=self.id,
            guild_id=self.guild_id,
            channel_id=str(self.channel_id),
            creator_id=self.creator_id,
            message=self.message,
            next_reminder_at=self.next_reminder_at,
            repeat_every_seconds=self.repeat_every_seconds,
            is_active=self.is_active,
            as_embed=self.as_embed,
            embed_title=self.embed_title,
            embed_color=self.embed_color,
            embed_footer=self.embed_footer,
            embed_json=self.embed_json,
            created_at=self.created_at,
            last_updated_at=self.last_updated_at,
        )
