"""Mapped row for a reaction on a sent reminder."""

from datetime import datetime, timezone

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from Services.database import Base, UTCDateTime


class VoteRow(Base):
    """One person's reaction with one emoji on one sent reminder message.

    The key includes the emoji, so like Discord reactions a person can react
    with several emojis on the same message, but with each emoji only once.
    """
    __tablename__ = "reminder_reactions"

    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    emoji: Mapped[str] = mapped_column(String, primary_key=True)
    # Lists who reacted in the order they did.
    voted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=lambda: datetime.now(timezone.utc))
