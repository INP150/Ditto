from Entities.reminder import Reminder
from typing import Dict, List
from datetime import datetime

from Services.Interfaces.reminder_storage import ReminderStorage, matches
from time_helpers import utc_now


class InMemoryReminderStorage(ReminderStorage):
    """In memory implementation of the ReminderStorage interface, for testing."""
    def __init__(self) -> None:
        self.reminders: Dict[int, Reminder] = {}

    async def add_reminder(self, reminder: Reminder) -> None:
        self.reminders[reminder.id] = reminder

    async def get_reminder(self, reminder_id: int) -> Reminder | None:
        return self.reminders.get(reminder_id)

    async def get_all_reminders(self) -> Dict[int, Reminder]:
        return dict(self.reminders)

    async def get_due_reminders(self, now: datetime) -> List[Reminder]:
        return sorted(
            (r for r in self.reminders.values() if r.is_active and r.next_reminder_at <= now),
            key=lambda r: r.next_reminder_at,
        )

    async def find_reminders(
        self,
        guild_id: int | None = None,
        channel_id: int | None = None,
        creator_id: int | None = None,
    ) -> List[Reminder]:
        return sorted(
            (r for r in self.reminders.values() if matches(r, guild_id, channel_id, creator_id)),
            key=lambda r: (not r.is_active, r.next_reminder_at),
        )

    async def get_next_id(self) -> int:
        return (max(self.reminders) if self.reminders else 0) + 1

    async def update_reminder(self, reminder: Reminder) -> None:
        self.reminders[reminder.id] = reminder

    async def delete_reminder(self, reminder_id: int) -> None:
        self.reminders.pop(reminder_id, None)
