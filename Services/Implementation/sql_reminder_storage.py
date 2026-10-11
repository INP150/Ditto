"""SQL storage backend for reminders."""

from datetime import datetime
from typing import Dict, List

from sqlalchemy import delete, func, select, update

from Entities.reminder import Reminder
from Services.Interfaces.reminder_storage import ReminderStorage
from Services.Models.reminder_row import ReminderRow
from Services.database import session_scope


class SqlReminderStorage(ReminderStorage):
    """Stores reminders in the SQL database."""

    async def add_reminder(self, reminder: Reminder) -> None:
        """Insert a new reminder."""
        async with session_scope() as session:
            session.add(ReminderRow.from_entity(reminder))

    async def get_reminder(self, reminder_id: int) -> Reminder | None:
        """Get a reminder by its ID, or None when it does not exist."""
        async with session_scope() as session:
            row = await session.get(ReminderRow, reminder_id)
            return row.to_entity() if row is not None else None

    async def get_all_reminders(self) -> Dict[int, Reminder]:
        """Get every reminder, keyed by ID."""
        async with session_scope() as session:
            rows = (await session.scalars(select(ReminderRow))).all()
            return {row.id: row.to_entity() for row in rows}

    async def get_due_reminders(self, now: datetime) -> List[Reminder]:
        """Get active reminders due at or before `now`, earliest first."""
        statement = (
            select(ReminderRow)
            .where(ReminderRow.is_active.is_(True))
            .where(ReminderRow.next_reminder_at <= now)
            .order_by(ReminderRow.next_reminder_at)
        )
        async with session_scope() as session:
            rows = (await session.scalars(statement)).all()
            return [row.to_entity() for row in rows]

    async def find_reminders(
        self,
        guild_id: int | None = None,
        channel_id: int | None = None,
        creator_id: int | None = None,
    ) -> List[Reminder]:
        """Get the reminders matching every filter given, active ones first, then by when they are due."""
        statement = select(ReminderRow).order_by(
            ReminderRow.is_active.desc(), ReminderRow.next_reminder_at
        )
        if guild_id is not None:
            statement = statement.where(ReminderRow.guild_id == guild_id)
        if channel_id is not None:
            statement = statement.where(ReminderRow.channel_id == channel_id)
        if creator_id is not None:
            statement = statement.where(ReminderRow.creator_id == creator_id)

        async with session_scope() as session:
            rows = (await session.scalars(statement)).all()
            return [row.to_entity() for row in rows]

    async def get_next_id(self) -> int:
        """Return the ID to use for the next reminder."""
        async with session_scope() as session:
            highest = await session.scalar(select(func.max(ReminderRow.id)))
            return (highest or 0) + 1

    async def update_reminder(self, reminder: Reminder) -> None:
        """Update an existing reminder, or insert it when it is not stored yet."""
        row = ReminderRow.from_entity(reminder)
        values = {
            column: getattr(row, column)
            for column in (
                "guild_id", "channel_id", "creator_id", "message", "next_reminder_at",
                "repeat_every_seconds", "is_active", "as_embed", "embed_title",
                "embed_color", "embed_footer", "embed_json", "created_at", "last_updated_at",
            )
        }
        async with session_scope() as session:
            result = await session.execute(
                update(ReminderRow).where(ReminderRow.id == reminder.id).values(**values)
            )
            if result.rowcount == 0:
                session.add(row)

    async def delete_reminder(self, reminder_id: int) -> None:
        """Delete a reminder by its ID."""
        async with session_scope() as session:
            await session.execute(delete(ReminderRow).where(ReminderRow.id == reminder_id))
