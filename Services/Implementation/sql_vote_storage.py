"""SQL storage for reactions on sent reminders."""

from sqlalchemy import select

from Services.Models.vote_row import VoteRow
from Services.database import session_scope


class SqlVoteStorage:
    """Stores who reacted with which emoji on each sent reminder."""

    async def toggle_vote(self, message_id: int, user_id: int, emoji: str) -> dict[str, list[int]]:
        """Add or take back one reaction, returning who reacted with each emoji.

        Reacting with an emoji the user already chose takes it back; other
        emojis the user reacted with are left alone. The returned user IDs are
        in the order people reacted.
        """
        async with session_scope() as session:
            existing = await session.get(VoteRow, (message_id, user_id, emoji))
            if existing is not None:
                await session.delete(existing)
            else:
                session.add(VoteRow(message_id=message_id, user_id=user_id, emoji=emoji))
            await session.flush()

            rows = await session.execute(
                select(VoteRow.emoji, VoteRow.user_id)
                .where(VoteRow.message_id == message_id)
                .order_by(VoteRow.voted_at, VoteRow.user_id)
            )
            voters: dict[str, list[int]] = {}
            for row_emoji, row_user in rows.all():
                voters.setdefault(row_emoji, []).append(row_user)
            return voters
