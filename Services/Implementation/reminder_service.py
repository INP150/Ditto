"""Domain logic for reminders, independent of Discord."""

from datetime import datetime, timedelta
from typing import Callable, List

from Entities.reminder import Reminder
from Services.Implementation.json_reminder_storage import JsonReminderStorage
from Services.Interfaces.reminder_storage import ReminderStorage
from const import DONT_REPEAT_VALUE
from time_helpers import ensure_utc, utc_now


class ReminderService:
    """Creates, queries and advances reminders on top of a storage backend."""

    def __init__(self, storage: ReminderStorage):
        """Initialize the reminder service."""
        self.storage = storage

    async def create_reminder(
        self,
        channel_id: int | str,
        creator_id: int,
        guild_id: int | None,
        message: str,
        next_reminder_at: datetime,
        repeat_every_seconds: int = DONT_REPEAT_VALUE,
        as_embed: bool = False,
        embed_title: str | None = None,
        embed_color: int | None = None,
        embed_footer: str | None = None,
        embed_json: str | None = None,
        vote_emojis: str | None = None,
    ) -> Reminder:
        """Store and return a new reminder."""
        now = utc_now()
        reminder = Reminder(
            id=await self.storage.get_next_id(),
            guild_id=guild_id,
            channel_id=str(channel_id),
            creator_id=creator_id,
            message=message,
            next_reminder_at=ensure_utc(next_reminder_at),
            repeat_every_seconds=repeat_every_seconds,
            created_at=now,
            last_updated_at=now,
            as_embed=as_embed,
            embed_title=embed_title,
            embed_color=embed_color,
            embed_footer=embed_footer,
            embed_json=embed_json,
            vote_emojis=vote_emojis,
        )
        await self.storage.add_reminder(reminder)
        return reminder

    async def get_reminder(self, reminder_id: int) -> Reminder | None:
        """Get a reminder by its ID."""
        return await self.storage.get_reminder(reminder_id)

    async def get_all_reminders(self) -> dict[int, Reminder]:
        """Get every reminder, keyed by ID."""
        return await self.storage.get_all_reminders()

    async def find_reminders(
        self,
        guild_id: int | None = None,
        channel_id: int | None = None,
        creator_id: int | None = None,
    ) -> List[Reminder]:
        """Get the reminders in a server, a channel and/or by a user."""
        return await self.storage.find_reminders(guild_id, channel_id, creator_id)

    async def fill_missing_guild_ids(self, guild_of_channel: Callable[[int], int | None]) -> int:
        """Set the server of reminders stored before reminders were tied to one.

        `guild_of_channel` maps a channel ID to its server ID, or None when the
        channel is unknown or not in a server. Returns how many were updated.
        """
        updated = 0
        for reminder in (await self.storage.get_all_reminders()).values():
            if reminder.guild_id is not None:
                continue
            guild_id = guild_of_channel(int(reminder.channel_id))
            if guild_id is not None:
                reminder.guild_id = guild_id
                await self.storage.update_reminder(reminder)
                updated += 1
        return updated

    async def delete_reminder(self, reminder_id: int) -> bool:
        """Delete a reminder, returning whether it existed."""
        if await self.storage.get_reminder(reminder_id) is None:
            return False
        await self.storage.delete_reminder(reminder_id)
        return True

    async def pause_reminder(self, reminder_id: int) -> bool:
        """Temporarily stop a reminder from firing."""
        return await self._set_active(reminder_id, False)

    async def resume_reminder(self, reminder_id: int) -> Reminder | None:
        """Resume a paused reminder, returning it with its next time.

        A repeating reminder keeps its original rhythm and skips the occurrences
        missed while paused. A one-off reminder that is already overdue fires in
        a minute.
        """
        reminder = await self.storage.get_reminder(reminder_id)
        if reminder is None:
            return None

        now = utc_now()
        reminder.is_active = True
        if reminder.next_reminder_at <= now:
            if reminder.repeat_every_seconds > 0:
                reminder.reschedule_after(now)
            else:
                reminder.next_reminder_at = now + timedelta(minutes=1)
        await self._save(reminder)
        return reminder

    async def postpone_reminder(self, reminder_id: int, until: datetime) -> Reminder | None:
        """Move a reminder's next time to `until`, after which it repeats as before.

        A paused reminder is resumed, since postponing says when it should fire.
        """
        reminder = await self.storage.get_reminder(reminder_id)
        if reminder is None:
            return None

        reminder.next_reminder_at = ensure_utc(until)
        reminder.is_active = True
        await self._save(reminder)
        return reminder

    async def update_reminder(self, reminder: Reminder) -> None:
        """Persist changes made to a reminder."""
        await self._save(reminder)

    async def get_due_reminders(self, now: datetime | None = None) -> List[Reminder]:
        """Get reminders that should fire now, earliest first."""
        return await self.storage.get_due_reminders(now or utc_now())

    async def record_fired(self, reminder: Reminder, now: datetime | None = None) -> Reminder:
        """Advance a reminder past the occurrence that was just sent."""
        reminder.reschedule_after(ensure_utc(now) if now is not None else utc_now())
        await self._save(reminder)
        return reminder

    async def _save(self, reminder: Reminder) -> None:
        """Stamp and write a reminder."""
        reminder.last_updated_at = utc_now()
        await self.storage.update_reminder(reminder)

    async def _set_active(self, reminder_id: int, is_active: bool) -> bool:
        """Flip a reminder's active flag if it exists."""
        reminder = await self.storage.get_reminder(reminder_id)
        if reminder is None:
            return False
        reminder.is_active = is_active
        await self._save(reminder)
        return True


if __name__ == "__main__":
    import asyncio

    async def demo() -> None:
        storage = JsonReminderStorage("reminders.json")
        service = ReminderService(storage)

        reminder = await service.create_reminder(
            channel_id=123,
            creator_id=1,
            guild_id=None,
            message="Hello, World!",
            next_reminder_at=utc_now(),
            repeat_every_seconds=3600,
        )
        print("created:", reminder)

        await service.pause_reminder(reminder.id)
        await service.resume_reminder(reminder.id)
        await service.postpone_reminder(reminder.id, utc_now() + timedelta(days=7))
        await service.delete_reminder(reminder.id)

        for stored in (await service.get_all_reminders()).values():
            print("stored:", stored)

    asyncio.run(demo())
