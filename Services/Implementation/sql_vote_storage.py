"""SQL storage for votes on sent reminders."""

from sqlalchemy import delete, func, select

from Services.Models.vote_row import VoteRow
from Services.database import session_scope


class SqlVoteStorage:
    """Stores who voted for which emoji on each sent reminder."""

    async def toggle_vote(self, message_id: int, user_id: int, emoji: str) -> dict[str, int]:
        """Cast, move or withdraw a vote, returning the message's vote counts by emoji.

        Voting for the emoji the user already chose withdraws the vote; voting
        for another emoji moves it there.
        """
        async with session_scope() as session:
            current = await session.scalar(
                select(VoteRow.emoji).where(VoteRow.message_id == message_id, VoteRow.user_id == user_id)
            )
            await session.execute(
                delete(VoteRow).where(VoteRow.message_id == message_id, VoteRow.user_id == user_id)
            )
            if current != emoji:
                session.add(VoteRow(message_id=message_id, user_id=user_id, emoji=emoji))
            await session.flush()

            rows = await session.execute(
                select(VoteRow.emoji, func.count())
                .where(VoteRow.message_id == message_id)
                .group_by(VoteRow.emoji)
            )
            return {row_emoji: count for row_emoji, count in rows.all()}
