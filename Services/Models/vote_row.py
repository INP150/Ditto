"""Mapped row for a vote on a sent reminder."""

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from Services.database import Base


class VoteRow(Base):
    """One person's vote on one sent reminder message.

    The key is the message and the voter, so each person has a single vote per
    message; voting for another emoji replaces it.
    """
    __tablename__ = "reminder_votes"

    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    emoji: Mapped[str] = mapped_column(String)
