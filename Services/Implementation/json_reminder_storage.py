from Services.Interfaces.reminder_storage import ReminderStorage, matches
import json
from datetime import datetime
from Entities.reminder import Reminder, ReminderCodec
from typing import Dict, List
import os


class JsonReminderStorage(ReminderStorage):
    """Keeps reminders in a JSON file, rewriting the whole file on every change."""
    def __init__(self, filename: str):
        self.filename = filename

    def save(self, reminders: dict[int, Reminder]) -> None:
        temp_filename = self.filename + ".tmp"
        payload = [ReminderCodec.to_dict(r) for r in reminders.values()]

        with open(temp_filename, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        os.replace(temp_filename, self.filename)

    def load_all(self) -> dict[int, Reminder]:
        if not os.path.exists(self.filename):
            return {}
        try:
            with open(self.filename, "r", encoding="utf-8") as f:
                raw = json.load(f)
            reminders = [ReminderCodec.from_dict(item) for item in raw]
            return {r.id: r for r in reminders}
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error: Failed to load reminders from {self.filename}. Message: {e}")
            return {}

    async def add_reminder(self, reminder: Reminder) -> None:
        reminders = self.load_all()
        reminders[reminder.id] = reminder
        self.save(reminders)

    async def get_reminder(self, reminder_id: int) -> Reminder | None:
        return self.load_all().get(reminder_id)

    async def get_all_reminders(self) -> Dict[int, Reminder]:
        return self.load_all()

    async def get_due_reminders(self, now: datetime) -> List[Reminder]:
        return sorted(
            (r for r in self.load_all().values() if r.is_active and r.next_reminder_at <= now),
            key=lambda r: r.next_reminder_at,
        )

    async def find_reminders(
        self,
        guild_id: int | None = None,
        channel_id: int | None = None,
        creator_id: int | None = None,
    ) -> List[Reminder]:
        return sorted(
            (r for r in self.load_all().values() if matches(r, guild_id, channel_id, creator_id)),
            key=lambda r: (not r.is_active, r.next_reminder_at),
        )

    async def get_next_id(self) -> int:
        reminders = self.load_all()
        return (max(reminders) if reminders else 0) + 1

    async def update_reminder(self, reminder: Reminder) -> None:
        reminders = self.load_all()
        reminders[reminder.id] = reminder
        self.save(reminders)

    async def delete_reminder(self, reminder_id: int) -> None:
        reminders = self.load_all()
        if reminders.pop(reminder_id, None) is not None:
            self.save(reminders)
