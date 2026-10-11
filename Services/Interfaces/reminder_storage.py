from datetime import datetime
from typing import Dict, List

from Entities.reminder import Reminder


class ReminderStorage:
    """Storage backend for reminders.

    Implementations persist reminders somewhere - the database, a file or memory.
    All methods are coroutines so the SQL backend can await its driver.
    """

    async def add_reminder(self, reminder: Reminder) -> None:
        """Insert a new reminder."""
        raise NotImplementedError

    async def get_reminder(self, reminder_id: int) -> Reminder | None:
        """Get a reminder by its ID, or None when it does not exist."""
        raise NotImplementedError

    async def get_all_reminders(self) -> Dict[int, Reminder]:
        """Get every reminder, keyed by ID."""
        raise NotImplementedError

    async def get_due_reminders(self, now: datetime) -> List[Reminder]:
        """Get active reminders due at or before `now`, earliest first."""
        raise NotImplementedError

    async def find_reminders(
        self,
        guild_id: int | None = None,
        channel_id: int | None = None,
        creator_id: int | None = None,
    ) -> List[Reminder]:
        """Get the reminders matching every filter given, active ones first, then by when they are due.

        A filter left as None is not applied.
        """
        raise NotImplementedError

    async def get_next_id(self) -> int:
        """Return the ID to use for the next reminder."""
        raise NotImplementedError

    async def update_reminder(self, reminder: Reminder) -> None:
        """Update an existing reminder."""
        raise NotImplementedError

    async def delete_reminder(self, reminder_id: int) -> None:
        """Delete a reminder by its ID."""
        raise NotImplementedError


def matches(
    reminder: Reminder,
    guild_id: int | None,
    channel_id: int | None,
    creator_id: int | None,
) -> bool:
    """Whether a reminder passes the filters of ReminderStorage.find_reminders."""
    return (
        (guild_id is None or reminder.guild_id == guild_id)
        and (channel_id is None or reminder.channel_id == str(channel_id))
        and (creator_id is None or reminder.creator_id == creator_id)
    )
