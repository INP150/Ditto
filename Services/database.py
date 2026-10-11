"""SQLAlchemy engine and session setup for the bot's SQLite database."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import Connection, DateTime, TypeDecorator, inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from const import DATABASE_URL
from time_helpers import ensure_utc


class Base(DeclarativeBase):
    """Base class for the mapped tables."""
    pass


class UTCDateTime(TypeDecorator):
    """Store datetimes as naive UTC and hand them back as aware UTC.

    SQLite has no timezone support and returns naive values, which would break
    comparisons against aware datetimes. Normalising in the column type keeps
    every datetime the rest of the code sees aware, and keeps the stored values
    sortable so range queries on next_reminder_at work.
    """
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        """Convert to naive UTC before storing."""
        if value is None:
            return None
        return ensure_utc(value).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        """Convert back to aware UTC after reading."""
        if value is None:
            return None
        return ensure_utc(value)


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def database_url() -> str:
    """Return the database URL, taking DATABASE_URL from the environment when set."""
    return os.getenv("DATABASE_URL", DATABASE_URL)


def ensure_sqlite_folder(url: str) -> None:
    """Create the folder a SQLite file path points at, since SQLite will not."""
    if "sqlite" not in url:
        return

    _, _, path = url.partition("://")
    path = path.split("?")[0].removeprefix("/")  # leave relative paths relative
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)


async def init_engine(url: str | None = None) -> AsyncEngine:
    """Create the engine and make sure the tables exist."""
    global _engine, _session_factory

    if _engine is None:
        resolved = database_url() if url is None else url
        ensure_sqlite_folder(resolved)
        _engine = create_async_engine(resolved)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    from Services.Models import reminder_row, vote_row # noqa: F401 - registers the tables

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(add_missing_columns)

    return _engine


def add_missing_columns(conn: Connection) -> None:
    """Add nullable columns that were introduced after a table was created.

    create_all only creates missing tables, so a database from an older version
    of the bot would otherwise lack the new columns.
    """
    inspector = inspect(conn)
    for table in Base.metadata.sorted_tables:
        existing = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing or not column.nullable:
                continue
            column_type = column.type.compile(dialect=conn.dialect)
            conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {column.name} {column_type}'))


async def dispose_engine() -> None:
    """Close the engine and release the database file."""
    global _engine, _session_factory

    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Yield a session, committing on success and rolling back on error."""
    if _session_factory is None:
        raise RuntimeError("The database engine is not initialised, call init_engine() first")

    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
