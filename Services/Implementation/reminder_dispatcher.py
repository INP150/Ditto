"""Sends due reminders to Discord."""

import discord

from Entities.reminder import Reminder
from Services.Implementation.reminder_service import ReminderService
from const import MISSING_REMINDER_CHANNEL
from embed_helpers import build_reminder_content
from time_helpers import utc_now
from vote_helpers import build_vote_view, split_vote_emojis


class ReminderDispatcher:
    """Checks for due reminders on a fixed interval and posts them."""

    def __init__(self, bot: discord.Client, service: ReminderService):
        self.bot = bot
        self.service = service

    async def dispatch_due(self) -> int:
        """Send every reminder that is due, returning how many were sent.

        A failing reminder is logged and skipped so one bad channel or a lost
        permission cannot stop the other reminders from being sent.
        """
        now = utc_now()
        sent = 0
        for reminder in await self.service.get_due_reminders(now):
            try:
                await self.send(reminder, now)
                sent += 1
            except Exception as error:
                print(f"Failed to send reminder {reminder.id}: {error}")
                # Advance it regardless, otherwise a broken reminder is retried forever.
                await self.service.record_fired(reminder, now)
        return sent

    async def send(self, reminder: Reminder, now=None) -> None:
        """Post one reminder to its channel and schedule the next occurrence."""
        channel_id = int(reminder.channel_id)
        # Threads are not always cached, so fall back to asking Discord.
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException as error:
                raise RuntimeError(MISSING_REMINDER_CHANNEL) from error

        await channel.send(
            **build_reminder_content(reminder),
            view=build_vote_view(split_vote_emojis(reminder.vote_emojis)),
        )
        await self.service.record_fired(reminder, now)
